# 个人 AI 知识助手 - PRD（精简版）

## 一、项目定位

一个具备 RAG 能力的个人 AI 知识助手，通过多 Agent 协同实现：

- **智能对话**：识别意图，必要时引用权威文章增强回答
- **知识沉淀**：一键整理文章到知识库
- **内容创作**：AI 生成技术博客，在线编辑后发布
- **定时推送**：每天早上搜索行业前沿，邮件确认后入库

## 二、简历技术亮点

| 技术点                     | 体现                         |
| ----------------------- | -------------------------- |
| **多 Agent 协同**          | 6 个 Agent 分工合作，主 Agent 调度  |
| **Harness Engineering** | 自动化工作流 + 人在回路 + 可观测        |
| **RAG**                 | 向量检索增强回答权威性                |
| **意图识别**                | 闲聊/简单问答/专业咨询分流处理           |
| **Human-in-the-loop**   | 邮件审批 + 在线编辑 + 框选 AI 修改     |
| **定时编排**                | GitHub Actions 定时触发 + 邮件链路 |

***

## 三、核心 Agent 设计（6 个）

```
┌─────────────────────────────────────────┐
│  Master Agent（主对话/调度）              │
│  - 意图识别：闲聊/简单/专业               │
│  - 决策：是否需要搜索文章                 │
│  - 调度子 Agent，上下文隔离              │
└─────────────────────────────────────────┘
         ↓ 调度
┌──────────┬──────────┬──────────┬──────────┬──────────┐
│ Search   │ Feishu   │ Blog     │ RAG      │ Email    │
│ Agent    │ Agent    │ Agent    │ Agent    │ Agent    │
│ 搜索文章 │ 飞书展示  │ 博客生成 │ 知识问答 │ 邮件推送 │
└──────────┴──────────┴──────────┴──────────┴──────────┘
```

### Agent 1: Master Agent（主对话 + 调度）

**职责**：意图识别 + 任务调度 + 普通聊天

**意图识别**：

```python
INTENTS = {
    "chat": "闲聊",              # 自己处理
    "simple_qa": "简单问题",      # 自己处理
    "professional": "专业咨询",   # → search_agent 找文章
    "save_article": "存知识库",   # → knowledge_agent
    "write_blog": "写博客",       # → blog_agent
    "query_knowledge": "查知识库" # → rag_agent
}
```

**决策逻辑**：

- 闲聊/简单问题 → 直接回答
- 专业问题 → 先搜文章，回答时附"标题+摘要+链接"
- 回答后询问："是否推送到飞书云文档？"
- 回答后询问："是否整理到知识库？"

### Agent 2: Search Agent（搜索）

**职责**：根据场景用不同策略搜索网络文章

**两种模式**（关键设计！）：

1. **相关性模式**（对话用） - 按"权威性+匹配度"排序
   - 适用：用户对话中问专业问题
   - 例子：用户问"什么是 RAG？" → 找最权威的 RAG 解析文章
   - 排序权重：权威性 40% + 相关性 40% + 时间 20%
2. **最新模式**（每日早报用） - 按"发布时间"排序
   - 适用：定时任务，每天 7 点
   - 例子：搜"AI Agent 前沿技术" → 找当天/24h 内的
   - 排序权重：时间 70% + 相关性 20% + 权威性 10%

**输入**：`query: str, max_results: int = 5, mode: str = "relevance"`

- `mode="relevance"`：按相关性排序（默认，对话用）
- `mode="latest"`：按时间排序（每日早报用）

**输出**：

```python
[{
    "title": str,
    "url": str,
    "snippet": str,        # 摘要片段
    "source": str,
    "published_at": str,   # 发布时间（最新模式用）
    "score": float,        # 相关性评分
}]
```

**为什么不能只找最新？**

- 用户问"什么是 RAG？"，找最新的可能是 2026 年的新闻
- 但 2023 年的权威教程才是用户真正需要的
- 经典文章 ≠ 旧文章，**质量 > 时效**（除早报场景）

### Agent 3: Knowledge Agent（知识库存储）

**职责**：将搜索到的文章整理到飞书云文档（给用户看）

**文档结构**：

```
# {话题标题}
日期：2026-01-01

## 文章总结
[AI 生成的所有文章综合总结]

## 文章列表

### 1. {标题}
- 摘要：...
- 链接：...
- 来源：...

### 2. {标题}
...
```

### Agent 4: Blog Agent（博客生成）

**职责**：基于 AI 回答 + 文章内容生成技术博客

**博客结构**：

```
# {标题}
> 基于对 {话题} 的研究

## 背景
## 核心内容
## 技术要点
## 代码示例（如有）
## 总结
## 参考资料（附链接）
```

### Agent 5: RAG Agent（知识库问答）

**职责**：从个人向量知识库检索相关内容增强回答

### Agent 6: Email Agent（邮件推送）

**职责**：定时任务结果通过 Resend 邮件推送

### Agent 7: Feishu Agent（飞书云文档展示）

**职责**：将搜索到的文章写入飞书云文档（标题+摘要+链接+总结），方便用户查阅

***

## 四、数据模型（Turso libSQL 设计）

### 4.1 3 张表 + 关联关系

```
┌──────────────────────────────────────────────────┐
│  Turso libSQL（9GB 免费，无字数限制）                       │
├──────────────────────────────────────────────────┤
│                                                    │
│  📋 ai_sessions（会话表）                          │
│     session_id (主键)                              │
│     title (会话标题)                                │
│     created_at                                      │
│     last_active                                     │
│     message_count                                   │
│           ↓ 1:N                                    │
│                                                    │
│  📋 ai_messages（消息表）                          │
│     message_id (主键)                              │
│     session_id (外键 → ai_sessions)               │
│     role (user / assistant)                        │
│     content (消息内容)                              │
│     trace_id (关联追踪)                             │
│     created_at                                      │
│           ↓ 1:1                                    │
│                                                    │
│  📋 ai_trace_calls（追踪明细）                     │
│     call_id (主键)                                 │
│     trace_id (逻辑外键)                            │
│     agent_name                                      │
│     input_data                                      │
│     output_data                                     │
│     duration_ms                                     │
│     status                                          │
│     metadata                                        │
│     timestamp                                       │
└──────────────────────────────────────────────────┘
```

### 4.2 三层关系说明

**会话（Session）→ 消息（Messages）→ 追踪（Trace Calls）**

- **一次会话**：多个来回（user/assistant）
- **一次问答（一对消息）**：一个 trace\_id
- **一次 trace**：多个 Agent 调用

### 4.3 字段详细说明

**ai\_sessions 表**：

| 字段             | 类型     | 说明        |
| -------------- | ------ | --------- |
| session\_id    | 文本(主键) | UUID      |
| title          | 文本     | 自动从首条消息生成 |
| created\_at    | 日期     | 创建时间      |
| last\_active   | 日期     | 最后活跃时间    |
| message\_count | 数字     | 消息数量      |

**ai\_messages 表**：

| 字段          | 类型     | 说明                      |
| ----------- | ------ | ----------------------- |
| message\_id | 文本(主键) | UUID                    |
| session\_id | 文本(外键) | 关联会话                    |
| role        | 单选     | user / assistant        |
| content     | 长文本    | 消息内容                    |
| trace\_id   | 文本     | 关联追踪（user/assistant 共享） |
| created\_at | 日期     | 创建时间                    |

**ai\_trace\_calls 表**：

| 字段           | 类型     | 说明                    |
| ------------ | ------ | --------------------- |
| call\_id     | 文本(主键) | UUID                  |
| trace\_id    | 文本     | 关联一次问答                |
| agent\_name  | 文本     | master/search/llm/... |
| input\_data  | 长文本    | JSON 字符串              |
| output\_data | 长文本    | JSON 字符串              |
| duration\_ms | 数字     | 耗时                    |
| status       | 单选     | success/error         |
| metadata     | 长文本    | JSON 字符串              |
| timestamp    | 日期     | 调用时间                  |

***

## 五、会话恢复机制（Trae/Doubao 式）

### 5.1 核心需求

用户点开历史对话后：

1. ✅ 显示历史对话记录
2. ✅ 能继续对话
3. ✅ **Agent 不丢失记忆**（关键！）

### 5.2 实现原理

**Agent 是无状态的**，记忆来自历史消息。点开历史对话 = 加载历史消息作为上下文。

### 5.3 流程

```
┌─────────────────────────────────────────┐
│ 1. 用户点开历史会话 "RAG 是什么"         │
│    session_id = uuid-1                  │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ 2. 前端调用 GET /api/sessions/uuid-1/   │
│    messages                              │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ 3. 后端从 ai_messages 表加载所有消息     │
│    返回 [{role:user, ...},              │
│          {role:assistant, ...}, ...]    │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ 4. 前端渲染历史消息                      │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ 5. 用户输入新问题 "它有什么优势？"        │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ 6. 前端调用 POST /api/chat              │
│    body: {                              │
│      session_id: "uuid-1",              │
│      history: [...所有历史消息...],     │
│      new_input: "它有什么优势？"         │
│    }                                    │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ 7. 后端构造完整上下文                     │
│    messages = history + [new_input]     │
│    → 调用 Master Agent                  │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ 8. 保存新消息到 ai_messages 表           │
│    记录 trace 到 ai_trace_calls 表       │
└────────────────┬────────────────────────┘
                 ↓
┌─────────────────────────────────────────┐
│ 9. 前端更新界面（显示新回答）            │
└─────────────────────────────────────────┘
```

### 5.4 上下文压缩机制（Trae 式）

**核心原则**：不强制截断，不让 AI 失忆

**两种触发方式**：

1. **被动压缩**：token 数超过阈值（默认 100K，DeepSeek 上下文是 128K）自动触发
2. **主动压缩**：用户点按钮立即压缩 / 清空 / 下载

```python
def build_context(session_id, max_tokens=100_000):
    """
    智能构建上下文：超长就压缩，不超长就全传
    
    为什么不是"只传最近 N 条"？
    - 那样会让 AI 失忆（前面讨论的内容完全丢失）
    - 应该用摘要压缩代替截断
    """
    messages = load_all_messages(session_id)
    total_tokens = count_tokens(messages)
    
    if total_tokens <= max_tokens:
        return messages  # 不超 → 全部传，完整记忆
    
    # 超阈值 → 压缩老消息为摘要
    return compress_old_messages(messages, keep_recent=10)


def compress_old_messages(messages, keep_recent=10):
    """
    压缩老消息为摘要（不丢记忆的关键）
    """
    recent = messages[-keep_recent:]  # 保留最近 10 条完整对话
    
    old = messages[:-keep_recent]
    if not old:
        return recent
    
    # 用 LLM 总结老对话
    summary = llm.summarize(old)
    
    # 摘要作为 system message 放在最前面
    compressed = {
        "role": "system",
        "content": f"## 前面对话的摘要\n{summary}"
    }
    return [compressed] + recent
```

**前端交互**：

```
[⚙️ 上下文管理]  当前: 105K / 100K tokens ⚠️
  ├─ [立即压缩]  把历史对话摘要成 1 条
  ├─ [清空会话]  重新开始
  └─ [下载历史]  导出为 Markdown
```

**分档提醒机制**（按对话轮数 + token 数双触发）：

| 轮数       | tokens   | 提醒等级  | UI 表现                                                       |
| -------- | -------- | ----- | ----------------------------------------------------------- |
| < 30 轮   | < 10K    | 🟢 正常 | 无提示                                                         |
| 30-50 轮  | 10K-30K  | 🟡 提示 | 顶部黄色条："对话较长，回答可能不够精准，建议压缩"                                  |
| 50-100 轮 | 30K-100K | 🟠 推荐 | 顶部橙色条："已 50 轮对话，是否立即压缩？" \[立即压缩] \[继续对话]                    |
| > 100 轮  | > 100K   | 🔴 警告 | 强制弹窗："已达 100 轮 / 105K tokens，**必须压缩**才能继续" \[压缩并继续] \[清空重开] |

**实现逻辑**：

```python
def get_context_warning(message_count, total_tokens):
    """根据轮数和 token 数返回警告等级"""
    if message_count >= 100 or total_tokens >= 100_000:
        return "danger"  # 🔴 强制
    if message_count >= 50 or total_tokens >= 30_000:
        return "warning"  # 🟠 推荐
    if message_count >= 30 or total_tokens >= 10_000:
        return "info"  # 🟡 提示
    return None  # 🟢 正常
```

**用户主动压缩触发**：

- 顶部警告条 \[立即压缩] 按钮
- 输入框旁的 ⚙️ 菜单
- 任何一轮发送消息前检测 → 弹确认框

**关键原则**：

- 提醒而不强制（让用户决定）
- 但 100 轮 / 100K 后**必须压缩**（技术限制）
- 压缩前可以 \[下载历史] 保留完整记录

**关键优势**：

- ✅ 不丢记忆（摘要保留关键信息）
- ✅ 用户可控（按钮触发）
- ✅ 自动降级（超阈值自动压缩）
- ✅ 类似 Trae/ChatGPT 体验

### 5.5 为什么 Agent 不丢记忆？

**关键认知**：

- Agent **本身无状态**（每次调用是独立的）
- **"记忆"= 历史消息作为输入**
- 只要传完整历史给 Agent，Agent 就像"记得"之前说过的话

**示例**：

```python
# 用户点开历史会话
history = load_messages(session_id)  # 加载历史
# history = [
#   {role: "user", content: "什么是 RAG？"},
#   {role: "assistant", content: "RAG 是..."},
# ]

# 用户继续问
new_input = "它有什么优势？"

# 构造完整上下文
full_messages = history + [{role: "user", content: new_input}]

# 调用 Agent（Agent 看到完整历史 = 有记忆）
response = agent.invoke({"messages": full_messages})
```

### 5.6 前端体验

```
┌──────────────────────────────────────┐
│  侧边栏              │  主对话区       │
│  ┌──────────────┐    │                │
│  │ 🆕 新建对话  │    │  历史消息：     │
│  └──────────────┘    │  ┌──────────┐ │
│  ┌──────────────┐    │  │ 👤 RAG？  │ │
│  │ RAG 是什么    │    │  └──────────┘ │
│  │ 2026-01-01   │    │  ┌──────────┐ │
│  │ 5 条消息     │ ← 选中 │ 🤖 RAG是..│ │
│  └──────────────┘    │  └──────────┘ │
│  ┌──────────────┐    │                │
│  │ 多 Agent 架构 │    │  新输入框：    │
│  │ 2025-12-30   │    │  [       ]    │
│  └──────────────┘    │                │
└──────────────────────────────────────┘
```

### 5.7 简历怎么写

> 实现会话恢复机制：用户点开历史对话时从 Turso 加载历史消息作为 Agent 上下文，实现多轮对话记忆持久化；通过限制上下文长度控制 token 消耗，类似 ChatGPT/Trae 产品的会话管理体验。

***

***

## 四、核心场景流程

### 场景 1：智能对话（核心）

```
用户："什么是 RAG？"
    ↓
Master Agent 意图识别 → "professional"
    ↓
调度 RAG Agent → 先查个人知识库（已存的文章）
    ↓
调度 Search Agent → 补充搜索网络最新文章
    ↓
Master Agent 综合生成回答（附文章引用）：
┌─────────────────────────────────────┐
│ RAG（检索增强生成）是一种...          │
│                                      │
│ 📚 知识库相关内容：                   │
│ - 你之前整理的《RAG 完全指南》摘要    │
│                                      │
│ 📎 网络最新文章：                     │
│ 1. [RAG 进阶实践](url)               │
│    摘要：...                         │
│ 2. [RAG 性能优化](url)               │
│    摘要：...                         │
└─────────────────────────────────────┘
    ↓
Master Agent 询问："是否整理到知识库？"
    ↓
用户："是"
    ↓
调度 Knowledge Agent → 写入知识库
    ↓
Master Agent："已存入知识库 ✅"
    ↓
Master Agent："是否基于这些内容生成一篇技术博客？"
    ↓
用户："是"
    ↓
调度 Blog Agent → 生成博客草稿
    ↓
弹窗 Markdown 编辑器（详见场景 3）
```

### 场景 2：定时推送（每日早报）

```
07:00 GitHub Actions 触发
    ↓
调度 Search Agent → "AI Agent 前沿技术" → 5 篇文章
    ↓
调度 Feishu Agent → 写入飞书云文档（标题+摘要+链接+总结）
    ↓
调度 Email Agent → Resend 邮件：
┌─────────────────────────────────────┐
│ 📚 今日 AI Agent 前沿资讯（5 篇）    │
│                                      │
│ 1. {标题}                            │
│    摘要：...                         │
│    🔗 {链接}                         │
│                                      │
│ ...（共 5 篇）                       │
│                                      │
│ 综合总结：...                        │
│                                      │
│ [✅ 已写入飞书云文档]                    │
│ [📝 生成技术博客]                    │
│ [❌ 仅查看]                          │
└─────────────────────────────────────┘
    ↓
用户点击"生成技术博客"
    ↓
跳转到聊天机器人页面 → 场景 3
```

### 场景 3：博客在线编辑（Trae 风格）

```
Blog Agent 生成博客草稿
    ↓
弹窗 Markdown 编辑器：
┌─────────────────────────────────────┐
│  Markdown 编辑器             [下载] │
│ ┌─────────────────────────────────┐ │
│ │ # RAG 技术深度解析              │ │
│ │                                  │ │
│ │ ## 背景                          │ │
│ │ RAG 是一种结合检索和生成...      │ │
│ │                  ┌────────────┐  │ │
│ │  [框选的文字]    │ AI 修改框  │  │ │
│ │                  │ [输入指令] │  │ │
│ │                  │ [生成]     │  │ │
│ │                  └────────────┘  │ │
│ └─────────────────────────────────┘ │
│                                      │
│ [发布到博客]  [下载 .md]  [关闭]    │
└─────────────────────────────────────┘
```

**框选 AI 修改流程**：

1. 用户选中一段文字
2. 弹出小输入框（类似 Trae）
3. 输入修改指令（如"更详细一些"）
4. Blog Agent 局部重写该段
5. 替换选中的文字
6. 继续编辑或发布

**发布选项**：

- 下载 `.md` 文件
- 通过 API 发布到博客平台（VitePress）

***

## 五、技术架构

### 5.1 技术栈

| 类别       | 选型             | 说明           |
| -------- | -------------- | ------------ |
| Agent 框架 | LangGraph      | 状态机编排        |
| LLM      | DeepSeek       | 对话 + 生成      |
| 搜索       | Tavily API     | AI 优化搜索      |
| 数据库/向量   | Turso libSQL   | 9GB 免费，含向量扩展 |
| 飞书       | 飞书 Open API    | 云文档，展示每日文章   |
| 邮件       | Resend         | 免费 100 封/天   |
| 定时       | GitHub Actions | 免费定时         |
| 前端       | HTML + JS      | 轻量，无需框架      |
| 部署       | Vercel         | Serverless   |

### 5.2 项目结构

```
harness/
├── common.py              # 公共导入
├── master_agent.py        # 主对话 Agent
├── agents/
│   ├── search_agent.py    # 搜索 Agent
│   ├── feishu_agent.py    # 飞书云文档 Agent
│   ├── blog_agent.py      # 博客 Agent
│   ├── rag_agent.py       # RAG Agent
│   └── email_agent.py     # 邮件 Agent
├── tools/
│   ├── tavily_tool.py     # 搜索工具
│   ├── feishu_tool.py     # 飞书云文档 API
│   ├── turso_tool.py     # Turso API
│   └── resend_tool.py     # 邮件工具
├── api/
│   ├── chat.py            # 对话接口
│   ├── daily.py           # 定时任务入口
│   └── publish.py         # 博客发布
├── web/
│   └── index.html         # 聊天 + 编辑器界面
├── .github/workflows/
│   └── daily.yml          # 定时任务
├── .env
└── requirements.txt
```

### 5.3 上下文隔离设计

```
Master Agent 上下文（精简）：
- current_intent
- active_agent
- task_status
- 待用户确认的选项

子 Agent 独立上下文：
- search_agent: 搜索结果
- blog_agent: 博客草稿、编辑历史
- rag_agent: 检索结果
```

***

## 六、开发里程碑

| 阶段     | 内容                          | 产出        |
| ------ | --------------------------- | --------- |
| **M1** | Master Agent + Search Agent | 能对话 + 搜文章 |
| **M2** | Knowledge Agent             | 能存知识库文档   |
| **M3** | Blog Agent + 编辑器            | 能生成编辑博客   |
| **M4** | RAG Agent                   | 知识库问答     |
| **M5** | Email Agent + 定时            | 每日早报推送    |
| **M6** | 部署 Vercel                   | 上线运行      |

***

## 七、已确认配置

| 服务                | Key / ID                                                    | 用途       | 状态 |
| ----------------- | ----------------------------------------------------------- | -------- | -- |
| **Tavily**（搜索）    | `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` | 搜索权威文章   | ✅  |
| **飞书 App ID**     | `cli_aace260d3239dbe4`                                      | 操作飞书云文档  | ✅  |
| **飞书 App Secret** | `wX6S2emp7dfQ1qQe5IqlPdYvB8TeRFoc`                          | 操作飞书云文档  | ✅  |
| **Resend**（邮件）    | `re_XQpDFZPn_QJPd5zaMqigZN1DfXSiMZEqP`                      | 每日早报邮件推送 | ✅  |
| **DeepSeek**      | `sk-1e52a65d5af34443a28cd3b948ffe7ba`                       | LLM 对话   | ✅  |

**待办**：

- ⏳ 博客平台 API（按钮点下暂用下载本地 Markdown）

**配置文件位置**：[.env](file:///Users/gaozhenqi/Desktop/harness/.env) （不提交到 Git）

***

## 八、简历文案

> **个人 AI 知识助手（多 Agent + Harness Engineering）**
>
> - 基于 LangGraph 构建 6 个协同 Agent，实现智能对话、知识检索、内容创作全流程
> - 设计意图识别机制，区分闲聊/简单问答/专业咨询，动态调度搜索和 RAG Agent
> - 实现 Human-in-the-loop：邮件审批 + Trae 风格在线 Markdown 编辑器（支持框选 AI 局部重写）
> - 集成 Turso (libSQL) 存储对话/trace/知识库，飞书云文档展示每日文章，构建知识沉淀闭环
> - GitHub Actions 定时任务 + Resend 邮件，实现每日行业前沿自动推送
> - 主-子 Agent 上下文隔离架构，避免上下文爆炸，支持长对话

