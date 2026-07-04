"""
api/sessions.py
==========================================================
会话管理端点
- GET    /api/sessions                 列出
- POST   /api/sessions                 新建
- GET    /api/sessions/{id}            详情
- PATCH  /api/sessions/{id}            更新（标题/归档）
- DELETE /api/sessions/{id}            删除
- GET    /api/sessions/{id}/messages   消息历史
- POST   /api/sessions/{id}/compress   立即压缩
- POST   /api/sessions/{id}/clear      清空
- GET    /api/sessions/{id}/export     导出
==========================================================
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
from flask import Blueprint, request, jsonify

from common import *
from common import log, ok, err, E, db_query, db_exec, new_id, now_iso, truncate
from tools.task_tracker_tool import get_active_task, cancel_task

sessions_bp = Blueprint("sessions", __name__)


@sessions_bp.get("/api/sessions")
def list_sessions():
    """列出所有会话（按 last_active DESC）"""
    limit  = int(request.args.get("limit", 20))
    offset = int(request.args.get("offset", 0))
    archived = request.args.get("is_archived", "false").lower() == "true"

    rows = db_query(
        """SELECT s.session_id, s.title, s.created_at, s.last_active,
                  s.total_tokens, s.message_count, s.is_archived,
                  (SELECT content FROM messages m
                   WHERE m.session_id = s.session_id
                   ORDER BY m.created_at DESC LIMIT 1) AS last_message,
                  (SELECT role FROM messages m
                   WHERE m.session_id = s.session_id
                   ORDER BY m.created_at DESC LIMIT 1) AS last_role
           FROM sessions s
           WHERE s.is_archived = ?
           ORDER BY s.last_active DESC
           LIMIT ? OFFSET ?""",
        [1 if archived else 0, limit, offset],
    )

    sessions = []
    for r in rows:
        sessions.append({
            "session_id":            r["session_id"],
            "title":                 r["title"],
            "created_at":            r["created_at"],
            "last_active":           r["last_active"],
            "message_count":         r["message_count"],
            "is_archived":           bool(r["is_archived"]),
            "last_message_preview":  truncate(r["last_message"] or "", 60),
            "last_message_role":     r["last_role"],
        })

    return jsonify(ok({"total": len(sessions), "limit": limit, "offset": offset, "sessions": sessions}))


@sessions_bp.post("/api/sessions")
def create_session():
    """新建一个空会话"""
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "新会话").strip()[:100]
    sid = new_id("sess-")
    now = now_iso()
    db_exec(
        "INSERT INTO sessions (session_id, title, created_at, last_active) VALUES (?,?,?,?)",
        [sid, title, now, now],
    )
    return jsonify(ok({"session_id": sid, "title": title, "created_at": now}))


@sessions_bp.get("/api/sessions/<session_id>")
def get_session(session_id):
    """会话详情"""
    sess = db_query_one("SELECT * FROM sessions WHERE session_id=?", [session_id])
    if not sess:
        return jsonify(err(E.SESSION_NOT_FOUND, f"会话不存在: {session_id}")), 404
    sess["is_archived"] = bool(sess.get("is_archived"))
    return jsonify(ok(sess))


@sessions_bp.patch("/api/sessions/<session_id>")
def update_session(session_id):
    """更新会话（标题 / 归档）"""
    body = request.get_json(silent=True) or {}
    if not db_query_one("SELECT 1 FROM sessions WHERE session_id=?", [session_id]):
        return jsonify(err(E.SESSION_NOT_FOUND, "会话不存在")), 404

    fields, params = [], []
    if "title" in body:
        fields.append("title=?")
        params.append(str(body["title"])[:100])
    if "is_archived" in body:
        fields.append("is_archived=?")
        params.append(1 if body["is_archived"] else 0)

    if not fields:
        return jsonify(err(4002, "没有可更新字段"))

    params.append(session_id)
    db_exec(f"UPDATE sessions SET {', '.join(fields)} WHERE session_id=?", params)
    return jsonify(ok({"updated": True}))


@sessions_bp.delete("/api/sessions/<session_id>")
def delete_session(session_id):
    """删除会话（级联删除 messages + trace_calls）"""
    msg_count = db_query_one("SELECT COUNT(*) AS c FROM messages WHERE session_id=?", [session_id])
    # 显式级联删除（SQLite 外键不一定开启）
    db_exec("DELETE FROM messages WHERE session_id=?", [session_id])
    db_exec("DELETE FROM sessions WHERE session_id=?", [session_id])
    return jsonify(ok({"deleted": True, "deleted_messages": msg_count["c"] if msg_count else 0}))


@sessions_bp.get("/api/sessions/<session_id>/messages")
def get_messages(session_id):
    """获取会话的所有消息"""
    limit = int(request.args.get("limit", 100))
    if not db_query_one("SELECT 1 FROM sessions WHERE session_id=?", [session_id]):
        return jsonify(err(E.SESSION_NOT_FOUND, "会话不存在")), 404

    rows = db_query(
        "SELECT * FROM messages WHERE session_id=? ORDER BY created_at ASC LIMIT ?",
        [session_id, limit],
    )
    sess = db_query_one("SELECT total_tokens FROM sessions WHERE session_id=?", [session_id])
    total_tokens = sess["total_tokens"] if sess else 0

    if total_tokens >= 100_000 * 1.0:
        warning = "force_compress"
    elif total_tokens >= 100_000 * 0.5:
        warning = "should_compress"
    elif total_tokens >= 100_000 * 0.3:
        warning = "info"
    else:
        warning = None

    return jsonify(ok({
        "session_id":     session_id,
        "total_tokens":   total_tokens,
        "message_count":  len(rows),
        "warning_level":  warning,
        "messages":       [dict(r) for r in rows],
    }))


@sessions_bp.post("/api/sessions/<session_id>/clear")
def clear_session(session_id):
    """清空会话的所有消息（保留 session 本身）"""
    if not db_query_one("SELECT 1 FROM sessions WHERE session_id=?", [session_id]):
        return jsonify(err(E.SESSION_NOT_FOUND, "会话不存在")), 404
    db_exec("DELETE FROM messages WHERE session_id=?", [session_id])
    db_exec("UPDATE sessions SET total_tokens=0, message_count=0 WHERE session_id=?", [session_id])
    return jsonify(ok({"cleared": True}))


@sessions_bp.post("/api/sessions/<session_id>/compress")
def compress_session(session_id):
    """
    立即压缩（M1 占位：用 LLM 摘要老消息，删除老的，插入 1 条 system 摘要）
    """
    if not db_query_one("SELECT 1 FROM sessions WHERE session_id=?", [session_id]):
        return jsonify(err(E.SESSION_NOT_FOUND, "会话不存在")), 404

    keep_recent = 10
    rows = db_query(
        "SELECT * FROM messages WHERE session_id=? ORDER BY created_at ASC",
        [session_id],
    )
    if len(rows) <= keep_recent:
        return jsonify(ok({"compressed": False, "reason": "no_need"}))

    old_msgs = [dict(r) for r in rows[:-keep_recent]]
    recent   = rows[-keep_recent:]

    # 1) 调 LLM 摘要（M1 占位：直接拼凑，避免卡 M1）
    from common import llm_chat
    old_text = "\n".join([f"[{m['role']}] {m['content'][:200]}" for m in old_msgs])
    try:
        summary = llm_chat([{
            "role": "user",
            "content": f"请把以下对话历史压缩成 3-5 句中文摘要，保留关键信息：\n\n{old_text}"
        }], temperature=0.3, max_tokens=400)["content"]
    except Exception as e:
        log.warning(f"[compress] LLM 摘要失败，用截断代替: {e}")
        summary = f"（已压缩 {len(old_msgs)} 条消息的摘要）"

    # 2) 删老的
    old_ids = [m["message_id"] for m in old_msgs]
    placeholders = ",".join(["?"] * len(old_ids))
    db_exec(f"DELETE FROM messages WHERE message_id IN ({placeholders})", old_ids)

    # 3) 插一条 system 摘要
    summary_id = new_id("msg-")
    db_exec(
        """INSERT INTO messages (message_id, session_id, role, content, tokens, created_at)
           VALUES (?,?,?,?,?,?)""",
        [summary_id, session_id, "system", f"## 前面对话的摘要\n{summary}", 0, now_iso()],
    )

    # 4) 更新 session
    db_exec(
        """UPDATE sessions
           SET total_tokens = (SELECT COALESCE(SUM(tokens),0) FROM messages WHERE session_id=?),
               message_count = (SELECT COUNT(*) FROM messages WHERE session_id=?)
           WHERE session_id=?""",
        [session_id, session_id, session_id],
    )

    new_sess = db_query_one("SELECT total_tokens FROM sessions WHERE session_id=?", [session_id])
    return jsonify(ok({
        "compressed":        True,
        "summary_message_id":summary_id,
        "kept_messages":     len(recent) + 1,
        "new_tokens":        new_sess["total_tokens"] if new_sess else 0,
    }))


@sessions_bp.get("/api/sessions/<session_id>/export")
def export_session(session_id):
    """导出整个会话为 Markdown"""
    sess = db_query_one("SELECT * FROM sessions WHERE session_id=?", [session_id])
    if not sess:
        return jsonify(err(E.SESSION_NOT_FOUND, "会话不存在")), 404
    rows = db_query(
        "SELECT * FROM messages WHERE session_id=? ORDER BY created_at ASC",
        [session_id],
    )

    md_lines = [f"# {sess['title']}\n", f"_导出于 {now_iso()}_\n"]
    for r in rows:
        role_cn = {"user": "用户", "assistant": "助手", "system": "系统"}.get(r["role"], r["role"])
        md_lines.append(f"\n## {role_cn} · {r['created_at']}\n\n{r['content']}\n")

    return jsonify(ok({
        "filename": f"session-{session_id}.md",
        "content":  "\n".join(md_lines),
    }))


# ---------- 回退（撤销到某条消息之前）----------
@sessions_bp.post("/api/sessions/<session_id>/rollback/<message_id>")
def rollback_session(session_id, message_id):
    """
    回退到指定消息之前：
    1. 删除该消息及之后的所有消息
    2. 清理这些消息产生的侧效应（知识库文章、博客文章）
    3. 更新 session 统计
    """
    sess = db_query_one("SELECT * FROM sessions WHERE session_id=?", [session_id])
    if not sess:
        return jsonify(err(E.SESSION_NOT_FOUND, "会话不存在")), 404

    # 找到目标消息的 created_at
    target = db_query_one(
        "SELECT created_at FROM messages WHERE message_id=? AND session_id=?",
        [message_id, session_id],
    )
    if not target:
        return jsonify(err(4002, "消息不存在")), 404

    # 收集所有 >= target_ts 的消息（用于清理侧效应和后续删除）
    # 使用子查询先找到所有要删除的 message_id，避免 created_at 字符串比较问题
    target_ts = target["created_at"]
    rows = db_query(
        """SELECT message_id, meta, role
           FROM messages
           WHERE session_id=? AND created_at >= ?
           ORDER BY created_at ASC""",
        [session_id, target_ts],
    )

    removed_knowledge = []
    removed_articles = []
    msg_ids_to_delete = []
    for r in rows:
        msg_ids_to_delete.append(r["message_id"])
        if r["role"] == "assistant" and r["meta"]:
            try:
                meta = json.loads(r["meta"])
            except Exception:
                meta = {}
            for kid in meta.get("knowledge_ids", []):
                db_exec("DELETE FROM knowledge_chunks WHERE article_id=?", [kid])
                db_exec("DELETE FROM knowledge_articles WHERE article_id=?", [kid])
                removed_knowledge.append(kid)
            for aid in meta.get("article_ids", []):
                db_exec("DELETE FROM articles WHERE article_id=?", [aid])
                removed_articles.append(aid)

    # 用 message_id 精确删除（避免 created_at 字符串比较在 Turso 上失效）
    deleted_count = 0
    if msg_ids_to_delete:
        placeholders = ",".join(["?"] * len(msg_ids_to_delete))
        result = db_exec(
            f"DELETE FROM messages WHERE message_id IN ({placeholders})",
            msg_ids_to_delete,
        )
        # Turso libsql_client ResultSet 用 len(rows) 获取影响行数
        deleted_count = len(result.rows) if hasattr(result, 'rows') and result.rows else len(msg_ids_to_delete)
    else:
        deleted_count = 0

    # 更新 session 统计
    db_exec(
        """UPDATE sessions
           SET total_tokens = (SELECT COALESCE(SUM(tokens),0) FROM messages WHERE session_id=?),
               message_count = (SELECT COUNT(*) FROM messages WHERE session_id=?)
           WHERE session_id=?""",
        [session_id, session_id, session_id],
    )

    log.info(f"[rollback] session={session_id} target={message_id} "
             f"deleted_messages={deleted_count} removed_knowledge={len(removed_knowledge)} removed_articles={len(removed_articles)}")

    return jsonify(ok({
        "rollback_to": message_id,
        "deleted_messages": deleted_count,
        "removed_knowledge_articles": removed_knowledge,
        "removed_blog_articles": removed_articles,
    }))


# ---------- 中断当前正在执行的任务 ----------
@sessions_bp.post("/api/sessions/<session_id>/interrupt")
def interrupt_session(session_id):
    """
    中断当前会话正在执行的任务（用户点编辑→重发时调用）
    1. 找到最新一条 assistant 消息前创建的知识库文章和博客文章，清理它们
    2. 如果 assistant 消息不存在（还没入库），清理最近一条 user 消息之后创建的资源
    3. 不删除消息本身
    """
    sess = db_query_one("SELECT * FROM sessions WHERE session_id=?", [session_id])
    if not sess:
        return jsonify(err(E.SESSION_NOT_FOUND, "会话不存在")), 404

    # 找到最后一条 user 消息的时间
    last_user = db_query_one(
        "SELECT message_id, created_at FROM messages WHERE session_id=? AND role='user' ORDER BY created_at DESC LIMIT 1",
        [session_id],
    )
    if not last_user:
        return jsonify(ok({"cleaned": False, "reason": "没有可中断的任务"}))

    active_task = get_active_task(session_id=session_id)
    if active_task and active_task.get("can_interrupt"):
        cancel_task(active_task["task_id"], reason="用户手动中断任务")

    # 收集 user 消息之后创建的 assistant 消息的 meta
    rows = db_query(
        """SELECT message_id, meta, role FROM messages
           WHERE session_id=? AND created_at >= ?
           ORDER BY created_at ASC""",
        [session_id, last_user["created_at"]],
    )

    cleaned_knowledge = 0
    cleaned_articles = 0
    for r in rows:
        if r["role"] == "assistant" and r["meta"]:
            try:
                meta = json.loads(r["meta"])
            except Exception:
                meta = {}
            for kid in meta.get("knowledge_ids", []):
                try:
                    db_exec("DELETE FROM knowledge_chunks WHERE article_id=?", [kid])
                    db_exec("DELETE FROM knowledge_articles WHERE article_id=?", [kid])
                    cleaned_knowledge += 1
                except Exception:
                    pass
            for aid in meta.get("article_ids", []):
                try:
                    db_exec("DELETE FROM articles WHERE article_id=?", [aid])
                    cleaned_articles += 1
                except Exception:
                    pass

    # 检查是否已有 assistant 消息（如果流式已正常完成）
    last_asst = db_query_one(
        "SELECT message_id FROM messages WHERE session_id=? AND role='assistant' AND created_at >= ? ORDER BY created_at DESC LIMIT 1",
        [session_id, last_user["created_at"]],
    )

    if not last_asst:
        # 流式被中断，还没有 assistant 消息 → 写入"任务已中断"
        interrupted_content = "任务已中断：用户手动停止了当前执行流程。"
        msg_id = new_id("msg-")
        meta = json.dumps({
            "knowledge_ids": [],
            "article_ids": [],
            "interrupted": True,
            "interrupted_reason": "user_cancelled",
        }, ensure_ascii=False)
        now = now_iso()
        db_exec(
            """INSERT INTO messages (message_id, session_id, role, content, trace_id, tokens, meta, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            [msg_id, session_id, "assistant", interrupted_content,
             new_id("trace-"), count_tokens(interrupted_content), meta, now],
        )
        # 更新 session
        db_exec(
            """UPDATE sessions
               SET total_tokens = (SELECT COALESCE(SUM(tokens),0) FROM messages WHERE session_id=?),
                   message_count = (SELECT COUNT(*) FROM messages WHERE session_id=?),
                   last_active = ?
               WHERE session_id=?""",
            [session_id, session_id, now, session_id],
        )

    # 也检查最新 user 之后的最近知识库文章（可能没通过 meta 追踪到的）
    # 检查 knowledge_articles 表中在 last_user 时间之后创建的且没有被 meta 引用的
    recent_knowledge = db_query(
        "SELECT article_id FROM knowledge_articles WHERE created_at >= ?",
        [last_user["created_at"]],
    )
    for k in recent_knowledge:
        try:
            db_exec("DELETE FROM knowledge_chunks WHERE article_id=?", [k["article_id"]])
            db_exec("DELETE FROM knowledge_articles WHERE article_id=?", [k["article_id"]])
            cleaned_knowledge += 1
        except Exception:
            pass

    log.info(f"[interrupt] session={session_id} cleaned_knowledge={cleaned_knowledge} cleaned_articles={cleaned_articles}")
    return jsonify(ok({
        "cleaned": True,
        "cleaned_knowledge": cleaned_knowledge,
        "cleaned_articles": cleaned_articles,
        "interrupted_message_added": last_asst is None,
        "active_task_id": active_task["task_id"] if active_task else None,
    }))


# 兼容 Vercel
def handler(request):
    return sessions_bp.wsgi_app
