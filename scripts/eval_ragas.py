"""
eval_ragas.py
==========================================================
使用 RAGAS 评估知识库检索质量

运行方式：
  1. 先导入文章：python scripts/seed_ai_articles.py
  2. 再运行评估：python scripts/eval_ragas.py

评估指标：
  - Context Precision：检索到的上下文中，实际相关的比例
  - Context Recall：ground truth 中被检索到的比例
  - Context F1：精确率和召回率的调和平均
  - Context Relevancy：检索上下文与查询的相关度

F1 >= 0.7 可认为检索质量合格
==========================================================
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import log
from tools.retriever_tool import multi_recall_search


# ============================================================
# 测试数据集：{question, ground_truth_contexts}
# ground_truth_contexts 是应该被检索到的关键词列表，
# 用于判断检索结果是否命中相关 chunk
# ============================================================

TEST_DATASET = [
    {
        "question": "什么是 RAG？RAG 的核心架构包含哪些模块？",
        "ground_truth_keywords": [
            "检索增强生成", "Retrieval-Augmented Generation", "RAG",
            "索引模块", "Indexing", "检索模块", "Retrieval",
            "生成模块", "Generation", "Naive RAG", "Advanced RAG",
        ],
    },
    {
        "question": "混合检索和多路召回有什么区别？RRF 是怎么融合的？",
        "ground_truth_keywords": [
            "混合检索", "Hybrid Search", "多路召回", "Multi-Recall",
            "倒数排序融合", "RRF", "Reciprocal Rank Fusion",
            "BM25", "向量检索", "融合策略",
        ],
    },
    {
        "question": "RRF 公式是什么？k 值取多少最合适？",
        "ground_truth_keywords": [
            "RRF", "Reciprocal Rank Fusion", "倒数排序融合",
            "k = 60", "平滑常数", "1 / (k + rank)", "排名",
        ],
    },
    {
        "question": "RAGAS 有哪些评估指标？F1 值怎么计算？",
        "ground_truth_keywords": [
            "RAGAS", "评估", "Context Precision", "Context Recall",
            "Faithfulness", "Answer Relevancy", "F1",
            "调和平均", "Precision", "Recall",
        ],
    },
    {
        "question": "文档切片策略有哪些？chunk_size 和 overlap 怎么设置？",
        "ground_truth_keywords": [
            "切片", "Chunking", "chunk_size", "chunk_overlap",
            "递归字符分割", "语义切片", "固定大小切片",
            "Small-to-Big", "重叠",
        ],
    },
    {
        "question": "LangChain 和 LlamaIndex 在 RAG 方面各有什么优势？",
        "ground_truth_keywords": [
            "LangChain", "LlamaIndex", "RAG", "框架",
            "Chain", "Agent", "Index", "QueryEngine",
        ],
    },
    {
        "question": "AI Agent 的核心组件有哪些？什么是 ReAct 模式？",
        "ground_truth_keywords": [
            "Agent", "推理引擎", "LLM", "记忆系统", "Memory",
            "工具使用", "Tool Use", "ReAct",
            "Reasoning", "Acting", "规划模块",
        ],
    },
    {
        "question": "ReAct 和 Function Calling 两种 Agent 模式有什么区别？",
        "ground_truth_keywords": [
            "ReAct", "Function Calling", "Agent", "Tool Use",
            "Thought", "Action", "Observation", "JSON",
        ],
    },
    {
        "question": "多 Agent 系统有哪些编排模式？AutoGen 和 CrewAI 有什么区别？",
        "ground_truth_keywords": [
            "多 Agent", "Multi-Agent", "AutoGen", "CrewAI",
            "编排", "Sequential", "Parallel", "Router",
            "Collaborative",
        ],
    },
    {
        "question": "有哪些主流的 embedding 模型？怎么选择？",
        "ground_truth_keywords": [
            "Embedding", "BGE-M3", "text-embedding-3", "通义千问",
            "MTEB", "向量模型", "embedding 模型",
            "Jina", "DashScope",
        ],
    },
    {
        "question": "如何评估 RAG 系统的检索质量？",
        "ground_truth_keywords": [
            "评估", "RAG", "检索质量", "RAGAS",
            "Precision", "Recall", "F1", "NDCG", "MRR",
        ],
    },
    {
        "question": "BM25 和向量检索各自有什么优缺点？",
        "ground_truth_keywords": [
            "BM25", "向量检索", "稀疏检索", "稠密检索",
            "关键词匹配", "语义相似", "余弦相似度",
        ],
    },
]

TOP_K = 5


# ============================================================
# 评估函数
# ============================================================

def _hit_keywords(chunk_text: str, article_title: str, keywords: list[str]) -> int:
    """计算 chunk 命中了多少个 ground truth 关键词"""
    text = (chunk_text + " " + article_title).lower()
    hits = 0
    for kw in keywords:
        if kw.lower() in text:
            hits += 1
    return hits


def evaluate_retrieval(test_dataset: list[dict], top_k: int = TOP_K) -> dict:
    """
    对每条测试 query 执行检索，计算 Precision@K、Recall@K、F1@K

    Precision@K = 相关 chunk 数 / K
    Recall@K   = 命中的不同关键词数 / ground truth 关键词总数
    F1@K       = 2 * P * R / (P + R)
    """
    all_precisions = []
    all_recalls = []
    all_f1s = []
    details = []

    for idx, item in enumerate(test_dataset):
        question = item["question"]
        gt_keywords = item["ground_truth_keywords"]
        gt_keyword_count = len(gt_keywords)

        # 执行多路召回 + RRF 检索
        results = multi_recall_search(question, top_k=top_k)

        # 统计每个 chunk 的关键词命中数
        chunk_hits = []
        for r in results:
            article_title = r.get("article", {}).get("title", "")
            hits = _hit_keywords(r["chunk_text"], article_title, gt_keywords)
            chunk_hits.append(hits)

        # 相关 chunk：命中 >= 1 个关键词
        relevant_count = sum(1 for h in chunk_hits if h > 0)
        # 唯一命中的关键词（去重）
        all_hit_keywords: set[str] = set()
        for r in results:
            article_title = r.get("article", {}).get("title", "")
            text = (r["chunk_text"] + " " + article_title).lower()
            for kw in gt_keywords:
                if kw.lower() in text:
                    all_hit_keywords.add(kw.lower())

        precision = relevant_count / top_k if top_k > 0 else 0
        recall = len(all_hit_keywords) / gt_keyword_count if gt_keyword_count > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        all_precisions.append(precision)
        all_recalls.append(recall)
        all_f1s.append(f1)

        details.append({
            "question": question[:60],
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "retrieved": len(results),
            "relevant": relevant_count,
            "hit_keywords": len(all_hit_keywords),
            "total_gt_keywords": gt_keyword_count,
        })

    avg_precision = sum(all_precisions) / len(all_precisions)
    avg_recall = sum(all_recalls) / len(all_recalls)
    avg_f1 = sum(all_f1s) / len(all_f1s)

    return {
        "avg_precision": round(avg_precision, 4),
        "avg_recall": round(avg_recall, 4),
        "avg_f1": round(avg_f1, 4),
        "num_queries": len(test_dataset),
        "top_k": top_k,
        "details": details,
    }


def print_report(result: dict):
    """打印评估报告"""
    print("\n" + "=" * 60)
    print("  RAG 检索质量评估报告（多路召回 + RRF）")
    print("=" * 60)
    print(f"  测试查询数：{result['num_queries']}")
    print(f"  Top-K：{result['top_k']}")
    print("-" * 60)
    print(f"  Avg Precision@{result['top_k']} : {result['avg_precision']:.4f}")
    print(f"  Avg Recall@{result['top_k']}    : {result['avg_recall']:.4f}")
    print(f"  Avg F1@{result['top_k']}        : {result['avg_f1']:.4f}")
    print("-" * 60)

    # 判定是否合格
    if result["avg_f1"] >= 0.7:
        print("  结论：检索质量合格  (F1 >= 0.7)")
    elif result["avg_f1"] >= 0.5:
        print("  结论：检索质量一般  (0.5 <= F1 < 0.7)，建议优化")
    else:
        print("  结论：检索质量不足  (F1 < 0.5)，需要显著改进")
    print("=" * 60)

    # 逐条详情
    print("\n  逐条详情：")
    print(f"  {'查询':<40s} {'P':>6s} {'R':>6s} {'F1':>6s}  {'相关/K':>8s}  {'命中KW':>8s}")
    print("  " + "-" * 85)
    for d in result["details"]:
        q = d["question"][:38]
        print(f"  {q:<40s} {d['precision']:>6.4f} {d['recall']:>6.4f} {d['f1']:>6.4f}  "
              f"{d['relevant']}/{d['retrieved']:<5d}  {d['hit_keywords']:>3d}/{d['total_gt_keywords']:<3d}")


def compare_with_hybrid(result_rrf: dict):
    """
    简单对比：也出一份传统 hybrid_search 的结果，与 RRF 对比
    注：hybrid_search 目前委托给 multi_recall_search，所以这里分别用
    multi_recall_search 仅 vector+bm25 双路 vs 全三路来对比
    """
    print("\n\n" + "=" * 60)
    print("  各路召回路径消融对比")
    print("=" * 60)

    configs = {
        "向量 + BM25（双路）": ["vector", "bm25"],
        "向量 + BM25 + 标签（三路）": ["vector", "bm25", "tag"],
    }

    for name, paths in configs.items():
        all_f1s = []
        for item in TEST_DATASET:
            results = multi_recall_search(item["question"], top_k=TOP_K, recall_paths=paths)
            chunk_hits = []
            for r in results:
                article_title = r.get("article", {}).get("title", "")
                hits = _hit_keywords(r["chunk_text"], article_title, item["ground_truth_keywords"])
                chunk_hits.append(hits)

            relevant = sum(1 for h in chunk_hits if h > 0)
            precision = relevant / TOP_K

            all_hit = set()
            for r in results:
                article_title = r.get("article", {}).get("title", "")
                text = (r["chunk_text"] + " " + article_title).lower()
                for kw in item["ground_truth_keywords"]:
                    if kw.lower() in text:
                        all_hit.add(kw.lower())
            recall = len(all_hit) / len(item["ground_truth_keywords"])
            f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0
            all_f1s.append(f1)

        avg_f1 = sum(all_f1s) / len(all_f1s)
        print(f"  {name:<30s} Avg F1@{TOP_K} = {avg_f1:.4f}")


if __name__ == "__main__":
    print("正在评估多路召回 + RRF 检索质量...")
    result = evaluate_retrieval(TEST_DATASET, top_k=TOP_K)
    print_report(result)
    compare_with_hybrid(result)
