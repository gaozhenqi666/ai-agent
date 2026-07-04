"""
agents/embedder.py
==========================================================
阿里云 DashScope text-embedding-v4 客户端
- 兼容 OpenAI 协议（/v1/embeddings）
- 1024 维 float32
- 支持批量（默认 10 条/批）
- 返回 list[list[float]]
==========================================================
"""

from __future__ import annotations
from common import *  # 项目级基础库
from common import log, Config

import httpx


# ---------- 1. 批量 embedding ----------
def embed_texts(texts: list[str], batch_size: int | None = None) -> list[list[float]]:
    """
    批量文本 → 向量
    输入: ["text1", "text2", ...]
    输出: [[0.1, 0.2, ...], [...], ...]
    """
    if not texts:
        return []
    if not Config.DASHSCOPE_API_KEY:
        raise RuntimeError("DASHSCOPE_API_KEY 未配置")

    batch_size = batch_size or Config.EMBEDDING_BATCH
    all_embeddings: list[list[float]] = []

    for i in range(0, len(texts), batch_size):
        batch = texts[i:i + batch_size]
        log.info(f"[embedder] 批次 {i // batch_size + 1}/{(len(texts) + batch_size - 1) // batch_size}，{len(batch)} 条")
        embeddings = _call_dashscope(batch)
        all_embeddings.extend(embeddings)

    return all_embeddings


def embed_one(text: str) -> list[float]:
    """单条文本 → 向量"""
    return embed_texts([text])[0]


# ---------- 2. HTTP 调用 ----------
def _call_dashscope(texts: list[str]) -> list[list[float]]:
    """调 DashScope 兼容 OpenAI 的 /v1/embeddings"""
    url = f"{Config.DASHSCOPE_BASE_URL}/embeddings"
    headers = {
        "Authorization": f"Bearer {Config.DASHSCOPE_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":          Config.EMBEDDING_MODEL,
        "input":          texts,
        "encoding_format":"float",
        "dimensions":     Config.EMBEDDING_DIM,
    }

    try:
        with httpx.Client(timeout=60.0) as client:
            resp = client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()
    except httpx.HTTPStatusError as e:
        log.error(f"[embedder] HTTP {e.response.status_code}: {e.response.text[:200]}")
        raise
    except Exception as e:
        log.error(f"[embedder] 调用失败: {e}")
        raise

    # 解析 OpenAI 格式响应
    try:
        items = data["data"]
        # 按 index 排序（默认已经有序）
        items = sorted(items, key=lambda x: x.get("index", 0))
        return [item["embedding"] for item in items]
    except (KeyError, TypeError) as e:
        log.error(f"[embedder] 响应解析失败: {e}, data={str(data)[:200]}")
        raise


# ---------- 快速测试 ----------
if __name__ == "__main__":
    vecs = embed_texts(["RAG 是什么", "什么是 RAG"])
    print(f"返回 {len(vecs)} 条向量，维度 {len(vecs[0]) if vecs else 0}")
    if len(vecs) >= 2:
        from common import cosine_similarity
        sim = cosine_similarity(vecs[0], vecs[1])
        print(f"两条相似度: {sim:.4f}")
