# 个人 AI 知识助手 - 数据库设计文档（Turso libSQL）

> 版本: v0.2.0  
> 编写日期: 2026-07-01  
> 编写依据: PRD.md + SRS.md

---

## 目录

- [1. 概述](#1-概述)
- [2. ER 图](#2-er-图)
- [3. 表结构](#3-表结构)
  - [3.1 sessions（会话表）](#31-sessions会话表)
  - [3.2 messages（消息表）](#32-messages消息表)
  - [3.3 trace_calls（追踪表）](#33-trace_calls追踪表)
  - [3.4 knowledge_articles（知识库文章）](#34-knowledge_articles知识库文章)
  - [3.5 blogs（博客表）](#35-blogs博客表)
  - [3.6 daily_reports（每日报告）](#36-daily_reports每日报告)
- [4. 索引设计](#4-索引设计)
- [5. 约束与外键](#5-约束与外键)
- [6. 触发器](#6-触发器)
- [7. 安全策略（替代 RLS）](#7-安全策略替代-rls)
- [8. 性能与扩展](#8-性能与扩展)
- [9. 迁移脚本](#9-迁移脚本)
- [10. Python 客户端示例](#10-python-客户端示例)
- [11. 数据生命周期](#11-数据生命周期)
- [12. 附录](#12-附录)

---

## 1. 概述

### 1.1 数据库选型

| 项 | 选型 | 说明 |
| --- | --- | --- |
| 数据库 | **Turso (libSQL)** | SQLite 兼容，边缘复制 |
| 免费额度 | 9GB 存储 + 5亿读/月 + 1000万写/月 | 满足个人使用 |
| 向量扩展 | **sqlite-vec** | 嵌入式 KNN 检索 |
| 字符集 | UTF-8 | 支持中文 |
| 时区 | 存储 UTC（TEXT ISO 8601），展示本地化 | - |

### 1.2 为何选 Turso

| 优势 | 说明 |
| --- | --- |
| **SQLite 兼容** | 单文件部署，开发简单 |
| **边缘复制** | 全球多区域低延迟（个人项目意义不大） |
| **9GB 免费** | 满足个人项目长期使用 |
| **支持 libSQL 协议** | 兼容 SQLite 工具链 |
| **无冷启动** | Serverless 但有边缘缓存 |

### 1.3 设计原则

1. **3 张核心表实现 3 层关系**：sessions → messages → trace_calls
2. **每对问答共享一个 trace_id**：user 和 assistant 消息用 trace_id 关联
3. **严格外键约束 + 级联删除**：删除 session 自动清理其 messages
4. **TEXT 存 JSON / UUID / 时间**：SQLite 动态类型，存为字符串
5. **BLOB 存向量**：float32 数组，配合 sqlite-vec 检索
6. **应用层鉴权**：SQLite 无 RLS，鉴权放在 Python 层

### 1.4 与 PostgreSQL 的关键差异

| 维度 | PostgreSQL | Turso libSQL |
| --- | --- | --- |
| UUID 类型 | 原生 `UUID` | `TEXT`（应用层生成） |
| 时间戳 | `TIMESTAMPTZ` | `TEXT`（ISO 8601 UTC） |
| 布尔 | `BOOLEAN` | `INTEGER`（0/1） |
| JSON | `JSONB`（二进制） | `TEXT`（JSON1 扩展查询） |
| 数组 | `TEXT[]` 原生 | `TEXT`（JSON 数组） |
| 向量 | `VECTOR(1536)` + HNSW | `BLOB` + sqlite-vec |
| RLS | 原生支持 | 无，应用层实现 |
| 触发器语言 | plpgsql | SQLite 内联（无独立语言） |
| 模式 | `schema.table` | 单库（无 schema） |

### 1.5 数据规模预估

| 表 | 预估规模 |
| --- | --- |
| sessions | 100-500 |
| messages | 10K-50K |
| trace_calls | 50K-200K |
| knowledge_articles | 500-2000 |
| blogs | 50-200 |
| daily_reports | 365/年 |

**总规模**：< 1M 行，远低于 9GB 限额。

---

## 2. ER 图

```
┌────────────────────────────────────────────────────────────────┐
│ Turso libSQL Database                                          │
├────────────────────────────────────────────────────────────────┤
│                                                                  │
│  sessions (会话)                                                │
│  ├─ session_id (TEXT PK) ─────────────────────────────────┐    │
│  ├─ user_id (TEXT)                                        │    │
│  ├─ title (TEXT)                                          │    │
│  ├─ created_at / last_active (TEXT ISO 8601)              │    │
│  ├─ message_count (INTEGER)                              │    │
│  ├─ is_archived (INTEGER 0/1)                            │    │
│  └─ metadata (TEXT JSON)                                 │    │
│         │                                                  │    │
│         │ 1:N                                              │    │
│         ↓                                                  │    │
│  messages (消息)                                            │    │
│  ├─ message_id (TEXT PK)                                 │    │
│  ├─ session_id (TEXT FK → sessions) ─────────────────────┘    │
│  ├─ role (TEXT: user/assistant/system)                      │
│  ├─ content (TEXT)                                          │
│  ├─ trace_id (TEXT)                                         │
│  ├─ tokens (INTEGER)                                        │
│  └─ metadata (TEXT JSON)                                   │
│         │                                                     │
│         │ 1:N (按 trace_id)                                  │
│         ↓                                                     │
│  trace_calls (追踪)                                            │
│  ├─ call_id (TEXT PK)                                       │
│  ├─ trace_id (TEXT)                                         │
│  ├─ session_id (TEXT FK)                                    │
│  ├─ message_id (TEXT FK, nullable)                          │
│  ├─ agent_name / operation (TEXT)                           │
│  ├─ input_data / output_data (TEXT JSON)                    │
│  ├─ duration_ms (INTEGER)                                   │
│  ├─ status (TEXT: success/error/timeout)                    │
│  └─ error_message (TEXT)                                    │
│                                                               │
│  knowledge_articles (知识库)                                   │
│  ├─ article_id (TEXT PK)                                    │
│  ├─ title / url / content / summary (TEXT)                  │
│  ├─ source / published_at (TEXT)                            │
│  ├─ embedding (BLOB float32[1536])                          │
│  ├─ tags (TEXT JSON 数组)                                    │
│  └─ saved_by_session_id (TEXT FK)                           │
│                                                               │
│  blogs (博客)                                                  │
│  ├─ blog_id (TEXT PK)                                       │
│  ├─ session_id (TEXT FK)                                    │
│  ├─ title / content / topic (TEXT)                          │
│  ├─ status (draft/published)                                │
│  └─ edit_history (TEXT JSON)                                │
│                                                               │
│  daily_reports (每日报告)                                       │
│  ├─ report_id (TEXT PK)                                     │
│  ├─ report_date (TEXT YYYY-MM-DD, UNIQUE)                   │
│  ├─ topic / article_ids / summary                           │
│  └─ email_sent / feishu_doc_url                             │
└────────────────────────────────────────────────────────────────┘
```

---

## 3. 表结构

### 3.1 sessions（会话表）

**用途**：存储用户会话元数据。

| 字段 | 类型 | 约束 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `session_id` | TEXT | PRIMARY KEY | - | UUID v4（应用层生成） |
| `user_id` | TEXT | NOT NULL | - | 用户 ID（预留多用户） |
| `title` | TEXT | NOT NULL | `'新对话'` | 会话标题 |
| `created_at` | TEXT | NOT NULL | `strftime(...)` | 创建时间（ISO 8601 UTC） |
| `last_active` | TEXT | NOT NULL | `strftime(...)` | 最后活跃时间 |
| `message_count` | INTEGER | NOT NULL, CHECK ≥ 0 | 0 | 消息数量 |
| `is_archived` | INTEGER | NOT NULL, CHECK 0/1 | 0 | 是否归档 |
| `metadata` | TEXT | NOT NULL | `'{}'` | JSON 字符串 |

**`metadata` 字段示例**：

```json
{
  "total_tokens": 15234,
  "compressed_at": "2026-07-01T08:00:00Z",
  "last_warning_level": "info"
}
```

**创建 SQL**：

```sql
CREATE TABLE sessions (
  session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '新对话',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  last_active TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  message_count INTEGER NOT NULL DEFAULT 0 CHECK (message_count >= 0),
  is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
  metadata TEXT NOT NULL DEFAULT '{}'
);
```

**索引**：

```sql
CREATE INDEX idx_sessions_user_active 
  ON sessions(user_id, last_active DESC);
CREATE INDEX idx_sessions_archived_active 
  ON sessions(is_archived, last_active DESC);
```

---

### 3.2 messages（消息表）

**用途**：存储会话中的每条消息。

| 字段 | 类型 | 约束 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `message_id` | TEXT | PRIMARY KEY | - | UUID v4 |
| `session_id` | TEXT | NOT NULL, FK → sessions | - | 所属会话 |
| `role` | TEXT | NOT NULL, CHECK IN (...) | - | 角色 |
| `content` | TEXT | NOT NULL | - | 消息内容 |
| `trace_id` | TEXT | NOT NULL | - | 关联追踪 |
| `tokens` | INTEGER | NOT NULL, CHECK ≥ 0 | 0 | token 数量 |
| `created_at` | TEXT | NOT NULL | `strftime(...)` | 创建时间 |
| `metadata` | TEXT | NOT NULL | `'{}'` | JSON 字符串 |

**`role` 枚举**：

```sql
CHECK (role IN ('user', 'assistant', 'system'))
```

**`metadata` 字段示例**（assistant 消息）：

```json
{
  "articles": [
    {
      "title": "RAG 完全指南",
      "url": "https://...",
      "snippet": "..."
    }
  ],
  "intent": "professional",
  "model": "deepseek-chat",
  "compressed": false
}
```

**创建 SQL**：

```sql
CREATE TABLE messages (
  message_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  tokens INTEGER NOT NULL DEFAULT 0 CHECK (tokens >= 0),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  metadata TEXT NOT NULL DEFAULT '{}'
);
```

**索引**：

```sql
CREATE INDEX idx_messages_session_created 
  ON messages(session_id, created_at);
CREATE INDEX idx_messages_trace 
  ON messages(trace_id);
```

---

### 3.3 trace_calls（追踪表）

**用途**：记录每次 Agent 调用的详细信息。

| 字段 | 类型 | 约束 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `call_id` | TEXT | PRIMARY KEY | - | UUID v4 |
| `trace_id` | TEXT | NOT NULL | - | 一次问答的所有调用共享 |
| `session_id` | TEXT | NOT NULL, FK → sessions | - | 所属会话 |
| `message_id` | TEXT | FK → messages, nullable | - | 关联消息 |
| `agent_name` | TEXT | NOT NULL | - | Agent 名称 |
| `operation` | TEXT | NOT NULL | - | 操作名称 |
| `input_data` | TEXT | - | - | JSON 字符串 |
| `output_data` | TEXT | - | - | JSON 字符串 |
| `duration_ms` | INTEGER | NOT NULL, CHECK ≥ 0 | - | 耗时（毫秒） |
| `status` | TEXT | NOT NULL, CHECK IN (...) | - | 状态 |
| `error_message` | TEXT | - | - | 错误信息 |
| `metadata` | TEXT | NOT NULL | `'{}'` | JSON 字符串 |
| `created_at` | TEXT | NOT NULL | `strftime(...)` | 调用时间 |

**`agent_name` 约定**：

```
master       - Master Agent
search       - Search Agent
knowledge    - Knowledge Agent
blog         - Blog Agent
rag          - RAG Agent
email        - Email Agent
llm          - LLM 底层调用
intent       - 意图识别
```

**`status` 枚举**：

```sql
CHECK (status IN ('success', 'error', 'timeout'))
```

**创建 SQL**：

```sql
CREATE TABLE trace_calls (
  call_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  message_id TEXT REFERENCES messages(message_id) ON DELETE SET NULL,
  agent_name TEXT NOT NULL,
  operation TEXT NOT NULL,
  input_data TEXT,
  output_data TEXT,
  duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
  status TEXT NOT NULL CHECK (status IN ('success', 'error', 'timeout')),
  error_message TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
```

**索引**：

```sql
CREATE INDEX idx_trace_calls_trace_created 
  ON trace_calls(trace_id, created_at);
CREATE INDEX idx_trace_calls_session_created 
  ON trace_calls(session_id, created_at DESC);
CREATE INDEX idx_trace_calls_agent_op 
  ON trace_calls(agent_name, operation);
CREATE INDEX idx_trace_calls_status_error 
  ON trace_calls(status, created_at DESC) 
  WHERE status != 'success';
```

---

### 3.4 knowledge_articles（知识库文章）

**用途**：存储用户整理到知识库的文章（含向量）。

| 字段 | 类型 | 约束 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `article_id` | TEXT | PRIMARY KEY | - | UUID v4 |
| `title` | TEXT | NOT NULL | - | 标题 |
| `url` | TEXT | UNIQUE | - | 链接（去重） |
| `content` | TEXT | NOT NULL | - | 完整内容 |
| `summary` | TEXT | - | - | AI 摘要 |
| `source` | TEXT | - | - | 来源 |
| `published_at` | TEXT | - | - | 原始发布时间（ISO 8601） |
| `embedding` | BLOB | - | - | float32 数组（1536 * 4 bytes） |
| `tags` | TEXT | NOT NULL | `'[]'` | JSON 数组 |
| `saved_by_session_id` | TEXT | FK → sessions, nullable | - | 保存来源会话 |
| `created_at` | TEXT | NOT NULL | `strftime(...)` | 入库时间 |
| `updated_at` | TEXT | NOT NULL | `strftime(...)` | 更新时间 |

**`tags` JSON 示例**：

```json
["RAG", "AI", "LLM"]
```

**创建 SQL**：

```sql
CREATE TABLE knowledge_articles (
  article_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  url TEXT UNIQUE,
  content TEXT NOT NULL,
  summary TEXT,
  source TEXT,
  published_at TEXT,
  embedding BLOB,  -- float32 数组，1536 维
  tags TEXT NOT NULL DEFAULT '[]',
  saved_by_session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
```

**索引**：

```sql
CREATE INDEX idx_articles_created 
  ON knowledge_articles(created_at DESC);
```

**说明**：

- `embedding` 用 BLOB 存 float32 数组（1536 维 × 4 字节 = 6KB）
- 向量检索使用 `sqlite-vec` 扩展（见第 8 节）
- `tags` 存 JSON 数组，查询用 `json_each()`

**标签查询示例**：

```sql
-- 查包含 "RAG" 标签的文章
SELECT * FROM knowledge_articles
WHERE EXISTS (
  SELECT 1 FROM json_each(tags) 
  WHERE value = 'RAG'
);
```

---

### 3.5 blogs（博客表）

**用途**：存储生成的博客及其编辑历史。

| 字段 | 类型 | 约束 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `blog_id` | TEXT | PRIMARY KEY | - | UUID v4 |
| `session_id` | TEXT | FK → sessions, nullable | - | 关联会话 |
| `title` | TEXT | NOT NULL | - | 标题 |
| `content` | TEXT | NOT NULL | - | Markdown 内容 |
| `topic` | TEXT | - | - | 主题 |
| `status` | TEXT | NOT NULL, CHECK IN (...) | `'draft'` | 状态 |
| `published_at` | TEXT | - | - | 发布时间（ISO 8601） |
| `edit_history` | TEXT | NOT NULL | `'[]'` | JSON 数组 |
| `metadata` | TEXT | NOT NULL | `'{}'` | JSON 字符串 |
| `created_at` | TEXT | NOT NULL | `strftime(...)` | 创建时间 |
| `updated_at` | TEXT | NOT NULL | `strftime(...)` | 更新时间 |

**`status` 枚举**：

```sql
CHECK (status IN ('draft', 'published'))
```

**`edit_history` JSON 结构**：

```json
[
  {
    "version": 1,
    "before": "原文本...",
    "after": "新文本...",
    "instruction": "更详细一些",
    "created_at": "2026-07-01T00:01:00Z"
  }
]
```

**创建 SQL**：

```sql
CREATE TABLE blogs (
  blog_id TEXT PRIMARY KEY,
  session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  topic TEXT,
  status TEXT NOT NULL DEFAULT 'draft' 
    CHECK (status IN ('draft', 'published')),
  published_at TEXT,
  edit_history TEXT NOT NULL DEFAULT '[]',
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
```

**索引**：

```sql
CREATE INDEX idx_blogs_session 
  ON blogs(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX idx_blogs_status_created 
  ON blogs(status, created_at DESC);
```

---

### 3.6 daily_reports（每日报告）

**用途**：存储每日早报记录。

| 字段 | 类型 | 约束 | 默认 | 说明 |
| --- | --- | --- | --- | --- |
| `report_id` | TEXT | PRIMARY KEY | - | UUID v4 |
| `report_date` | TEXT | NOT NULL, UNIQUE | - | 报告日期（YYYY-MM-DD） |
| `topic` | TEXT | NOT NULL | - | 搜索主题 |
| `article_ids` | TEXT | NOT NULL | `'[]'` | JSON 数组（UUID 列表） |
| `summary` | TEXT | - | - | AI 综合总结 |
| `email_sent` | INTEGER | NOT NULL, CHECK 0/1 | 0 | 是否已发送 |
| `email_sent_at` | TEXT | - | - | 发送时间 |
| `feishu_doc_url` | TEXT | - | - | 飞书云文档链接 |
| `metadata` | TEXT | NOT NULL | `'{}'` | JSON 字符串 |
| `created_at` | TEXT | NOT NULL | `strftime(...)` | 创建时间 |

**`article_ids` JSON 示例**：

```json
["550e8400-e29b-41d4-a716-446655440000", "650e8400-..."]
```

**创建 SQL**：

```sql
CREATE TABLE daily_reports (
  report_id TEXT PRIMARY KEY,
  report_date TEXT NOT NULL UNIQUE,
  topic TEXT NOT NULL,
  article_ids TEXT NOT NULL DEFAULT '[]',
  summary TEXT,
  email_sent INTEGER NOT NULL DEFAULT 0 CHECK (email_sent IN (0, 1)),
  email_sent_at TEXT,
  feishu_doc_url TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);
```

**索引**：

```sql
CREATE INDEX idx_reports_date 
  ON daily_reports(report_date DESC);
```

---

## 4. 索引设计

### 4.1 索引汇总

| 表 | 索引名 | 字段 | 类型 | 用途 |
| --- | --- | --- | --- | --- |
| sessions | idx_sessions_user_active | (user_id, last_active DESC) | B-Tree | 列表查询 |
| sessions | idx_sessions_archived_active | (is_archived, last_active DESC) | B-Tree | 过滤归档 |
| messages | idx_messages_session_created | (session_id, created_at) | B-Tree | 加载历史 |
| messages | idx_messages_trace | (trace_id) | B-Tree | 追踪关联 |
| trace_calls | idx_trace_calls_trace_created | (trace_id, created_at) | B-Tree | 追踪排序 |
| trace_calls | idx_trace_calls_session_created | (session_id, created_at DESC) | B-Tree | 会话追踪 |
| trace_calls | idx_trace_calls_agent_op | (agent_name, operation) | B-Tree | 统计 |
| trace_calls | idx_trace_calls_status_error | (status, created_at) WHERE status!='success' | 部分索引 | 错误查询 |
| knowledge_articles | idx_articles_created | (created_at DESC) | B-Tree | 列表 |
| blogs | idx_blogs_session | (session_id) WHERE session_id IS NOT NULL | 部分索引 | 会话关联 |
| blogs | idx_blogs_status_created | (status, created_at DESC) | B-Tree | 列表 |
| daily_reports | idx_reports_date | (report_date DESC) | B-Tree | 列表 |

### 4.2 向量检索索引

**libSQL 没有内置的 HNSW，但 sqlite-vec 提供 KNN 检索**：

```sql
-- 加载 sqlite-vec 扩展（每次连接时）
-- 在 Python 客户端自动加载
```

详见第 8.2 节。

---

## 5. 约束与外键

### 5.1 主键约束

所有表使用 UUID v4 字符串作为主键（应用层生成）：

```python
import uuid
session_id = str(uuid.uuid4())
```

### 5.2 外键约束

| 外键 | 引用 | 级联策略 |
| --- | --- | --- |
| messages.session_id | sessions.session_id | ON DELETE CASCADE |
| trace_calls.session_id | sessions.session_id | ON DELETE CASCADE |
| trace_calls.message_id | messages.message_id | ON DELETE SET NULL |
| knowledge_articles.saved_by_session_id | sessions.session_id | ON DELETE SET NULL |
| blogs.session_id | sessions.session_id | ON DELETE SET NULL |

**注意**：SQLite 外键默认**未启用**，需在每次连接时执行：

```sql
PRAGMA foreign_keys = ON;
```

### 5.3 CHECK 约束

| 表 | 字段 | 约束 |
| --- | --- | --- |
| sessions | message_count | >= 0 |
| sessions | is_archived | IN (0, 1) |
| messages | role | IN ('user', 'assistant', 'system') |
| messages | tokens | >= 0 |
| trace_calls | duration_ms | >= 0 |
| trace_calls | status | IN ('success', 'error', 'timeout') |
| blogs | status | IN ('draft', 'published') |
| daily_reports | email_sent | IN (0, 1) |

---

## 6. 触发器

SQLite 触发器使用内联语法（无 plpgsql）。

### 6.1 自动更新会话统计

```sql
-- 插入消息时 +1
CREATE TRIGGER trigger_update_session_stats_on_insert
AFTER INSERT ON messages
FOR EACH ROW
BEGIN
  UPDATE sessions
  SET 
    last_active = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
    message_count = message_count + 1
  WHERE session_id = NEW.session_id;
END;

-- 删除消息时 -1
CREATE TRIGGER trigger_update_session_stats_on_delete
AFTER DELETE ON messages
FOR EACH ROW
BEGIN
  UPDATE sessions
  SET 
    message_count = MAX(message_count - 1, 0),
    last_active = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
  WHERE session_id = OLD.session_id;
END;
```

### 6.2 自动更新 updated_at

```sql
CREATE TRIGGER trigger_knowledge_articles_updated_at
BEFORE UPDATE ON knowledge_articles
FOR EACH ROW
BEGIN
  UPDATE knowledge_articles
  SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
  WHERE article_id = OLD.article_id;
END;

CREATE TRIGGER trigger_blogs_updated_at
BEFORE UPDATE ON blogs
FOR EACH ROW
BEGIN
  UPDATE blogs
  SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
  WHERE blog_id = OLD.blog_id;
END;
```

**注意**：SQLite 的 `BEFORE UPDATE` 触发器中修改 `NEW` 列需要使用 `UPDATE ... SET` 而非 `NEW.column = value`（后者在 SQLite 中**不**生效）。

### 6.3 上下文压缩时的 session metadata 更新

```sql
CREATE TRIGGER trigger_update_session_metadata_on_compress
AFTER INSERT ON messages
FOR EACH ROW
WHEN NEW.role = 'system' 
  AND json_extract(NEW.metadata, '$.compressed') = 1
BEGIN
  UPDATE sessions
  SET metadata = json_set(
    json_set(
      metadata, 
      '$.total_tokens', 
      NEW.tokens
    ),
    '$.compressed_at',
    NEW.created_at
  )
  WHERE session_id = NEW.session_id;
END;
```

---

## 7. 安全策略（替代 RLS）

### 7.1 libSQL 无内置 RLS

Turso libSQL 不支持 Row Level Security。鉴权在**应用层**实现：

1. **数据库 Token**：Turso 提供 `authToken`，只有后端持有
2. **API Key 鉴权**：所有 API 请求需 `Authorization: Bearer <KEY>`
3. **单用户场景**：无多用户隔离需求，简化处理

### 7.2 应用层鉴权

```python
# common.py
import os
from fastapi import Header, HTTPException

API_KEY = os.environ["HARNESS_API_KEY"]

async def verify_api_key(authorization: str = Header(...)):
    if authorization != f"Bearer {API_KEY}":
        raise HTTPException(status_code=401, detail="Invalid API key")
```

### 7.3 客户端隔离

**前端**：直接调后端 API（不直连 DB）

**后端**：唯一持有 `TURSO_AUTH_TOKEN` 的服务

**Git**：`.env` 加入 `.gitignore`，Token 不进版本控制

### 7.4 未来多用户

若扩展为多用户，需在 Python 层为每个查询加上 `WHERE user_id = ?` 条件。

---

## 8. 性能与扩展

### 8.1 性能优化

#### 8.1.1 WAL 模式（写性能）

```sql
PRAGMA journal_mode = WAL;        -- 写并发更好
PRAGMA synchronous = NORMAL;      -- 略降安全性换性能
PRAGMA cache_size = -64000;       -- 64MB 缓存
PRAGMA temp_store = MEMORY;
```

#### 8.1.2 查询优化

- 高频字段都建索引
- 复合索引遵循最左前缀
- 避免 `SELECT *`，只查必要列

#### 8.1.3 JSON 性能

- `json_extract()` 比 `LIKE '%...%'` 快
- 必要时建表达式索引：

```sql
CREATE INDEX idx_articles_first_tag 
  ON knowledge_articles(json_extract(tags, '$[0]'));
```

### 8.2 向量检索（sqlite-vec）

#### 8.2.1 安装扩展

Turso 已内置 `sqlite-vec`，本地开发用 `pip install sqlite-vec`。

#### 8.2.2 向量编码

```python
import struct

def encode_vector(vec: list[float]) -> bytes:
    """float32 列表 → BLOB（little-endian）"""
    return struct.pack(f'{len(vec)}f', *vec)

def decode_vector(blob: bytes) -> list[float]:
    """BLOB → float32 列表"""
    n = len(blob) // 4
    return list(struct.unpack(f'{n}f', blob))
```

#### 8.2.3 KNN 查询

```sql
-- 余弦距离 KNN（Top K）
SELECT 
  article_id,
  title,
  vec_distance_cosine(embedding, ?) AS distance
FROM knowledge_articles
WHERE embedding IS NOT NULL
ORDER BY distance
LIMIT ?;
```

> sqlite-vec 提供 `vec_distance_cosine()`、`vec_distance_l2()` 等函数。

#### 8.2.4 ANN 加速（数据量大时）

sqlite-vec 自动优化小数据集的 KNN；数据 > 1 万条时考虑用 `vec0` 虚拟表。

```sql
-- 创建 vec0 虚拟表（ANN 索引）
CREATE VIRTUAL TABLE vec_articles USING vec0(
  article_id TEXT PRIMARY KEY,
  embedding float[1536]
);
```

> 当前预估 500-2000 篇文章，无需 ANN，普通 KNN 足够。

### 8.3 Turso 边缘复制

```python
# 写入主区域
client = libsql.connect("harness-db.turso.io", auth_token=TOKEN)
# 边缘读副本（只读）
reader = libsql.connect("harness-db-eu.turso.io", auth_token=TOKEN, sync_url=...)
```

> 单用户场景，暂不启用。

### 8.4 扩展策略

#### 8.4.1 归档老旧 trace

```sql
-- 6 个月前的 trace_calls 备份到 _archive 表
CREATE TABLE trace_calls_archive AS SELECT * FROM trace_calls WHERE 1=0;

-- 定期归档
INSERT INTO trace_calls_archive 
SELECT * FROM trace_calls 
WHERE created_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-6 months');

DELETE FROM trace_calls 
WHERE created_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-6 months');
```

---

## 9. 迁移脚本

### 9.1 完整初始化脚本

```sql
-- ====================================================
-- 个人 AI 知识助手 - Turso libSQL 数据库初始化
-- ====================================================

PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;

-- ====================================================
-- 1. sessions 表
-- ====================================================
CREATE TABLE IF NOT EXISTS sessions (
  session_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  title TEXT NOT NULL DEFAULT '新对话',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  last_active TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  message_count INTEGER NOT NULL DEFAULT 0 CHECK (message_count >= 0),
  is_archived INTEGER NOT NULL DEFAULT 0 CHECK (is_archived IN (0, 1)),
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_sessions_user_active 
  ON sessions(user_id, last_active DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_archived_active 
  ON sessions(is_archived, last_active DESC);

-- ====================================================
-- 2. messages 表
-- ====================================================
CREATE TABLE IF NOT EXISTS messages (
  message_id TEXT PRIMARY KEY,
  session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content TEXT NOT NULL,
  trace_id TEXT NOT NULL,
  tokens INTEGER NOT NULL DEFAULT 0 CHECK (tokens >= 0),
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_messages_session_created 
  ON messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_trace 
  ON messages(trace_id);

-- ====================================================
-- 3. trace_calls 表
-- ====================================================
CREATE TABLE IF NOT EXISTS trace_calls (
  call_id TEXT PRIMARY KEY,
  trace_id TEXT NOT NULL,
  session_id TEXT NOT NULL REFERENCES sessions(session_id) ON DELETE CASCADE,
  message_id TEXT REFERENCES messages(message_id) ON DELETE SET NULL,
  agent_name TEXT NOT NULL,
  operation TEXT NOT NULL,
  input_data TEXT,
  output_data TEXT,
  duration_ms INTEGER NOT NULL CHECK (duration_ms >= 0),
  status TEXT NOT NULL CHECK (status IN ('success', 'error', 'timeout')),
  error_message TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_trace_calls_trace_created 
  ON trace_calls(trace_id, created_at);
CREATE INDEX IF NOT EXISTS idx_trace_calls_session_created 
  ON trace_calls(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_trace_calls_agent_op 
  ON trace_calls(agent_name, operation);
CREATE INDEX IF NOT EXISTS idx_trace_calls_status_error 
  ON trace_calls(status, created_at DESC) 
  WHERE status != 'success';

-- ====================================================
-- 4. knowledge_articles 表
-- ====================================================
CREATE TABLE IF NOT EXISTS knowledge_articles (
  article_id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  url TEXT UNIQUE,
  content TEXT NOT NULL,
  summary TEXT,
  source TEXT,
  published_at TEXT,
  embedding BLOB,
  tags TEXT NOT NULL DEFAULT '[]',
  saved_by_session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_articles_created 
  ON knowledge_articles(created_at DESC);

-- ====================================================
-- 5. blogs 表
-- ====================================================
CREATE TABLE IF NOT EXISTS blogs (
  blog_id TEXT PRIMARY KEY,
  session_id TEXT REFERENCES sessions(session_id) ON DELETE SET NULL,
  title TEXT NOT NULL,
  content TEXT NOT NULL,
  topic TEXT,
  status TEXT NOT NULL DEFAULT 'draft' 
    CHECK (status IN ('draft', 'published')),
  published_at TEXT,
  edit_history TEXT NOT NULL DEFAULT '[]',
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
  updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_blogs_session 
  ON blogs(session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_blogs_status_created 
  ON blogs(status, created_at DESC);

-- ====================================================
-- 6. daily_reports 表
-- ====================================================
CREATE TABLE IF NOT EXISTS daily_reports (
  report_id TEXT PRIMARY KEY,
  report_date TEXT NOT NULL UNIQUE,
  topic TEXT NOT NULL,
  article_ids TEXT NOT NULL DEFAULT '[]',
  summary TEXT,
  email_sent INTEGER NOT NULL DEFAULT 0 CHECK (email_sent IN (0, 1)),
  email_sent_at TEXT,
  feishu_doc_url TEXT,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
);

CREATE INDEX IF NOT EXISTS idx_reports_date 
  ON daily_reports(report_date DESC);

-- ====================================================
-- 7. 触发器
-- ====================================================

-- 会话统计（插入）
CREATE TRIGGER IF NOT EXISTS trigger_update_session_stats_on_insert
AFTER INSERT ON messages
FOR EACH ROW
BEGIN
  UPDATE sessions
  SET 
    last_active = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
    message_count = message_count + 1
  WHERE session_id = NEW.session_id;
END;

-- 会话统计（删除）
CREATE TRIGGER IF NOT EXISTS trigger_update_session_stats_on_delete
AFTER DELETE ON messages
FOR EACH ROW
BEGIN
  UPDATE sessions
  SET 
    message_count = MAX(message_count - 1, 0),
    last_active = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
  WHERE session_id = OLD.session_id;
END;

-- knowledge_articles updated_at
CREATE TRIGGER IF NOT EXISTS trigger_knowledge_articles_updated_at
BEFORE UPDATE ON knowledge_articles
FOR EACH ROW
BEGIN
  UPDATE knowledge_articles
  SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
  WHERE article_id = OLD.article_id;
END;

-- blogs updated_at
CREATE TRIGGER IF NOT EXISTS trigger_blogs_updated_at
BEFORE UPDATE ON blogs
FOR EACH ROW
BEGIN
  UPDATE blogs
  SET updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
  WHERE blog_id = OLD.blog_id;
END;
```

### 9.2 种子数据（可选）

```sql
-- 插入示例 session
INSERT INTO sessions (session_id, user_id, title)
VALUES (
  'example-uuid-1',
  'default-user',
  '示例会话：RAG 入门'
);
```

### 9.3 回滚脚本

```sql
DROP TABLE IF EXISTS daily_reports;
DROP TABLE IF EXISTS blogs;
DROP TABLE IF EXISTS knowledge_articles;
DROP TABLE IF EXISTS trace_calls;
DROP TABLE IF EXISTS messages;
DROP TABLE IF EXISTS sessions;
```

---

## 10. Python 客户端示例

### 10.1 安装

```bash
pip install libsql-client
# 或
pip install libsql
```

### 10.2 客户端封装（推荐放在 `common.py`）

```python
# common.py
import os
import libsql
from contextlib import contextmanager

TURSO_URL = os.environ["TURSO_DATABASE_URL"]      # libsql://xxx.turso.io
TURSO_TOKEN = os.environ["TURSO_AUTH_TOKEN"]      # Turso 生成的 token

@contextmanager
def get_db():
    """数据库连接上下文管理器"""
    conn = libsql.connect(TURSO_URL, auth_token=TURSO_TOKEN)
    conn.execute("PRAGMA foreign_keys = ON;")
    try:
        yield conn
    finally:
        conn.close()
```

### 10.3 CRUD 示例

```python
# agents/knowledge_agent.py
from common import get_db
import uuid
import json

def create_article(title, url, content, tags):
    """创建文章"""
    with get_db() as db:
        article_id = str(uuid.uuid4())
        db.execute(
            """
            INSERT INTO knowledge_articles 
              (article_id, title, url, content, tags)
            VALUES (?, ?, ?, ?, ?)
            """,
            [article_id, title, url, content, json.dumps(tags)]
        )
        db.commit()
        return article_id

def get_article(article_id):
    """获取文章"""
    with get_db() as db:
        result = db.execute(
            "SELECT * FROM knowledge_articles WHERE article_id = ?",
            [article_id]
        ).fetchone()
        
        if not result:
            return None
        
        # result 是 tuple，转 dict
        keys = ['article_id', 'title', 'url', 'content', 'summary',
                'source', 'published_at', 'embedding', 'tags',
                'saved_by_session_id', 'created_at', 'updated_at']
        article = dict(zip(keys, result))
        article['tags'] = json.loads(article['tags'])
        return article
```

### 10.4 会话上下文加载

```python
# common.py
def build_context(session_id, max_tokens=100_000):
    """智能构建上下文：超长就压缩，否则全传"""
    with get_db() as db:
        rows = db.execute(
            """
            SELECT message_id, role, content, tokens
            FROM messages
            WHERE session_id = ?
            ORDER BY created_at ASC
            """,
            [session_id]
        ).fetchall()
    
    messages = [
        {"message_id": r[0], "role": r[1], "content": r[2], "tokens": r[3]}
        for r in rows
    ]
    
    total_tokens = sum(m["tokens"] for m in messages)
    
    if total_tokens <= max_tokens:
        return messages  # 不超 → 全部传
    
    # 超阈值 → 压缩
    return compress_old_messages(messages, keep_recent=10)
```

### 10.5 上下文压缩

```python
def compress_old_messages(messages, keep_recent=10):
    """压缩老消息为摘要（不丢记忆的关键）"""
    from common import llm  # DeepSeek client
    
    recent = messages[-keep_recent:]
    old = messages[:-keep_recent]
    
    if not old:
        return recent
    
    # LLM 总结
    summary = llm.summarize(old)
    
    # 插入 system 消息
    summary_msg = {
        "message_id": str(uuid.uuid4()),
        "role": "system",
        "content": f"## 前面对话的摘要\n{summary}",
        "tokens": count_tokens(summary),
    }
    
    with get_db() as db:
        # 删除老消息
        old_ids = [m["message_id"] for m in old]
        placeholders = ",".join("?" * len(old_ids))
        db.execute(
            f"DELETE FROM messages WHERE message_id IN ({placeholders})",
          old_ids
        )
        
        # 插入摘要
        db.execute(
            """
            INSERT INTO messages (message_id, session_id, role, content, trace_id, tokens, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [
                summary_msg["message_id"],
                recent[0]["session_id"] if recent else None,
                "system",
                summary_msg["content"],
                "summary",
                summary_msg["tokens"],
                json.dumps({"compressed": True})
            ]
        )
        db.commit()
    
    return [summary_msg] + recent
```

### 10.6 Trace 记录

```python
import time
import uuid
import json

class TraceRecorder:
    """trace 记录器（上下文管理器）"""
    
    def __init__(self, session_id, agent_name, operation, input_data=None):
        self.call_id = str(uuid.uuid4())
        self.trace_id = str(uuid.uuid4())  # 每个问答一个新 trace
        self.session_id = session_id
        self.agent_name = agent_name
        self.operation = operation
        self.input_data = input_data
        self.start_time = None
    
    def __enter__(self):
        self.start_time = time.time()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = int((time.time() - self.start_time) * 1000)
        
        if exc_type is None:
            status = "success"
            error_message = None
        elif exc_type is TimeoutError:
            status = "timeout"
            error_message = str(exc_val)
        else:
            status = "error"
            error_message = str(exc_val)
        
        with get_db() as db:
            db.execute(
                """
                INSERT INTO trace_calls
                  (call_id, trace_id, session_id, agent_name, operation,
                   input_data, output_data, duration_ms, status, error_message)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    self.call_id, self.trace_id, self.session_id,
                    self.agent_name, self.operation,
                    json.dumps(self.input_data) if self.input_data else None,
                    None,  # output_data 由调用方手动设置
                    duration_ms, status, error_message
                ]
            )
            db.commit()

# 使用示例
with TraceRecorder(session_id, "search", "search_query", {"query": "..."}) as trace:
    results = tavily.search(...)
    trace.output_data = {"results": results}  # 记录输出
```

### 10.7 向量检索

```python
def encode_vector(vec: list[float]) -> bytes:
    """float32 列表 → BLOB"""
    import struct
    return struct.pack(f'{len(vec)}f', *vec)

def vector_search(query_embedding: list[float], top_k: int = 5, threshold: float = 0.7):
    """语义检索"""
    query_blob = encode_vector(query_embedding)
    
    with get_db() as db:
        rows = db.execute(
            """
            SELECT 
                article_id, title, content, summary, url,
                1 - vec_distance_cosine(embedding, ?) AS score
            FROM knowledge_articles
            WHERE embedding IS NOT NULL
              AND 1 - vec_distance_cosine(embedding, ?) > ?
            ORDER BY vec_distance_cosine(embedding, ?)
            LIMIT ?
            """,
            [query_blob, query_blob, threshold, query_blob, top_k]
        ).fetchall()
    
    return [
        {
            "article_id": r[0], "title": r[1], "content": r[2],
            "summary": r[3], "url": r[4], "score": r[5]
        }
        for r in rows
    ]
```

---

## 11. 数据生命周期

### 11.1 保留策略

| 数据类型 | 保留期 | 归档策略 |
| --- | --- | --- |
| sessions | 永久 | 不归档 |
| messages | 永久 | 不归档 |
| trace_calls | 6 个月 | 定期清理 |
| knowledge_articles | 永久 | 不归档 |
| blogs | 永久 | 不归档 |
| daily_reports | 1 年 | 定期清理 |

### 11.2 清理脚本

```sql
-- 清理 6 个月前的 trace_calls
DELETE FROM trace_calls
WHERE created_at < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-6 months');

-- 清理 1 年前的 daily_reports
DELETE FROM daily_reports
WHERE report_date < strftime('%Y-%m-%dT%H:%M:%fZ', 'now', '-1 year');
```

### 11.3 备份策略

- Turso 自动每日备份（Pro 版保留 30 天 / 免费版保留 7 天）
- 关键数据可手动导出：

```bash
turso db shell harness-db < schema.sql
turso db dump harness-db > backup-$(date +%Y%m%d).sql
```

---

## 12. 附录

### 12.1 表名约定

| 类别 | 命名 | 例子 |
| --- | --- | --- |
| 核心实体 | 复数名词 | `sessions`, `messages` |
| 关联表 | 单数实体名 | `trace_calls`（不是 `traces`） |
| 时间事件 | `事件_对象` | `daily_reports` |

**不使用**前缀（如 `ai_sessions`）——表名已具备语义。

### 12.2 字段命名

| 类别 | 命名 | 例子 |
| --- | --- | --- |
| 主键 | `{table}_id` | `session_id`, `message_id` |
| 外键 | `{referenced}_id` | `session_id`, `message_id` |
| 时间 | `created_at`, `updated_at`, `{action}_at` | `last_active` |
| 布尔 | `is_{state}`（存 0/1） | `is_archived` |
| 计数 | `{noun}_count` | `message_count` |
| 枚举 | 单数名词 | `role`, `status` |
| 扩展 | `metadata`（TEXT JSON） | - |

### 12.3 关键 SQL 示例

#### 查询会话总 token 数

```sql
SELECT 
  s.session_id,
  s.title,
  COALESCE(SUM(m.tokens), 0) AS total_tokens,
  s.message_count
FROM sessions s
LEFT JOIN messages m ON m.session_id = s.session_id
WHERE s.session_id = ?
GROUP BY s.session_id, s.title, s.message_count;
```

#### 一次问答的完整追踪

```sql
SELECT 
  tc.call_id,
  tc.agent_name,
  tc.operation,
  tc.input_data,
  tc.output_data,
  tc.duration_ms,
  tc.status,
  tc.error_message,
  tc.created_at,
  m.role AS message_role
FROM trace_calls tc
LEFT JOIN messages m ON m.message_id = tc.message_id
WHERE tc.trace_id = ?
ORDER BY tc.created_at ASC;
```

#### 语义检索 Top K

```sql
SELECT 
  article_id,
  title,
  summary,
  url,
  1 - vec_distance_cosine(embedding, ?) AS score
FROM knowledge_articles
WHERE embedding IS NOT NULL
  AND 1 - vec_distance_cosine(embedding, ?) > ?
ORDER BY vec_distance_cosine(embedding, ?)
LIMIT ?;
```

#### 按标签查询文章

```sql
SELECT * FROM knowledge_articles
WHERE EXISTS (
  SELECT 1 FROM json_each(tags) 
  WHERE json_each.value = 'RAG'
);
```

### 12.4 .env 配置

```bash
# Turso libSQL
TURSO_DATABASE_URL=libsql://harness-db-xxx.turso.io
TURSO_AUTH_TOKEN=xxx

# LLM
DEEPSEEK_API_KEY=sk-xxx

# 搜索
TAVILY_API_KEY=tvly-xxx

# 邮件
RESEND_API_KEY=re_xxx

# 应用
HARNESS_API_KEY=your-api-key-here
USER_ID=default-user   # 单用户场景的固定 user_id
```

### 12.5 与 PRD/SRS 的对应关系

| PRD/SRS 概念 | DB.md 实现 |
| --- | --- |
| 3 张表（会话/消息/追踪） | `sessions` / `messages` / `trace_calls` |
| 每对问答共享 trace_id | `messages.trace_id` 字段 |
| 级联删除会话 | `ON DELETE CASCADE` |
| RLS | 移到应用层（libSQL 无内置） |
| 100K token 压缩 | `build_context()` + `compress_old_messages()` |
| 警告分档 | `total_tokens` 字段 + 应用层判断 |

### 12.6 变更历史

| 版本 | 日期 | 变更 |
| --- | --- | --- |
| v0.1.0 | 2026-07-01 | 初稿 |
| v0.2.0 | 2026-07-01 | 改用 Turso libSQL（与 PRD 对齐） |
