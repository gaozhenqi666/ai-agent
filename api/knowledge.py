"""
api/knowledge.py
==========================================================
知识库端点
- GET    /api/knowledge/articles              列表
- POST   /api/knowledge/articles              新增
- GET    /api/knowledge/articles/{id}         详情
- PATCH  /api/knowledge/articles/{id}         更新
- DELETE /api/knowledge/articles/{id}         删除
- POST   /api/knowledge/search                语义检索（M2 TODO）
- GET    /api/knowledge/stats                 统计
- POST   /api/ai/rewrite                      AI 改写（编辑器用）
==========================================================
"""

from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import json
import time
from flask import Blueprint, request, jsonify

from common import *
from common import log, ok, err, E, db_query, db_exec, new_id, now_iso, count_tokens, llm_chat, Config

knowledge_bp = Blueprint("knowledge", __name__)


# ---------- 1. 列表 ----------
@knowledge_bp.get("/api/knowledge/articles")
def list_articles():
    """列出知识库文章"""
    limit  = int(request.args.get("limit", 20))
    offset = int(request.args.get("offset", 0))
    tag    = request.args.get("tag")
    source = request.args.get("source")
    search = request.args.get("search")
    status = request.args.get("status")  # 不默认过滤状态
    sort   = request.args.get("sort", "latest")

    sql    = "SELECT * FROM knowledge_articles WHERE 1=1"
    params = []

    if status:
        sql += " AND status=?"
        params.append(status)

    if tag:
        sql += " AND tags LIKE ?"
        params.append(f'%"{tag}"%')
    if source:
        sql += " AND source=?"
        params.append(source)
    if search:
        sql += " AND (title LIKE ? OR summary LIKE ?)"
        params += [f"%{search}%", f"%{search}%"]

    if sort == "most_cited":
        sql += " ORDER BY view_count DESC, created_at DESC"
    elif sort == "most_relevant":
        # M1 占位：按更新时间排序（M2 接入向量检索）
        sql += " ORDER BY updated_at DESC"
    else:
        sql += " ORDER BY created_at DESC"

    sql += " LIMIT ? OFFSET ?"
    params += [limit, offset]

    rows = db_query(sql, params)

    items = []
    for r in rows:
        items.append({
            "article_id":    r["article_id"],
            "title":         r["title"],
            "url":           r["url"],
            "summary":       r["summary"],
            "source":        r["source"],
            "tags":          json.loads(r["tags"]) if r["tags"] else [],
            "status":        r["status"],
            "view_count":    r["view_count"],
            "published_at":  r["published_at"],
            "created_at":    r["created_at"],
            "updated_at":    r["updated_at"],
        })

    return jsonify(ok({"total": len(items), "items": items}))


# ---------- 2. 详情 ----------
@knowledge_bp.get("/api/knowledge/articles/<article_id>")
def get_article(article_id):
    row = db_query_one("SELECT * FROM knowledge_articles WHERE article_id=?", [article_id])
    if not row:
        return jsonify(err(3002, "文章不存在")), 404

    # 增加 view_count
    db_exec("UPDATE knowledge_articles SET view_count=view_count+1 WHERE article_id=?", [article_id])

    row["tags"] = json.loads(row["tags"]) if row["tags"] else []
    return jsonify(ok(row))


# ---------- 3. 新增 ----------
@knowledge_bp.post("/api/knowledge/articles")
def create_article():
    body = request.get_json(silent=True) or {}
    if not body.get("title") or not body.get("content"):
        return jsonify(err(3001, "title 和 content 必填"))

    # === 内容质量检查（防止 AI 话术 / 反爬页入库）===
    from agents.scraper import _validate_article_content
    content = body["content"]
    if len(content) < 500:
        return jsonify(err(3004, f"内容过短（{len(content)} 字符），拒绝入库"))
    quality = _validate_article_content(content)
    if not quality["valid"]:
        log.warning(f"[knowledge/create] ⚠️ 拒绝入库（{body.get('title')}）：{quality['reason']}")
        return jsonify(err(3004, f"内容质量不合格：{quality['reason']}"))

    aid = new_id("art-")
    now = now_iso()
    tags = body.get("tags") or []
    if not isinstance(tags, list):
        return jsonify(err(3001, "tags 必须是 list"))

    db_exec(
        """INSERT INTO knowledge_articles
           (article_id, title, url, content, summary, source, tags, status, published_at, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [aid, body["title"], body.get("url"), content,
         content[:200], body.get("source", "Manual"),
         json.dumps(tags, ensure_ascii=False), body.get("status", "draft"),
         body.get("published_at") or now, now, now],
    )

    # 异步切分 + 存 chunks（M1 先同步：等切分完成才返回）
    chunk_count = 0
    try:
        from agents.chunker import recursive_split
        from agents.retriever import save_chunks
        chunks = recursive_split(content, chunk_size=500, overlap=50)
        chunk_count = save_chunks(aid, chunks)
        log.info(f"[knowledge/create] 文章 {aid} 切成 {chunk_count} 个 chunks")
    except Exception as e:
        log.error(f"[knowledge/create] 切分失败: {e}")
        # 仍然返回成功，文章已存；chunks 失败可以后补

    return jsonify(ok({
        "article_id":            aid,
        "chunk_count":           chunk_count,
        "embedding_generated":   chunk_count > 0,
        "created_at":            now,
    })), 201


# ---------- 3.5 URL 导入（爬取+切片+嵌入） ----------
@knowledge_bp.post("/api/knowledge/import")
def import_from_url():
    """
    Body: { "url": "https://..." }
    流程: 爬取网页 → 存文章 → 切片 → 嵌入向量
    """
    body = request.get_json(silent=True) or {}
    url = (body.get("url") or "").strip()
    if not url:
        return jsonify(err(3001, "url 必填"))

    # 1) 爬取
    from agents.scraper import scrape_url
    result = scrape_url(url)

    if not result["success"]:
        error_msg = result.get("error", "未知错误")
        if result.get("anti_scraping"):
            return jsonify(err(3002, f"⚠️ 反爬检测: {error_msg}"))
        return jsonify(err(3003, f"抓取失败: {error_msg}"))

    # 2) 存文章
    aid = new_id("art-")
    now = now_iso()
    title = result["title"]
    content = result["content"]
    author = result.get("author", "")
    domain = result.get("domain", "")

    db_exec(
        """INSERT INTO knowledge_articles
           (article_id, title, url, content, summary, source, tags, status, published_at, created_at, updated_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        [aid, title, url, content,
         content[:200], f"爬取-{domain}",
         json.dumps(["爬取", domain], ensure_ascii=False), "draft",
         now, now, now],
    )

    # 3) 切片 + 嵌入
    chunk_count = 0
    try:
        from agents.chunker import recursive_split
        from agents.retriever import save_chunks
        chunks = recursive_split(content, chunk_size=500, overlap=50)
        chunk_count = save_chunks(aid, chunks)
        log.info(f"[knowledge/import] 文章 {aid} 切成 {chunk_count} 个 chunks")
    except Exception as e:
        log.error(f"[knowledge/import] 切分失败: {e}")

    return jsonify(ok({
        "article_id":            aid,
        "title":                 title,
        "author":                author,
        "domain":                domain,
        "content_length":        len(content),
        "chunk_count":           chunk_count,
        "embedding_generated":   chunk_count > 0,
        "created_at":            now,
    })), 201


# ---------- 4. 更新 ----------
@knowledge_bp.patch("/api/knowledge/articles/<article_id>")
def update_article(article_id):
    body = request.get_json(silent=True) or {}
    if not db_query_one("SELECT 1 FROM knowledge_articles WHERE article_id=?", [article_id]):
        return jsonify(err(3002, "文章不存在")), 404

    fields, params = [], []
    re_chunk = "content" in body   # 内容变了需要重新切分
    for k in ["title", "url", "content", "summary", "source", "status", "published_at"]:
        if k in body:
            fields.append(f"{k}=?")
            params.append(body[k])
    if "tags" in body:
        fields.append("tags=?")
        params.append(json.dumps(body["tags"], ensure_ascii=False))

    fields.append("updated_at=?")
    params.append(now_iso())
    params.append(article_id)
    db_exec(f"UPDATE knowledge_articles SET {', '.join(fields)} WHERE article_id=?", params)

    # 重新切分 + 重新 embed
    chunk_count = 0
    if re_chunk:
        try:
            from agents.chunker import recursive_split
            from agents.retriever import delete_chunks, save_chunks
            delete_chunks(article_id)
            chunks = recursive_split(body["content"], chunk_size=500, overlap=50)
            chunk_count = save_chunks(article_id, chunks)
            log.info(f"[knowledge/update] 文章 {article_id} 重新切成 {chunk_count} 个 chunks")
        except Exception as e:
            log.error(f"[knowledge/update] 重新切分失败: {e}")

    return jsonify(ok({
        "updated":               True,
        "embedding_regenerated": chunk_count > 0,
        "chunk_count":           chunk_count,
    }))


# ---------- 5. 删除 ----------
@knowledge_bp.delete("/api/knowledge/articles/<article_id>")
def delete_article(article_id):
    db_exec("DELETE FROM knowledge_articles WHERE article_id=?", [article_id])
    return jsonify(ok({"deleted": True}))


# ---------- 6. 统计 ----------
@knowledge_bp.get("/api/knowledge/stats")
def knowledge_stats():
    rows = db_query("SELECT status, COUNT(*) AS c FROM knowledge_articles GROUP BY status", [])
    by_status = {r["status"]: r["c"] for r in rows}

    src_rows = db_query("SELECT source, COUNT(*) AS c FROM knowledge_articles GROUP BY source ORDER BY c DESC", [])
    by_source = [{"source": r["source"], "count": r["c"]} for r in src_rows]

    size_row = db_query_one("SELECT COALESCE(SUM(LENGTH(content)), 0) AS size FROM knowledge_articles", [])
    total_bytes = size_row["size"] if size_row else 0

    total = sum(by_status.values())

    last_row = db_query_one("SELECT MAX(updated_at) AS lu FROM knowledge_articles", [])
    last_updated = last_row["lu"] if last_row else None

    def human_size(n):
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.1f} {unit}"
            n /= 1024
        return f"{n:.1f} TB"

    return jsonify(ok({
        "total_articles":   total,
        "total_sources":    len(by_source),
        "total_size_bytes": total_bytes,
        "total_size_human": human_size(total_bytes),
        "by_status":        by_status,
        "by_source":        by_source,
        "last_updated":     last_updated,
    }))


# ---------- 7. 语义检索（混合：向量 + 关键词 + 权重融合）----------
@knowledge_bp.post("/api/knowledge/search")
def knowledge_search():
    body = request.get_json(silent=True) or {}
    query = (body.get("query") or "").strip()
    top_k = int(body.get("top_k", 5))
    vector_weight = float(body.get("vector_weight", 0.5))
    keyword_weight = float(body.get("keyword_weight", 0.5))
    return_articles = bool(body.get("return_articles", True))

    if not query:
        return jsonify(err(3001, "query 不能为空"))

    from agents.retriever import hybrid_search
    results = hybrid_search(
        query=query,
        top_k=top_k,
        vector_weight=vector_weight,
        keyword_weight=keyword_weight,
        return_articles=return_articles,
    )

    return jsonify(ok({
        "query":          query,
        "vector_weight":  vector_weight,
        "keyword_weight": keyword_weight,
        "result_count":   len(results),
        "results":        results,
    }))


# ---------- 8. AI 改写（编辑器用）----------
@knowledge_bp.post("/api/ai/rewrite")
def ai_rewrite():
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    instruction = (body.get("instruction") or "").strip() or "用更清晰、更口语的方式重写这段文字"

    if not text:
        return jsonify(err(4007, "text 不能为空"))
    if len(text) > 8000:
        return jsonify(err(4007, "文本过长（> 8000 字符）"))

    system = "你是一名资深技术编辑。用户会给你一段文字和改写要求，输出改写后的完整文字（保持原意、整段输出，不要 markdown 包裹，不要解释）。"
    user = f"原文：\n{text}\n\n要求：{instruction}\n\n改写后："

    t0 = time.time()
    try:
        resp = llm_chat([
            {"role": "system", "content": system},
            {"role": "user",   "content": user},
        ], temperature=0.5, max_tokens=2000)
        rewritten = resp["content"].strip()
    except Exception as e:
        log.error(f"[ai/rewrite] LLM 失败: {e}")
        return jsonify(err(E.LLM_FAILED, f"LLM 调用失败: {e}")), 500

    duration_ms = int((time.time() - t0) * 1000)
    trace_id = new_id("trace-")

    # 写 trace
    try:
        db_exec(
            """INSERT INTO trace_calls (call_id, trace_id, agent_name, operation, input, output, duration_ms, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [new_id("call-"), trace_id, "rewrite", "ai_rewrite",
             json.dumps({"text_len": len(text), "instruction": instruction}, ensure_ascii=False),
             json.dumps({"rewritten_len": len(rewritten)}, ensure_ascii=False),
             duration_ms, "success", now_iso()],
        )
    except Exception as e:
        log.warning(f"[ai/rewrite] trace 写入失败: {e}")

    return jsonify(ok({
        "original":   text,
        "rewritten":  rewritten,
        "diff":       {"kept": "", "removed": "", "added": rewritten},  # 简单占位
        "usage":      resp["usage"],
        "trace_id":   trace_id,
    }))


# 兼容 Vercel
def handler(request):
    return knowledge_bp.wsgi_app
