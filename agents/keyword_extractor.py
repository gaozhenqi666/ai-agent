"""
agents/keyword_extractor.py
==========================================================
从用户问题中提取关键词（用于 BM25 / 关键词检索）
- 用 LLM（DeepSeek）提取 3-8 个关键词
- 失败时 fallback 到简单的 jieba / 字符分词
==========================================================
"""

from __future__ import annotations
from common import *  # 项目级基础库
from common import log, llm_chat, Config

import json
import re


SYSTEM_PROMPT = """你是一个关键词提取助手。从用户问题中提取 3-8 个**检索关键词**，用于在知识库中精准匹配。

要求：
1. 优先提取：专有名词、技术术语、型号、错误代码、人名
2. 中英文混排时分开提取
3. 输出严格的 JSON 数组格式：["关键词1", "关键词2", ...]
4. 不要解释，不要多余文字
"""


def extract_keywords(query: str, max_keywords: int = 6) -> list[str]:
    """
    从 query 中提取关键词
    优先用 LLM，失败用本地分词
    """
    if not query or not query.strip():
        return []

    keywords = _extract_with_llm(query, max_keywords)
    if keywords:
        return keywords

    # fallback: 本地分词
    return _extract_with_local(query, max_keywords)


# ---------- 1. LLM 提取 ----------
def _extract_with_llm(query: str, max_keywords: int) -> list[str]:
    user = f"问题：{query}\n\n提取关键词（JSON 数组）："

    try:
        resp = llm_chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user},
            ],
            temperature=0.1,
            max_tokens=200,
        )
        text = resp["content"].strip()
        log.info(f"[keyword_extractor] LLM 返回: {text[:100]}")

        # 解析 JSON（容错：可能包在 ```json ... ``` 里）
        m = re.search(r"\[.*?\]", text, re.DOTALL)
        if m:
            arr = json.loads(m.group(0))
            if isinstance(arr, list):
                return [str(x).strip() for x in arr if str(x).strip()][:max_keywords]
        return []
    except Exception as e:
        log.warning(f"[keyword_extractor] LLM 提取失败，回退本地分词: {e}")
        return []


# ---------- 2. 本地分词（fallback）----------
def _extract_with_local(query: str, max_keywords: int) -> list[str]:
    """
    简单的本地分词：
    1. 提取英文/数字 token
    2. 提取中文 2-4 字词
    3. 保留长度 >= 2 的有意义片段
    """
    keywords = set()

    # 1) 英文 + 数字 token
    for m in re.findall(r"[A-Za-z0-9_\-\.]{2,}", query):
        keywords.add(m)

    # 2) 中文 2~4 字词
    for m in re.findall(r"[\u4e00-\u9fff]{2,4}", query):
        # 简单过滤：跳过太常见的字
        if not _is_stopword(m):
            keywords.add(m)

    # 3) 数字 + 中文（型号、错误码等）
    for m in re.findall(r"[0-9]+[\u4e00-\u9fffA-Za-z]{1,5}", query):
        keywords.add(m)

    result = list(keywords)[:max_keywords]
    log.info(f"[keyword_extractor] 本地分词: {result}")
    return result


def _is_stopword(text: str) -> bool:
    """简单停用词过滤"""
    stops = {
        "什么", "怎么", "如何", "为何", "为什么", "可以", "应该", "需要",
        "一个", "这个", "那个", "我们", "你们", "他们", "自己", "进行",
        "好的", "是的", "不对", "或者", "然后", "因为", "所以", "但是",
        "现在", "以前", "以后", "时候", "地方", "东西", "情况", "问题",
    }
    return text in stops


# ---------- 快速测试 ----------
if __name__ == "__main__":
    qs = [
        "iPhone 15 怎么查序列号？",
        "RAG 中的 BM25 是什么意思",
        "Python asyncio.gather 和 TaskGroup 的区别",
    ]
    for q in qs:
        kws = extract_keywords(q)
        print(f"Q: {q}\n   关键词: {kws}\n")
