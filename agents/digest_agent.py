"""
agents/digest_agent.py
==========================================================
定时文章订阅执行器
- 根据用户预设 query 搜索文章
- 保存到飞书
- 发送邮件提醒
==========================================================
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

try:
    from common import db_exec, db_query, db_query_one, log, new_id, now_iso
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common import db_exec, db_query, db_query_one, log, new_id, now_iso

from agents.chat_agent import _search_tavily
from agents.email_agent import send_email
from tools.agent_protocol_tool import normalize_search_results
from tools.feishu_doc_tool import build_digest_payload, save_search_to_feishu
from tools.runtime_cache_tool import cache_get, cache_set


DEFAULT_LOOKBACK_MINUTES = 15
SLOT_LOCK_TTL_SECONDS = 60 * 60 * 24 * 45
FINGERPRINT_TTL_SECONDS = 60 * 60 * 24 * 180


def list_enabled_subscriptions() -> list[dict]:
    return db_query(
        """SELECT * FROM digest_subscriptions
           WHERE enabled=1
           ORDER BY updated_at DESC""",
        [],
    )


def list_subscriptions() -> list[dict]:
    return db_query(
        "SELECT * FROM digest_subscriptions ORDER BY updated_at DESC",
        [],
    )


def get_subscription(subscription_id: str) -> dict | None:
    return db_query_one(
        "SELECT * FROM digest_subscriptions WHERE subscription_id=?",
        [subscription_id],
    )


def _get_timezone(timezone_name: str | None) -> ZoneInfo:
    name = (timezone_name or "Asia/Shanghai").strip() or "Asia/Shanghai"
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        log.warning(f"[digest] 未知时区 {name!r}，回退 Asia/Shanghai")
        return ZoneInfo("Asia/Shanghai")


def _parse_cron_field(field: str, minimum: int, maximum: int) -> set[int]:
    field = (field or "*").strip()
    if not field or field == "*":
        return set(range(minimum, maximum + 1))

    values: set[int] = set()
    for part in field.split(","):
        part = part.strip()
        if not part:
            continue
        if "/" in part:
            base, step_text = part.split("/", 1)
            step = max(1, int(step_text))
        else:
            base, step = part, 1

        if base == "*" or not base:
            start, end = minimum, maximum
        elif "-" in base:
            start_text, end_text = base.split("-", 1)
            start, end = int(start_text), int(end_text)
        else:
            start = end = int(base)

        if minimum == 0 and maximum == 6:
            if start == 7:
                start = 0
            if end == 7:
                end = 0

        if start > end and minimum == 0 and maximum == 6:
            end += 7
            for value in range(start, end + 1, step):
                values.add(value % 7)
            continue

        start = max(minimum, start)
        end = min(maximum, end)
        for value in range(start, end + 1, step):
            values.add(value)
    return values


def _cron_matches(dt_local: datetime, cron_expr: str) -> bool:
    parts = (cron_expr or "").split()
    if len(parts) != 5:
        raise ValueError(f"不支持的 cron 表达式: {cron_expr!r}")

    minute, hour, day, month, weekday = parts
    cron_weekday = (dt_local.weekday() + 1) % 7
    return (
        dt_local.minute in _parse_cron_field(minute, 0, 59)
        and dt_local.hour in _parse_cron_field(hour, 0, 23)
        and dt_local.day in _parse_cron_field(day, 1, 31)
        and dt_local.month in _parse_cron_field(month, 1, 12)
        and cron_weekday in _parse_cron_field(weekday, 0, 6)
    )


def find_due_slot(
    schedule_cron: str,
    timezone_name: str,
    *,
    now_utc: datetime | None = None,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
) -> datetime | None:
    tz = _get_timezone(timezone_name)
    current_utc = now_utc or datetime.now(timezone.utc)
    current_local = current_utc.astimezone(tz).replace(second=0, microsecond=0)

    for offset in range(max(0, lookback_minutes) + 1):
        candidate = current_local - timedelta(minutes=offset)
        if _cron_matches(candidate, schedule_cron):
            return candidate
    return None


def _slot_key(dt_local: datetime) -> str:
    return dt_local.strftime("%Y-%m-%dT%H:%M")


def _slot_cache_key(subscription_id: str, slot_key: str) -> str:
    return f"{subscription_id}:{slot_key}"


def _fingerprint_cache_key(subscription_id: str) -> str:
    return f"{subscription_id}:latest"


def _result_fingerprint(query: str, search_results: list[dict]) -> str:
    payload = {
        "query": (query or "").strip(),
        "items": [
            {
                "title": (item.get("title") or "").strip(),
                "url": (item.get("url") or "").strip(),
            }
            for item in search_results
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _mark_subscription_status(subscription_id: str, status: str, error: str = ""):
    now = now_iso()
    db_exec(
        """UPDATE digest_subscriptions
           SET last_run_at=?, last_status=?, last_error=?, updated_at=?
           WHERE subscription_id=?""",
        [now, status, error[:500], now, subscription_id],
    )


def evaluate_subscription_schedule(
    subscription: dict,
    *,
    now_utc: datetime | None = None,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
) -> dict:
    subscription_id = subscription.get("subscription_id", "")
    if int(subscription.get("enabled") or 0) != 1:
        return {"due": False, "reason": "disabled"}

    due_slot = find_due_slot(
        subscription.get("schedule_cron") or "0 9 * * *",
        subscription.get("timezone") or "Asia/Shanghai",
        now_utc=now_utc,
        lookback_minutes=lookback_minutes,
    )
    if not due_slot:
        return {"due": False, "reason": "not_due"}

    slot_key = _slot_key(due_slot)
    if cache_get("digest_slot_lock", _slot_cache_key(subscription_id, slot_key)):
        return {"due": False, "reason": "already_triggered", "slot_key": slot_key}

    return {"due": True, "reason": "due", "slot_key": slot_key, "slot_local": due_slot.isoformat()}


def create_subscription(
    *,
    email: str,
    query: str,
    schedule_cron: str = "0 9 * * *",
    timezone: str = "Asia/Shanghai",
    max_results: int = 5,
    send_to_feishu: bool = True,
    send_email_notice: bool = True,
    enabled: bool = True,
    tags: list[str] | None = None,
) -> dict:
    subscription_id = new_id("sub-")
    now = now_iso()
    db_exec(
        """INSERT INTO digest_subscriptions
           (subscription_id, email, query, schedule_cron, timezone, max_results,
            enabled, send_to_feishu, send_email, tags_json, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            subscription_id,
            email.strip(),
            query.strip(),
            schedule_cron.strip() or "0 9 * * *",
            timezone.strip() or "Asia/Shanghai",
            max(1, min(int(max_results or 5), 10)),
            1 if enabled else 0,
            1 if send_to_feishu else 0,
            1 if send_email_notice else 0,
            json.dumps(tags or [], ensure_ascii=False),
            now,
            now,
        ],
    )
    return get_subscription(subscription_id) or {}


def update_subscription(subscription_id: str, updates: dict) -> dict | None:
    current = get_subscription(subscription_id)
    if not current:
        return None

    fields = []
    params = []
    for key in ("email", "query", "schedule_cron", "timezone", "max_results"):
        if key in updates:
            fields.append(f"{key}=?")
            value = updates[key]
            if key == "max_results":
                value = max(1, min(int(value or 5), 10))
            params.append(value)

    bool_fields = {
        "enabled": "enabled",
        "send_to_feishu": "send_to_feishu",
        "send_email": "send_email",
    }
    for incoming, column in bool_fields.items():
        if incoming in updates:
            fields.append(f"{column}=?")
            params.append(1 if updates[incoming] else 0)

    if "tags" in updates:
        fields.append("tags_json=?")
        params.append(json.dumps(updates["tags"] or [], ensure_ascii=False))

    if not fields:
        return current

    fields.append("updated_at=?")
    params.append(now_iso())
    params.append(subscription_id)
    db_exec(
        f"UPDATE digest_subscriptions SET {', '.join(fields)} WHERE subscription_id=?",
        params,
    )
    return get_subscription(subscription_id)


def delete_subscription(subscription_id: str) -> bool:
    if not get_subscription(subscription_id):
        return False
    db_exec("DELETE FROM digest_subscriptions WHERE subscription_id=?", [subscription_id])
    return True


def _format_email_body(subscription: dict, digest_payload: dict, feishu_url: str) -> str:
    lines = [
        f"你的订阅主题「{subscription['query']}」有新的文章整理结果。",
        "",
        digest_payload.get("title", "本次推荐"),
    ]
    summary = (digest_payload.get("summary") or "").strip()
    if summary:
        lines.extend(["", "总结：", summary, "", "文章列表："])
    else:
        lines.extend(["", "文章列表："])

    for article in digest_payload.get("articles", []):
        lines.append(f"{article['index']}. {article['title']}")
        if article.get("url"):
            lines.append(f"   {article['url']}")
        if article.get("excerpt"):
            lines.append(f"   {article['excerpt'][:220]}")
    if feishu_url:
        lines.extend(["", f"飞书文档：{feishu_url}"])
    lines.extend(["", "这封邮件由 Harness 定时任务自动发送。"])
    return "\n".join(lines)


def run_subscription(
    subscription: dict,
    *,
    slot_key: str | None = None,
    allow_duplicate: bool = False,
    trigger: str = "manual",
) -> dict:
    query = (subscription.get("query") or "").strip()
    if not query:
        raise ValueError("订阅缺少 query")

    subscription_id = subscription["subscription_id"]
    search_results = normalize_search_results(
        _search_tavily(query, max_results=int(subscription.get("max_results") or 5))
    )
    if not search_results:
        raise RuntimeError(f"订阅「{query}」未搜索到结果")

    digest_payload = build_digest_payload(search_results, query)

    fingerprint = _result_fingerprint(query, search_results)
    latest_fingerprint = cache_get("digest_result_fingerprint", _fingerprint_cache_key(subscription_id)) or {}
    previous_hash = latest_fingerprint.get("fingerprint") if isinstance(latest_fingerprint, dict) else None
    if previous_hash == fingerprint and not allow_duplicate:
        _mark_subscription_status(subscription_id, "skipped_duplicate", "")
        if slot_key:
            cache_set(
                "digest_slot_lock",
                _slot_cache_key(subscription_id, slot_key),
                {"subscription_id": subscription_id, "slot_key": slot_key, "status": "skipped_duplicate"},
                ttl_seconds=SLOT_LOCK_TTL_SECONDS,
            )
        return {
            "subscription_id": subscription_id,
            "query": query,
            "article_count": len(search_results),
            "doc_url": "",
            "email_sent": False,
            "email_provider": "",
            "skipped": True,
            "skip_reason": "duplicate_results",
            "trigger": trigger,
        }

    feishu_result = {"success": False, "doc_url": ""}
    if int(subscription.get("send_to_feishu") or 0):
        feishu_result = save_search_to_feishu(search_results=search_results, query=query)
        if not feishu_result.get("success"):
            raise RuntimeError(feishu_result.get("error") or "飞书保存失败")

    email_result = {"success": False}
    if int(subscription.get("send_email") or 0):
        email_result = send_email(
            to=subscription["email"],
            subject=f"Harness 订阅更新：{query}",
            body=_format_email_body(
                subscription,
                feishu_result.get("digest_payload") or digest_payload,
                feishu_result.get("doc_url", ""),
            ),
        )
        if not email_result.get("success"):
            raise RuntimeError(email_result.get("error") or "邮件发送失败")

    _mark_subscription_status(subscription_id, "success", "")
    cache_set(
        "digest_result_fingerprint",
        _fingerprint_cache_key(subscription_id),
        {
            "fingerprint": fingerprint,
            "query": query,
            "urls": [item.get("url", "") for item in search_results],
            "doc_url": feishu_result.get("doc_url", ""),
        },
        ttl_seconds=FINGERPRINT_TTL_SECONDS,
    )
    if slot_key:
        cache_set(
            "digest_slot_lock",
            _slot_cache_key(subscription_id, slot_key),
            {"subscription_id": subscription_id, "slot_key": slot_key, "status": "success"},
            ttl_seconds=SLOT_LOCK_TTL_SECONDS,
        )

    return {
        "subscription_id": subscription_id,
        "query": query,
        "article_count": len(search_results),
        "doc_url": feishu_result.get("doc_url", ""),
        "email_sent": bool(email_result.get("success")),
        "email_provider": email_result.get("provider", ""),
        "skipped": False,
        "trigger": trigger,
    }


def run_enabled_subscriptions() -> dict:
    results = []
    failures = []
    for subscription in list_enabled_subscriptions():
        try:
            results.append(run_subscription(subscription))
        except Exception as e:
            log.error(f"[digest] 订阅执行失败 {subscription.get('subscription_id')}: {e}")
            _mark_subscription_status(subscription["subscription_id"], "failed", str(e))
            failures.append({
                "subscription_id": subscription["subscription_id"],
                "query": subscription.get("query", ""),
                "error": str(e),
            })
    return {
        "success": len(failures) == 0,
        "ran": len(results),
        "failed": len(failures),
        "results": results,
        "failures": failures,
    }


def run_due_subscriptions(
    *,
    now_utc: datetime | None = None,
    lookback_minutes: int = DEFAULT_LOOKBACK_MINUTES,
) -> dict:
    results = []
    failures = []
    skipped = []

    for subscription in list_enabled_subscriptions():
        schedule = evaluate_subscription_schedule(
            subscription,
            now_utc=now_utc,
            lookback_minutes=lookback_minutes,
        )
        if not schedule.get("due"):
            skipped.append({
                "subscription_id": subscription.get("subscription_id", ""),
                "query": subscription.get("query", ""),
                "reason": schedule.get("reason", "not_due"),
            })
            continue

        slot_key = schedule.get("slot_key") or ""
        try:
            result = run_subscription(
                subscription,
                slot_key=slot_key,
                allow_duplicate=False,
                trigger="scheduled",
            )
            if result.get("skipped"):
                skipped.append({
                    "subscription_id": subscription.get("subscription_id", ""),
                    "query": subscription.get("query", ""),
                    "reason": result.get("skip_reason", "skipped"),
                    "slot_key": slot_key,
                })
            else:
                results.append(result)
        except Exception as e:
            log.error(f"[digest] 定时订阅执行失败 {subscription.get('subscription_id')}: {e}")
            _mark_subscription_status(subscription["subscription_id"], "failed", str(e))
            failures.append({
                "subscription_id": subscription["subscription_id"],
                "query": subscription.get("query", ""),
                "error": str(e),
                "slot_key": slot_key,
            })

    return {
        "success": len(failures) == 0,
        "ran": len(results),
        "failed": len(failures),
        "skipped": len(skipped),
        "results": results,
        "failures": failures,
        "skipped_items": skipped,
    }


def run_subscription_by_id(subscription_id: str, *, force: bool = False) -> dict:
    subscription = get_subscription(subscription_id)
    if not subscription:
        raise ValueError("订阅不存在")
    return run_subscription(subscription, allow_duplicate=force, trigger="manual")
