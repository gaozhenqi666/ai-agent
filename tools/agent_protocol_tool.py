"""
tools/agent_protocol_tool.py
==========================================================
Agent 间数据协议
- 收敛跨 Agent 传输格式
- 在进入下游 Agent 前做字段校验
- 避免把脏 dict 直接拼进 LLM 上下文
==========================================================
"""

from __future__ import annotations

from typing import Any


RESPONSE_KINDS = {
    "search_results",
    "knowledge_hits",
    "knowledge_saved",
    "blog_article",
    "feishu_doc",
    "email_delivery",
    "chat_response",
}


def _as_str(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def normalize_search_results(raw_results: list[dict] | None) -> list[dict]:
    results: list[dict] = []
    for item in raw_results or []:
        url = _as_str(item.get("url"))
        title = _as_str(item.get("title"))
        if not url or not title:
            continue
        results.append({
            "title": title[:300],
            "url": url[:1500],
            "snippet": _as_str(item.get("snippet"))[:1000],
        })
    return results


def normalize_knowledge_hits(raw_hits: list[dict] | None) -> list[dict]:
    hits: list[dict] = []
    for item in raw_hits or []:
        if item.get("article_id") and item.get("chunk_id") and item.get("title") and item.get("chunk_text"):
            hits.append({
                "article_id": _as_str(item.get("article_id")),
                "chunk_id": _as_str(item.get("chunk_id")),
                "title": _as_str(item.get("title"))[:300],
                "url": _as_str(item.get("url"))[:1500],
                "source": _as_str(item.get("source"))[:200],
                "chunk_text": _as_str(item.get("chunk_text"))[:3000],
                "score": float(item.get("score") or 0.0),
                "chunk_index": int(item.get("chunk_index") or 0),
            })
            continue
        article = item.get("article") or {}
        article_id = _as_str(item.get("article_id") or article.get("article_id"))
        chunk_id = _as_str(item.get("chunk_id"))
        title = _as_str(article.get("title"))
        chunk_text = _as_str(item.get("chunk_text"))
        if not article_id or not chunk_id or not title or not chunk_text:
            continue
        score = float(item.get("score") or 0.0)
        hits.append({
            "article_id": article_id,
            "chunk_id": chunk_id,
            "title": title[:300],
            "url": _as_str(article.get("url"))[:1500],
            "source": _as_str(article.get("source"))[:200],
            "chunk_text": chunk_text[:3000],
            "score": score,
            "chunk_index": int(item.get("chunk_index") or 0),
        })
    return hits


def ensure_step_params(action: str, params: dict | None) -> dict:
    payload = dict(params or {})
    if action in {"search_web", "search_web_if_needed", "search_knowledge_articles"}:
        if not _as_str(payload.get("query")):
            raise ValueError(f"{action} 缺少 query")
    elif action in {"save_to_knowledge", "generate_blog", "save_to_feishu"}:
        payload["search_results"] = normalize_search_results(payload.get("search_results"))
        if not payload["search_results"]:
            raise ValueError(f"{action} 缺少合法的 search_results")
    elif action == "send_email":
        payload["search_results"] = normalize_search_results(payload.get("search_results"))
        if not payload["search_results"]:
            raise ValueError("send_email 缺少 search_results")
    elif action == "chat":
        if not _as_str(payload.get("message")):
            raise ValueError("chat 缺少 message")
    return payload


def build_agent_result(kind: str, **kwargs) -> dict:
    if kind not in RESPONSE_KINDS:
        raise ValueError(f"未知响应类型: {kind}")

    payload = {"ok": kwargs.pop("ok", True), "kind": kind}
    payload.update(kwargs)

    if kind == "search_results":
        payload["search_results"] = normalize_search_results(payload.get("search_results"))
        payload["count"] = int(payload.get("count") or len(payload["search_results"]))
        if not _as_str(payload.get("query")):
            raise ValueError("search_results 缺少 query")
    elif kind == "knowledge_hits":
        payload["knowledge_hits"] = normalize_knowledge_hits(payload.get("knowledge_hits"))
        payload["count"] = int(payload.get("count") or len(payload["knowledge_hits"]))
    elif kind == "knowledge_saved":
        payload["saved_items"] = int(payload.get("saved_items") or 0)
        payload["message"] = _as_str(payload.get("message"))
    elif kind == "blog_article":
        payload["article_id"] = _as_str(payload.get("article_id"))
        payload["title"] = _as_str(payload.get("title"))
        payload["url"] = _as_str(payload.get("url"))
    elif kind == "feishu_doc":
        payload["doc_id"] = _as_str(payload.get("doc_id"))
        payload["doc_url"] = _as_str(payload.get("doc_url"))
        payload["article_count"] = int(payload.get("article_count") or 0)
    elif kind == "email_delivery":
        payload["to"] = _as_str(payload.get("to"))
        payload["email_sent"] = bool(payload.get("email_sent"))
    elif kind == "chat_response":
        payload["message"] = _as_str(payload.get("message"))

    return payload


def build_kb_context_block(hits: list[dict], max_chars: int = 4000) -> str:
    if not hits:
        return ""

    lines = [
        "=" * 50,
        "【重要】以下是用户个人知识库的检索结果，优先基于这些内容回答：",
        "=" * 50,
    ]
    for idx, item in enumerate(hits, 1):
        lines.append(f"\n{idx}. 标题: {item['title']}")
        if item.get("url"):
            lines.append(f"   来源: {item['url']}")
        elif item.get("source"):
            lines.append(f"   来源: {item['source']}")
        lines.append(f"   相关度: {item['score']:.3f}")
        lines.append(f"   片段: {item['chunk_text'][:800]}")

    lines.append("\n要求：")
    lines.append("1. 优先使用知识库内容回答，缺失时再补充通用常识")
    lines.append("2. 不要编造知识库里没有的具体事实")
    block = "\n".join(lines)
    return block[:max_chars]
