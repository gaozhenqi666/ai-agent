"""
seed_ai_articles.py
==========================================================
向知识库批量导入 AI / Agent / RAG 相关文章

运行方式：
  python scripts/seed_ai_articles.py
==========================================================
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common import db_exec, now_iso, new_id, log
from tools.chunker_tool import recursive_split
from tools.retriever_tool import save_chunks

ARTICLES = [
    # ==================== RAG 专题 ====================
    {
        "title": "Retrieval-Augmented Generation (RAG) 全面综述",
        "url": "https://arxiv.org/abs/2312.10997",
        "tags": ["RAG", "综述", "LLM"],
        "content": (
            "检索增强生成（Retrieval-Augmented Generation，RAG）是一种将信息检索与文本生成相结合的技术框架。"
            "RAG 通过在生成回答之前从外部知识库中检索相关文档片段，然后将这些片段作为上下文注入到大型语言模型（LLM）的提示中，"
            "从而显著减少幻觉（hallucination）并提高回答的事实准确性。\n\n"
            "RAG 的核心架构包含三个关键模块：\n"
            "1. 索引模块（Indexing）：将文档切分为 chunks，使用 embedding 模型将每个 chunk 编码为向量，存入向量数据库。\n"
            "2. 检索模块（Retrieval）：接收用户查询，用相同的 embedding 模型编码查询向量，在向量数据库中通过近似最近邻（ANN）搜索召回 Top-K 相关 chunks。\n"
            "3. 生成模块（Generation）：将检索到的 chunks 与原始查询拼接成增强 prompt，交给 LLM 生成最终回答。\n\n"
            "高级 RAG 范式演进分为三个阶段：\n"
            "- Naive RAG：基础的索引-检索-生成流水线。\n"
            "- Advanced RAG：引入查询重写（Query Rewriting）、混合检索（Hybrid Search）、重排序（Reranking）等优化。\n"
            "- Modular RAG：将 RAG 模块化，支持即插即用的组件组合，如 Self-RAG、CRAG、Graph RAG 等。\n\n"
            "评估 RAG 系统通常从三个维度考虑：\n"
            "- 检索质量：衡量检索到的文档与查询的相关性（Context Precision、Context Recall）。\n"
            "- 生成质量：衡量生成回答的忠实度（Faithfulness）和相关度（Answer Relevance）。\n"
            "- 端到端质量：从用户角度评估整体回答的满意度。\n"
            "RAGAS（RAG Assessment）是目前最流行的 RAG 评估框架，提供了 Context Precision、Context Recall、"
            "Faithfulness、Answer Relevancy 等核心指标。"
        ),
    },
    {
        "title": "混合检索与多路召回技术详解",
        "url": "https://www.pinecone.io/learn/hybrid-search/",
        "tags": ["混合检索", "多路召回", "RRF", "BM25"],
        "content": (
            "混合检索（Hybrid Search）是融合稠密向量检索和稀疏关键词检索的搜索策略，目的是结合语义理解和精确关键词匹配的优势。\n\n"
            "稀疏检索（Sparse Retrieval）：\n"
            "- BM25：经典的词频-逆文档频率算法，根据词项在文档中出现的频率和文档长度进行评分。擅长精确关键词匹配，"
            "但对同义词、语义变体不敏感。\n"
            "- TF-IDF：与 BM25 类似的统计方法，但缺少文档长度归一化。\n\n"
            "稠密检索（Dense Retrieval）：\n"
            "- 使用预训练语言模型（如 BERT、text-embedding-3）将文本编码为高维向量。\n"
            "- 通过余弦相似度或欧几里得距离计算语义相关性。\n"
            "- 擅长捕捉语义相似性，但可能在精确关键词匹配上表现欠佳。\n\n"
            "多路召回（Multi-Recall）：\n"
            "在混合检索的基础上，进一步引入更多召回通路：\n"
            "- 向量召回：基于 embedding 的语义匹配\n"
            "- BM25 召回：基于词频的关键词匹配\n"
            "- 标签召回：基于文章标签的精确匹配\n"
            "- 实体召回：基于命名实体识别的结构化匹配\n\n"
            "融合策略：\n"
            "1. 线性加权融合（Weighted Sum）：score = α * vector_score + β * bm25_score\n"
            "   缺点：需要手动调参，不同量纲的分数直接相加不合理\n"
            "2. 倒数排序融合（RRF，Reciprocal Rank Fusion）：score = Σ 1 / (k + rank_i)\n"
            "   优点：无需归一化，对各路分数的量纲不敏感，业界广泛使用\n"
            "3. 学习排序（Learning to Rank）：使用标注数据训练模型学习各路信号的权重\n\n"
            "RRF 的核心优势：\n"
            "- 与量纲无关：只关心相对排序，不关心绝对分数\n"
            "- 可扩展：任意数量的召回通路都可以无缝融合\n"
            "- 鲁棒性：对单路召回的波动不敏感\n"
            "- k 值选择：常用 k=60，k 越大越平滑但区分度越低"
        ),
    },
    {
        "title": "Reciprocal Rank Fusion (RRF) 原理解析",
        "url": "https://plg.uwaterloo.ca/~gvcormac/cormacksigir09-rrf.pdf",
        "tags": ["RRF", "融合排序", "信息检索"],
        "content": (
            "倒数排序融合（Reciprocal Rank Fusion，RRF）是 Cormack 等人在 SIGIR 2009 提出的结果融合方法。\n\n"
            "RRF 公式：\n"
            "RRF_score(d) = Σ_{r∈R} 1 / (k + rank_r(d))\n\n"
            "其中：\n"
            "- d 是待排序的文档\n"
            "- R 是所有召回通路（检索器）的集合\n"
            "- rank_r(d) 是文档 d 在检索器 r 结果列表中的排名（从 1 开始）\n"
            "- k 是平滑常数，通常取 60\n\n"
            "k 值的影响：\n"
            "- k = 0：排名第1贡献1.0，排名第10贡献0.1，高低排名差异巨大\n"
            "- k = 60：排名第1贡献0.0164，排名第10贡献0.0143，差异较小\n"
            "- k → ∞：所有排名贡献趋于相等，失去区分能力\n"
            "- 经验最优：k ∈ [60, 100]\n\n"
            "RRF 为什么有效：\n"
            "1. 不同检索器的分数分布差异很大（如余弦相似度 ∈ [0,1]，BM25 可能 >10），"
            "直接加权求和需要归一化，而 RRF 天然与量纲无关\n"
            "2. 排名信息比绝对分数更稳定——一个文档在某路排第 3 总是好的，无论绝对分数是多少\n"
            "3. RRF 自带'多数投票'效应：在更多检索路中排名靠前的文档会累积更高的 RRF 分数\n\n"
            "RRF vs 加权求和对比实验：\n"
            "在 TREC 数据集上，RRF 通常比线性加权融合提升 5%-15% 的 NDCG@10。\n"
            "当各路检索器的分数分布差异大时（如向量分 ∈ [0.7, 0.95]，BM25 分 ∈ [0, 15]），RRF 的优势更为显著。"
        ),
    },
    {
        "title": "RAG 检索质量评估：从 Precision 到 RAGAS",
        "url": "https://docs.ragas.io/",
        "tags": ["RAGAS", "评估", "F1", "Retrieval"],
        "content": (
            "评估 RAG 系统的检索质量是确保 RAG 应用可靠性的关键步骤。\n\n"
            "传统检索指标：\n"
            "- Precision@K：Top-K 结果中相关文档的比例\n"
            "- Recall@K：所有相关文档中被召回到 Top-K 的比例\n"
            "- F1@K：Precision 和 Recall 的调和平均 = 2 * P * R / (P + R)\n"
            "- MRR（Mean Reciprocal Rank）：第一个相关文档的倒数排名\n"
            "- NDCG（Normalized Discounted Cumulative Gain）：考虑相关度等级和位置的排序质量\n\n"
            "RAGAS（RAG Assessment）框架：\n"
            "RAGAS 是专门为 RAG 系统设计的评估框架，核心指标包括：\n\n"
            "检索相关指标：\n"
            "- Context Precision：检索到的上下文中，实际用于生成回答的相关片段比例\n"
            "- Context Recall：ground truth 中应该被检索到的上下文，实际被检索到的比例\n"
            "- Context Relevancy：检索到的上下文与查询的实际相关程度\n\n"
            "生成相关指标：\n"
            "- Faithfulness：生成回答中基于检索上下文的事实性声明比例\n"
            "- Answer Relevancy：生成回答与查询的相关程度\n"
            "- Answer Correctness：生成回答相对于 ground truth 的准确性\n\n"
            "使用 RAGAS 的典型流程：\n"
            "1. 准备测试数据集：{question, ground_truth_contexts, ground_truth_answer}\n"
            "2. 对每个 question 运行 RAG pipeline，获取 retrieved_contexts 和 generated_answer\n"
            "3. 调用 ragas.evaluate() 计算各项指标\n"
            "4. 分析指标得分矩阵，定位检索或生成环节的问题\n\n"
            "F1 作为 RAG 检索质量的核心指标：\n"
            "F1 同时考虑了精确率（检索到的内容有多少是相关的）和召回率（相关的内容有多少被检索到了），"
            "是衡量检索系统平衡性的最佳单一指标。对于生产环境的 RAG 系统，Context F1 >= 0.7 通常被认为是可接受的水平。"
        ),
    },
    {
        "title": "Chunking 策略对 RAG 检索效果的实验分析",
        "url": "https://www.llamaindex.ai/blog/evaluating-the-ideal-chunk-size-for-a-rag-system-using-llamaindex",
        "tags": ["Chunking", "RAG", "文本切片", "检索优化"],
        "content": (
            "文档切片（Chunking）是 RAG pipeline 中最基础但最关键的一步。\n\n"
            "核心切片参数：\n"
            "- chunk_size：每个文本片段的最大字符数或 token 数\n"
            "- chunk_overlap：相邻片段之间的重叠字符数或 token 数\n\n"
            "常见切片策略：\n"
            "1. 固定大小切片（Fixed-size）：按固定字符/token 数均匀切分\n"
            "   优点：简单高效；缺点：可能切断语义单元\n"
            "2. 递归字符分割（Recursive Character Split）：按分隔符层级逐级切分\n"
            "   分隔符优先级：段落 > 句子 > 词语 > 字符\n"
            "   优点：在保持语义完整性和满足长度限制之间取得平衡\n"
            "3. 语义切片（Semantic Chunking）：使用 embedding 模型检测语义边界\n"
            "   优点：最大程度保持语义完整；缺点：计算开销大\n"
            "4. 句子级切片（Sentence-based）：以句子为最小单位\n"
            "   优点：自然语义边界；缺点：句子长度不均\n\n"
            "实验发现（LlamaIndex 研究）：\n"
            "- chunk_size=256（约 150 中文）更适合回答精确事实性问题\n"
            "- chunk_size=1024（约 600 中文）更适合回答需要上下文理解的综合分析问题\n"
            "- chunk_overlap=10%-20% 是比较好的折中选择\n"
            "- 对于中文文本，chunk_size 在 400-800 字符，overlap 在 50-100 字符效果较好\n\n"
            "Small-to-Big 检索策略：\n"
            "- 用小 chunk 做检索（提高精确度），返回时扩展为完整段落（保留上下文）\n"
            "- 综合了高精度检索和完整上下文的优势"
        ),
    },
    {
        "title": "LangChain 与 LlamaIndex RAG 框架对比",
        "url": "https://blog.langchain.dev/",
        "tags": ["LangChain", "LlamaIndex", "RAG", "框架"],
        "content": (
            "LangChain 和 LlamaIndex 是构建 RAG 应用的两大主流框架。\n\n"
            "LangChain 特点：\n"
            "- 通用 LLM 应用框架，RAG 只是其功能子集\n"
            "- 以 Chain 和 Agent 为核心抽象\n"
            "- 提供丰富的文档加载器、文本分割器、向量存储集成\n"
            "- LCEL（LangChain Expression Language）支持声明式链构建\n"
            "- 生态丰富：与 50+ 向量数据库、20+ LLM 提供商集成\n\n"
            "LlamaIndex 特点：\n"
            "- 专注数据索引和检索的框架\n"
            "- 以 Index 和 QueryEngine 为核心抽象\n"
            "- 提供更丰富的检索策略：树索引、关键词表索引、知识图谱索引\n"
            "- 内置多种高级 RAG 模式：Sentence Window Retrieval、Auto-Merging Retrieval\n"
            "- 更好的文档结构保留和关系抽取能力\n\n"
            "选择建议：\n"
            "- 如果项目以 RAG 为核心 → 优先 LlamaIndex\n"
            "- 如果需要 Agent、工具调用、复杂编排 → 优先 LangChain\n"
            "- 简单场景 → 两个都可以，看团队熟悉度\n"
            "- 自建轻量框架 → 基于 LangChain/LlamaIndex 的思想，根据需求自行裁剪"
        ),
    },
    # ==================== AI Agent 专题 ====================
    {
        "title": "AI Agent 架构设计与实践指南",
        "url": "https://lilianweng.github.io/posts/2023-06-23-agent/",
        "tags": ["Agent", "LLM", "架构设计", "Tool Use"],
        "content": (
            "AI Agent（智能体）是以大语言模型（LLM）为核心推理引擎，能够感知环境、制定计划、执行行动的自主系统。\n\n"
            "Agent 核心组件：\n"
            "1. 推理引擎（LLM Brain）：负责任务分解、规划和决策\n"
            "   常用技术：Chain-of-Thought (CoT)、Tree-of-Thought (ToT)、ReAct\n"
            "2. 记忆系统（Memory）：\n"
            "   - 短期记忆：当前对话上下文\n"
            "   - 长期记忆：外部向量数据库或知识图谱\n"
            "   - 工作记忆：当前任务的中间状态\n"
            "3. 工具使用（Tool Use）：\n"
            "   - Function Calling：LLM 调用预定义的 API 函数\n"
            "   - 搜索引擎：获取实时信息\n"
            "   - 代码解释器：执行计算和数据处理\n"
            "4. 规划模块（Planning）：\n"
            "   - 任务分解：将复杂任务拆解为子任务\n"
            "   - 自我反思：评估执行结果并迭代优化\n\n"
            "ReAct（Reasoning + Acting）模式：\n"
            "- Thought → Action → Observation → Thought → ...\n"
            "- 交替进行推理和行动，是最经典的 Agent 执行范式\n\n"
            "多 Agent 架构：\n"
            "- 主从架构（Master-Worker）：一个主 Agent 分配任务给多个 Worker Agent\n"
            "- 协作架构（Collaborative）：多个 Agent 平等对话协作\n"
            "- 专家混合（MoE）：不同专家 Agent 处理不同领域的问题\n\n"
            "Agent 评估维度：\n"
            "- 任务完成率：成功完成目标的比例\n"
            "- 效率：完成任务的步骤数和时间\n"
            "- 鲁棒性：面对意外情况的处理能力\n"
            "- 安全性：是否产生有害或不符合预期的行为"
        ),
    },
    {
        "title": "ReAct Agent 与 Function Calling 深度对比",
        "url": "https://react-lm.github.io/",
        "tags": ["ReAct", "Function Calling", "Agent", "Planning"],
        "content": (
            "ReAct（Reasoning and Acting）和 Function Calling 是当前主流的两种 Agent 执行模式。\n\n"
            "ReAct 模式：\n"
            "- 完整形式：Thought → Action → Action Input → Observation → ... → Final Answer\n"
            "- Thought 步骤允许 LLM 显式推理，提高复杂任务的决策质量\n"
            "- 通过提示词（Prompt）控制行为，无需特殊的 API 支持\n"
            "- 适用于所有 LLM，不限于支持 Function Calling 的模型\n"
            "- 缺点：token 消耗大（每步都要输出 Thought），推理速度慢\n\n"
            "Function Calling 模式：\n"
            "- LLM 原生支持直接输出 JSON 格式的函数调用\n"
            "- 无需额外的 Thought 步骤，token 效率更高\n"
            "- 执行可靠：工具定义明确，参数约束清晰\n"
            "- 缺点：需要模型原生支持，灵活性不如 ReAct\n\n"
            "混合模式：\n"
            "- 先 Function Calling 执行具体操作\n"
            "- 遇到复杂决策时切换回 ReAct 模式进行多步推理\n"
            "- 在工具调用前后添加隐式推理步骤（CoT inside function）\n\n"
            "Tool Use 最佳实践：\n"
            "1. 工具描述清晰：名称+功能+参数+返回值+使用场景\n"
            "2. 小粒度工具：每个工具只做一件事\n"
            "3. 输入校验：在工具调用层做参数验证，不依赖 LLM 输出正确性\n"
            "4. 错误处理：工具返回友好的错误信息，让 LLM 能自我纠正\n"
            "5. 工具分层：基础工具（search/web/code）+ 复合工具（search_and_summarize）"
        ),
    },
    {
        "title": "多 Agent 协作系统：从 AutoGen 到 CrewAI",
        "url": "https://microsoft.github.io/autogen/",
        "tags": ["Multi-Agent", "AutoGen", "CrewAI", "协作"],
        "content": (
            "多 Agent 系统（Multi-Agent System，MAS）通过让多个专业化 Agent 协作完成任务，超越了单 Agent 的能力边界。\n\n"
            "AutoGen（Microsoft）：\n"
            "- 基于对话的多 Agent 框架\n"
            "- 核心概念：ConversableAgent，通过消息传递进行交互\n"
            "- 支持人机协作（Human-in-the-Loop）\n"
            "- 内置 GroupChat 模式：多个 Agent 在群聊中协作\n"
            "- 优势：微软生态支持，学术研究级质量\n\n"
            "CrewAI：\n"
            "- 基于角色（Role）的多 Agent 编排框架\n"
            "- 核心概念：Agent + Task + Crew + Process\n"
            "- Agent 有明确的角色、目标、背景故事\n"
            "- Task 有描述、期望输出、指定执行 Agent\n"
            "- Process 定义执行顺序（Sequential / Hierarchical）\n"
            "- 优势：API 简洁，适合快速原型\n\n"
            "LangGraph（LangChain）：\n"
            "- 基于有向图的状态机 Agent 框架\n"
            "- 支持条件分支、循环、人机交互\n"
            "- 适合复杂的多步 Agent 工作流\n"
            "- 优势：与 LangChain 生态无缝集成\n\n"
            "多 Agent 编排模式：\n"
            "1. 顺序执行（Sequential）：A → B → C，线性流水线\n"
            "2. 并行执行（Parallel）：多个 Agent 同时工作，结果合并\n"
            "3. 路由分发（Router）：中央 Agent 根据查询类型分发到专家 Agent\n"
            "4. 辩论模式（Debate）：多个 Agent 从不同视角分析，最终共识\n"
            "5. 层级执行（Hierarchical）：上级 Agent 拆解任务，下级 Agent 执行子任务"
        ),
    },
    {
        "title": "Embedding 模型对比：从 BGE 到 text-embedding-3",
        "url": "https://huggingface.co/spaces/mteb/leaderboard",
        "tags": ["Embedding", "BGE", "向量模型", "MTEB"],
        "content": (
            "Embedding 模型是将文本转换为稠密向量的核心组件，是 RAG 系统的第一道关口。\n\n"
            "主流中文 Embedding 模型对比：\n\n"
            "1. BGE-M3（BAAI）：\n"
            "   - 支持中英多语言，1024 维\n"
            "   - 同时支持 Dense 和 Sparse 检索\n"
            "   - MTEB 中文榜单排名前三\n"
            "   - 开源可自部署\n\n"
            "2. text-embedding-3（OpenAI）：\n"
            "   - 支持多语言，维度可调（256-3072）\n"
            "   - 小维度版本（256）性价比极高\n"
            "   - 大维度版本（3072）检索精度最高\n"
            "   - 需 API 调用，不可自部署\n\n"
            "3. 通义千问 embedding（DashScope）：\n"
            "   - 中文场景优化，1024 维\n"
            "   - 支持 50+ 语言\n"
            "   - 中文检索效果与 BGE 接近\n"
            "   - 阿里云 API，性价比高\n\n"
            "4. Jina Embeddings v3：\n"
            "   - 多语言、多任务，1024 维\n"
            "   - 支持任务特定 LoRA 适配\n"
            "   - 开源可自部署\n\n"
            "Embedding 选型建议：\n"
            "- 成本敏感 + 中文为主 → 通义千问 text-embedding-v4\n"
            "- 精度优先 + 可自部署 → BGE-M3\n"
            "- 英文为主 → text-embedding-3-large\n"
            "- 多语言混合 → Jina Embeddings v3\n\n"
            "评估 Embedding 模型：\n"
            "- MTEB 排行榜：权威的 embedding 模型综合评测\n"
            "- 检索任务子榜单：衡量在多个检索数据集上的平均表现\n"
            "- 聚类/分类/配对任务：更全面的能力评估"
        ),
    },
]

# === 导入函数 ===
def run():
    count = 0
    for art in ARTICLES:
        article_id = new_id("art-")
        now = now_iso()
        tags_json = json.dumps(art["tags"], ensure_ascii=False)

        db_exec(
            """INSERT INTO knowledge_articles
               (article_id, title, url, content, summary, source, tags, status, created_at, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            [article_id, art["title"], art["url"], art["content"],
             art["content"][:200], "Manual", tags_json, "published", now, now],
        )

        chunks = recursive_split(art["content"], chunk_size=500, overlap=50)
        n = save_chunks(article_id, chunks)
        count += 1
        log.info(f"  已导入: {art['title'][:40]} ({n} chunks)")

    log.info(f"共导入 {count} 篇文章")
    print(f"导入完成：{count} 篇 AI/RAG/Agent 文章")


if __name__ == "__main__":
    import json
    run()
