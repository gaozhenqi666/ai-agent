"""
api/articles.py
==========================================================
用户生成的博客文章端点
- GET    /api/articles                 列表
- GET    /api/articles/{id}            详情
- PATCH  /api/articles/{id}            更新
- DELETE /api/articles/{id}            删除
==========================================================
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flask import Blueprint, request, jsonify
from common import *
from common import log, ok, err, E, db_query, db_query_one, db_exec

articles_bp = Blueprint("articles", __name__)


@articles_bp.get("/api/articles")
def list_articles():
    """列出所有用户生成的文章"""
    limit = int(request.args.get("limit", 20))
    offset = int(request.args.get("offset", 0))
    status = request.args.get("status", "draft")
    search = (request.args.get("search") or "").strip()
    sort = request.args.get("sort", "updated")

    sql = """SELECT article_id, title, status, created_at, updated_at,
                    SUBSTR(content, 1, 200) AS preview
             FROM articles
             WHERE 1=1"""
    params = []
    if status != "all":
        sql += " AND status = ?"
        params.append(status)
    if search:
        sql += " AND (title LIKE ? OR content LIKE ?)"
        params.extend([f"%{search}%", f"%{search}%"])

    if sort == "created":
        sql += " ORDER BY created_at DESC"
    elif sort == "title":
        sql += " ORDER BY title COLLATE NOCASE ASC, updated_at DESC"
    else:
        sql += " ORDER BY updated_at DESC, created_at DESC"

    sql += " LIMIT ? OFFSET ?"
    params.extend([limit, offset])

    rows = db_query(sql, params)

    return jsonify(ok({
        "total": len(rows),
        "items": [dict(r) for r in rows],
    }))


@articles_bp.post("/api/articles")
def create_article():
    body = request.get_json(silent=True) or {}
    title = (body.get("title") or "未命名文章").strip()[:200]
    content = body.get("content") or "# 新文章\n\n"
    status = body.get("status") or "draft"
    article_id = new_id("art-")
    now = now_iso()
    db_exec(
        """INSERT INTO articles (article_id, title, content, status, created_at, updated_at)
           VALUES (?,?,?,?,?,?)""",
        [article_id, title, content, status, now, now],
    )
    return jsonify(ok({"article_id": article_id, "title": title, "created_at": now})), 201


@articles_bp.get("/api/articles/<article_id>")
def get_article(article_id):
    """获取单篇文章详情"""
    row = db_query_one("SELECT * FROM articles WHERE article_id=?", [article_id])
    if not row:
        return jsonify(err(4001, "文章不存在")), 404
    return jsonify(ok({"item": dict(row)}))


@articles_bp.patch("/api/articles/<article_id>")
def update_article(article_id):
    """更新文章"""
    body = request.get_json(silent=True) or {}
    if not db_query_one("SELECT 1 FROM articles WHERE article_id=?", [article_id]):
        return jsonify(err(4001, "文章不存在")), 404

    fields, params = [], []
    if "title" in body:
        fields.append("title=?")
        params.append(str(body["title"])[:200])
    if "content" in body:
        fields.append("content=?")
        params.append(body["content"])
    if "status" in body:
        fields.append("status=?")
        params.append(body["status"])

    if not fields:
        return jsonify(err(4002, "没有可更新字段"))

    from common import now_iso
    fields.append("updated_at=?")
    params.append(now_iso())
    params.append(article_id)

    db_exec(f"UPDATE articles SET {', '.join(fields)} WHERE article_id=?", params)
    return jsonify(ok({"updated": True}))


@articles_bp.delete("/api/articles/<article_id>")
def delete_article(article_id):
    """删除文章"""
    if not db_query_one("SELECT 1 FROM articles WHERE article_id=?", [article_id]):
        return jsonify(err(4001, "文章不存在")), 404

    db_exec("DELETE FROM articles WHERE article_id=?", [article_id])
    log.info(f"[articles] 已删除文章: {article_id}")
    return jsonify(ok({"deleted": True, "article_id": article_id}))


# ==========================================================
# AI 文章编辑（SSE 流式）
# ==========================================================
@articles_bp.post("/api/articles/<article_id>/ai-edit/stream")
def ai_edit_article_stream(article_id):
    """
    AI 文章编辑：用户框选文章中的内容，给出修改指令，AI 流式返回修改后的完整文章。
    入参 JSON:
        {
            "selected_text": "用户框选的内容（原文）",
            "instruction":   "用户的修改指令",
            "full_content":  "当前完整文章内容（用于上下文）"
        }
    返回: SSE 流
        event: start   - {article_id}
        event: content - {delta: "..."}（逐字流式）
        event: done    - {total_chars}
        event: error   - {message}
    """
    from flask import Response, stream_with_context
    from common import get_llm, Config, count_tokens, log
    from tools.security_tool import detect_injection, sanitize_input, audit_output

    body = request.get_json(silent=True) or {}
    selected = (body.get("selected_text") or "").strip()
    instruction = (body.get("instruction") or "").strip()
    full_content = (body.get("full_content") or "").strip()

    if not selected:
        return jsonify(err(4003, "selected_text 不能为空")), 400
    if not instruction:
        return jsonify(err(4004, "instruction 不能为空")), 400
    if not full_content:
        return jsonify(err(4005, "full_content 不能为空")), 400
    if len(selected) > 4000 or len(instruction) > 1000 or len(full_content) > 50000:
        return jsonify(err(4006, "输入过长，已触发编辑安全熔断")), 400

    attack = detect_injection(instruction) or detect_injection(selected)
    if attack:
        return jsonify(err(4007, f"检测到危险指令：{attack['reason']}")), 400

    # 验证文章存在
    if not db_query_one("SELECT 1 FROM articles WHERE article_id=?", [article_id]):
        return jsonify(err(4001, "文章不存在")), 404

    # 构造 prompt
    system_prompt = (
        "你是一位专业的文章编辑助手。用户会给你：\n"
        "1. 整篇文章的完整内容（仅作上下文参考）\n"
        "2. 用户在文章中框选出来的一段需要修改的文字\n"
        "3. 用户的修改指令\n\n"
        "请根据用户的指令，仅输出修改后的那段框选文字（不是整篇文章）。\n\n"
        "要求：\n"
        "- 只输出修改后的框选内容，不要输出整篇文章\n"
        "- 保留原内容的 Markdown 格式（如原来有标题、加粗等格式要保留）\n"
        "- 不要加任何解释、前缀或后缀，直接输出修改后的文字\n"
        "- 输出内容的长度应与原内容接近，不要大幅增减\n"
    )
    user_prompt = f"""【整篇文章上下文】
{full_content}

【用户框选的内容（需要修改的部分）】
{selected}

【用户的修改指令】
{sanitize_input(instruction)}

请直接输出修改后的框选内容。"""

    def generate():
        try:
            yield f"event: start\ndata: {json_dumps_safe({'article_id': article_id, 'selected_length': len(selected), 'instruction': instruction[:200]})}\n\n"

            client = get_llm()
            stream = client.chat.completions.create(
                model=Config.LLM_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=min(Config.LLM_MAX_TOKENS, 8000),
                stream=True,
            )

            total_chars = 0
            output_chunks: list[str] = []
            for chunk in stream:
                try:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if delta and delta.content:
                            text = delta.content
                            total_chars += len(text)
                            output_chunks.append(text)
                            if total_chars > 10000:
                                raise RuntimeError("AI 编辑输出过长，已触发安全熔断")
                            yield f"event: content\ndata: {json_dumps_safe({'delta': text})}\n\n"
                except Exception as e:
                    log.warning(f"[ai-edit] chunk 解析失败: {e}")
                    continue

            audit = audit_output("".join(output_chunks))
            if not audit["safe"]:
                raise RuntimeError("AI 编辑结果触发安全审计，已拦截输出")

            yield f"event: done\ndata: {json_dumps_safe({'total_chars': total_chars})}\n\n"
        except Exception as e:
            log.error(f"[ai-edit] 流式失败: {e}")
            yield f"event: error\ndata: {json_dumps_safe({'message': str(e)})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def json_dumps_safe(obj):
    import json
    return json.dumps(obj, ensure_ascii=False)
