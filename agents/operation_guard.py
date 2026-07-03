"""
agents/operation_guard.py
==========================================================
后置操作级安全护栏

防护级别：
  L1 拒绝 — 直接拦截，不执行（破坏性操作、越权、非法参数）
  L2 警告 — 执行但附加警告（高危操作，如大量删除）
  L3 审计 — 记录日志，不影响执行（常规操作）

原则：每个 agent 只能操作自己职责范围内的数据，
     不能跨 agent 操作（如 chat agent 无权删知识库文章）
==========================================================
"""

from __future__ import annotations
import re
import sys
from pathlib import Path

try:
    from common import log
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common import log


# ---------- 1. 破坏性操作模式 ----------
DESTRUCTIVE_PATTERNS: list[tuple[str, str]] = [
    # (正则, 描述)
    # 动词在前 → 目标在后
    (r"(删除|清空|删掉|抹除|wipe|delete|remove|drop|truncate)\s*(所有|全部|整个|all|every|一切)", "批量删除数据"),
    (r"(删|清|移除|delete).*(文章|article|内容|content|数据|data|数据库|database|表|table)", "删除数据库内容"),
    # 目标在前 → 动词在后（中文特有语序："把文章内容全删了"）
    (r"(文章|article|内容|content|数据|data|数据库|database).*?\s*(全|都|全部|彻底)\s*(删|清|移除|delete|drop)", "（反向语序）删除数据库内容"),
    (r"(格式化|format|重建|reset)\s*(数据库|database|db|硬盘|disk)", "数据库/存储破坏"),
    (r"(删除|移除|注销)\s*(账号|账户|account|用户|user)", "用户数据删除"),
    (r"执行\s*(rm|del|format|dd|mkfs)", "系统命令执行"),
    (r"(drop|truncate|alter)\s+(table|database)", "DDL 破坏操作"),
]

# ---------- 2. 跨 agent 越权模式 ----------
# 定义每个 agent 允许的数据域
AGENT_SCOPES: dict[str, set[str]] = {
    "chat":    {"messages", "sessions"},
    "search":  {"search_results"},
    "knowledge":{"knowledge_articles", "knowledge_chunks", "search_results"},
    "blog":    {"articles", "blog_content", "search_results"},
    "feishu":  {"search_results", "external_feishu"},
    "email":   {"messages", "sessions"},
}

# 操作 → 所需的数据域
# 注意：blog 和 knowledge agent 不包含删除操作（delete 不走 agent，手动操作）
OPERATION_SCOPES: dict[str, list[str]] = {
    "generate_blog":       ["search_results", "articles"],
    "save_to_knowledge":   ["knowledge_articles", "knowledge_chunks", "search_results"],
    "save_to_feishu":      ["search_results"],
    "search_web":          ["search_results"],
}


# ---------- 3. 护栏执行 ----------
def guard_operation(
    user_message: str,
    operation: str,
    params: dict | None = None,
    agent_name: str = "chat",
) -> dict:
    """
    操作执行前的安全护栏。

    返回:
      {"allowed": True} — 放行
      {"allowed": False, "level": "L1", "reason": "...", "blocked": True} — 拦截
      {"allowed": True, "level": "L2", "warning": "..."} — 警告但放行
    """

    # --- L1: 破坏性操作检测 ---
    for pattern, desc in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, user_message):
            log.warning(f"[guard] L1 拦截: {desc} | msg={user_message[:80]}")
            return {
                "allowed": False,
                "level": "L1",
                "blocked": True,
                "reason": f"检测到破坏性操作请求（{desc}），已拦截。如需操作请手动处理。",
                "matched_pattern": pattern,
            }

    # --- L1: 跨 agent 越权检测 ---
    if operation in OPERATION_SCOPES:
        required_scopes = set(OPERATION_SCOPES[operation])
        agent_scopes = AGENT_SCOPES.get(agent_name, set())
        missing = required_scopes - agent_scopes
        if missing and agent_scopes:
            log.warning(f"[guard] L1 越权拦截: agent={agent_name} 无权访问 {missing}")
            return {
                "allowed": False,
                "level": "L1",
                "blocked": True,
                "reason": f"当前 agent ({agent_name}) 无权执行 {operation} 操作，需要 {missing} 域权限。",
                "missing_scopes": list(missing),
            }

    # --- L2: 高风险操作检测 ---
    if params and params.get("count", 0) > 100:
        return {
            "allowed": True,
            "level": "L2",
            "warning": f"操作涉及 {params['count']} 条数据，数量较大，请确认。",
        }

    return {"allowed": True}


def guard_user_message(message: str) -> dict:
    """
    对用户消息做通用安全检查（在调用任何 agent 前执行）。

    返回:
      {"safe": True} — 安全
      {"safe": False, "reason": "..."} — 不安全，应拒绝
    """
    # 检测提示词注入
    try:
        from agents.security import detect_injection
        injection = detect_injection(message)
        if injection:
            return {"safe": False, "reason": injection["reason"]}
    except ImportError:
        pass

    # 检测恶意 URL
    malicious_urls = re.findall(
        r'(eval\(|javascript:|data:text/html|<script|onerror=|onload=)',
        message, re.IGNORECASE
    )
    if malicious_urls:
        return {"safe": False, "reason": "检测到恶意内容"}

    return {"safe": True}


# ---------- 测试 ----------
if __name__ == "__main__":
    tests = [
        ("把文章内容全删了", "delete_article", "blog"),
        ("帮我删除所有数据", "delete_knowledge", "chat"),
        ("把搜索结果存到知识库", "save_to_knowledge", "knowledge"),
        ("帮我生成一篇博客", "generate_blog", "blog"),
        ("删除所有session", "delete_session", "chat"),
        ("搜索AI最新论文", "search_web", "search"),
    ]
    for msg, op, agent in tests:
        r = guard_operation(msg, op, agent_name=agent)
        status = "❌ 拦截" if not r["allowed"] else "✅ 放行"
        extra = f"({r.get('reason', r.get('warning', ''))})" if not r["allowed"] or "warning" in r else ""
        print(f"  {status} [{agent}] {op:25s} ← {msg:30s} {extra}")
