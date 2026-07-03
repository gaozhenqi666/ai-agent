# 个人 AI 知识助手 - 软件需求规格说明书 (SRS)

> 版本: v0.1.0  
> 编写日期: 2026-07-01  
> 编写依据: PRD.md

---

## 目录

- [1. 引言](#1-引言)
- [2. 项目概述](#2-项目概述)
- [3. 功能需求](#3-功能需求)
- [4. 非功能需求](#4-非功能需求)
- [5. 外部接口需求](#5-外部接口需求)
- [6. 数据需求](#6-数据需求)
- [7. 约束与假设](#7-约束与假设)
- [8. 验收标准](#8-验收标准)
- [9. 附录](#9-附录)

---

## 1. 引言

### 1.1 编写目的

本文档定义"个人 AI 知识助手"系统的完整软件需求，作为开发、测试、部署和验收的唯一权威依据。所有代码实现必须以本文档为准；任何与本文档冲突的实现需先更新本文档。

### 1.2 项目背景

随着 AI 技术快速发展，独立开发者每天需要阅读大量技术文章、跟进行业前沿。仅靠浏览器收藏夹和笔记软件难以满足：

- **检索困难**：收藏的文章分散，无法快速找到
- **信息过载**：每天产生大量新内容，无法消化
- **创作割裂**：从"读到写"流程断裂，需要手动整理

本系统通过多 Agent 协同 + RAG + 定时推送，构建一个**会自己整理、回答、写作**的个人知识助手。

### 1.3 文档范围

涵盖：

- 6 个 Agent 的功能与交互
- 7 类核心场景的端到端流程
- 上下文管理与压缩机制
- 会话恢复与持久化
- 外部 API 集成（LLM/搜索/邮件）

**不涵盖**：

- 移动端 App
- 多用户/权限系统
- 文章付费墙处理
- 多语言（仅中文）

### 1.4 术语定义

| 术语 | 解释 |
| --- | --- |
| **Agent** | 独立 AI 处理单元，负责一类特定任务 |
| **Master Agent** | 主调度 Agent，统一入口 |
| **RAG** | Retrieval-Augmented Generation，检索增强生成 |
| **Trace** | 一次问答的完整执行链路，包含多个 Agent 调用 |
| **Context** | LLM 调用时传入的完整历史消息 |
| **上下文压缩** | 用 LLM 摘要压缩历史消息，控制 token 消耗 |
| **Harness** | 工作流自动化 + 人在回路 + 可观测性的工程模式 |
| **Human-in-the-loop** | 关键决策点由人类确认/编辑 |
| **libSQL** | SQLite 的 fork，支持边缘复制（Turso 托管） |
| **sqlite-vec** | 嵌入式向量检索扩展（KNN） |

### 1.5 参考文档

- `PRD.md` - 产品需求文档
- `API.md` - 接口设计文档
- `DB.md` - 数据库设计文档

---

## 2. 项目概述

### 2.1 产品定位

**面向独立开发者的个人 AI 知识助手**。通过多 Agent 协同，提供"读 → 存 → 写"全流程支持：

```
读：智能对话 + 行业早报
存：一键整理到知识库
写：AI 生成博客 + 在线编辑
```

### 2.2 用户特征

- **目标用户**：项目所有者（独立开发者）
- **技术背景**：熟悉 Python、前端、Agent 概念
- **使用场景**：
  - 工作中遇到技术问题 → 对话式检索
  - 通勤时间 → 阅读每日早报
  - 学习新领域 → 收藏 + 整理
  - 输出博客 → 一键生成初稿

### 2.3 运行环境

| 类别 | 选型 | 说明 |
| --- | --- | --- |
| Agent 框架 | LangGraph | 状态机编排 |
| LLM | DeepSeek | 对话 + 生成 |
| 搜索 | Tavily API | AI 优化搜索 |
| 数据库/向量   | Turso libSQL + sqlite-vec   | 9GB 免费，含向量扩展 |
| 邮件 | Resend | 免费 100 封/天 |
| 定时 | GitHub Actions | 免费定时 |
| 前端 | HTML + JavaScript | 轻量无框架 |
| 部署 | Vercel | Serverless |

### 2.4 架构总览

```
┌─────────────────────────────────────────────────────────┐
│ 前端 (web/index.html)                                    │
│  - 侧边栏：会话列表                                       │
│  - 主区：聊天 + Markdown 编辑器                           │
│  - 工具栏：上下文管理按钮                                 │
└────────────────────┬────────────────────────────────────┘
                     │ HTTPS + JSON
┌────────────────────┴────────────────────────────────────┐
│ API 层 (api/*.py)                                       │
│  - chat.py    对话入口                                  │
│  - daily.py   定时入口                                  │
│  - publish.py 博客发布                                  │
└────────────────────┬────────────────────────────────────┘
                     │
┌────────────────────┴────────────────────────────────────┐
│ Master Agent（调度）                                     │
│  ├─ 意图识别（chat/simple_qa/professional/...）          │
│  ├─ 上下文构建（加载历史 + 压缩）                        │
│  └─ 调度子 Agent（上下文隔离）                           │
└──┬───────┬───────┬───────┬───────┬──────────────────────┘
   │       │       │       │       │
   v       v       v       v       v
┌────┐ ┌────┐ ┌────┐ ┌────┐ ┌────┐
│Search│ │Knwl│ │Blog│ │RAG │ │Email│
└──┬─┘ └──┬─┘ └──┬─┘ └──┬─┘ └──┬─┘
   │       │       │       │       │
   v       v       v       v       v
┌────────────────────────────────────┐
│ Tools 层（外部 API 封装）            │
│  - Tavily / libSQL / Resend       │
└────────────────────────────────────┘
```

---

## 3. 功能需求

> 编号规则：FR-XYZ（X=Agent 编号，Y=顺序）

### 3.1 Master Agent（FR-1xx）

#### FR-101 意图识别

系统**必须**能够将用户输入分类为以下 6 种意图之一：

| 意图 | 含义 | 处理方 |
| --- | --- | --- |
| `chat` | 闲聊、寒暄 | Master 直接回答 |
| `simple_qa` | 简单事实问答 | Master 直接回答 |
| `professional` | 专业咨询 | Master + Search/RAG |
| `save_article` | 存知识库 | Knowledge Agent |
| `write_blog` | 写博客 | Blog Agent |
| `query_knowledge` | 查知识库 | RAG Agent |

**输入**：用户消息文本（≤ 4K 字符）  
**输出**：`{intent: str, confidence: float, entities: dict}`  
**错误处理**：confidence < 0.6 时降级为 `chat`

#### FR-102 任务调度

识别意图后，Master **必须**根据意图路由到对应 Agent：

```
chat / simple_qa     → Master LLM 直接回答
professional         → Search Agent 找文章 → Master LLM 综合
save_article         → Knowledge Agent 存文章
write_blog           → Blog Agent 生成草稿
query_knowledge      → RAG Agent 检索
```

调度时**必须**进行上下文隔离：子 Agent 只能看到 Master 传入的字段，不能看到完整 Master 上下文。

#### FR-103 普通对话处理

对 `chat` 和 `simple_qa` 意图，Master **必须**：

1. 构造 LLM 输入（system prompt + 历史 + 当前消息）
2. 调用 DeepSeek API
3. 流式返回（若启用 stream）或一次性返回
4. 记录到 `messages` 表和 `trace_calls` 表

#### FR-104 后续询问

对 `professional` 意图回答完成后，Master **必须**依次询问：

1. "是否整理到知识库？"
2. "是否基于这些内容生成技术博客？"

用户肯定时调度对应 Agent。

### 3.2 Search Agent（FR-2xx）

#### FR-201 相关性模式搜索

按"权威性 40% + 相关性 40% + 时间 20%"排序，用于对话中的专业问题。

**输入**：

```python
{
    "query": str,
    "max_results": int = 5,
    "mode": "relevance"   # 默认
}
```

**输出**：

```python
[{
    "title": str,
    "url": str,
    "snippet": str,
    "source": str,
    "published_at": str,
    "score": float
}]
```

#### FR-202 最新模式搜索

按"时间 70% + 相关性 20% + 权威性 10%"排序，用于每日早报。

**输入**：`mode: "latest"`  
**适用**：定时任务 07:00 触发

#### FR-203 搜索结果过滤

**必须**过滤掉：

- 已访问过的 URL（基于本地缓存）
- 来自被屏蔽来源的内容
- 长度 < 100 字符的 snippet

#### FR-204 错误降级

当 Tavily API 不可用时，**必须**：

1. 记录 warning 到 trace
2. 返回空列表
3. Master Agent 继续工作（不阻塞对话）

### 3.3 Knowledge Agent（FR-3xx）

#### FR-301 文章保存

将搜索结果或外部 URL 整理后存入知识库。

**输入**：

```python
{
    "title": str,
    "url": str,
    "content": str,
    "summary": str,
    "source": str,
    "tags": list[str]
}
```

**副作用**：

- 写入 `knowledge_articles` 表
- 自动生成 embedding（调用 embedding 模型）
- 触发 `updated_at` 更新

#### FR-302 文章去重

同一 URL 的文章**必须**不重复保存：

- 检测到 URL 重复时，**必须**返回 409 错误
- 错误信息**必须**包含已有的 `article_id`

#### FR-303 批量保存

支持一次保存多篇文章（如搜索结果整批入库）。

**约束**：单次 ≤ 20 篇；超出则返回 413 错误。

#### FR-304 向量检索

提供 `top_k` 个最相关的文章。

**输入**：`{query: str, top_k: int = 5, threshold: float = 0.7}`

**输出**：相似度 ≥ threshold 的文章列表，按 score 降序。

### 3.4 Blog Agent（FR-4xx）

#### FR-401 博客生成

基于 AI 对话历史 + 引用文章，生成结构化博客。

**输入**：

```python
{
    "session_id": str,                    # 来源会话
    "topic": Optional[str],               # 显式主题（可选）
    "reference_article_ids": list[str]    # 参考文章
}
```

**输出**：Markdown 格式博客草稿，结构：

```markdown
# {标题}
> 基于对 {话题} 的研究

## 背景
## 核心内容
## 技术要点
## 代码示例
## 总结
## 参考资料
```

#### FR-402 局部重写

用户框选一段文字，AI 局部重写。

**输入**：

```python
{
    "blog_id": str,
    "selected_text": str,
    "instruction": str,        # 如 "更详细一些"
    "context_before": str,
    "context_after": str
}
```

**输出**：`{new_text: str}`（替换原选中段）

**约束**：单次重写 ≤ 2K 字符；超出截断 + 警告。

#### FR-403 博客发布

支持两种发布方式：

- `download`：下载为 .md 文件
- `vitepress`：推送到 VitePress 仓库（GitHub API）

#### FR-404 版本管理

每次 `edit` **必须**记录版本（存入 `metadata`），支持：

- 查看历史版本
- 回滚到任一版本

### 3.5 RAG Agent（FR-5xx）

#### FR-501 语义检索

基于用户问题在个人知识库中检索。

**输入**：`{query: str, top_k: int = 5}`  
**实现**：调用 embedding API → sqlite-vec KNN 检索

#### FR-502 答案增强

将检索结果作为上下文追加到 LLM 输入。

**Prompt 模板**：

```
基于以下参考资料回答用户问题。如果资料不相关，如实说明。

## 资料
1. {title}\n{summary}\n{snippet}
2. ...

## 用户问题
{query}
```

#### FR-503 引用透明

回答中**必须**标注信息来源，格式：

```
[1] RAG 完全指南
    https://...
```

### 3.6 Email Agent（FR-6xx）

#### FR-601 每日早报推送

**触发**：

- 自动：GitHub Actions 每天 07:00（北京时间）
- 手动：调用 `/api/daily/run`

**流程**：

1. Search Agent 搜 5 篇最新文章
2. Knowledge Agent 保存到知识库
3. LLM 生成综合总结
4. Resend 发送邮件

**邮件内容**：

- 标题：`📚 今日 {topic} 前沿资讯（{date}）`
- 正文：5 篇文章（标题+摘要+链接）+ 综合总结
- 按钮：[✅ 已写入知识库] [📝 生成博客] [❌ 仅查看]

#### FR-602 发送幂等

**必须**保证同一日期不重复发送：

- 检查 `daily_reports.email_sent`
- 已发送则跳过（除非显式 force=true）

#### FR-603 发送失败重试

邮件发送失败时**必须**：

1. 记录到 `trace_calls`（status=error）
2. 重试 3 次（指数退避）
3. 3 次失败后报警（暂用邮件标题前缀 `[FAIL]`）

### 3.7 会话管理（FR-7xx）

#### FR-701 新建会话

用户**必须**能创建新会话，初始标题为"新对话"。创建后自动跳转到该会话。

#### FR-702 会话列表

**必须**展示所有未归档会话，按 `last_active` 倒序：

- 显示标题、最后活跃时间、消息数
- 支持点击切换

#### FR-703 会话恢复（关键！）

用户点开历史会话后，**必须**实现"记忆"：

1. 加载该 session 的所有消息
2. 拼接到新问题前
3. 传给 Master Agent

**关键认知**：Agent 本身无状态；"记忆"= 历史消息作为输入。

#### FR-704 会话删除

删除会话**必须**级联删除其所有消息和 trace。

#### FR-705 会话导出

**必须**支持导出为 Markdown 格式：

```markdown
# {session.title}

> 导出时间：{timestamp}

## {message-1.content}

**用户** | {timestamp}

---

## {message-2.content}

**助手** | {timestamp}

---
```

### 3.8 上下文管理（FR-8xx，关键功能！）

#### FR-801 上下文压缩（被动）

当 `total_tokens > 100_000` 时**自动**触发：

1. 保留最近 10 条消息
2. 用 LLM 摘要老消息
3. 摘要作为 1 条 system message 放在最前
4. 返回 `[summary_system_message] + recent_10_messages`

**核心原则**：

- ✅ 不强制截断
- ✅ 不丢记忆（摘要保留关键信息）
- ✅ 用户可控

#### FR-802 上下文压缩（主动）

用户点击 [立即压缩] 按钮时**立即**触发压缩。

#### FR-803 上下文清空

用户点击 [清空会话] **必须**：

1. 二次确认（防止误操作）
2. 删除所有消息
3. 保留 session 本身

#### FR-804 上下文下载

点击 [下载历史] **必须**导出为 Markdown 并下载。

#### FR-805 警告提醒（分档）

| 轮数 | tokens | 等级 | UI 表现 |
| --- | --- | --- | --- |
| < 30 | < 10K | 🟢 正常 | 无提示 |
| 30-50 | 10K-30K | 🟡 提示 | 顶部黄色条 |
| 50-100 | 30K-100K | 🟠 推荐 | 橙色条 + [立即压缩] 按钮 |
| > 100 | > 100K | 🔴 强制 | 强制弹窗 [压缩并继续] |

**关键原则**：提醒而不强制（让用户决定），但 100 轮 / 100K 后**必须压缩**（技术限制）。

### 3.9 功能需求汇总

| 编号 | 功能 | 优先级 |
| --- | --- | --- |
| FR-101 | 意图识别 | P0 |
| FR-102 | 任务调度 | P0 |
| FR-201 | 相关性搜索 | P0 |
| FR-202 | 最新模式搜索 | P1 |
| FR-301 | 文章保存 | P0 |
| FR-401 | 博客生成 | P1 |
| FR-402 | 局部重写 | P2 |
| FR-501 | 语义检索 | P1 |
| FR-601 | 每日早报 | P1 |
| FR-703 | 会话恢复 | P0 |
| FR-801 | 上下文压缩 | P0 |
| FR-805 | 警告提醒 | P0 |

---

## 4. 非功能需求

### 4.1 性能

| 编号 | 需求 | 指标 |
| --- | --- | --- |
| NFR-001 | 对话响应延迟（不含流式） | < 10s |
| NFR-002 | 搜索响应 | < 5s |
| NFR-003 | 历史消息加载 | < 1s |
| NFR-004 | 列表查询 | < 500ms |
| NFR-005 | 并发会话数 | ≥ 5 |
| NFR-006 | 首屏加载 | < 2s |

### 4.2 可用性

| 编号 | 需求 |
| --- | --- |
| NFR-010 | 系统可用性 ≥ 99%（不计外部 API 故障） |
| NFR-011 | 错误信息友好，开发者能根据信息定位问题 |
| NFR-012 | 所有外部 API 故障有降级方案 |

### 4.3 安全性

| 编号 | 需求 |
| --- | --- |
| NFR-020 | 所有 API 需鉴权（API Key） |
| NFR-021 | 敏感配置（API Key）不提交到 Git |
| NFR-022 | 数据库鉴权在应用层实现（libSQL 无 RLS，依赖 Token 控制） |
| NFR-023 | 外部 API Key 存储在 `.env` |
| NFR-024 | 用户输入需做长度限制（≤ 32K 字符） |

### 4.4 可观测性

| 编号 | 需求 |
| --- | --- |
| NFR-030 | 每次 LLM 调用记录到 `trace_calls` |
| NFR-031 | 错误日志必须包含 `trace_id` |
| NFR-032 | 关键指标可查询：响应时间、token 消耗、Agent 调用次数 |
| NFR-033 | 所有 API 调用记录 `duration_ms` |

### 4.5 可扩展性

| 编号 | 需求 |
| --- | --- |
| NFR-040 | 新增 Agent 不影响现有 Agent |
| NFR-041 | LLM 提供商可替换（DeepSeek → 其他） |
| NFR-042 | 数据库可水平扩展（Turso 边缘复制） |
| NFR-043 | Agent 上下文隔离，避免上下文爆炸 |

### 4.6 可维护性

| 编号 | 需求 |
| --- | --- |
| NFR-050 | 公共依赖集中在 `common.py` |
| NFR-051 | Agent 独立目录（`agents/`） |
| NFR-052 | 配置文件与代码分离（`.env`） |
| NFR-053 | 文档先行（SRS + API + DB） |
| NFR-054 | 接口设计遵循 RESTful 规范 |

### 4.7 兼容性

| 编号 | 需求 |
| --- | --- |
| NFR-060 | 支持 Chrome / Edge / Safari / Firefox 最新版 |
| NFR-061 | 支持移动端浏览器响应式布局 |
| NFR-062 | API 遵循 OpenAPI 3.0 规范 |

---

## 5. 外部接口需求

### 5.1 用户接口

- 浏览器（Chrome ≥ 100 / Edge ≥ 100 / Safari ≥ 15 / Firefox ≥ 100）
- 邮箱（接收每日早报）

### 5.2 外部 API

| 服务 | 用途 | 必选 |
| --- | --- | --- |
| DeepSeek | LLM 对话 + 生成 | ✅ |
| Tavily | 网络文章搜索 | ✅ |
| Turso libSQL | 数据库 + 边缘复制 | ✅ |
| Resend | 邮件推送 | ✅ |
| 飞书 Open API | 云文档（每日早报） | ⏳ 可选 |
| 博客平台 API | 博客发布 | ⏳ 可选（默认下载） |

### 5.3 内部 API

详见 `API.md`。核心接口：

- `POST /api/chat` - 对话入口
- `GET /api/sessions` - 会话列表
- `POST /api/sessions/{id}/compress` - 压缩上下文
- `GET /api/sessions/{id}/export` - 导出会话
- `POST /api/daily/run` - 手动触发早报

---

## 6. 数据需求

详见 `DB.md`。核心数据实体：

```
sessions（会话）
  └─ messages（消息）
       └─ trace_calls（追踪）
       
knowledge_articles（知识库文章）
blogs（博客）
daily_reports（每日报告）
```

**关键设计**：

- 3 张核心表实现 3 层关系（会话 → 消息 → 追踪）
- 每对问答（user + assistant）共享一个 `trace_id`
- 数据库使用 Turso（libSQL + sqlite-vec）

---

## 7. 约束与假设

### 7.1 技术约束（Hard Constraints）

来自工程约定（不可违反）：

1. **数据库必须使用 Turso libSQL**（SQLite 兼容 + 边缘复制）
2. **Trace 数据必须存储在 Turso**（不是其他存储）
3. **会话/Q&A 记录必须存储在 Turso**
4. **公共依赖必须集中在 `common.py`**
5. **Agent 特定依赖在各自的 agent 文件中 import**
6. **Agent 文件存储在 `agents/` 目录**
7. **项目根包含**：`common.py` / `master_agent.py` / `.env` / `requirements.txt`

### 7.2 业务约束

1. 单一用户场景（不做权限/多用户）
2. 上下文压缩阈值 100K tokens（DeepSeek 上下文 128K）
3. 用户消息长度限制 ≤ 32K 字符
4. 单次搜索结果 ≤ 10 篇
5. 邮件推送频率：1 次/天（每日早报）

### 7.3 假设

1. 用户具备基本的浏览器使用能力
2. 网络环境稳定
3. 用户对 AI 输出有基本判断力（不会被 AI 误导）
4. DeepSeek / Tavily / Resend 长期可用
5. Turso 免费额度满足需求

### 7.4 依赖

| 依赖 | 用途 | 必需 |
| --- | --- | --- |
| Python ≥ 3.10 | 后端 | ✅ |
| LangGraph | Agent 编排 | ✅ |
| libsql-client | DB 客户端 | ✅ |
| httpx | HTTP 客户端 | ✅ |
| pydantic | 数据校验 | ✅ |
| FastAPI | Web 框架 | ✅ |
| tavily-python | 搜索 | ✅ |
| resend | 邮件 | ✅ |

---

## 8. 验收标准

### 8.1 功能验收（M1-M6）

| 阶段 | 验收项 | 通过条件 |
| --- | --- | --- |
| **M1** | Master Agent + Search Agent | 能对话 + 搜文章 |
| **M2** | Knowledge Agent | 能存知识库文档 |
| **M3** | Blog Agent + 编辑器 | 能生成编辑博客 |
| **M4** | RAG Agent | 知识库问答 |
| **M5** | Email Agent + 定时 | 每日早报推送 |
| **M6** | 部署 Vercel | 上线运行 |

### 8.2 性能验收

- [ ] 对话响应 < 10s
- [ ] 加载历史 < 1s
- [ ] 并发 5 个会话无错误
- [ ] 首屏加载 < 2s

### 8.3 安全验收

- [ ] `.env` 未提交到 Git
- [ ] API Key 未硬编码在代码中
- [ ] 无鉴权请求返回 401
- [ ] 数据库 RLS 启用
- [ ] 用户输入有长度限制

### 8.4 可观测性验收

- [ ] 每次 LLM 调用有 trace 记录
- [ ] 错误日志包含 trace_id
- [ ] 可通过 `GET /api/traces/{id}` 查询完整调用链

### 8.5 上下文管理验收

- [ ] 会话恢复不丢失记忆（点开历史能继续）
- [ ] 超过 100K tokens 自动压缩
- [ ] 压缩后回答仍能引用前面信息
- [ ] 30 轮以上出现黄色提示
- [ ] 50 轮以上出现橙色提示 + 压缩按钮
- [ ] 100 轮以上强制压缩弹窗

---

## 9. 附录

### 9.1 Agent 上下文隔离设计

```
Master Agent 上下文（精简）：
- current_intent
- active_agent
- task_status
- 待用户确认的选项

子 Agent 独立上下文：
- search_agent: query, results
- blog_agent: draft, edit_history
- rag_agent: retrieved_docs
```

**为什么需要隔离？** 避免上下文爆炸。Master 不需要知道 Search 的具体实现细节，只需调用。

### 9.2 简历技术亮点对应

| 技术点 | 对应需求 |
| --- | --- |
| 多 Agent 协同 | FR-1xx, FR-2xx, ..., FR-6xx |
| Harness Engineering | FR-703, FR-801, FR-805 |
| RAG | FR-501, FR-502 |
| 意图识别 | FR-101 |
| Human-in-the-loop | FR-104, FR-402, FR-805 |
| 定时编排 | FR-601 |

### 9.3 变更历史

| 版本 | 日期 | 作者 | 变更说明 |
| --- | --- | --- | --- |
| v0.1.0 | 2026-07-01 | - | 初稿，基于 PRD.md 生成 |
