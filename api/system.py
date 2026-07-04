"""
api/system.py
==========================================================
系统端点
- GET /api/health         健康检查
- GET /api/system/config  公开配置
- GET /api/system/stats   系统统计
==========================================================
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from flask import Blueprint, jsonify

from common import *
from common import log, ok, err, db_query, db_query_one, now_iso

system_bp = Blueprint("system", __name__)


@system_bp.get("/api/health")
def health():
    """健康检查"""
    services = {"database": "unknown", "llm": "unknown", "search": "unknown"}
    overall = "ok"

    # DB 检查
    try:
        db_query_one("SELECT 1 AS x", [])
        services["database"] = "ok"
    except Exception as e:
        services["database"] = f"error: {e}"[:80]
        overall = "degraded"

    # LLM 检查（不实际调，浅查）
    services["llm"] = "ok" if Config.LLM_API_KEY else "no_api_key"

    # 搜索服务占位
    services["search"] = "ok" if Config.TAVILY_API_KEY else "no_api_key"

    return jsonify(ok({
        "status":    overall,
        "version":   "0.1.0",
        "services":  services,
        "timestamp": now_iso(),
    }))


@system_bp.get("/api/system/config")
def system_config():
    """公开配置（不含密钥）"""
    return jsonify(ok({
        "llm_model":        Config.LLM_MODEL,
        "context_window":   Config.CONTEXT_WINDOW_TOKENS,
        "warn_ratio":       Config.CONTEXT_WARN_RATIO,
        "compress_ratio":   Config.CONTEXT_COMPRESS_RATIO,
        "keep_recent":      Config.CONTEXT_KEEP_RECENT,
        "features": {
            "knowledge_base":  True,
            "blog":            True,
            "daily_report":    True,
            "task_tracking":   True,
            "semantic_search": True,
            "digest_subscription": True,
        },
    }))


@system_bp.get("/api/system/stats")
def system_stats():
    """系统统计（表行数）"""
    try:
        sess = db_query_one("SELECT COUNT(*) AS c FROM sessions", [])
        msg  = db_query_one("SELECT COUNT(*) AS c FROM messages", [])
        trc  = db_query_one("SELECT COUNT(*) AS c FROM trace_calls", [])
        art  = db_query_one("SELECT COUNT(*) AS c FROM knowledge_articles", [])
    except Exception as e:
        return jsonify(err(5002, f"DB 错误: {e}")), 500

    return jsonify(ok({
        "sessions":      sess["c"] if sess else 0,
        "messages":      msg["c"]  if msg  else 0,
        "trace_calls":   trc["c"]  if trc  else 0,
        "articles":      art["c"]  if art  else 0,
        "timestamp":     now_iso(),
    }))


# 兼容 Vercel
def handler(request):
    return system_bp.wsgi_app
