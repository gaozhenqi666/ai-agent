# 个人 AI 知识助手 - API 设计文档

> 版本: v0.1.0  
> 编写日期: 2026-07-01  
> 编写依据: PRD.md + SRS.md

---

## 目录

- [1. 概述](#1-概述)
- [2. 通用规范](#2-通用规范)
- [3. 接口列表](#3-接口列表)
- [4. 接口详情](#4-接口详情)
  - [4.1 健康检查](#41-健康检查)
  - [4.2 会话管理](#42-会话管理)
  - [4.3 对话](#43-对话)
  - [4.4 追踪](#44-追踪)
  - [4.5 知识库](#45-知识库)
  - [4.6 博客](#46-博客)
  - [4.7 每日早报](#47-每日早报)
  - [4.8 系统](#48-系统)
- [5. 错误码](#5-错误码)
- [6. 鉴权与限流](#6-鉴权与限流)
- [7. 版本与变更](#7-版本与变更)

---

## 1. 概述

### 1.1 基础信息

| 项 | 值 |
| --- | --- |
| Base URL | `https://<your-domain>.vercel.app/api` |
| 协议 | HTTPS |
| 数据格式 | JSON（请求 / 响应） |
| 字符编码 | UTF-8 |
| API 版本 | v1（通过 URL 前缀 `/api/v1/` 区分，可选） |
| 流式协议 | Server-Sent Events (SSE) |

### 1.2 设计原则

1. **RESTful**：资源用名词，操作用 HTTP 动词
2. **统一响应格式**：所有响应都包含 `code` / `message` / `data`
3. **错误可定位**：错误响应包含 `error.type` 和 `error.details`
4. **幂等性**：GET/PUT/DELETE 天然幂等，POST 必要时支持 `Idempotency-Key`
5. **版本化**：URL 中带版本号（可选 `/api/v1/`）

### 1.3 模块划分

```
/api/health           健康检查
/api/sessions         会话管理
/api/chat             对话入口
/api/traces           追踪查询
/api/knowledge        知识库
/api/blogs            博客
/api/daily            每日早报
/api/system           系统管理
```

---

## 2. 通用规范

### 2.1 鉴权 Header

所有非公开 API 需在 Header 中携带：

```
Authorization: Bearer <API_KEY>
Content-Type: application/json
```

`API_KEY` 存储在后端 `.env` 中，前后端共享。**不**通过 URL 传参。

### 2.2 请求头规范

| Header | 必填 | 说明 |
| --- | --- | --- |
| `Authorization` | ✅ | `Bearer <API_KEY>` |
| `Content-Type` | ✅ | `application/json` |
| `X-Request-Id` | ❌ | 客户端生成的请求 ID，用于日志追踪 |
| `X-Session-Id` | ❌ | 当前会话 ID（可选，用于服务端优化） |
| `Idempotency-Key` | ❌ | 幂等键，防止重复提交 |

### 2.3 通用响应格式

**成功**：

```json
{
  "code": 0,
  "message": "ok",
  "data": { ... },
  "request_id": "req-uuid-1"
}
```

**失败**：

```json
{
  "code": 4001,
  "message": "Session not found",
  "error": {
    "type": "SESSION_NOT_FOUND",
    "details": "session_id: uuid-xxx"
  },
  "request_id": "req-uuid-1"
}
```

### 2.4 分页规范

**Query 参数**：

- `limit`：每页数量，默认 20，最大 100
- `offset`：偏移量，默认 0
- `cursor`：游标分页（可选，用于大列表）

**响应包含**：

```json
{
  "code": 0,
  "data": {
    "total": 100,
    "limit": 20,
    "offset": 0,
    "items": [...]
  }
}
```

### 2.5 时间格式

所有时间字段使用 **ISO 8601** + UTC：

```
2026-07-01T08:00:00Z
2026-07-01T16:00:00+08:00
```

### 2.6 ID 格式

所有 ID 使用 **UUID v4**：

```
550e8400-e29b-41d4-a716-446655440000
```

---

## 3. 接口列表

| 模块 | 方法 | 路径 | 说明 | 鉴权 |
| --- | --- | --- | --- | --- |
| **健康** | GET | `/health` | 服务健康检查 | ❌ |
| **会话** | GET | `/sessions` | 列出所有会话 | ✅ |
| | POST | `/sessions` | 新建会话 | ✅ |
| | GET | `/sessions/{id}` | 获取会话详情 | ✅ |
| | PATCH | `/sessions/{id}` | 更新会话 | ✅ |
| | DELETE | `/sessions/{id}` | 删除会话 | ✅ |
| | GET | `/sessions/{id}/messages` | 获取消息列表 | ✅ |
| | POST | `/sessions/{id}/compress` | 立即压缩上下文 | ✅ |
| | POST | `/sessions/{id}/clear` | 清空会话 | ✅ |
| | GET | `/sessions/{id}/export` | 导出会话 | ✅ |
| **对话** | POST | `/chat` | 发送消息（同步） | ✅ |
| | POST | `/chat/stream` | 发送消息（流式） | ✅ |
| **追踪** | GET | `/traces/{id}` | 获取追踪详情 | ✅ |
| **知识库** | GET | `/knowledge/articles` | 列出文章 | ✅ |
| | POST | `/knowledge/articles` | 添加文章 | ✅ |
| | GET | `/knowledge/articles/{id}` | 文章详情 | ✅ |
| | PATCH | `/knowledge/articles/{id}` | 更新文章 | ✅ |
| | DELETE | `/knowledge/articles/{id}` | 删除文章 | ✅ |
| | POST | `/knowledge/search` | 语义检索 | ✅ |
| **博客** | GET | `/blogs` | 列出博客 | ✅ |
| | POST | `/blogs/generate` | 生成博客 | ✅ |
| | GET | `/blogs/{id}` | 博客详情 | ✅ |
| | PATCH | `/blogs/{id}` | 更新博客 | ✅ |
| | POST | `/blogs/{id}/edit` | AI 局部编辑 | ✅ |
| | POST | `/blogs/{id}/publish` | 发布博客 | ✅ |
| | GET | `/blogs/{id}/download` | 下载 Markdown | ✅ |
| **早报** | POST | `/daily/run` | 手动触发 | ✅ |
| | GET | `/daily/reports` | 列出报告 | ✅ |
| | GET | `/daily/reports/{date}` | 获取报告 | ✅ |
| **系统** | GET | `/system/config` | 获取公开配置 | ❌ |
| | GET | `/system/stats` | 系统统计 | ✅ |

---

## 4. 接口详情

### 4.1 健康检查

#### GET /api/health

**鉴权**：否

**响应**：

```json
{
  "code": 0,
  "data": {
    "status": "ok",
    "version": "0.1.0",
    "services": {
      "database": "ok",
      "llm": "ok",
      "search": "ok"
    },
    "timestamp": "2026-07-01T08:00:00Z"
  }
}
```

**说明**：

- `status: "ok"` 表示所有服务正常
- 任何子服务异常返回 503

---

### 4.2 会话管理

#### 4.2.1 列出所有会话

**GET** `/api/sessions`

**Query 参数**：

| 参数 | 类型 | 必填 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `limit` | int | ❌ | 20 | 数量限制（最大 100） |
| `offset` | int | ❌ | 0 | 偏移量 |
| `is_archived` | bool | ❌ | false | 是否归档 |

**响应**：

```json
{
  "code": 0,
  "data": {
    "total": 25,
    "limit": 20,
    "offset": 0,
    "sessions": [
      {
        "session_id": "550e8400-e29b-41d4-a716-446655440000",
        "title": "RAG 是什么",
        "created_at": "2026-07-01T00:00:00Z",
        "last_active": "2026-07-01T08:30:00Z",
        "message_count": 12,
        "is_archived": false,
        "last_message_preview": "RAG 是检索增强生成...",
        "last_message_role": "assistant"
      }
    ]
  }
}
```

**排序**：`last_active DESC`

---

#### 4.2.2 新建会话

**POST** `/api/sessions`

**请求体**：

```json
{
  "title": "可选，默认 '新对话'"
}
```

**响应**：

```json
{
  "code": 0,
  "data": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "新对话",
    "created_at": "2026-07-01T08:00:00Z",
    "message_count": 0
  }
}
```

**状态码**：

- 201 Created

---

#### 4.2.3 获取会话详情

**GET** `/api/sessions/{session_id}`

**Query 参数**：

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `include_messages` | bool | true | 是否包含消息 |
| `message_limit` | int | 50 | 消息数量限制（最大 200） |

**响应**：

```json
{
  "code": 0,
  "data": {
    "session_id": "550e8400-e29b-41d4-a716-446655440000",
    "title": "RAG 是什么",
    "created_at": "2026-07-01T00:00:00Z",
    "last_active": "2026-07-01T08:30:00Z",
    "message_count": 12,
    "is_archived": false,
    "context_warning": "info",
    "total_tokens": 15234,
    "messages": [
      {
        "message_id": "msg-uuid-1",
        "role": "user",
        "content": "什么是 RAG？",
        "trace_id": "trace-uuid-1",
        "tokens": 8,
        "created_at": "2026-07-01T00:00:00Z"
      },
      {
        "message_id": "msg-uuid-2",
        "role": "assistant",
        "content": "RAG 是检索增强生成...",
        "trace_id": "trace-uuid-1",
        "tokens": 256,
        "created_at": "2026-07-01T00:00:05Z",
        "articles": [
          {
            "title": "RAG 完全指南",
            "url": "https://...",
            "snippet": "..."
          }
        ]
      }
    ]
  }
}
```

**`context_warning` 取值**：

- `null` - 正常
- `"info"` - 30-50 轮 / 10K-30K
- `"warning"` - 50-100 轮 / 30K-100K
- `"danger"` - > 100 轮 / > 100K

---

#### 4.2.4 更新会话

**PATCH** `/api/sessions/{session_id}`

**请求体**（字段均可选）：

```json
{
  "title": "RAG 深入理解",
  "is_archived": true
}
```

**响应**：

```json
{
  "code": 0,
  "data": {
    "session_id": "550e8400-...",
    "title": "RAG 深入理解",
    "is_archived": true,
    "updated_at": "2026-07-01T08:00:00Z"
  }
}
```

---

#### 4.2.5 删除会话

**DELETE** `/api/sessions/{session_id}`

**响应**：

```json
{
  "code": 0,
  "data": {
    "deleted": true,
    "deleted_messages": 12,
    "deleted_traces": 5
  }
}
```

**说明**：级联删除所有 messages 和 trace_calls。

---

#### 4.2.6 获取消息列表

**GET** `/api/sessions/{session_id}/messages`

**Query 参数**：

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `limit` | int | 50 | 数量限制 |
| `before` | UUID | - | 获取此 message_id 之前的消息（分页） |
| `include_compressed` | bool | true | 是否包含压缩后的摘要 |

**响应**：

```json
{
  "code": 0,
  "data": {
    "session_id": "550e8400-...",
    "total_tokens": 15234,
    "message_count": 12,
    "warning_level": "info",
    "messages": [
      {
        "message_id": "msg-uuid-1",
        "role": "user",
        "content": "什么是 RAG？",
        "trace_id": "trace-uuid-1",
        "tokens": 8,
        "created_at": "2026-07-01T00:00:00Z"
      }
    ]
  }
}
```

---

#### 4.2.7 立即压缩上下文

**POST** `/api/sessions/{session_id}/compress`

**请求体**（可选）：

```json
{
  "keep_recent": 10
}
```

**响应**：

```json
{
  "code": 0,
  "data": {
    "compressed": true,
    "original_tokens": 105000,
    "new_tokens": 23456,
    "summary_message_id": "msg-sum-uuid-1",
    "kept_messages": 10
  }
}
```

**实现逻辑**：

```python
def compress_context(session_id, keep_recent=10):
    messages = load_all_messages(session_id)
    if len(messages) <= keep_recent:
        return {"compressed": False, "reason": "no need"}
    
    recent = messages[-keep_recent:]
    old = messages[:-keep_recent]
    
    # LLM 摘要
    summary = llm.summarize(old)
    
    # 插入 system 消息
    summary_msg = {
        "role": "system",
        "content": f"## 前面对话的摘要\n{summary}"
    }
    
    # 删除老消息，插入摘要
    delete_old_messages(session_id, old)
    insert_message(session_id, summary_msg)
    
    return {"compressed": True, ...}
```

---

#### 4.2.8 清空会话

**POST** `/api/sessions/{session_id}/clear`

**请求体**（可选）：

```json
{
  "confirm": true
}
```

**响应**：

```json
{
  "code": 0,
  "data": {
    "cleared": true,
    "deleted_messages": 12,
    "session_id": "550e8400-..."
  }
}
```

**说明**：清空**不**删除会话本身，只删除消息。

---

#### 4.2.9 导出会话

**GET** `/api/sessions/{session_id}/export`

**Query 参数**：

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `format` | string | `md` | `md` / `json` |

**响应**（format=md）：

```http
HTTP/1.1 200 OK
Content-Type: text/markdown
Content-Disposition: attachment; filename="session-xxx-2026-07-01.md"

# RAG 是什么

> 导出时间：2026-07-01 16:00:00 (UTC+8)
> 消息数：12

---

## 什么是 RAG？

**用户** | 2026-07-01 00:00:00

---

## RAG 是检索增强生成...

**助手** | 2026-07-01 00:00:05

---
```

---

### 4.3 对话

#### 4.3.1 发送消息（同步）

**POST** `/api/chat`

**请求体**：

```json
{
  "session_id": "550e8400-...",
  "message": "什么是 RAG？",
  "history": [],                // 可选，不传则服务器从 DB 加载
  "stream": false,
  "options": {
    "model": "deepseek-chat",   // 可选
    "temperature": 0.7
  }
}
```

**`session_id` 为空时**：自动创建新会话。

**响应**：

```json
{
  "code": 0,
  "data": {
    "session_id": "550e8400-...",
    "user_message_id": "msg-uuid-1",
    "assistant_message_id": "msg-uuid-2",
    "trace_id": "trace-uuid-1",
    "intent": "professional",
    "intent_confidence": 0.92,
    "response": "RAG（检索增强生成）是一种...",
    "articles": [
      {
        "title": "RAG 完全指南",
        "url": "https://...",
        "snippet": "...",
        "source": "Tavily"
      }
    ],
    "actions": [                  // 后续可选操作
      {
        "type": "save_to_kb",
        "label": "是否整理到知识库？"
      },
      {
        "type": "write_blog",
        "label": "是否生成技术博客？"
      }
    ],
    "usage": {
      "prompt_tokens": 1234,
      "completion_tokens": 567,
      "total_tokens": 1801,
      "duration_ms": 3200
    },
    "context_warning": null
  }
}
```

**错误码**：

- 4001 - 会话不存在
- 4005 - 消息过长
- 4006 - Token 超限（需先压缩）
- 5001 - LLM 调用失败

---

#### 4.3.2 发送消息（流式）

**POST** `/api/chat/stream`

**请求体**：同 4.3.1

**响应**：`Content-Type: text/event-stream`

**SSE 事件类型**：

```
event: start
data: {"session_id":"...","trace_id":"..."}

event: intent
data: {"intent":"professional","confidence":0.92}

event: tool_call
data: {"agent":"search","operation":"search_query","input":{...}}

event: tool_result
data: {"agent":"search","output":{"results":[...]}}

event: content
data: {"delta":"RAG 是"}

event: content
data: {"delta":"检索增强"}

event: content
data: {"delta":"生成..."}

event: done
data: {"message_id":"msg-uuid-2","usage":{...}}

```

**错误事件**：

```
event: error
data: {"code":5001,"message":"LLM 调用失败","error":{...}}
```

---

### 4.4 追踪

#### 4.4.1 获取追踪详情

**GET** `/api/traces/{trace_id}`

**响应**：

```json
{
  "code": 0,
  "data": {
    "trace_id": "trace-uuid-1",
    "session_id": "550e8400-...",
    "started_at": "2026-07-01T00:00:00Z",
    "duration_ms": 3200,
    "status": "success",
    "calls": [
      {
        "call_id": "call-uuid-1",
        "agent_name": "master",
        "operation": "intent_recognition",
        "input_data": { "message": "什么是 RAG？" },
        "output_data": { "intent": "professional" },
        "duration_ms": 800,
        "status": "success",
        "created_at": "2026-07-01T00:00:00Z"
      },
      {
        "call_id": "call-uuid-2",
        "agent_name": "search",
        "operation": "search_query",
        "input_data": {
          "query": "RAG 检索增强生成",
          "mode": "relevance"
        },
        "output_data": {
          "results_count": 5
        },
        "duration_ms": 1200,
        "status": "success",
        "created_at": "2026-07-01T00:00:01Z"
      },
      {
        "call_id": "call-uuid-3",
        "agent_name": "llm",
        "operation": "generate_response",
        "input_data": { "prompt_tokens": 1234 },
        "output_data": { "content_length": 567 },
        "duration_ms": 1200,
        "status": "success",
        "created_at": "2026-07-01T00:00:02Z"
      }
    ]
  }
}
```

**用途**：

- 调试 Agent 行为
- 性能分析
- Token 消耗统计

---

### 4.5 知识库

#### 4.5.1 列出文章

**GET** `/api/knowledge/articles`

**Query 参数**：

| 参数 | 类型 | 默认 | 说明 |
| --- | --- | --- | --- |
| `limit` | int | 20 | 数量限制 |
| `offset` | int | 0 | 偏移量 |
| `tag` | string | - | 按标签过滤 |
| `source` | string | - | 按来源过滤 |
| `search` | string | - | 关键词搜索（标题/摘要） |

**响应**：

```json
{
  "code": 0,
  "data": {
    "total": 50,
    "items": [
      {
        "article_id": "art-uuid-1",
        "title": "RAG 完全指南",
        "url": "https://...",
        "summary": "...",
        "source": "Tavily",
        "tags": ["RAG", "AI"],
        "published_at": "2025-12-01T00:00:00Z",
        "created_at": "2026-07-01T00:00:00Z"
      }
    ]
  }
}
```

---

#### 4.5.2 添加文章

**POST** `/api/knowledge/articles`

**请求体**：

```json
{
  "title": "RAG 完全指南",
  "url": "https://...",
  "content": "完整文章内容...",
  "summary": "AI 摘要...",
  "source": "Tavily",
  "published_at": "2025-12-01T00:00:00Z",
  "tags": ["RAG", "AI"],
  "saved_by_session_id": "550e8400-..."  // 可选
}
```

**响应**（201 Created）：

```json
{
  "code": 0,
  "data": {
    "article_id": "art-uuid-1",
    "embedding_generated": true,
    "created_at": "2026-07-01T00:00:00Z"
  }
}
```

**错误码**：

- 3001 - 文章 URL 重复

**副作用**：

- 自动调用 embedding API 生成向量
- 存储到 `knowledge_articles.embedding`

---

#### 4.5.3 批量添加

**POST** `/api/knowledge/articles/batch`

**请求体**：

```json
{
  "articles": [
    { "title": "...", "url": "...", "content": "..." },
    { "title": "...", "url": "...", "content": "..." }
  ]
}
```

**约束**：单次 ≤ 20 篇。

---

#### 4.5.4 文章详情

**GET** `/api/knowledge/articles/{article_id}`

**响应**：

```json
{
  "code": 0,
  "data": {
    "article_id": "art-uuid-1",
    "title": "RAG 完全指南",
    "url": "https://...",
    "content": "完整内容...",
    "summary": "...",
    "source": "Tavily",
    "tags": ["RAG", "AI"],
    "published_at": "2025-12-01T00:00:00Z",
    "created_at": "2026-07-01T00:00:00Z",
    "updated_at": "2026-07-01T00:00:00Z"
  }
}
```

---

#### 4.5.5 更新文章

**PATCH** `/api/knowledge/articles/{article_id}`

**请求体**（字段均可选）：

```json
{
  "title": "新标题",
  "summary": "新摘要",
  "tags": ["新标签"]
}
```

**注意**：更新 `content` 会触发 embedding 重新生成。

---

#### 4.5.6 删除文章

**DELETE** `/api/knowledge/articles/{article_id}`

**响应**：

```json
{
  "code": 0,
  "data": { "deleted": true }
}
```

---

#### 4.5.7 语义检索

**POST** `/api/knowledge/search`

**请求体**：

```json
{
  "query": "什么是 RAG？",
  "top_k": 5,
  "threshold": 0.7
}
```

**响应**：

```json
{
  "code": 0,
  "data": {
    "query": "什么是 RAG？",
    "results": [
      {
        "article_id": "art-uuid-1",
        "title": "RAG 完全指南",
        "content": "...",
        "summary": "...",
        "url": "https://...",
        "score": 0.92
      }
    ]
  }
}
```

**实现**：

```sql
SELECT article_id, title, content,
       1 - (embedding <=> $1) AS score
FROM knowledge_articles
WHERE 1 - (embedding <=> $1) > $2
ORDER BY embedding <=> $1
LIMIT $3;
```

---

#### 4.5.8 知识库统计

**GET** `/api/knowledge/stats`

**鉴权**：✅

**响应**：

```json
{
  "code": 0,
  "data": {
    "total_articles": 142,
    "total_sources": 38,
    "total_size_bytes": 2411724,
    "total_size_human": "2.3 MB",
    "by_status": {
      "draft": 12,
      "published": 128,
      "archived": 2
    },
    "by_source": [
      { "source": "Tavily",  "count": 86 },
      { "source": "Feishu",  "count": 41 },
      { "source": "Manual",  "count": 15 }
    ],
    "last_updated": "2026-07-01T08:30:00Z"
  }
}
```

**说明**：

- 用于知识库页顶部统计条（142 篇 / 38 来源 / 2.3 MB）
- `by_source` 按 `source` 字段聚合

---

#### 4.5.9 AI 改写（编辑器用）

**POST** `/api/ai/rewrite`

**鉴权**：✅

**用途**：编辑器里"框选文字 → 输入框提需求 → AI 改写"流程

**请求体**：

```json
{
  "text": "很多人会担心引入 BM25 会增加复杂度,其实恰恰相反。它的索引只有向量的 1/100 大小,...",
  "instruction": "用更口语、更短的方式重写",
  "article_id": "art-uuid-1",        // 可选（用于上下文理解）
  "session_id": "550e8400-..."        // 可选（用于 trace 关联）
}
```

**响应**：

```json
{
  "code": 0,
  "data": {
    "original": "它的索引只有向量的 1/100 大小,...",
    "rewritten": "它的索引只有向量的百分之一,...",
    "diff": {
      "kept": "它的索引只有向量的",
      "removed": "1/100 大小",
      "added": "百分之一"
    },
    "usage": {
      "prompt_tokens": 412,
      "completion_tokens": 96,
      "total_tokens": 508,
      "duration_ms": 1240
    },
    "trace_id": "trace-uuid-1"
  }
}
```

**错误码**：

- 4007 - 文本过长（> 8000 字符）
- 5001 - LLM 调用失败

**实现要点**：

```python
def ai_rewrite(text, instruction):
    system = "你是一名资深技术编辑。用户会给你一段文字和改写要求，输出改写后的完整文字（保持原意、整段输出，不要 markdown 包裹）。"
    user = f"原文：\n{text}\n\n要求：{instruction}\n\n改写后："

    response = llm.chat([system, user])
    return response
```

---

### 4.6 博客

#### 4.6.1 列出博客

**GET** `/api/blogs`

**Query 参数**：

- `status`：draft / published
- `limit`, `offset`

---

#### 4.6.2 生成博客

**POST** `/api/blogs/generate`

**请求体**：

```json
{
  "session_id": "550e8400-...",
  "topic": "RAG 技术",                    // 可选
  "reference_article_ids": ["art-uuid-1", "art-uuid-2"],
  "style": "tutorial"                     // tutorial / analysis / news
}
```

**响应**：

```json
{
  "code": 0,
  "data": {
    "blog_id": "blog-uuid-1",
    "title": "RAG 技术深度解析",
    "content": "# RAG 技术深度解析\n\n## 背景\n...",
    "topic": "RAG 技术",
    "status": "draft",
    "references": [
      { "article_id": "art-uuid-1", "title": "..." }
    ],
    "created_at": "2026-07-01T00:00:00Z"
  }
}
```

**生成耗时**：3-10 秒（取决于参考文章数）。

---

#### 4.6.3 博客详情

**GET** `/api/blogs/{blog_id}`

**响应**：

```json
{
  "code": 0,
  "data": {
    "blog_id": "blog-uuid-1",
    "session_id": "550e8400-...",
    "title": "RAG 技术深度解析",
    "content": "...",
    "topic": "RAG 技术",
    "status": "draft",
    "version": 3,                        // 编辑次数
    "edit_history": [
      {
        "version": 1,
        "before": "...",
        "after": "...",
        "instruction": "更详细一些",
        "created_at": "2026-07-01T00:01:00Z"
      }
    ],
    "created_at": "2026-07-01T00:00:00Z",
    "updated_at": "2026-07-01T00:01:00Z"
  }
}
```

---

#### 4.6.4 更新博客

**PATCH** `/api/blogs/{blog_id}`

**请求体**：

```json
{
  "title": "新标题",
  "content": "新内容（Markdown）"
}
```

**说明**：手动编辑，**不**记录到 `edit_history`。

---

#### 4.6.5 AI 局部编辑

**POST** `/api/blogs/{blog_id}/edit`

**请求体**：

```json
{
  "selected_text": "RAG 是一种结合检索和生成的技术。",
  "instruction": "更详细一些，加入例子",
  "context_before": "## 背景\n",
  "context_after": "\n## 总结"
}
```

**响应**：

```json
{
  "code": 0,
  "data": {
    "new_text": "RAG 是一种结合检索和生成的技术。例如在客服系统中，RAG 可以从知识库检索相关文档，然后由 LLM 生成回答...",
    "edit_id": "edit-uuid-1",
    "version": 4
  }
}
```

**副作用**：

- `blog.content` 中替换选中段
- 记录到 `edit_history`

---

#### 4.6.6 发布博客

**POST** `/api/blogs/{blog_id}/publish`

**请求体**：

```json
{
  "platform": "vitepress",         // vitepress / download
  "commit_message": "feat: 新增 RAG 文章"  // 可选
}
```

**响应**（platform=vitepress）：

```json
{
  "code": 0,
  "data": {
    "published": true,
    "platform": "vitepress",
    "url": "https://blog.example.com/posts/rag-deep-dive",
    "published_at": "2026-07-01T00:00:00Z"
  }
}
```

**响应**（platform=download）：见 4.6.7。

---

#### 4.6.7 下载 Markdown

**GET** `/api/blogs/{blog_id}/download`

**响应**：

```http
HTTP/1.1 200 OK
Content-Type: text/markdown
Content-Disposition: attachment; filename="rag-deep-dive.md"

# RAG 技术深度解析
...
```

---

### 4.7 每日早报

#### 4.7.1 手动触发

**POST** `/api/daily/run`

**请求体**：

```json
{
  "topic": "AI Agent 前沿技术",        // 可选，默认主题
  "max_results": 5,                    // 文章数
  "send_email": true,
  "save_to_kb": true,
  "save_to_feishu": false,             // 暂未实现
  "force": false                       // 是否强制重发
}
```

**注意**：定时任务（GitHub Actions）调用的也是这个接口。

**响应**：

```json
{
  "code": 0,
  "data": {
    "report_id": "report-uuid-1",
    "report_date": "2026-07-01",
    "topic": "AI Agent 前沿技术",
    "articles_found": 5,
    "email_sent": true,
    "email_sent_at": "2026-07-01T07:00:05Z",
    "summary": "..."
  }
}
```

**说明**：

- `force=true` 时强制重新生成（覆盖已有报告）
- 异步执行可能耗时 10-30 秒

---

#### 4.7.2 列出报告

**GET** `/api/daily/reports`

**Query 参数**：

- `limit`, `offset`
- `start_date`, `end_date`：按日期范围过滤

**响应**：

```json
{
  "code": 0,
  "data": {
    "total": 30,
    "items": [
      {
        "report_id": "report-uuid-1",
        "report_date": "2026-07-01",
        "topic": "AI Agent 前沿技术",
        "email_sent": true,
        "created_at": "2026-07-01T07:00:00Z"
      }
    ]
  }
}
```

---

#### 4.7.3 获取某日报告

**GET** `/api/daily/reports/{date}`

**Path 参数**：

- `date`：YYYY-MM-DD 格式

**响应**：

```json
{
  "code": 0,
  "data": {
    "report_id": "report-uuid-1",
    "report_date": "2026-07-01",
    "topic": "AI Agent 前沿技术",
    "articles": [
      {
        "article_id": "art-uuid-1",
        "title": "...",
        "url": "https://...",
        "snippet": "...",
        "source": "Tavily"
      }
    ],
    "summary": "AI 生成的综合总结...",
    "email_sent": true,
    "email_sent_at": "2026-07-01T07:00:05Z",
    "feishu_doc_url": null,
    "created_at": "2026-07-01T07:00:00Z"
  }
}
```

---

### 4.8 系统

#### 4.8.1 获取公开配置

**GET** `/api/system/config`

**鉴权**：否

**响应**：

```json
{
  "code": 0,
  "data": {
    "version": "0.1.0",
    "features": {
      "context_compression": true,
      "blog_editor": true,
      "daily_report": true
    },
    "limits": {
      "max_message_length": 32768,
      "max_session_messages": 200,
      "compression_threshold": 100000
    }
  }
}
```

---

#### 4.8.2 系统统计

**GET** `/api/system/stats`

**响应**：

```json
{
  "code": 0,
  "data": {
    "sessions": {
      "total": 25,
      "active_7d": 5
    },
    "messages": {
      "total": 500,
      "total_tokens": 250000
    },
    "knowledge_articles": {
      "total": 50
    },
    "blogs": {
      "total": 10,
      "published": 3
    },
    "daily_reports": {
      "total": 30,
      "last_sent_at": "2026-07-01T07:00:05Z"
    }
  }
}
```

---

## 5. 错误码

### 5.1 HTTP 状态码

| 状态码 | 含义 | 说明 |
| --- | --- | --- |
| 200 | OK | 成功 |
| 201 | Created | 资源创建成功 |
| 204 | No Content | 成功无返回（如 DELETE） |
| 400 | Bad Request | 请求参数错误 |
| 401 | Unauthorized | 未鉴权 / 鉴权失败 |
| 403 | Forbidden | 无权限 |
| 404 | Not Found | 资源不存在 |
| 409 | Conflict | 资源冲突（如重复） |
| 413 | Payload Too Large | 请求过大 |
| 429 | Too Many Requests | 频率限制 |
| 500 | Internal Server Error | 服务器错误 |
| 503 | Service Unavailable | 服务不可用 |

### 5.2 业务错误码

> 业务错误码通过响应体 `code` 字段返回（HTTP 状态码仍为 200/4xx/5xx）。

| 错误码 | 类型 | 说明 | HTTP |
| --- | --- | --- | --- |
| 0 | SUCCESS | 成功 | 200 |
| 1001 | LLM_API_ERROR | LLM 调用失败 | 500 |
| 1002 | SEARCH_API_ERROR | 搜索 API 失败 | 500 |
| 1003 | EMAIL_SEND_ERROR | 邮件发送失败 | 500 |
| 1004 | TOKEN_LIMIT_EXCEEDED | Token 超限 | 400 |
| 1005 | MESSAGE_TOO_LONG | 消息过长 | 413 |
| 1006 | LLM_TIMEOUT | LLM 调用超时 | 504 |
| 2001 | SESSION_NOT_FOUND | 会话不存在 | 404 |
| 2002 | MESSAGE_NOT_FOUND | 消息不存在 | 404 |
| 2003 | ARTICLE_NOT_FOUND | 文章不存在 | 404 |
| 2004 | BLOG_NOT_FOUND | 博客不存在 | 404 |
| 2005 | REPORT_NOT_FOUND | 报告不存在 | 404 |
| 2006 | TRACE_NOT_FOUND | 追踪不存在 | 404 |
| 3001 | DUPLICATE_ARTICLE | 文章 URL 重复 | 409 |
| 3002 | DUPLICATE_BLOG | 博客标题重复 | 409 |
| 3003 | DUPLICATE_SESSION_TITLE | 会话标题重复 | 409 |
| 4001 | INVALID_PARAMS | 参数错误 | 400 |
| 4002 | MISSING_REQUIRED_FIELD | 缺少必填字段 | 400 |
| 4003 | INVALID_FORMAT | 格式错误 | 400 |
| 9001 | UNAUTHORIZED | 未鉴权 | 401 |
| 9002 | FORBIDDEN | 无权限 | 403 |
| 9003 | RATE_LIMIT_EXCEEDED | 频率限制 | 429 |
| 9999 | INTERNAL_ERROR | 内部错误 | 500 |

### 5.3 错误响应示例

```json
{
  "code": 2001,
  "message": "Session not found",
  "error": {
    "type": "SESSION_NOT_FOUND",
    "details": {
      "session_id": "550e8400-e29b-41d4-a716-446655440000"
    },
    "suggestion": "请检查 session_id 是否正确"
  },
  "request_id": "req-uuid-1"
}
```

---

## 6. 鉴权与限流

### 6.1 鉴权方式

**当前实现**：单一 API Key

```
Authorization: Bearer <API_KEY>
```

`API_KEY` 存储在后端 `.env` 中（`HARNESS_API_KEY`），前后端共享。

**未来升级**：可对接完整 Auth 服务（OAuth / JWT）

### 6.2 限流策略

| 维度 | 限制 |
| --- | --- |
| 全局 QPS | 10 req/s |
| 单 IP QPS | 5 req/s |
| 对话接口 | 30 req/min |
| 早报触发 | 1 req/hour（防误触发） |
| 知识库搜索 | 60 req/min |

**超出限制**：返回 429 + `Retry-After` 头。

### 6.3 CORS

允许的 Origin：

- `https://<your-domain>.vercel.app`
- `http://localhost:3000`（开发环境）

允许的方法：`GET, POST, PATCH, DELETE, OPTIONS`

允许的头：`Authorization, Content-Type, X-Request-Id, Idempotency-Key`

---

## 7. 版本与变更

### 7.1 版本号

API 版本通过 URL 前缀管理：

```
/api/v1/sessions
/api/v2/sessions   (未来)
```

**当前版本**：`v0.1.0`（开发中，未发布 v1）

### 7.2 兼容性

- 主版本变更：破坏性变更，需 v2
- 次版本变更：新增字段（向后兼容）
- 修订版本变更：bug 修复

### 7.3 变更历史

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v0.1.0 | 2026-07-01 | 初稿，基于 PRD + SRS 生成 |
