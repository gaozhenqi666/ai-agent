"""
agents/feishu_doc.py
==========================================================
飞书云文档操作
- 获取 tenant_access_token
- 创建新版文档
- 写入内容块（标题、文本、链接、分割线）
- 将搜索结果结构化写入文档
==========================================================
"""

from __future__ import annotations
import httpx
from common import log, Config, llm_chat

FEISHU_API_BASE = "https://open.feishu.cn/open-apis"


# ---------- 1. Token ----------
def _get_feishu_token() -> str:
    """获取飞书 tenant_access_token"""
    if not Config.FEISHU_APP_ID or not Config.FEISHU_APP_SECRET:
        raise RuntimeError("FEISHU_APP_ID / FEISHU_APP_SECRET 未配置")

    resp = httpx.post(
        f"{FEISHU_API_BASE}/auth/v3/tenant_access_token/internal",
        json={
            "app_id": Config.FEISHU_APP_ID,
            "app_secret": Config.FEISHU_APP_SECRET,
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"获取飞书 token 失败: {data}")
    return data["tenant_access_token"]


# ---------- 2. 文档创建 ----------
def _create_doc(title: str, token: str) -> str:
    """创建飞书新版文档，返回 document_id"""
    resp = httpx.post(
        f"{FEISHU_API_BASE}/docx/v1/documents",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"title": title},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        raise RuntimeError(f"创建飞书文档失败: {data}")
    doc_id = data["data"]["document"]["document_id"]
    log.info(f"[feishu] 文档已创建: {doc_id}")
    return doc_id


def _add_blocks(doc_id: str, parent_block_id: str, blocks: list[dict], token: str):
    """向文档指定父块下添加子块"""
    url = f"{FEISHU_API_BASE}/docx/v1/documents/{doc_id}/blocks/{parent_block_id}/children"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json={"children": blocks},
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()
    if data.get("code") != 0:
        log.error(f"[feishu] 添加块失败, body={resp.text[:500]}")
        raise RuntimeError(f"添加文档块失败: code={data.get('code')}, msg={data.get('msg', resp.text[:200])}")
    log.info(f"[feishu] 已添加 {len(blocks)} 个块到文档 {doc_id}")

# ---------- 3. 块构建器 ----------
def _text_block(content: str, bold: bool = False) -> dict:
    """普通文本块"""
    style = {}
    if bold:
        style["bold"] = True
    return {
        "block_type": 2,
        "text": {
            "elements": [{
                "text_run": {
                    "content": content,
                    "text_element_style": style,
                }
            }]
        }
    }


def _heading1_block(content: str) -> dict:
    """一级标题"""
    return {
        "block_type": 3,
        "heading1": {
            "elements": [{
                "text_run": {"content": content}
            }]
        }
    }


def _heading2_block(content: str) -> dict:
    """二级标题"""
    return {
        "block_type": 4,
        "heading2": {
            "elements": [{
                "text_run": {"content": content}
            }]
        }
    }


def _link_block(label: str, url: str) -> dict:
    """带链接的文本块"""
    return {
        "block_type": 2,
        "text": {
            "elements": [{
                "text_run": {
                    "content": label,
                    "text_element_style": {
                        "link": {"url": url},
                    }
                }
            }]
        }
    }


def _divider_block() -> dict:
    """分割线"""
    return {"block_type": 21}


# ---------- 4. 搜索结果 → 飞书文档 ----------

def _generate_doc_title(search_results: list[dict], query: str) -> str:
    """用 LLM 生成总结性文档标题（不暴露内部 query）"""
    if len(search_results) == 1:
        return search_results[0].get("title", query[:40])

    try:
        material = "\n".join([r.get("title", "")[:80] for r in search_results[:5]])
        prompt = (
            f"给以下文章列表生成一个简洁的文档标题（≤20字），主题是「{query[:30]}」：\n"
            f"{material}\n直接输出标题："
        )
        resp = llm_chat([
            {"role": "system", "content": "你只输出一个文档标题，不要任何解释。"},
            {"role": "user", "content": prompt},
        ], temperature=0.3, max_tokens=30)
        title = resp["content"].strip().strip("「」《》\"\"''").strip()
        if title and len(title) <= 30:
            return title
    except Exception as e:
        log.warning(f"[feishu] 标题生成失败: {e}")

    return f"「{query[:30]}」相关文章" if len(query) > 5 else "文章合集"


def _is_garbage_content(text: str) -> bool:
    """判断爬取内容是否是垃圾（扩展页/商店页/非文章）"""
    garbage_patterns = [
        "Chrome Web Store", "chrome.google.com", "addons.mozilla",
        "The publisher has a good record", "Ratings are updated daily",
        "github.com", "GitHub -",  # 代码仓库不是文章
        "npmjs.com/package",
    ]
    return any(p in text for p in garbage_patterns)


def _generate_summary(search_results: list[dict], query: str) -> str:
    """当搜索结果 > 1 条时，用 LLM 生成总结"""
    if len(search_results) <= 1:
        return ""

    items_text = "\n".join([
        f"{i+1}. {r['title']}\n   摘要: {r.get('snippet', '')[:200]}"
        for i, r in enumerate(search_results)
    ])

    try:
        resp = llm_chat([{
            "role": "user",
            "content": (
                f"用户搜索了「{query}」，以下是 {len(search_results)} 篇相关文章的标题和摘要：\n\n"
                f"{items_text}\n\n"
                f"请用 3-5 句话对这些文章做一个总结，概括它们的共同主题、核心观点和推荐阅读顺序。"
                f"直接输出中文总结，不要用标题。"
            )
        }], temperature=0.5, max_tokens=400)
        summary = resp["content"].strip()
        return summary
    except Exception as e:
        log.warning(f"[feishu] LLM 生成总结失败: {e}")
        # 回退：简单拼接
        titles = "、".join([r["title"] for r in search_results])
        return f"以上 {len(search_results)} 篇文章涵盖了「{query}」相关的多个方面，建议按顺序阅读。"


def save_search_to_feishu(search_results: list[dict], query: str) -> dict:
    """
    将搜索结果保存到飞书云文档。
    - 每篇文章：标题（H2）+ 摘要 + 链接
    - 如果 >1 篇，末尾附加 LLM 生成的总结

    :param search_results: Tavily 搜索结果列表 [{title, url, snippet}, ...]
    :param query: 用户搜索关键词
    :return: {"success": True, "doc_url": "...", "doc_id": "..."} 或 {"success": False, "error": "..."}
    """
    n = len(search_results)
    if n == 0:
        return {"success": False, "error": "没有搜索结果可保存"}

    try:
        token = _get_feishu_token()
    except Exception as e:
        log.error(f"[feishu] 获取 token 失败: {e}")
        return {"success": False, "error": f"飞书认证失败: {e}"}

    doc_title = _generate_doc_title(search_results, query)

    try:
        doc_id = _create_doc(doc_title, token)
    except Exception as e:
        log.error(f"[feishu] 创建文档失败: {e}")
        return {"success": False, "error": f"创建飞书文档失败: {e}"}

    # 构建内容块
    blocks = []

    # 总标题（H1）
    blocks.append(_heading1_block(doc_title))

    for i, r in enumerate(search_results, 1):
        # 标题（H2）
        blocks.append(_heading2_block(f"{i}. {r['title']}"))

        # 摘要：优先用爬取正文（非垃圾），其次用原 snippet
        full = r.get("full_content", "")
        snippet = r.get("snippet", "").strip()

        if full and len(full) > 200 and not _is_garbage_content(full):
            blocks.append(_text_block(full[:500]))
        elif snippet:
            blocks.append(_text_block(snippet[:300] if len(snippet) > 300 else snippet))

        # 链接
        if r.get("url"):
            blocks.append(_link_block(f"🔗 {r['url']}", r["url"]))

    # 如果 >1 篇，加总结
    if n > 1:
        blocks.append(_heading2_block("总结"))
        summary = _generate_summary(search_results, query)
        blocks.append(_text_block(summary))

    # 写入文档
    try:
        _add_blocks(doc_id, doc_id, blocks, token)
    except Exception as e:
        log.error(f"[feishu] 写入文档内容失败: {e}")
        return {"success": False, "error": f"写入飞书文档失败: {e}", "doc_id": doc_id}

    doc_url = f"https://{Config.FEISHU_APP_ID}.feishu.cn/docx/{doc_id}"

    log.info(f"[feishu] 文档保存完成: {doc_url}, 共 {n} 篇文章")
    return {
        "success": True,
        "doc_id": doc_id,
        "doc_url": doc_url,
        "article_count": n,
    }
