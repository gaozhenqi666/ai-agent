"""
agents/runtime_cache.py
==========================================================
轻量缓存
- Tavily 搜索结果缓存
- 检索结果缓存
- 减少重复联网和重复上下文注入
==========================================================
"""

from __future__ import annotations

import json
import hashlib
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from common import db_exec, db_query_one, now_iso, log
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common import db_exec, db_query_one, now_iso, log


def _to_key(scope: str, raw_key: str) -> str:
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return f"{scope}:{digest}"


def cache_get(scope: str, raw_key: str):
    cache_key = _to_key(scope, raw_key)
    row = db_query_one("SELECT payload, expires_at FROM app_cache WHERE cache_key=?", [cache_key])
    if not row:
        return None

    expires_at = row.get("expires_at") or ""
    if expires_at and expires_at <= now_iso():
        try:
            db_exec("DELETE FROM app_cache WHERE cache_key=?", [cache_key])
        except Exception:
            pass
        return None

    try:
        return json.loads(row["payload"])
    except Exception:
        return None


def cache_set(scope: str, raw_key: str, payload, ttl_seconds: int = 900):
    cache_key = _to_key(scope, raw_key)
    now = datetime.now(timezone.utc)
    expires_at = datetime.fromtimestamp(now.timestamp() + ttl_seconds, timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    payload_text = json.dumps(payload, ensure_ascii=False)
    now_text = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    db_exec(
        """INSERT OR REPLACE INTO app_cache
           (cache_key, scope, payload, expires_at, created_at, updated_at)
           VALUES (
             ?,
             ?,
             ?,
             ?,
             COALESCE((SELECT created_at FROM app_cache WHERE cache_key=?), ?),
             ?
           )""",
        [cache_key, scope, payload_text, expires_at, cache_key, now_text, now_text],
    )


def cache_delete(scope: str, raw_key: str):
    db_exec("DELETE FROM app_cache WHERE cache_key=?", [_to_key(scope, raw_key)])
