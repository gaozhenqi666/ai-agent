"""
api/tasks.py
==========================================================
后台任务查询端点
- GET /api/tasks/active
- GET /api/tasks/{id}
==========================================================
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Blueprint, request, jsonify

from common import ok, err
from tools.task_tracker_tool import get_active_task, get_task


tasks_bp = Blueprint("tasks", __name__)


@tasks_bp.get("/api/tasks/active")
def active_task():
    task_id = (request.args.get("task_id") or "").strip() or None
    session_id = (request.args.get("session_id") or "").strip() or None
    task = get_active_task(task_id=task_id, session_id=session_id)
    return jsonify(ok({"task": task}))


@tasks_bp.get("/api/tasks/<task_id>")
def task_detail(task_id):
    task = get_task(task_id)
    if not task:
        return jsonify(err(4040, "任务不存在")), 404
    return jsonify(ok({"task": task}))
