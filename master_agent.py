"""
master_agent.py
==========================================================
主控 Agent（M0）

M2 架构：
1. 混合意图识别：正则 + 余弦相似度（intent_classifier）
2. Plan-Execute 编排：分析 → 生成步骤 → 分发执行（plan_executor）
3. 操作级安全护栏：执行前检查（operation_guard）
4. Agent 生命周期：wake → execute → sleep，不残留 token
==========================================================
"""

from __future__ import annotations
import json
import time
from common import *  # 项目级基础库
from common import log, new_id, now_iso, count_tokens


# ---------- 1. 混合意图识别 ----------
def detect_intent(message: str) -> dict:
    """
    正则 + 余弦混合意图识别。
    返回: {"intent": "search", "confidence": 0.95, "method": "regex|cosine|fallback"}
    """
    try:
        from agents.intent_classifier import detect_intent_hybrid
        return detect_intent_hybrid(message)
    except ImportError:
        # 回退到简单关键词
        return _detect_intent_fallback(message)


def _detect_intent_fallback(message: str) -> dict:
    """纯正则回退（intent_classifier 不可用时）"""
    msg = message.strip().lower()
    if any(k in msg for k in ["搜索", "搜一下", "查", "search"]):
        return {"intent": "search", "confidence": 0.9, "method": "regex_fallback"}
    if any(k in msg for k in ["博客", "blog", "写文章", "生成文章"]):
        return {"intent": "blog", "confidence": 0.9, "method": "regex_fallback"}
    if any(k in msg for k in ["知识库", "knowledge", "存到知识库"]):
        return {"intent": "knowledge", "confidence": 0.9, "method": "regex_fallback"}
    if any(k in msg for k in ["飞书", "feishu"]):
        return {"intent": "feishu", "confidence": 0.9, "method": "regex_fallback"}
    if any(k in msg for k in ["改写", "润色", "重写", "rewrite", "polish"]):
        return {"intent": "rewrite", "confidence": 0.9, "method": "regex_fallback"}
    return {"intent": "chat", "confidence": 0.0, "method": "regex_fallback"}


# ---------- 2. 编排：识别 → 规划 → 执行 ----------
def route(message: str, session_id: str | None, **kwargs) -> dict:
    """
    主入口：
    1. 识别意图（正则 + 余弦）
    2. 安全护栏检查
    3. Plan-Execute：生成步骤 → 按序执行
    4. 非 plan-execute 路径：走传统 chat_agent（兼容）
    """
    trace_id = kwargs.get("trace_id", new_id("trace-"))
    t0 = time.time()

    # --- Step 1: 安全前置检查 ---
    from agents.security import detect_injection, sanitize_input

    injection = detect_injection(message)
    if injection:
        log.warning(f"[master] 注入拦截: {injection['reason']}")
        return {
            "session_id": session_id,
            "response": f"⚠️ 您的请求被安全系统拦截：{injection['reason']}",
            "blocked": True,
            "blocked_reason": injection["reason"],
            "trace_id": trace_id,
            "intent": "blocked",
            "duration_ms": int((time.time() - t0) * 1000),
        }

    message = sanitize_input(message)

    # --- Step 2: 意图识别 ---
    intent_info = detect_intent(message)
    log.info(f"[master] trace={trace_id} intent={intent_info} session={session_id}")

    # 记录 trace
    try:
        db_exec(
            """INSERT INTO trace_calls (call_id, trace_id, agent_name, operation, input, output, duration_ms, status, created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            [new_id("call-"), trace_id, "master", "route",
             json.dumps({"message": message, "intent": intent_info, "session_id": session_id}, ensure_ascii=False),
             json.dumps({"status": "routed"}, ensure_ascii=False),
             0, "success", now_iso()],
        )
    except Exception as e:
        log.warning(f"[master] trace 写入失败: {e}")

    # --- Step 3: 尝试 Plan-Execute（需要搜索 → 操作的流程）---
    intent_name = intent_info["intent"]
    needs_planning = intent_name in ("search", "blog", "knowledge", "feishu")

    if needs_planning:
        try:
            from agents.plan_executor import PlanExecutor

            executor = PlanExecutor(session_id=session_id, trace_id=trace_id)
            steps = executor.plan(message, intent_info)

            if len(steps) > 1 or (steps and steps[0].agent != "chat"):
                log.info(f"[master] Plan-Execute: {len(steps)} steps")
                exec_result = executor.execute(steps)
                duration_ms = int((time.time() - t0) * 1000)

                if exec_result["success"]:
                    parts = []
                    for s in exec_result.get("steps", []):
                        if s.get("status") == "done":
                            r = s.get("result", {})
                            if r.get("message"):
                                parts.append(r["message"])
                            elif r.get("doc_url"):
                                parts.append(f"已保存到飞书：[{r['doc_url']}]({r['doc_url']})")
                            elif r.get("url"):
                                parts.append(f"博客已生成：[{r.get('title', '')}]({r['url']})")
                            elif r.get("search_results"):
                                parts.append(f"搜索完成，找到 {r['count']} 条结果")
                            elif r.get("email_sent"):
                                parts.append(f"邮件已发送至 {r.get('to', '')}")
                    response_text = "\n\n".join(parts) if parts else "操作完成"
                else:
                    response_text = f"操作失败：{exec_result.get('error', '未知错误')}"

                result = {
                    "session_id": session_id,
                    "response": response_text,
                    "intent": intent_name,
                    "trace_id": trace_id,
                    "duration_ms": duration_ms,
                    "plan_steps": len(steps),
                    "plan_result": exec_result,
                }
                _update_trace(trace_id, t0)
                return result
        except ImportError as e:
            log.warning(f"[master] Plan-Executor 不可用: {e}")
        except Exception as e:
            log.error(f"[master] Plan-Execute 失败: {e}，回退到传统路由")

    # --- Step 4: 传统路由 ---
    if intent_name == "chat":
        from agents import chat_agent
        result = chat_agent.handle(message=message, session_id=session_id, trace_id=trace_id, **kwargs)
    elif intent_name == "rewrite":
        from agents import chat_agent
        result = chat_agent.handle(
            message=f"（改写请求）{message}", session_id=session_id, trace_id=trace_id, **kwargs
        )
    elif intent_name == "email":
        from agents import chat_agent
        from agents.email_agent import send_email as _send_email
        # LLM 先理解邮件内容，再调用发送
        result = chat_agent.handle(
            message=message, session_id=session_id, trace_id=trace_id, **kwargs
        )
    else:
        from agents import chat_agent
        result = chat_agent.handle(message=message, session_id=session_id, trace_id=trace_id, **kwargs)

    _update_trace(trace_id, t0)
    result["trace_id"] = trace_id
    result["intent"] = intent_name
    return result


def _update_trace(trace_id: str, t0: float):
    """更新 trace 调用时长"""
    duration_ms = int((time.time() - t0) * 1000)
    try:
        db_exec(
            "UPDATE trace_calls SET duration_ms=? WHERE trace_id=? AND agent_name='master'",
            [duration_ms, trace_id],
        )
    except Exception:
        pass


# ---------- 3. API 层统一入口 ----------
def handle_request(payload: dict) -> dict:
    """
    API 层的统一入口
    payload 来自 request.json()：
      { session_id, message, history?, stream?, options? }
    """
    message = (payload.get("message") or "").strip()
    session_id = payload.get("session_id") or None
    stream = bool(payload.get("stream", False))
    options = payload.get("options") or {}

    if not message:
        return err(E.SESSION_NOT_FOUND if not session_id else 4001, "message 不能为空")

    # 流式模式：直接走 chat_agent 流式（plan-execute 暂不处理流式）
    if stream:
        return {"_stream": True, "message": message, "session_id": session_id, "options": options}

    return route(message=message, session_id=session_id, stream=stream, options=options)


if __name__ == "__main__":
    import sys
    msg = sys.argv[1] if len(sys.argv) > 1 else "你好"
    out = handle_request({"message": msg})
    print(json.dumps(out, ensure_ascii=False, indent=2))
