from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from agents.digest_agent import run_due_subscriptions  # noqa: E402
from common import Config  # noqa: E402


def main() -> int:
    if not Config.TURSO_URL:
        print("TURSO_URL 未配置，无法执行云端订阅任务", file=sys.stderr)
        return 2

    result = run_due_subscriptions()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
