from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.digest_agent import create_subscription, list_subscriptions, update_subscription  # noqa: E402


DEFAULT_EMAIL = "3556045497@qq.com"
DEFAULT_QUERY = "AI 行业前沿技术 文章"
DEFAULT_CRON = "30 7 * * *"
DEFAULT_TIMEZONE = "Asia/Shanghai"
DEFAULT_MAX_RESULTS = 5
DEFAULT_TAGS = ["default", "ai-frontier"]


def main() -> int:
    matched = None
    for item in list_subscriptions():
        if (item.get("email") or "").strip() == DEFAULT_EMAIL and "AI" in (item.get("query") or ""):
            matched = item
            break

    payload = {
        "email": DEFAULT_EMAIL,
        "query": DEFAULT_QUERY,
        "schedule_cron": DEFAULT_CRON,
        "timezone": DEFAULT_TIMEZONE,
        "max_results": DEFAULT_MAX_RESULTS,
        "send_to_feishu": True,
        "send_email_notice": True,
        "enabled": True,
        "tags": DEFAULT_TAGS,
    }

    if matched:
        update_payload = {
            **payload,
            "send_email": payload["send_email_notice"],
        }
        update_payload.pop("send_email_notice", None)
        item = update_subscription(matched["subscription_id"], update_payload) or matched
        print(json.dumps({"mode": "updated", "item": item}, ensure_ascii=False, indent=2))
        return 0

    item = create_subscription(**payload)
    print(json.dumps({"mode": "created", "item": item}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
