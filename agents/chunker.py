"""
agents/chunker.py
==========================================================
递归字符切片器（RecursiveCharacterTextSplitter）
- 按层级分隔符递归切：段落 → 行 → 句 → 词 → 字符
- 默认 chunk_size=500, overlap=50
- 每个 chunk 包含：text, start_pos, end_pos, chunk_index
==========================================================
"""

from __future__ import annotations
from common import *  # 项目级基础库
from common import log

DEFAULT_SEPARATORS = ["\n\n", "\n", "。", "！", "？", ".", "!", "?", " ", ""]
DEFAULT_CHUNK_SIZE = 500
DEFAULT_OVERLAP    = 50


def recursive_split(
    text: str,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
    overlap: int    = DEFAULT_OVERLAP,
    separators: list | None = None,
) -> list[dict]:
    """
    递归字符切片主入口
    返回: list of {chunk_index, text, start_pos, end_pos, size}
    """
    if not text or not text.strip():
        return []

    seps = separators or DEFAULT_SEPARATORS
    raw_chunks = _split_recursive(text, seps, chunk_size, overlap)

    # 后处理：补充位置信息（start_pos, end_pos）和 chunk_index
    return _annotate_positions(text, raw_chunks)


def _split_recursive(
    text: str,
    separators: list[str],
    chunk_size: int,
    overlap: int,
) -> list[str]:
    """递归切分核心（不带位置信息）"""
    final_chunks: list[str] = []
    separator = separators[-1]      # 默认最后一级
    new_seps: list[str] = []

    # 找到第一个在 text 中实际存在的分隔符
    for i, sep in enumerate(separators):
        if sep == "" or sep in text:
            separator = sep
            new_seps = separators[i + 1:]
            break

    # 用选中的分隔符切
    if separator:
        splits = text.split(separator)
    else:
        # 字符级硬切
        splits = list(text)

    good_splits: list[str] = []
    for s in splits:
        if len(s) < chunk_size:
            good_splits.append(s)
        else:
            # 当前段太长：先 flush 已累积的
            if good_splits:
                merged = _merge_splits(good_splits, separator, chunk_size, overlap)
                final_chunks.extend(merged)
                good_splits = []
            # 继续递归
            if not new_seps or separator == "":
                # 没有更细的分隔符了，硬切
                hard_chunks = _hard_split(s, chunk_size, overlap)
                final_chunks.extend(hard_chunks)
            else:
                sub_chunks = _split_recursive(s, new_seps, chunk_size, overlap)
                final_chunks.extend(sub_chunks)

    if good_splits:
        merged = _merge_splits(good_splits, separator, chunk_size, overlap)
        final_chunks.extend(merged)

    return [c for c in final_chunks if c.strip()]


def _merge_splits(splits: list[str], separator: str, chunk_size: int, overlap: int) -> list[str]:
    """
    把小段合并成不超过 chunk_size 的大段
    overlap：相邻 chunk 的重叠字符数（从上一个 chunk 末尾取）
    """
    separator = separator if separator else ""
    chunks: list[str] = []
    current = ""
    for s in splits:
        if current:
            candidate = current + separator + s
        else:
            candidate = s
        if len(candidate) <= chunk_size:
            current = candidate
        else:
            if current:
                chunks.append(current)
                # 下一个 chunk 从 current 末尾 overlap 字符开始
                if overlap > 0 and len(current) > overlap:
                    current = current[-overlap:] + separator + s
                else:
                    current = s
                if len(current) > chunk_size:
                    # 仍然超长，硬切
                    sub = _hard_split(current, chunk_size, overlap)
                    chunks.extend(sub[:-1])
                    current = sub[-1] if sub else ""
            else:
                current = s
    if current:
        chunks.append(current)
    return chunks


def _hard_split(text: str, chunk_size: int, overlap: int) -> list[str]:
    """硬切（按字符），保留 overlap"""
    if len(text) <= chunk_size:
        return [text]
    step = max(1, chunk_size - overlap)
    chunks = []
    for i in range(0, len(text), step):
        c = text[i:i + chunk_size]
        if c:
            chunks.append(c)
        if i + chunk_size >= len(text):
            break
    return chunks


def _annotate_positions(original: str, chunks: list[str]) -> list[dict]:
    """
    给每个 chunk 标注：起止位置（在原文中的字符 index）+ 序号
    """
    out: list[dict] = []
    pos = 0
    for idx, ch in enumerate(chunks):
        # 从 pos 开始找 ch 的位置（用 startswith 防止前导 separator 干扰）
        idx_found = original.find(ch, pos)
        if idx_found < 0:
            # 找不到（比如 overlap 把 chunk 切碎），按顺序递增
            idx_found = pos
        start = idx_found
        end   = idx_found + len(ch)
        out.append({
            "chunk_index": idx,
            "text":        ch,
            "start_pos":   start,
            "end_pos":     end,
            "size":        len(ch),
        })
        pos = max(end - 0, start + 1)  # overlap 块时前进到 end
    return out


# ---------- 快速测试 ----------
if __name__ == "__main__":
    sample = """
RAG 是检索增强生成（Retrieval-Augmented Generation）的缩写。它的核心思想是：
让大模型在回答问题之前，先去外部知识库检索相关资料，然后基于这些资料生成答案。

为什么需要 RAG？大模型的知识是冻结的（训练完就固定了），无法回答最新信息，
也无法引用私有数据。RAG 通过外挂知识库解决了这两个问题。

典型流程：
1. 用户提问 → query
2. query 转向量 → 检索向量数据库中 Top K 相似文档
3. 把检索到的文档和 query 一起塞给 LLM
4. LLM 基于文档生成答案

工程上的关键点：
- 切片策略：递归字符切片、语义切片
- 检索策略：BM25 + 向量检索 + RRF 融合
- 评估指标：召回率、答案准确率、延迟
    """.strip()

    chunks = recursive_split(sample, chunk_size=200, overlap=30)
    print(f"切成 {len(chunks)} 段:")
    for c in chunks:
        print(f"  [{c['chunk_index']}] {c['start_pos']}-{c['end_pos']} ({c['size']} 字符)")
        print(f"      {c['text'][:60]!r}...")
