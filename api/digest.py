"""
api/digest.py
==========================================================
定时订阅接口
- GET    /api/digest/subscriptions
- POST   /api/digest/subscriptions
- PATCH  /api/digest/subscriptions/{id}
- DELETE /api/digest/subscriptions/{id}
- POST   /api/digest/run
==========================================================
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Blueprint, jsonify, request

from common import err, ok, verify_internal_api_key
from agents.digest_agent import (
    create_subscription,
    delete_subscription,
    list_subscriptions as list_digest_subscriptions,
    run_due_subscriptions,
    run_enabled_subscriptions,
    run_subscription_by_id,
    update_subscription,
)


digest_bp = Blueprint("digest", __name__)


@digest_bp.get("/api/digest/subscriptions")
def list_subscriptions():
    return jsonify(ok({"items": list_digest_subscriptions()}))


@digest_bp.post("/api/digest/subscriptions")
def create_subscription_api():
    body = request.get_json(silent=True) or {}
    email = (body.get("email") or "").strip()
    query = (body.get("query") or "").strip()
    if not email or not query:
        return jsonify(err(4301, "email 和 query 必填")), 400

    item = create_subscription(
        email=email,
        query=query,
        schedule_cron=body.get("schedule_cron") or "0 9 * * *",
        timezone=body.get("timezone") or "Asia/Shanghai",
        max_results=body.get("max_results") or 5,
        send_to_feishu=bool(body.get("send_to_feishu", True)),
        send_email_notice=bool(body.get("send_email", True)),
        enabled=bool(body.get("enabled", True)),
        tags=body.get("tags") or [],
    )
    return jsonify(ok({"item": item})), 201


@digest_bp.patch("/api/digest/subscriptions/<subscription_id>")
def update_subscription_api(subscription_id: str):
    body = request.get_json(silent=True) or {}
    item = update_subscription(subscription_id, body)
    if not item:
        return jsonify(err(4304, "订阅不存在")), 404
    return jsonify(ok({"item": item}))


@digest_bp.delete("/api/digest/subscriptions/<subscription_id>")
def delete_subscription_api(subscription_id: str):
    if not delete_subscription(subscription_id):
        return jsonify(err(4304, "订阅不存在")), 404
    return jsonify(ok({"deleted": True, "subscription_id": subscription_id}))


@digest_bp.post("/api/digest/run")
def run_digest_api():
    internal_key = (
        request.headers.get("X-Internal-API-Key")
        or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    )
    if not verify_internal_api_key(internal_key):
        return jsonify(err(4303, "未授权的内部调用")), 403

    body = request.get_json(silent=True) or {}
    mode = (body.get("mode") or request.args.get("mode") or "due").strip().lower()
    subscription_id = (body.get("subscription_id") or request.args.get("subscription_id") or "").strip()
    force = bool(body.get("force", False))

    if subscription_id:
        try:
            result = run_subscription_by_id(subscription_id, force=force)
        except ValueError:
            return jsonify(err(4304, "订阅不存在")), 404
    elif mode == "all":
        result = run_enabled_subscriptions()
    else:
        result = run_due_subscriptions()
    return jsonify(ok(result))
