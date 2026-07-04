-- ==========================================================
-- harness schema.sql
-- Turso libSQL（SQLite 兼容）
-- 3 表：sessions（顶层） / messages（中层） / trace_calls（底层）
-- 详细文档：DB.md
-- ==========================================================

-- ---------- 1. sessions 会话表 ----------
CREATE TABLE IF NOT EXISTS sessions (
    session_id      TEXT PRIMARY KEY,                     -- UUID
    title           TEXT NOT NULL DEFAULT '新会话',        -- 会话标题（首条消息自动生成）
    created_at      TEXT NOT NULL,                         -- ISO 8601
    last_active     TEXT NOT NULL,                         -- ISO 8601（用于排序）
    total_tokens    INTEGER NOT NULL DEFAULT 0,            -- 累计 token
    message_count   INTEGER NOT NULL DEFAULT 0,            -- 消息条数
    is_archived     INTEGER NOT NULL DEFAULT 0,            -- 0/1
    summary         TEXT                                   -- 压缩后的摘要（可选）
);

CREATE INDEX IF NOT EXISTS idx_sessions_last_active ON sessions(last_active DESC);
CREATE INDEX IF NOT EXISTS idx_sessions_archived    ON sessions(is_archived);


-- ---------- 2. messages 消息表 ----------
-- 一对 user+assistant 共享一个 trace_id
CREATE TABLE IF NOT EXISTS messages (
    message_id      TEXT PRIMARY KEY,                     -- UUID
    session_id      TEXT NOT NULL,                         -- 关联会话
    role            TEXT NOT NULL,                         -- 'user' / 'assistant' / 'system'
    content         TEXT NOT NULL,                         -- 消息内容
    trace_id        TEXT,                                  -- 关联 trace_calls（user/assistant 共享）
    tokens          INTEGER NOT NULL DEFAULT 0,            -- 本条 token 数
    meta            TEXT,                                  -- JSON：{knowledge_ids:[], article_ids:[]} 侧效应
    created_at      TEXT NOT NULL,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_session  ON messages(session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_messages_trace    ON messages(trace_id);


-- ---------- 3. trace_calls 追踪表 ----------
-- 记录一次问答中所有 agent / 工具调用
CREATE TABLE IF NOT EXISTS trace_calls (
    call_id         TEXT PRIMARY KEY,                     -- UUID
    trace_id        TEXT NOT NULL,                         -- 关联一对问答
    agent_name      TEXT NOT NULL,                         -- 'master' / 'chat' / 'knowledge' / ...
    operation       TEXT NOT NULL,                         -- 'chat' / 'search' / 'rewrite' / ...
    input           TEXT,                                  -- JSON 序列化
    output          TEXT,                                  -- JSON 序列化
    duration_ms     INTEGER NOT NULL DEFAULT 0,
    status          TEXT NOT NULL DEFAULT 'success',       -- 'success' / 'failed'
    error_message   TEXT,
    created_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_traces_trace  ON trace_calls(trace_id);
CREATE INDEX IF NOT EXISTS idx_traces_agent  ON trace_calls(agent_name, created_at DESC);


-- ---------- 4. knowledge_articles 知识库文章（M2 用，M1 先建好占位） ----------
CREATE TABLE IF NOT EXISTS knowledge_articles (
    article_id      TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    url             TEXT,
    content         TEXT NOT NULL,                          -- 原文（用户要求存原文，用于父子索引回溯）
    summary         TEXT,
    source          TEXT NOT NULL DEFAULT 'Manual',        -- 'Tavily' / 'Feishu' / 'Manual'
    tags            TEXT NOT NULL DEFAULT '[]',            -- JSON 数组字符串
    status          TEXT NOT NULL DEFAULT 'draft',         -- 'draft' / 'published' / 'archived'
    view_count      INTEGER NOT NULL DEFAULT 0,
    published_at    TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_kb_status    ON knowledge_articles(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_kb_source    ON knowledge_articles(source);


-- ---------- 5. knowledge_chunks 知识库切片（父子索引 + 向量 + 元数据） ----------
-- 每个 chunk 引用父文章（article_id），并存储 embedding 和关键词
CREATE TABLE IF NOT EXISTS knowledge_chunks (
    chunk_id        TEXT PRIMARY KEY,                       -- UUID
    article_id      TEXT NOT NULL,                          -- 父文章 ID（便签）
    chunk_index     INTEGER NOT NULL,                       -- 在父文章中的顺序（0-based）
    chunk_text      TEXT NOT NULL,                          -- 切片内容
    embedding       BLOB,                                   -- float32 数组（1024 维 = 4096 bytes）
    -- 位置信息（用于回溯到原文）
    start_pos       INTEGER NOT NULL,                       -- 起始字符位置
    end_pos         INTEGER NOT NULL,                       -- 结束字符位置
    chunk_size      INTEGER NOT NULL,                       -- 字符长度
    -- 元数据索引
    keywords        TEXT NOT NULL DEFAULT '[]',            -- JSON 数组，BM25 关键词检索用
    created_at      TEXT NOT NULL,
    FOREIGN KEY (article_id) REFERENCES knowledge_articles(article_id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_kc_article    ON knowledge_chunks(article_id, chunk_index);
CREATE INDEX IF NOT EXISTS idx_kc_keywords   ON knowledge_chunks(keywords);


-- ---------- 6. articles 用户生成的博客文章 ----------
CREATE TABLE IF NOT EXISTS articles (
    article_id      TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'draft',         -- 'draft' / 'published'
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status, created_at DESC);


-- ---------- 7. agent_tasks 后台任务追踪 ----------
CREATE TABLE IF NOT EXISTS agent_tasks (
    task_id          TEXT PRIMARY KEY,
    session_id       TEXT,
    trace_id         TEXT,
    kind             TEXT NOT NULL DEFAULT 'chat',
    status           TEXT NOT NULL DEFAULT 'running',      -- pending/running/completed/failed/cancelled
    title            TEXT NOT NULL,
    current_step     TEXT,
    detail           TEXT,
    progress_json    TEXT NOT NULL DEFAULT '[]',           -- [{key,label,status,detail,...}]
    result_json      TEXT,
    error_message    TEXT,
    can_interrupt    INTEGER NOT NULL DEFAULT 1,
    started_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    finished_at      TEXT,
    FOREIGN KEY (session_id) REFERENCES sessions(session_id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_tasks_status       ON agent_tasks(status, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_session      ON agent_tasks(session_id, updated_at DESC);


-- ---------- 8. app_cache 轻量缓存 ----------
CREATE TABLE IF NOT EXISTS app_cache (
    cache_key        TEXT PRIMARY KEY,
    scope            TEXT NOT NULL,
    payload          TEXT NOT NULL,
    expires_at       TEXT NOT NULL,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cache_scope        ON app_cache(scope, expires_at);


-- ---------- 9. digest_subscriptions 定时文章订阅 ----------
CREATE TABLE IF NOT EXISTS digest_subscriptions (
    subscription_id   TEXT PRIMARY KEY,
    email             TEXT NOT NULL,
    query             TEXT NOT NULL,
    schedule_cron     TEXT NOT NULL DEFAULT '0 9 * * *',
    timezone          TEXT NOT NULL DEFAULT 'Asia/Shanghai',
    max_results       INTEGER NOT NULL DEFAULT 5,
    enabled           INTEGER NOT NULL DEFAULT 1,
    send_to_feishu    INTEGER NOT NULL DEFAULT 1,
    send_email        INTEGER NOT NULL DEFAULT 1,
    tags_json         TEXT NOT NULL DEFAULT '[]',
    last_run_at       TEXT,
    last_status       TEXT,
    last_error        TEXT,
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_digest_subscriptions_enabled
    ON digest_subscriptions(enabled, updated_at DESC);
