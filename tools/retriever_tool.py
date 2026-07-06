"""
agents/retriever.py
==========================================================
多路召回 + RRF（倒数排序融合）检索器

三路独立召回：
- 路 1：向量检索（dense embedding + cosine similarity）
- 路 2：关键词检索（BM25 简化版：chunk_text + chunk.keywords + article.tags）
- 路 3：标签/标题匹配（query 关键词 → article.tags + title 精确命中）

融合方式：
- RRF（Reciprocal Rank Fusion）：score = Σ 1 / (k + rank_i)，默认 k = 60

hybrid_search() 保留为兼容入口，内部委托给 multi_recall_search()
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


# ---------- 3. 多路召回 + RRF 融合 ----------
def multi_recall_search(
    query: str,
    top_k: int = 5,
    rrf_k: int = 60,
    recall_paths: list[str] | None = None,
    return_articles: bool = True,
) -> list[dict]:
    """
    多路召回 + RRF 融合检索

    三路独立召回：
      - "vector":  向量检索（dense embedding + cosine similarity）
      - "bm25":    BM25 关键词检索（含 chunk_text / chunk.keywords / article.tags）
      - "tag":     标签/标题匹配（query 词命中 article.tags 和 title）

    RRF 融合公式：
      RRF_score(chunk) = Σ 1 / (rrf_k + rank_of_chunk_in_path)
      默认 rrf_k = 60

    返回格式同 hybrid_search()，额外附上 rrf_score 和各路 rank 明细
    """
    if not query or not query.strip():
        return []

    if recall_paths is None:
        recall_paths = ["vector", "bm25", "tag"]

    # 缓存 key
    cache_key = json.dumps({
        "query": query, "top_k": top_k, "rrf_k": rrf_k,
        "paths": sorted(recall_paths), "return_articles": return_articles,
    }, ensure_ascii=False, sort_keys=True)
    cached = cache_get("multi_recall", cache_key)
    if cached is not None:
        return cached

    log.info(f"[retriever] 多路召回: {query!r} paths={recall_paths} top_k={top_k}")

    # 1) 提取关键词（向量路不需要，bm25 和 tag 路需要）
    keywords = extract_keywords(query)

    # 2) 加载所有 published chunks（全量进内存）
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

    # 3) 各路独立打分
    # 给每个 row 附加一个 dict 存储各路 rank
    for r in rows:
        r["_path_scores"] = {}

    # ---- 路 1：向量检索 ----
    if "vector" in recall_paths:
        query_vec = embed_one(query)
        for r in rows:
            emb = blob_to_embedding(r["embedding"]) if r.get("embedding") else []
            r["_path_scores"]["vector"] = cosine_similarity(query_vec, emb) if emb else 0.0

    # ---- 路 2：BM25 关键词 ----
    if "bm25" in recall_paths:
        for r in rows:
            r["_path_scores"]["bm25"] = _bm25_score(query, keywords, r)

    # ---- 路 3：标签/标题匹配 ----
    if "tag" in recall_paths:
        for r in rows:
            r["_path_scores"]["tag"] = _tag_title_score(keywords, r)

    # 4) 各路分别排名（score 降序 → rank 从 1 开始）
    chunk_ids = [r["chunk_id"] for r in rows]
    rrf_accum = {cid: 0.0 for cid in chunk_ids}
    rrf_detail = {cid: {} for cid in chunk_ids}

    for path in recall_paths:
        # 按该路 score 降序排列
        sorted_rows = sorted(rows, key=lambda r: r["_path_scores"].get(path, 0.0), reverse=True)
        for rank_idx, r in enumerate(sorted_rows):
            cid = r["chunk_id"]
            rank_i = rank_idx + 1  # rank 从 1 开始
            contribution = 1.0 / (rrf_k + rank_i)
            rrf_accum[cid] += contribution
            rrf_detail[cid][path] = {"rank": rank_i, "score": round(r["_path_scores"].get(path, 0.0), 4)}

    # 5) 按 RRF 总分排序
    for r in rows:
        r["rrf_score"] = rrf_accum[r["chunk_id"]]
        r["_rrf_detail"] = rrf_detail[r["chunk_id"]]
        # 同时保留各路原始分供展示
        for path in recall_paths:
            r[f"{path}_score"] = r["_path_scores"].get(path, 0.0)

    rows.sort(key=lambda r: r["rrf_score"], reverse=True)
    top = rows[:top_k]

    # 6) 整理返回
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
            "score":         round(r["rrf_score"], 4),       # RRF 融合分
            "rrf_score":     round(r["rrf_score"], 4),
            "vector_score":  round(r.get("vector_score", r["_path_scores"].get("vector", 0.0)), 4),
            "keyword_score": round(r.get("bm25_score", r["_path_scores"].get("bm25", 0.0)), 4),
            "tag_score":     round(r.get("tag_score", r["_path_scores"].get("tag", 0.0)), 4),
            "rrf_detail":    {p: {"rank": d["rank"], "score": d["score"]}
                              for p, d in r["_rrf_detail"].items()},
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

    cache_set("multi_recall", cache_key, results, ttl_seconds=600)
    return results


def _tag_title_score(keywords: list[str], chunk_row: dict) -> float:
    """
    路 3：标签/标题匹配打分

    - article.tags 精确命中一个关键词 +0.5
    - article.title 包含一个关键词 +0.3
    - query 完整字符串在 title 中 +0.5
    """
    score = 0.0
    tags_raw = chunk_row.get("tags") or "[]"
    tags = json.loads(tags_raw) if isinstance(tags_raw, str) else (tags_raw or [])
    title = (chunk_row.get("title") or "").lower()

    for kw in keywords:
        kw_lower = kw.lower().strip()
        if not kw_lower or len(kw_lower) < 2:
            continue
        # 标签命中（tag 通常是英文如 "RAG", "Agent"，做小写匹配）
        for tag in tags:
            if isinstance(tag, str) and kw_lower in tag.lower():
                score += 0.5
                break
        # 标题命中
        if kw_lower in title:
            score += 0.3

    return score


# ---------- 4. 混合检索（兼容旧接口，委托 multi_recall_search）----------
def hybrid_search(
    query: str,
    top_k: int = 5,
    vector_weight: float = 0.5,
    keyword_weight: float = 0.5,
    return_articles: bool = True,
) -> list[dict]:
    """
    兼容旧接口 —— 内部使用 RRF 多路召回
    vector_weight / keyword_weight 参数保留但不影响 RRF 行为
    """
    return multi_recall_search(
        query=query,
        top_k=top_k,
        return_articles=return_articles,
    )


# ---------- 5. BM25 简化版 ----------
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


# ---------- 6. 给 LLM 喂数据（按父文章去重）----------
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
    print("=== 多路召回 + RRF 融合测试 ===")
    results = multi_recall_search("什么是 RAG", top_k=3)
    print(f"找到 {len(results)} 条结果:")
    for r in results:
        detail = r.get("rrf_detail", {})
        paths_info = ", ".join(f"{p}: rank={d['rank']}" for p, d in detail.items())
        print(f"  - [RRF={r['score']:.4f}] {r['article']['title']} | {r['chunk_text'][:50]}...")
        print(f"    各路排名: {paths_info}")
