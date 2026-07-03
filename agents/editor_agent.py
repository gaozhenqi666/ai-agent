"""
agents/editor_agent.py
==========================================================
文章编辑 Agent（独立于 master_agent）

职责：
  更新 articles 表中的文章（标题 + 正文）。
  只操作 articles 表，不涉及 knowledge_chunks（知识库文章前端改不了）。

不交给 master_agent 管理 — 编辑器 API 直接调用，上下文短。
==========================================================
"""

from __future__ import annotations
import sys
from pathlib import Path

try:
    from common import log, now_iso, db_exec, db_query_one
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common import log, now_iso, db_exec, db_query_one


def update_article(article_id: str, new_title: str = "", new_content: str = "") -> dict:
    """
    更新 articles 表中的文章。

    返回:
      {"success": True, "article_id": "art-xxx"}
      {"success": False, "error": "..."}
    """
    if not article_id:
        return {"success": False, "error": "缺少 article_id"}

    article = db_query_one("SELECT * FROM articles WHERE article_id=?", [article_id])
    if not article:
        return {"success": False, "error": f"文章 {article_id} 不存在"}

    title = new_title or article["title"]
    content = new_content or article["content"]

    if not content.strip():
        return {"success": False, "error": "文章内容不能为空"}

    now = now_iso()
    db_exec(
        "UPDATE articles SET title=?, content=?, updated_at=? WHERE article_id=?",
        [title, content, now, article_id],
    )
    log.info(f"[editor] 文章已更新: {article_id} ({title})")

    return {"success": True, "article_id": article_id, "title": title}


def get_article(article_id: str) -> dict | None:
    """获取文章（供编辑器前端使用）"""
    return db_query_one("SELECT * FROM articles WHERE article_id=?", [article_id])
