"""
common.py
==========================================================
项目级基础库（所有 agent 共享），符合 project_memory 硬约束：
- common.py 只放基础库，不放 agent 业务逻辑
- agent 文件用 `from common import *` 引入
- agent 自己的依赖（如 tavily、resend）在 agent 文件内单独 import
==========================================================
"""

from __future__ import annotations  # 启用 PEP 563 注解延迟求值，兼容 Python 3.9

# ---------- 1. 路径 + 环境 ----------
import os
import sys
import logging
from pathlib import Path
from dotenv import load_dotenv

# 加载项目根目录下的 .env
ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

# ---------- 2. 全局配置 ----------
class Config:
    """所有配置常量集中在这里，方便统一调整"""

    # LLM（DeepSeek，OpenAI 兼容协议）
    LLM_API_KEY    = os.getenv("API_KEY", "")
    LLM_BASE_URL   = os.getenv("BASE_URL", "https://api.deepseek.com")
    LLM_MODEL      = os.getenv("MODEL_NAME", "deepseek-chat")
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.7"))
    LLM_MAX_TOKENS  = int(os.getenv("LLM_MAX_TOKENS", "2048"))
    LLM_TIMEOUT_S   = int(os.getenv("LLM_TIMEOUT_S", "60"))

    # Turso libSQL
    TURSO_URL    = os.getenv("TURSO_URL", "")
    TURSO_TOKEN  = os.getenv("TURSO_TOKEN", "")

    # 上下文压缩阈值（与 SRS / PRD 对齐）
    CONTEXT_WINDOW_TOKENS    = 100_000   # DeepSeek 上下文窗口
    CONTEXT_WARN_RATIO       = 0.30      # 30K 黄色提示
    CONTEXT_COMPRESS_RATIO   = 0.50      # 50K 橙色 + 立即压缩按钮
    CONTEXT_FORCE_RATIO      = 1.00      # 100K 强制压缩
    CONTEXT_KEEP_RECENT      = 10        # 压缩后保留最近 N 条

    # 内部 API Key（前端 → 后端鉴权）
    INTERNAL_API_KEY = os.getenv("INTERNAL_API_KEY", "dev-key-change-me")

    # 业务服务
    TAVILY_API_KEY   = os.getenv("TAVILY_API_KEY", "")
    FEISHU_APP_ID    = os.getenv("FEISHU_APP_ID", "")
    FEISHU_APP_SECRET= os.getenv("FEISHU_APP_SECRET", "")
    RESEND_API_KEY   = os.getenv("RESEND_API_KEY", "")

    # 阿里云 DashScope（Embedding）
    DASHSCOPE_API_KEY  = os.getenv("DASHSCOPE_API_KEY", "")
    EMBEDDING_MODEL    = os.getenv("EMBEDDING_MODEL", "text-embedding-v4")
    EMBEDDING_DIM      = int(os.getenv("EMBEDDING_DIM", "1024"))
    EMBEDDING_BATCH    = int(os.getenv("EMBEDDING_BATCH_SIZE", "10"))
    DASHSCOPE_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"


# ---------- 3. 日志 ----------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("harness")


# ---------- 4. 统一响应格式 ----------
def ok(data: dict | list | None = None, message: str = "success") -> dict:
    """成功响应：{code: 0, message, data, request_id}"""
    import uuid
    return {"code": 0, "message": message, "data": data or {}, "request_id": str(uuid.uuid4())[:8]}


def err(code: int, message: str, error_type: str = "business", details: dict | None = None) -> dict:
    """业务错误响应：{code, message, error: {type, details}, request_id}"""
    import uuid
    return {
        "code": code,
        "message": message,
        "error": {"type": error_type, "details": details or {}},
        "request_id": str(uuid.uuid4())[:8],
    }


# ---------- 5. 错误码（与 API.md 5 节对齐） ----------
class E:
    # 4xxx 业务
    SESSION_NOT_FOUND  = 4001
    MESSAGE_TOO_LONG   = 4005
    TOKEN_EXCEEDED     = 4006
    REWRITE_TOO_LONG   = 4007
    # 5xxx 系统
    LLM_FAILED         = 5001
    DB_FAILED          = 5002
    EXTERNAL_FAILED    = 5003


# ---------- 6. LLM 客户端（OpenAI 兼容，用于 DeepSeek）----------
from openai import OpenAI

def get_llm() -> OpenAI:
    """返回 OpenAI 客户端实例（DeepSeek 兼容协议）"""
    if not Config.LLM_API_KEY:
        raise RuntimeError("API_KEY 未配置，请在 .env 填写")
    return OpenAI(
        api_key=Config.LLM_API_KEY,
        base_url=Config.LLM_BASE_URL,
        timeout=Config.LLM_TIMEOUT_S,
    )


def llm_chat(messages: list[dict], **kwargs) -> dict:
    """
    统一 LLM 调用入口。
    messages: [{"role": "...", "content": "..."}, ...]
    返回: {"content": "...", "usage": {...}, "model": "..."}
    """
    client = get_llm()
    params = {
        "model":      kwargs.get("model",      Config.LLM_MODEL),
        "messages":   messages,
        "temperature":kwargs.get("temperature",Config.LLM_TEMPERATURE),
        "max_tokens": kwargs.get("max_tokens", Config.LLM_MAX_TOKENS),
    }
    # stream 模式：返回生成器
    if kwargs.get("stream"):
        params["stream"] = True
        return client.chat.completions.create(**params)

    resp = client.chat.completions.create(**params)
    choice = resp.choices[0]
    return {
        "content":  choice.message.content or "",
        "usage":    {
            "prompt_tokens":     resp.usage.prompt_tokens,
            "completion_tokens": resp.usage.completion_tokens,
            "total_tokens":      resp.usage.total_tokens,
        },
        "model":    resp.model,
        "finish_reason": choice.finish_reason,
    }


# ---------- 7. Turso libSQL 客户端 ----------
import libsql_client

_db_client: "libsql_client.ClientSync | None" = None


def get_db() -> "libsql_client.ClientSync":
    """返回 libsql 同步客户端（单例）

    支持两种模式：
    - libsql:// 开头：远程 Turso（需 TURSO_TOKEN）
    - file: 开头或本地路径：本地 libSQL 文件（无需 token）
    """
    global _db_client
    if _db_client is None:
        url = Config.TURSO_URL
        if not url:
            raise RuntimeError("TURSO_URL 未配置")

        if url.startswith("libsql://"):
            if not Config.TURSO_TOKEN:
                raise RuntimeError("libsql:// 远程模式需要 TURSO_TOKEN")
            _db_client = libsql_client.create_client_sync(
                url=url, auth_token=Config.TURSO_TOKEN,
            )
        else:
            # 本地文件模式
            if not url.startswith("file:"):
                url = f"file:{url}" if not url.startswith("/") else f"file:{url}"
            _db_client = libsql_client.create_client_sync(url=url)

        # 开启外键
        try:
            _db_client.execute("PRAGMA foreign_keys = ON;")
        except Exception:
            pass
    return _db_client


def db_exec(sql: str, params: list | None = None) -> "libsql_client.ResultSet":
    """执行写操作（INSERT / UPDATE / DELETE / CREATE）"""
    return get_db().execute(sql, params or [])


def db_query(sql: str, params: list | None = None) -> list[dict]:
    """执行查询，返回 list[dict]（行 → dict）"""
    result = get_db().execute(sql, params or [])
    if not result.rows:
        return []
    # libsql-client 的 row 是 tuple，columns 在 result.columns
    cols = list(result.columns) if hasattr(result, "columns") else None
    out = []
    for row in result.rows:
        if cols is not None:
            out.append({c: v for c, v in zip(cols, row)})
        else:
            # 退化：尝试 _asdict
            try:
                out.append(row._asdict())
            except Exception:
                out.append({"_row": row})
    return out


def db_query_one(sql: str, params: list | None = None) -> dict | None:
    """查询单行"""
    rows = db_query(sql, params)
    return rows[0] if rows else None


# ---------- 8. Token 计数（tiktoken）----------
import tiktoken

_encoder: "tiktoken.Encoding | None" = None


def get_encoder() -> "tiktoken.Encoding":
    """返回 tiktoken 编码器（deepseek 用 cl100k_base）"""
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def count_tokens(text: str) -> int:
    """粗略 token 数（按 cl100k_base 编码）"""
    if not text:
        return 0
    return len(get_encoder().encode(text))


def count_messages_tokens(messages: list[dict]) -> int:
    """统计一组 message 的 token 数（每条加 4 的固定开销）"""
    total = 0
    for m in messages:
        total += 4  # role/分隔符固定开销
        total += count_tokens(m.get("content", ""))
    return total


# ---------- 9. 工具函数 ----------
def new_id(prefix: str = "") -> str:
    """生成短 UUID（带前缀）"""
    import uuid
    return f"{prefix}{uuid.uuid4().hex[:12]}" if prefix else uuid.uuid4().hex


def now_iso() -> str:
    """当前时间 ISO 格式"""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def truncate(text: str, max_len: int = 80) -> str:
    """截断字符串用于预览"""
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


# ---------- 10. Embedding 编解码（无 numpy 依赖）----------
import struct


def embedding_to_blob(embedding: list[float]) -> bytes:
    """list[float] → BLOB（float32 数组）"""
    if not embedding:
        return b""
    return struct.pack(f"{len(embedding)}f", *embedding)


def blob_to_embedding(blob: bytes | memoryview) -> list[float]:
    """BLOB → list[float]"""
    if not blob:
        return []
    n = len(blob) // 4
    if isinstance(blob, memoryview):
        blob = bytes(blob)
    return list(struct.unpack(f"{n}f", blob))


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """纯 Python 余弦相似度"""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot   = sum(x * y for x, y in zip(a, b))
    normA = sum(x * x for x in a) ** 0.5
    normB = sum(y * y for y in b) ** 0.5
    if normA == 0 or normB == 0:
        return 0.0
    return dot / (normA * normB)


# 导出通配符（agent 用 `from common import *` 时可拿到）
__all__ = [
    "ROOT", "Config", "log",
    "ok", "err", "E",
    "get_llm", "llm_chat",
    "get_db", "db_exec", "db_query", "db_query_one",
    "get_encoder", "count_tokens", "count_messages_tokens",
    "new_id", "now_iso", "truncate",
    "embedding_to_blob", "blob_to_embedding", "cosine_similarity",
]
