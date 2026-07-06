"""
build_eval_corpus.py
==========================================================
大规模知识库构建 + RAGAS 评测一体化脚本

用法：
  python3 scripts/build_eval_corpus.py

流程：
  1. 按 8 个主题生成 ~100 篇长文（LLM 逐篇生成，每篇 3000-5000 字）
  2. 自动 chunk + embed 存入知识库
  3. 自动生成 150 道跨主题评测题
  4. 运行多路召回 + RRF 检索
  5. 计算 F1 / Precision / Recall 并输出报告

预计时间：~15-25 分钟（受 LLM API 速率限制）
==========================================================
"""

import sys
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import db_exec, now_iso, new_id, log, llm_chat
from tools.chunker_tool import recursive_split
from tools.retriever_tool import save_chunks, multi_recall_search

# ============================================================
# 主题面设计（8 个主题，100 篇文章）
# ============================================================

TOPICS = {
    "RAG基础架构": [
        "RAG（检索增强生成）核心架构：索引、检索、生成三模块详解",
        "Naive RAG、Advanced RAG、Modular RAG 三代范式演进",
        "RAG 中检索模块的设计原则与工程实践",
        "RAG 的生成模块：如何将检索上下文有效注入 LLM Prompt",
        "RAG 中的知识库构建：文档解析、清洗、结构化",
        "RAG 索引模块深度解析：从文档到向量的全流程",
        "RAG 系统的延迟优化策略：检索加速与生成加速",
        "Self-RAG：自我反思式检索增强生成的原理与实现",
        "CRAG（Corrective RAG）：纠错式检索增强生成",
        "Graph RAG：基于知识图谱的检索增强生成方法",
        "RAG 中的 Query 改写技术：Multi-Query、HyDE、Step-Back",
        "RAG 应用中的幻觉问题：成因分析与缓解策略",
    ],
    "向量与嵌入模型": [
        "文本嵌入（Text Embedding）的数学原理与几何直觉",
        "BGE-M3 模型详解：多语言、多功能、多粒度的嵌入方案",
        "OpenAI text-embedding-3 系列：维度可调的嵌入模型创新",
        "对比学习（Contrastive Learning）在嵌入模型训练中的应用",
        "MTEB 基准评测：全面衡量嵌入模型的检索、分类、聚类能力",
        "嵌入模型的微调：如何针对特定领域优化检索效果",
        "稀疏嵌入 vs 稠密嵌入：SPLADE、BGE-M3 Sparse 对比",
        "多语言嵌入模型的挑战与解决方案",
        "嵌入模型的压缩与量化：从 float32 到 int8 的精度权衡",
        "ColBERT 与迟交互（Late Interaction）检索范式",
        "Matryoshka 嵌入表示：一个模型支持多维度输出的技术",
        "指令感知嵌入（Instruction-tuned Embedding）：按任务调整表示",
    ],
    "混合检索与排序": [
        "混合检索（Hybrid Search）的完整技术栈与实现方案",
        "稠密检索（Dense Retrieval）的索引结构：Flat、IVF、HNSW 对比",
        "BM25 算法完整推导：从 TF-IDF 到概率检索框架",
        "倒数排序融合（RRF）的数学原理与工程最佳实践",
        "多路召回架构设计：向量、关键词、实体、图谱四路融合",
        "重排序（Reranking）模型对比：Cohere、BGE-Reranker、RankGPT",
        "学习排序（Learning to Rank）在 RAG 中的应用",
        "两阶段检索：粗排召回 + 精排重排的工业级方案",
        "查询扩展（Query Expansion）与稀疏检索增强",
        "近似最近邻（ANN）搜索算法综述：LSH、PQ、HNSW、DiskANN",
        "RAG 中的多样性检索：MMR 与最大边际相关性",
        "检索结果的上下文窗口优化：合并、去重、排序策略",
    ],
    "文本切片策略": [
        "文档切片（Chunking）的工程实践：语义边界与长度平衡",
        "递归字符分割（Recursive Character Split）的算法实现",
        "语义切片（Semantic Chunking）：基于嵌入相似度的自适应切分",
        "句子感知切片（Sentence-Aware Chunking）：保持语言完整性",
        "Small-to-Big 检索策略：小粒度检索搭配大窗口返回",
        "父子文档索引（Parent-Child Index）：chunk 与原文的映射关系",
        "不同文档类型的切片策略：PDF、网页、代码、表格",
        "滑动窗口切片与上下文扩展技术",
        "基于文档结构的智能切片：利用标题层级和段落信息",
        "多粒度索引：同时维护粗粒度和细粒度的 chunk 索引",
        "切片大小对 RAG 性能影响的系统实验分析",
        "动态切片（Dynamic Chunking）：基于内容密度调整大小",
    ],
    "AI Agent设计": [
        "AI Agent 的认知架构：感知、推理、规划、执行的闭环",
        "ReAct 范式详解：Reasoning 与 Acting 交替协作机制",
        "Function Calling 深度解析：工具定义、参数校验、错误恢复",
        "Plan-and-Execute Agent：先规划后执行的两阶段范式",
        "Agent 记忆系统设计：短期、长期、工作记忆的协同",
        "Agent 的工具编排：工具注册、发现、调用、结果整合",
        "LLM Compiler：将任务编译为可执行 DAG 的 Agent 架构",
        "反思式 Agent（Reflexion）：通过自我批评改进执行结果",
        "代码生成 Agent：从 SWE-Agent 到 Devin 的技术演进",
        "Agent 的安全护栏：输入过滤、工具权限、输出审核",
        "Agent 的评估方法：任务完成率、工具调用准确性、效率",
        "多模态 Agent：整合视觉、语音、文本的感知与行动",
    ],
    "多智能体系统": [
        "多 Agent 系统（MAS）的核心通信协议与消息设计",
        "AutoGen 框架深入：对话驱动多 Agent 协作的实现",
        "CrewAI 的角色驱动架构：Agent、Task、Crew 的协作模型",
        "LangGraph 的状态图 Agent：条件分支、循环、人机协同",
        "多 Agent 辩论（Debate）机制：通过对抗提升推理质量",
        "层级式多 Agent 编排：主管 Agent 分解任务分配子 Agent",
        "并行 Agent 执行：任务拆分、结果合并、冲突消解",
        "Agent 间的知识共享与经验传递机制",
        "MetaGPT：模拟软件公司角色分工的多 Agent 代码生成",
        "多 Agent 强化学习：通过博弈优化协作策略",
        "ChatDev：基于自然语言沟通的虚拟软件团队",
        "多 Agent 系统的可观测性：日志、追踪、性能监控",
    ],
    "RAG评估与测试": [
        "RAGAS 评估框架全面解析：指标定义、计算方式、使用场景",
        "Context Precision 与 Context Recall 的详细计算与工程实现",
        "Faithfulness（忠实度）评估：基于 NLI 的事实一致性判断",
        "Answer Relevancy（回答相关性）的自动化评估方法",
        "RAG 评估数据集构建：如何标注高质量的评测集",
        "端到端 RAG 评估管线：检索评估 + 生成评估的串联",
        "人工评估 vs 自动评估：RAG 质量判断的适用场景与局限性",
        "基于 LLM-as-Judge 的 RAG 评估范式",
        "RAG 系统的 A/B 测试框架设计与指标选择",
        "RAG 评估中的陷阱：位置偏差、长度偏差、文体偏差",
        "合成数据生成：使用 LLM 自动构建 RAG 评测集",
        "RAG 系统的持续评估与回归测试策略",
        "RAG 检索质量的 F1、NDCG、MRR 多指标对比分析",
    ],
    "LLM与提示工程": [
        "Chain-of-Thought（CoT）提示：通过中间推理提升复杂任务准确率",
        "Tree-of-Thought（ToT）：探索多条推理路径的最优解搜索",
        "少样本提示（Few-Shot Prompting）的策略设计与示例选择",
        "提示注入（Prompt Injection）攻击与防御技术综述",
        "结构化输出：从 JSON Mode 到 Function Calling 的演进",
        "提示工程的系统化方法：模板设计、变量管理、A/B 优化",
        "长上下文 LLM 的提示策略：信息密度、位置效应、注意力分配",
        "System Prompt 设计原则：角色定义、约束声明、输出格式",
        "DSPy 框架：编程化提示优化与自动组合的声明式方法",
        "提示压缩（Prompt Compression）技术：减少 token 消耗的策略",
        "基于 LLM 的文本摘要策略：Extractive、Abstractive 与混合方法",
        "LLM 的对齐技术：RLHF、DPO、宪法 AI 的对比分析",
        "LLM 推理加速：KV Cache、Speculative Decoding、量化推理",
    ],
}

# ============================================================
# 批量生成文章（调用 LLM）
# ============================================================

SYSTEM_PROMPT = """你是一个技术文档撰写专家。请根据给定的文章标题，撰写一篇结构完整的技术文章。

要求：
1. 文章长度：3000-5000 字（中文），必须是完整段落，不能是提纲或列表
2. 内容：深入、具体、有细节，包含技术原理、实现方法、优缺点对比
3. 结构：有引言、正文分点、总结三个部分
4. 语言：专业但易读，避免空洞的套话
5. 只输出文章正文，不要包含标题、不要用 markdown 标题符号（#）"""


def generate_article(title: str, topic: str) -> str:
    """调用 LLM 生成一篇文章"""
    user_prompt = f"请撰写一篇技术文章，主题是：「{title}」\n\n这篇文章属于「{topic}」系列。"
    try:
        resp = llm_chat(
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            max_tokens=3000,
        )
        content = resp.get("content", "")
        if len(content) < 500:
            log.warning(f"  生成内容太短 ({len(content)} 字): {title[:30]}")
            return ""
        return content
    except Exception as e:
        log.error(f"  生成失败: {title[:30]} | {e}")
        return ""


def build_knowledge_base():
    """批量生成文章并入库"""
    total_articles = sum(len(titles) for titles in TOPICS.values())
    log.info(f"开始生成 {total_articles} 篇文章（8 个主题）...")

    count = 0
    total_chunks = 0

    for topic_name, titles in TOPICS.items():
        log.info(f"\n{'='*50}")
        log.info(f"主题: {topic_name} ({len(titles)} 篇)")
        log.info(f"{'='*50}")

        for idx, title in enumerate(titles, 1):
            log.info(f"  [{idx}/{len(titles)}] 生成: {title[:50]}...")
            content = generate_article(title, topic_name)
            if not content:
                log.warning(f"  跳过（生成失败）")
                continue

            # 入库
            article_id = new_id("art-")
            now = now_iso()
            tags = [topic_name]
            tags_json = json.dumps(tags, ensure_ascii=False)

            db_exec(
                """INSERT INTO knowledge_articles
                   (article_id, title, url, content, summary, source, tags, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?)""",
                [article_id, title, "", content, content[:200],
                 "LLM-Generated", tags_json, "published", now, now],
            )

            chunks = recursive_split(content, chunk_size=500, overlap=50)
            n = save_chunks(article_id, chunks)
            total_chunks += n
            count += 1

            log.info(f"    -> {len(content)} 字, {n} chunks")

            # 避免 API 限流
            time.sleep(0.5)

    log.info(f"\n导入完成: {count} 篇文章, {total_chunks} chunks")
    return count, total_chunks


# ============================================================
# 评测题生成
# ============================================================

QA_SYSTEM_PROMPT = """你是一个 RAG 系统评测专家。请根据给定的文章标题和主题生成检索评测题。

要求：
1. 为每篇文章生成 1-2 个自然语言问题
2. 问题应该能用该文章的内容回答（模拟真实用户查询）
3. 同时给出 ground truth 关键词（文章中应该出现的 5-10 个关键词）
4. 输出 JSON 格式：[{"question": "...", "ground_truth_keywords": [...]}, ...]
5. 只输出 JSON 数组，不要包含任何其他内容"""


def generate_questions() -> list[dict]:
    """批量生成评测题"""
    all_questions = []
    articles = db_exec(
        """SELECT article_id, title, tags FROM knowledge_articles
           WHERE status='published' AND source='LLM-Generated'
           ORDER BY rowid""",
        [],
    )

    log.info(f"为 {len(articles)} 篇文章生成评测题...")
    batch_size = 10
    for i in range(0, len(articles), batch_size):
        batch = articles[i:i + batch_size]
        titles_text = "\n".join(
            f"{j+1}. [{a['tags']}] {a['title']}"
            for j, a in enumerate(batch)
        )
        user_prompt = f"请为以下文章生成检索评测题（每篇 1-2 题），输出 JSON 数组：\n\n{titles_text}"

        try:
            resp = llm_chat(
                messages=[
                    {"role": "system", "content": QA_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.5,
                max_tokens=2000,
            )
            raw = resp.get("content", "")
            # 提取 JSON 数组
            json_match = raw.strip()
            if "```json" in json_match:
                json_match = json_match.split("```json")[1].split("```")[0]
            elif "```" in json_match:
                json_match = json_match.split("```")[1].split("```")[0]
            batch_questions = json.loads(json_match)
            all_questions.extend(batch_questions)
            log.info(f"  已生成 {len(all_questions)} 题 (batch {i//batch_size + 1})")
        except Exception as e:
            log.warning(f"  题目生成失败 batch {i//batch_size + 1}: {e}")

        time.sleep(0.3)

    return all_questions


# ============================================================
# RAGAS 评估
# ============================================================

def _hit_keywords(chunk_text: str, article_title: str, keywords: list[str]) -> int:
    text = (chunk_text + " " + article_title).lower()
    hits = 0
    for kw in keywords:
        if kw.lower() in text:
            hits += 1
    return hits


def evaluate(test_questions: list[dict], top_k: int = 5):
    """RAGAS 检索质量评估"""
    all_precisions = []
    all_recalls = []
    all_f1s = []
    details = []

    for idx, item in enumerate(test_questions):
        question = item["question"]
        gt_keywords = item.get("ground_truth_keywords", [])
        if not gt_keywords:
            continue
        gt_count = len(gt_keywords)

        results = multi_recall_search(question, top_k=top_k)

        chunk_hits = []
        all_hit_kw = set()
        for r in results:
            atitle = r.get("article", {}).get("title", "")
            hits = _hit_keywords(r["chunk_text"], atitle, gt_keywords)
            chunk_hits.append(hits)
            text = (r["chunk_text"] + " " + atitle).lower()
            for kw in gt_keywords:
                if kw.lower() in text:
                    all_hit_kw.add(kw.lower())

        relevant = sum(1 for h in chunk_hits if h > 0)
        precision = relevant / top_k if top_k > 0 else 0
        recall = len(all_hit_kw) / gt_count if gt_count > 0 else 0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

        all_precisions.append(precision)
        all_recalls.append(recall)
        all_f1s.append(f1)
        details.append({"question": question[:60], "precision": round(precision, 4),
                        "recall": round(recall, 4), "f1": round(f1, 4),
                        "relevant": relevant, "hit_kw": len(all_hit_kw), "gt_kw": gt_count})

    avg_p = sum(all_precisions) / len(all_precisions) if all_precisions else 0
    avg_r = sum(all_recalls) / len(all_recalls) if all_recalls else 0
    avg_f1 = sum(all_f1s) / len(all_f1s) if all_f1s else 0

    return {"avg_precision": round(avg_p, 4), "avg_recall": round(avg_r, 4),
            "avg_f1": round(avg_f1, 4), "num_queries": len(test_questions),
            "top_k": top_k, "details": details}


def print_report(result: dict):
    print("\n" + "=" * 70)
    print("  RAG 检索质量评估报告（大规模语料 + 多路召回 + RRF）")
    print("=" * 70)
    print(f"  评测题数量  : {result['num_queries']}")
    print(f"  Top-K       : {result['top_k']}")
    print(f"  召回路径    : vector + BM25 + tag → RRF(k=60)")
    print("-" * 70)
    print(f"  Avg Precision@{result['top_k']} : {result['avg_precision']:.4f}")
    print(f"  Avg Recall@{result['top_k']}    : {result['avg_recall']:.4f}")
    print(f"  Avg F1@{result['top_k']}        : {result['avg_f1']:.4f}")
    print("-" * 70)
    if result["avg_f1"] >= 0.85:
        print("  结论: ★★★ 优秀 (F1 >= 0.85)")
    elif result["avg_f1"] >= 0.75:
        print("  结论: ★★☆ 良好 (0.75 <= F1 < 0.85)")
    elif result["avg_f1"] >= 0.65:
        print("  结论: ★★ 合格 (0.65 <= F1 < 0.75)")
    elif result["avg_f1"] >= 0.5:
        print("  结论: ★ 一般 (0.5 <= F1 < 0.65)")
    else:
        print("  结论: 不合格 (F1 < 0.5)")
    print("=" * 70)

    # 按主题统计
    topic_stats = {}
    for d in result["details"]:
        for t in TOPICS:
            for title in TOPICS[t]:
                if title[:20] in d["question"] or any(
                    kw in d["question"] for kw in [t]
                ):
                    topic_stats.setdefault(t, []).append(d["f1"])
                    break

    if topic_stats:
        print("\n  按主题 F1 分布:")
        for t, scores in topic_stats.items():
            avg = sum(scores) / len(scores) if scores else 0
            bar = "█" * int(avg * 20)
            print(f"  {t:<16s}  F1={avg:.4f}  {bar}")

    # 弱项详情
    weak = sorted(result["details"], key=lambda d: d["f1"])[:5]
    print(f"\n  表现最弱的 5 题:")
    for d in weak:
        print(f"  F1={d['f1']:.4f} P={d['precision']:.2f} R={d['recall']:.2f} "
              f"相关={d['relevant']}/{result['top_k']} KW={d['hit_kw']}/{d['gt_kw']}  {d['question'][:40]}...")


def ablation_study(test_questions: list[dict], top_k: int = 5):
    """各路召回消融对比"""
    print("\n\n" + "=" * 70)
    print("  召回路径消融对比")
    print("=" * 70)

    configs = [
        ("仅向量", ["vector"]),
        ("向量 + BM25", ["vector", "bm25"]),
        ("向量 + BM25 + 标签", ["vector", "bm25", "tag"]),
    ]

    for name, paths in configs:
        f1s = []
        for item in test_questions:
            gt_keywords = item.get("ground_truth_keywords", [])
            if not gt_keywords:
                continue
            results = multi_recall_search(item["question"], top_k=top_k, recall_paths=paths)
            chunk_hits = []
            all_hit = set()
            for r in results:
                atitle = r.get("article", {}).get("title", "")
                hits = _hit_keywords(r["chunk_text"], atitle, gt_keywords)
                chunk_hits.append(hits)
                text = (r["chunk_text"] + " " + atitle).lower()
                for kw in gt_keywords:
                    if kw.lower() in text:
                        all_hit.add(kw.lower())
            relevant = sum(1 for h in chunk_hits if h > 0)
            p = relevant / top_k if top_k else 0
            r = len(all_hit) / len(gt_keywords) if gt_keywords else 0
            f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0
            f1s.append(f1)
        avg = sum(f1s) / len(f1s) if f1s else 0
        print(f"  {name:<28s} Avg F1@{top_k} = {avg:.4f}")


# ============================================================
# 入口
# ============================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-build", action="store_true", help="跳过知识库构建，直接跑评测")
    parser.add_argument("--skip-eval", action="store_true", help="跳过评测，仅构建知识库")
    parser.add_argument("--top-k", type=int, default=5, help="检索 Top-K (默认 5)")
    args = parser.parse_args()

    TOP_K = args.top_k

    if not args.skip_build:
        # Step 1: 构建知识库
        article_count, chunk_count = build_knowledge_base()
        print(f"\n知识库构建完成: {article_count} 篇文章, {chunk_count} chunks")
    else:
        # 统计已有文章
        rows = db_exec("SELECT COUNT(*) as c FROM knowledge_articles WHERE status='published'", [])
        article_count = rows[0]["c"] if rows else 0
        rows2 = db_exec("SELECT COUNT(*) as c FROM knowledge_chunks", [])
        chunk_count = rows2[0]["c"] if rows2 else 0
        print(f"已有知识库: {article_count} 篇文章, {chunk_count} chunks")

    if not args.skip_eval:
        # Step 2: 生成评测题
        print("\n正在生成评测题...")
        questions = generate_questions()
        print(f"生成 {len(questions)} 道评测题")

        # 保存评测题
        qa_path = Path(__file__).resolve().parent.parent / "data" / "eval_questions.json"
        qa_path.write_text(json.dumps(questions, ensure_ascii=False, indent=2))
        print(f"评测题已保存: {qa_path}")

        # Step 3: 评测
        print(f"\n开始 RAGAS 评估 (Top-K={TOP_K})...")
        result = evaluate(questions, top_k=TOP_K)
        print_report(result)

        # Step 4: 消融对比
        ablation_study(questions, top_k=TOP_K)

        # 保存结果
        result_path = Path(__file__).resolve().parent.parent / "data" / "eval_result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        print(f"\n评测结果已保存: {result_path}")
