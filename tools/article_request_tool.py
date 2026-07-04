from __future__ import annotations

import json
import re
from typing import Any

from common import db_query


ARTICLE_NOUN_PATTERN = r"(文章|论文|资料|教程|博客|paper|article|post|篇)s?"
SEARCH_VERB_PATTERN = r"(找|搜|搜索|查|查找|查询|检索|推荐|收集|整理)"


def extract_requested_count(message: str, default: int | None = None) -> int | None:
    text = (message or "").strip()
    if not text:
        return default
    matched = re.search(r"(\d+)\s*篇", text)
    if matched:
        return max(1, min(int(matched.group(1)), 10))

    cn_map = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
    matched = re.search(r"([一二两三四五六七八九十])\s*篇", text)
    if matched:
        return cn_map.get(matched.group(1), default)
    return default


def detect_action_targets(message: str) -> set[str]:
    text = message or ""
    targets: set[str] = set()
    # Blog: "生成博客" / "写博客" → 直接博客意图
    # "生成5篇文章"（有数字+篇）→ 搜索语境，不算博客
    # "生成文章"（无数字）→ 仍算博客意图
    if re.search(r"(生成|写|创作|撰写|来一篇|出一篇).*(博客|blog)", text):
        targets.add("blog")
    elif re.search(r"(生成|写|创作|撰写|来一篇|出一篇).*(文章|总结)", text):
        if not re.search(r"\d+\s*篇.*?文章", text):
            targets.add("blog")
    if re.search(r"(存|加入|存入|放到|放进|保存到|收藏到|整理到|收录到).*(知识库|knowledge)", text):
        targets.add("knowledge")
    if re.search(r"(存|保存|放到|放进|整理到|传到|搬到|挪到|发到|丢到|弄到).*飞书", text) or \
       re.search(r"飞书.*(存|保存|文档|整理|上|里|里面|中)", text):
        targets.add("feishu")
    if re.search(r"(推送|发|发送|传|转发|弄).*(邮箱|邮件|email|mail)", text) or \
       re.search(r"(邮箱|邮件|email|mail).*(推送|发|发送|接收|收)", text):
        targets.add("email")
    return targets


def has_explicit_search_intent(message: str) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    patterns = [
        rf"{SEARCH_VERB_PATTERN}.*{ARTICLE_NOUN_PATTERN}",
        rf"{ARTICLE_NOUN_PATTERN}.*{SEARCH_VERB_PATTERN}",
        rf"(关于|有关).+{ARTICLE_NOUN_PATTERN}",
    ]
    return any(re.search(pattern, text, flags=re.IGNORECASE) for pattern in patterns)


def is_count_refinement_request(message: str) -> bool:
    text = (message or "").strip()
    if not text:
        return False
    if has_explicit_search_intent(text):
        return False
    if detect_action_targets(text):
        return False
    requested = extract_requested_count(text)
    if not requested:
        return False
    return bool(re.search(r"(我要|给我|来|补|凑|扩|增加|再来|不够|至少|再)", text))


def normalize_search_query(query: str) -> str:
    cleaned = (query or "").strip()
    if not cleaned:
        return ""

    replacements = [
        r"^[，。,\s]*(现在|当前|马上|立刻|请|麻烦|帮我|帮忙|给我|替我)+",
        r"(存|保存|放到|放进|整理到|传到|发到|同步到|搬到|挪到).{0,8}(飞书|知识库)",
        r"(飞书|知识库).{0,8}(里|中|上|里面|文档|一下)?",
        r"(并|然后|再)?\s*(存|保存|放到|放进|整理到|传到|发到|同步到|搬到|挪到).*$",
        r"(并|然后|再)\s*(生成|写|创作|撰写|做|输出).*(博客|文章|总结|blog).*$",
    ]
    for pattern in replacements:
        cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)

    cleaned = re.sub(r"(\d+|[一二两三四五六七八九十]+)\s*篇", " ", cleaned)
    cleaned = re.sub(rf"{SEARCH_VERB_PATTERN}\s*", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"的\s*(文章|论文|资料|教程|博客)", r" \1", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\b(里|中|上|里面)\b", " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ，。,.；;:：")

    topic = ""
    for pattern in (
        r"关于\s*(.+?)(?:的)?\s*(文章|论文|资料|教程|博客)?$",
        r"有关\s*(.+?)(?:的)?\s*(文章|论文|资料|教程|博客)?$",
        r"(.+?)(?:的)?\s*(文章|论文|资料|教程|博客)$",
    ):
        matched = re.search(pattern, cleaned, flags=re.IGNORECASE)
        if matched:
            topic = (matched.group(1) or "").strip(" ，。,.；;:：")
            break

    if not topic:
        topic = cleaned

    topic = re.sub(r"\s+", " ", topic).strip(" ，。,.；;:：")
    if not topic:
        return query.strip()

    if re.search(r"(文章|论文|资料|教程|博客)$", topic, flags=re.IGNORECASE):
        return topic
    return topic


def build_refined_search_message(message: str, context_query: str) -> str:
    requested = extract_requested_count(message)
    if not requested:
        return message
    normalized = normalize_search_query(context_query)
    topic = re.sub(r"\s*(文章|论文|资料|教程|博客)$", "", normalized, flags=re.IGNORECASE).strip()
    if not topic:
        return message
    return f"帮我找{requested}篇关于{topic}的文章"


def load_recent_search_contexts(session_id: str, limit: int = 8) -> list[dict[str, Any]]:
    if not session_id:
        return []

    rows = db_query(
        """SELECT message_id, meta, created_at
           FROM messages
           WHERE session_id=? AND role='assistant'
           ORDER BY created_at DESC
           LIMIT ?""",
        [session_id, limit],
    )

    contexts: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for row in rows:
        raw_meta = row.get("meta")
        if not raw_meta:
            continue
        try:
            meta = json.loads(raw_meta)
        except Exception:
            continue
        search_results = meta.get("search_results") or meta.get("feishu_search_results")
        search_query = (meta.get("search_query") or meta.get("feishu_search_query") or "").strip()
        if not search_results or not search_query:
            continue
        key = json.dumps(
            {
                "query": search_query,
                "urls": [item.get("url", "") for item in search_results[:5]],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        contexts.append(
            {
                "message_id": row.get("message_id", ""),
                "created_at": row.get("created_at", ""),
                "search_query": search_query,
                "search_results": search_results,
                "normalized_query": normalize_search_query(search_query),
            }
        )
    return contexts


def select_followup_context(message: str, contexts: list[dict[str, Any]]) -> dict[str, Any]:
    if not contexts:
        return {"status": "missing"}

    latest = contexts[0]
    if len(contexts) == 1:
        return {"status": "reuse", "context": latest}

    unique_queries = {ctx.get("normalized_query") or ctx.get("search_query") for ctx in contexts}
    if len(unique_queries) == 1:
        return {"status": "reuse", "context": latest}

    if re.search(r"(刚刚|刚才|上一条|上一次|最新|这些|这几篇|这.{0,4}篇|上面|刚搜的|重新)", message):
        return {"status": "reuse", "context": latest}

    normalized_message = normalize_search_query(message)
    if normalized_message and normalized_message not in {"文章", "论文", "资料", "教程", "博客"}:
        matched = [
            ctx for ctx in contexts
            if normalized_message in (ctx.get("normalized_query") or "")
            or (ctx.get("normalized_query") or "") in normalized_message
        ]
        if len(matched) == 1:
            return {"status": "reuse", "context": matched[0]}

    return {"status": "ambiguous", "contexts": contexts[:3]}


def build_context_clarification(contexts: list[dict[str, Any]]) -> str:
    if not contexts:
        return "当前会话没有可用的文章结果。请先告诉我要搜索什么。"
    lines = ["我需要确认你要操作哪一组文章："]
    for idx, ctx in enumerate(contexts[:3], 1):
        count = len(ctx.get("search_results") or [])
        query = ctx.get("search_query") or "未命名搜索"
        lines.append(f"{idx}. 「{query}」这组，共 {count} 篇")
    lines.append("你可以直接回复：`第1组存到飞书`、`把刚刚那组存到飞书`，或者重新说完整需求。")
    return "\n".join(lines)


def build_clarification_payload(contexts: list[dict[str, Any]], action_targets: list[str] | set[str]) -> dict[str, Any]:
    return {
        "contexts": [
            {
                "search_query": ctx.get("search_query", ""),
                "search_results": ctx.get("search_results", []),
                "normalized_query": ctx.get("normalized_query", ""),
            }
            for ctx in contexts[:3]
        ],
        "action_targets": list(action_targets),
    }


def load_pending_article_clarification(session_id: str | None) -> dict[str, Any] | None:
    if not session_id:
        return None
    rows = db_query(
        """SELECT meta FROM messages
           WHERE session_id=? AND role='assistant'
           ORDER BY created_at DESC
           LIMIT 5""",
        [session_id],
    )
    for row in rows:
        raw_meta = row.get("meta")
        if not raw_meta:
            continue
        try:
            meta = json.loads(raw_meta)
        except Exception:
            continue
        payload = meta.get("pending_article_clarification")
        if payload and payload.get("contexts"):
            return payload
    return None


def _extract_topic_tokens(text: str) -> list[str]:
    normalized = normalize_search_query(text).lower()
    tokens = re.findall(r"[a-z0-9][a-z0-9_\-\.]{1,}|[\u4e00-\u9fff]{2,8}", normalized)
    generic = {
        "文章", "论文", "资料", "教程", "博客",
        "article", "articles", "paper", "papers", "blog", "blogs",
        "engineering",
    }
    return [token for token in tokens if token not in generic]


def resolve_clarification_selection(message: str, payload: dict[str, Any]) -> dict[str, Any] | None:
    contexts = payload.get("contexts") or []
    if not contexts:
        return None

    text = (message or "").strip().lower()
    index = None
    explicit_index = re.search(r"第\s*([123])\s*组", text)
    if explicit_index:
        index = int(explicit_index.group(1)) - 1
    elif "刚刚" in text or "上一组" in text or "最新" in text:
        index = 0

    if index is None:
        message_tokens = set(_extract_topic_tokens(message))
        for idx, ctx in enumerate(contexts):
            ctx_tokens = set(_extract_topic_tokens(ctx.get("search_query", "")))
            if ctx_tokens and ctx_tokens.issubset(message_tokens):
                index = idx
                break
            if ctx_tokens and message_tokens and ctx_tokens & message_tokens:
                index = idx
                break

    if index is None or not (0 <= index < len(contexts)):
        return None

    return {
        "context": contexts[index],
        "action_targets": payload.get("action_targets") or [],
    }


def escape_markdown_text(text: str) -> str:
    value = re.sub(r"\s+", " ", (text or "")).strip()
    if not value:
        return ""
    specials = "\\`*_{}[]()#+-.!|>"
    escaped = []
    for ch in value:
        escaped.append(f"\\{ch}" if ch in specials else ch)
    return "".join(escaped)
