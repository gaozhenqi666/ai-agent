"""
agents/retriever.py
==========================================================
混合检索器（双路 + 权重融合）
- 路 1：向量检索（cosine similarity）
- 路 2：关键词检索（BM25 简化版：chunk_text + chunk.keywords + article.tags 的 TF 匹配）
- 融合：按权重 (默认 0.6 向量 + 0.4 关键词) 加权求和
- 返回 Top K 切片 + 父文章信息
==========================================================
"""

from __future__ import annotations
from common import *  # 项目级基础库
from common import (
    log, db_query, db_query_one, db_exec, now_iso, new_id,
    embedding_to_blob, blob_to_embedding, cosine_similarity,
)

from .embedder_tool import embed_one
from .keyword_extractor_tool import extract_keywords
from .runtime_cache_tool import cache_get, cache_set

import json
import math
import re
from collections import Counter


# ---------- 1. 存 chunks（创建文章时调用）----------
def save_chunks(article_id: str, chunks: list[dict]) -> int:
    """
    保存文章的所有 chunks
    chunks: [{chunk_index, text, start_pos, end_pos, size, keywords, embedding}, ...]
    返回写入的 chunk 数
    """
    if not chunks:
        return 0

    # 批量 embed
    texts = [c["text"] for c in chunks]
    log.info(f"[retriever] 正在 embed {len(texts)} 个 chunks...")
    embeddings = embed_texts_batch(texts)

    # 逐条写库
    now = now_iso()
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        cid = new_id("chunk-")
        # 关键词默认是 chunk_text 中的高频词（如果调用方没传）
        keywords = chunk.get("keywords") or _extract_chunk_keywords(chunk["text"])
        db_exec(
            """INSERT INTO knowledge_chunks
               (chunk_id, article_id, chunk_index, chunk_text, embedding,
                start_pos, end_pos, chunk_size, keywords, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [
                cid, article_id, chunk["chunk_index"], chunk["text"],
                embedding_to_blob(emb),
                chunk["start_pos"], chunk["end_pos"], chunk["size"],
                json.dumps(keywords, ensure_ascii=False), now,
            ],
        )
    return len(chunks)


def embed_texts_batch(texts: list[str]) -> list[list[float]]:
    """薄包装：避免循环引用"""
    from .embedder_tool import embed_texts
    return embed_texts(texts)


def _extract_chunk_keywords(text: str, top_k: int = 5) -> list[str]:
    """
    从 chunk 文本中提取关键词（用于元数据索引）
    简单实现：中文 2-4 字 + 英文 token + 数字 + 型号
    """
    kws = set()
    for m in re.findall(r"[A-Za-z0-9_\-\.]{2,}", text):
        kws.add(m)
    for m in re.findall(r"[\u4e00-\u9fff]{2,4}", text):
        if not _is_simple_stopword(m):
            kws.add(m)
    return list(kws)[:top_k]


def _is_simple_stopword(text: str) -> bool:
    stops = {"什么", "怎么", "如何", "可以", "应该", "需要", "这个", "那个", "现在", "时候"}
    return text in stops


# ---------- 2. 删除文章的所有 chunks ----------
def delete_chunks(article_id: str) -> int:
    """删除文章的所有 chunks（更新文章时调用）"""
    res = db_query_one("SELECT COUNT(*) AS c FROM knowledge_chunks WHERE article_id=?", [article_id])
    cnt = res["c"] if res else 0
    db_exec("DELETE FROM knowledge_chunks WHERE article_id=?", [article_id])
    return cnt


# ---------- 3. 混合检索 ----------
def hybrid_search(
    query: str,
    top_k: int = 5,
    vector_weight: float = 0.5,
    keyword_weight: float = 0.5,
    return_articles: bool = True,
) -> list[dict]:
    """
    混合检索主入口
    返回: [
      {
        "chunk_id": "...",
        "article_id": "...",
        "chunk_text": "...",
        "chunk_index": 0,
        "start_pos": 0,
        "end_pos": 500,
        "score": 0.85,           # 融合分
        "vector_score": 0.78,
        "keyword_score": 0.42,
        "article": { ... }       # 父文章信息（如果 return_articles=True）
      },
      ...
    ]
    """
    if not query or not query.strip():
        return []

    cache_key = json.dumps({
        "query": query,
        "top_k": top_k,
        "vector_weight": vector_weight,
        "keyword_weight": keyword_weight,
        "return_articles": return_articles,
    }, ensure_ascii=False, sort_keys=True)
    cached = cache_get("hybrid_search", cache_key)
    if cached is not None:
        return cached

    log.info(f"[retriever] 混合检索: {query!r} top_k={top_k}")

    # 1) 提取关键词
    keywords = extract_keywords(query)
    log.info(f"[retriever] 关键词: {keywords}")

    # 2) 加载所有 published 文章的 chunks（粗筛）
    #    M1 数据量小：全量加载 + 全量计算
    rows = db_query(
        """SELECT c.chunk_id, c.article_id, c.chunk_index, c.chunk_text,
                  c.embedding, c.start_pos, c.end_pos, c.chunk_size, c.keywords,
                  a.title, a.url, a.summary, a.source, a.tags
           FROM knowledge_chunks c
           JOIN knowledge_articles a ON c.article_id = a.article_id
           WHERE a.status = 'published'""",
        [],
    )
    if not rows:
        return []

    # 3) 计算向量分
    query_vec = embed_one(query)
    for r in rows:
        emb = blob_to_embedding(r["embedding"]) if r.get("embedding") else []
        r["vector_score"] = cosine_similarity(query_vec, emb) if emb else 0.0

    # 4) 计算关键词分（BM25 简化版：词频 * 长度归一）
    for r in rows:
        r["keyword_score"] = _bm25_score(query, keywords, r)

    # 5) 归一化到 [0, 1] 然后加权
    v_scores = [r["vector_score"] for r in rows]
    k_scores = [r["keyword_score"] for r in rows]
    v_max = max(v_scores) if v_scores else 1
    k_max = max(k_scores) if k_scores else 1
    for r in rows:
        v_norm = r["vector_score"] / v_max if v_max else 0
        k_norm = r["keyword_score"] / k_max if k_max else 0
        r["score"] = vector_weight * v_norm + keyword_weight * k_norm

    # 6) 轻量重排：标题短语命中额外加分
    query_lower = query.lower()
    for r in rows:
        title = (r.get("title") or "").lower()
        boost = 0.0
        if query_lower and query_lower in title:
            boost += 0.12
        for kw in keywords[:5]:
            kw_lower = kw.lower()
            if kw_lower and kw_lower in title:
                boost += 0.04
        r["score"] += boost

    # 7) 排序，取 Top K
    rows.sort(key=lambda r: r["score"], reverse=True)
    top = rows[:top_k]

    # 8) 整理返回
    results = []
    for r in top:
        item = {
            "chunk_id":      r["chunk_id"],
            "article_id":    r["article_id"],
            "chunk_text":    r["chunk_text"],
            "chunk_index":   r["chunk_index"],
            "start_pos":     r["start_pos"],
            "end_pos":       r["end_pos"],
            "chunk_size":    r["chunk_size"],
            "score":         round(r["score"], 4),
            "vector_score":  round(r["vector_score"], 4),
            "keyword_score": round(r["keyword_score"], 4),
        }
        if return_articles:
            item["article"] = {
                "article_id": r["article_id"],
                "title":      r["title"],
                "url":        r["url"],
                "summary":    r["summary"],
                "source":     r["source"],
                "tags":       json.loads(r["tags"]) if r["tags"] else [],
            }
        results.append(item)

    cache_set("hybrid_search", cache_key, results, ttl_seconds=600)
    return results


# ---------- 4. BM25 简化版 ----------
def _bm25_score(query: str, keywords: list[str], chunk_row: dict) -> float:
    """
    简化 BM25：在 chunk_text + chunk.keywords + article.tags 中匹配
    k1=1.5, b=0.75
    """
    k1, b = 1.5, 0.75
    text = chunk_row.get("chunk_text", "")
    chunk_kws = json.loads(chunk_row.get("keywords") or "[]")
    article_tags = json.loads(chunk_row.get("tags") or "[]")

    # 合并待匹配文本：chunk_text 出现一次 + keywords 出现 2 次 + tags 出现 3 次（权重递增）
    field_weights = {
        "text":   (text, 1.0),
        "kw":     (" ".join(chunk_kws), 2.0),
        "tag":    (" ".join(article_tags), 3.0),
    }

    # 文档长度（用字符数近似）
    doc_len = len(text) + 1
    # 平均长度（M1 用常数 500 近似）
    avg_len = 500.0

    score = 0.0
    # 查询词：合并 query 本身的分词 + LLM 提取的关键词
    query_terms = set(keywords) | set(re.findall(r"[\u4e00-\u9fff]{2,4}", query)) | set(re.findall(r"[A-Za-z0-9_\-\.]{2,}", query))
    query_terms = {t for t in query_terms if len(t) >= 2}

    if not query_terms:
        return 0.0

    for term in query_terms:
        # 在 3 个字段中计算 TF
        tf_total = 0
        for _, (content, weight) in field_weights.items():
            if content and term in content:
                tf = content.count(term)
                tf_total += tf * weight
        if tf_total == 0:
            continue
        # IDF 近似（log((N - df + 0.5) / (df + 0.5) + 1)）
        idf = math.log(1.0 + 1.0)  # 简化：N 未知，给常数
        # BM25 公式
        numerator   = tf_total * (k1 + 1)
        denominator = tf_total + k1 * (1 - b + b * doc_len / avg_len)
        score += idf * (numerator / denominator) if denominator else 0

    return score


# ---------- 5. 给 LLM 喂数据（按父文章去重）----------
def expand_to_articles(chunks: list[dict]) -> list[dict]:
    """
    把 chunks 按 article_id 去重，附上完整原文
    """
    article_ids = list({c["article_id"] for c in chunks})
    if not article_ids:
        return []

    placeholders = ",".join(["?"] * len(article_ids))
    rows = db_query(
        f"SELECT * FROM knowledge_articles WHERE article_id IN ({placeholders})",
        article_ids,
    )

    articles = {r["article_id"]: {
        "article_id": r["article_id"],
        "title":      r["title"],
        "url":        r["url"],
        "content":    r["content"],  # 原文
        "summary":    r["summary"],
        "source":     r["source"],
        "tags":       json.loads(r["tags"]) if r["tags"] else [],
        "matched_chunks": [c for c in chunks if c["article_id"] == r["article_id"]],
    } for r in rows}

    return list(articles.values())


# ---------- 快速测试 ----------
if __name__ == "__main__":
    results = hybrid_search("什么是 RAG", top_k=3)
    print(f"找到 {len(results)} 条结果:")
    for r in results:
        print(f"  - [{r['score']:.3f}] {r['article']['title']} | {r['chunk_text'][:50]}...")
