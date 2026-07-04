"""
agents/task_tracker.py
==========================================================
后台任务追踪
- 用于前端展示任务进度
- 支持跨页面轮询当前任务
- 任务继续执行时，状态会持续落库
==========================================================
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    from common import db_exec, db_query_one, db_query, new_id, now_iso, log
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common import db_exec, db_query_one, db_query, new_id, now_iso, log


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def create_task(
    session_id: str | None,
    trace_id: str | None,
    kind: str,
    title: str,
    detail: str = "",
    steps: list[dict] | None = None,
    can_interrupt: bool = True,
) -> str:
    task_id = new_id("task-")
    now = now_iso()
    db_exec(
        """INSERT INTO agent_tasks
           (task_id, session_id, trace_id, kind, status, title, current_step,
            detail, progress_json, can_interrupt, started_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
        [
            task_id,
            session_id,
            trace_id,
            kind,
            "running",
            title[:200],
            steps[0]["key"] if steps else None,
            detail[:500] if detail else "",
            json.dumps(steps or [], ensure_ascii=False),
            1 if can_interrupt else 0,
            now,
            now,
        ],
    )
    return task_id


def get_task(task_id: str) -> dict | None:
    row = db_query_one("SELECT * FROM agent_tasks WHERE task_id=?", [task_id])
    return _normalize_task(row) if row else None


def get_active_task(task_id: str | None = None, session_id: str | None = None) -> dict | None:
    sql = "SELECT * FROM agent_tasks WHERE status NOT IN ('completed','failed','cancelled')"
    params: list[str] = []
    if task_id:
        sql += " AND task_id=?"
        params.append(task_id)
    if session_id:
        sql += " AND session_id=?"
        params.append(session_id)
    sql += " ORDER BY updated_at DESC LIMIT 1"
    row = db_query_one(sql, params)
    return _normalize_task(row) if row else None


def update_task(
    task_id: str,
    *,
    status: str | None = None,
    current_step: str | None = None,
    detail: str | None = None,
    result: dict | None = None,
    error_message: str | None = None,
) -> None:
    task = db_query_one("SELECT * FROM agent_tasks WHERE task_id=?", [task_id])
    if not task:
        return

    fields = []
    params = []
    now = now_iso()

    if status is not None:
        fields.append("status=?")
        params.append(status)
    if current_step is not None:
        fields.append("current_step=?")
        params.append(current_step)
    if detail is not None:
        fields.append("detail=?")
        params.append(detail[:500])
    if result is not None:
        fields.append("result_json=?")
        params.append(json.dumps(result, ensure_ascii=False))
    if error_message is not None:
        fields.append("error_message=?")
        params.append(error_message[:500])

    fields.append("updated_at=?")
    params.append(now)
    if status in TERMINAL_STATUSES:
        fields.append("finished_at=?")
        params.append(now)

    params.append(task_id)
    db_exec(f"UPDATE agent_tasks SET {', '.join(fields)} WHERE task_id=?", params)


def update_task_step(
    task_id: str,
    *,
    step_key: str,
    label: str,
    status: str,
    detail: str = "",
    agent: str = "",
    url: str = "",
    title: str = "",
) -> None:
    row = db_query_one("SELECT progress_json FROM agent_tasks WHERE task_id=?", [task_id])
    if not row:
        return

    try:
        steps = json.loads(row.get("progress_json") or "[]")
    except Exception:
        steps = []

    found = False
    now = now_iso()
    for item in steps:
        if item.get("key") == step_key:
            item.update({
                "label": label,
                "status": status,
                "detail": detail[:300],
                "agent": agent,
                "url": url,
                "title": title,
                "updated_at": now,
            })
            found = True
            break

    if not found:
        steps.append({
            "key": step_key,
            "label": label,
            "status": status,
            "detail": detail[:300],
            "agent": agent,
            "url": url,
            "title": title,
            "updated_at": now,
        })

    db_exec(
        """UPDATE agent_tasks
           SET current_step=?, progress_json=?, updated_at=?
           WHERE task_id=?""",
        [step_key, json.dumps(steps, ensure_ascii=False), now, task_id],
    )


def complete_task(task_id: str, detail: str = "", result: dict | None = None) -> None:
    update_task(task_id, status="completed", detail=detail, result=result)


def fail_task(task_id: str, error_message: str, detail: str = "") -> None:
    update_task(task_id, status="failed", detail=detail or error_message, error_message=error_message)


def cancel_task(task_id: str, reason: str = "任务已手动中断") -> None:
    update_task(task_id, status="cancelled", detail=reason, error_message=reason)


def attach_task_to_message_meta(meta: dict | None, task_id: str | None) -> dict:
    payload = dict(meta or {})
    if task_id:
        payload["task_id"] = task_id
    return payload


def _normalize_task(row: dict) -> dict:
    task = dict(row)
    for key in ("progress_json", "result_json"):
        try:
            task[key] = json.loads(task[key]) if task.get(key) else []
        except Exception:
            task[key] = []
    task["can_interrupt"] = bool(task.get("can_interrupt"))
    task["steps"] = task.pop("progress_json", [])
    task["result"] = task.pop("result_json", [])
    return task
