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
import re
from common import *  # 项目级基础库
from common import log, new_id, now_iso, count_tokens
from tools.task_tracker_tool import create_task, fail_task
from tools.article_request_tool import (
    build_context_clarification,
    build_clarification_payload,
    build_refined_search_message,
    detect_action_targets,
    escape_markdown_text,
    extract_requested_count,
    has_explicit_search_intent,
    is_count_refinement_request,
    load_pending_article_clarification,
    load_recent_search_contexts,
    resolve_clarification_selection,
    select_followup_context,
)


# ---------- 1. 混合意图识别 ----------
def detect_intent(message: str) -> dict:
    """
    正则 + 余弦混合意图识别。
    返回: {"intent": "search", "confidence": 0.95, "method": "regex|cosine|fallback"}
    """
    try:
        from tools.intent_classifier_tool import detect_intent_hybrid
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


def _should_plan(message: str, intent_name: str) -> bool:
    msg = message or ""
    if intent_name == "search":
        return True
    if intent_name == "feishu":
        return True
    if intent_name == "knowledge":
        return bool(re.search(r'(存|加入|存入|保存到|收藏到|收录到).{0,8}(知识库|knowledge)', msg))
    if intent_name == "blog":
        return bool(re.search(r'(生成|写|创作|撰写|来一篇|出一篇)\s*(博客|文章|blog)', msg))
    return False


def _analyze_article_request(message: str, session_id: str | None) -> dict:
    text = (message or "").strip()
    pending = load_pending_article_clarification(session_id)
    if pending:
        selected = resolve_clarification_selection(text, pending)
        if selected:
            context = selected["context"]
            return {
                "kind": "followup_action",
                "context": context,
                "search_query": context.get("search_query", ""),
                "search_results": context.get("search_results", []),
                "action_targets": selected.get("action_targets") or [],
            }

    action_targets = detect_action_targets(text)
    explicit_search = has_explicit_search_intent(text)
    requested_count = extract_requested_count(text)
    contexts = load_recent_search_contexts(session_id) if session_id else []

    if explicit_search:
        return {
            "kind": "new_search",
            "plan_message": text,
            "requested_count": requested_count,
            "action_targets": sorted(action_targets),
        }

    if action_targets:
        selected = select_followup_context(text, contexts)
        if selected["status"] == "reuse":
            context = selected["context"]
            return {
                "kind": "followup_action",
                "context": context,
                "search_query": context.get("search_query", ""),
                "search_results": context.get("search_results", []),
                "action_targets": sorted(action_targets),
            }
        if selected["status"] == "ambiguous":
            return {
                "kind": "clarify",
                "message": build_context_clarification(selected.get("contexts", [])),
                "payload": build_clarification_payload(selected.get("contexts", []), sorted(action_targets)),
            }
        return {
            "kind": "clarify",
            "message": "当前会话没有可用的文章结果。请先告诉我要搜索什么，或者直接说完整需求。",
        }

    if is_count_refinement_request(text):
        selected = select_followup_context(text, contexts)
        if selected["status"] == "reuse":
            context = selected["context"]
            return {
                "kind": "new_search",
                "plan_message": build_refined_search_message(text, context.get("search_query", "")),
                "requested_count": requested_count,
                "action_targets": [],
            }
        if selected["status"] == "ambiguous":
            return {
                "kind": "clarify",
                "message": build_context_clarification(selected.get("contexts", [])),
                "payload": build_clarification_payload(selected.get("contexts", []), []),
            }

    return {"kind": "default"}


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
    from tools.security_tool import detect_injection, sanitize_input

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
    article_request = _analyze_article_request(message, session_id)

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
    if article_request["kind"] == "clarify":
        duration_ms = int((time.time() - t0) * 1000)
        response_text = article_request["message"]
        if not session_id:
            from agents import chat_agent
            session_id = chat_agent._create_session()
        user_msg_id = new_id("msg-")
        asst_msg_id = new_id("msg-")
        now = now_iso()
        user_tokens = count_tokens(message)
        asst_tokens = count_tokens(response_text)
        db_exec(
            """INSERT INTO messages (message_id, session_id, role, content, trace_id, tokens, created_at)
               VALUES (?,?,?,?,?,?,?)""",
            [user_msg_id, session_id, "user", message, trace_id, user_tokens, now],
        )
        db_exec(
            """INSERT INTO messages (message_id, session_id, role, content, trace_id, tokens, meta, created_at)
               VALUES (?,?,?,?,?,?,?,?)""",
            [asst_msg_id, session_id, "assistant", response_text, trace_id, asst_tokens,
             json.dumps({"pending_article_clarification": article_request.get("payload") or {}}, ensure_ascii=False), now],
        )
        return {
            "session_id": session_id,
            "user_message_id": user_msg_id,
            "assistant_message_id": asst_msg_id,
            "response": response_text,
            "intent": "clarify",
            "trace_id": trace_id,
            "duration_ms": duration_ms,
            "requires_clarification": True,
        }

    plan_message = message
    preloaded_search_results = None
    if article_request["kind"] == "new_search":
        plan_message = article_request.get("plan_message") or message
        intent_name = "search"
        intent_info = {"intent": "search", "confidence": 1.0, "method": "article_request",
                       "action_targets": article_request.get("action_targets", [])}
    elif article_request["kind"] == "followup_action":
        preloaded_search_results = article_request.get("search_results") or []
        intent_name = "followup_action"
        intent_info = {
            "intent": "followup_action",
            "confidence": 1.0,
            "method": "article_request",
            "source_query": article_request.get("search_query") or plan_message,
            "action_targets": article_request.get("action_targets", []),
        }

    needs_planning = _should_plan(plan_message, intent_name)
    if article_request["kind"] == "followup_action":
        needs_planning = True

    if needs_planning:
        task_id = None
        try:
            from agents.plan_executor_agent import PlanExecutor
            from agents import chat_agent

            if not session_id or not chat_agent._get_session(session_id):
                session_id = chat_agent._create_session()
                auto_title = True
            else:
                sess = chat_agent._get_session(session_id)
                auto_title = (sess.get("message_count", 0) == 0) if sess else False

            task_id = create_task(
                session_id=session_id,
                trace_id=trace_id,
                kind="plan_execute",
                title=message[:120],
                detail="正在拆解并执行任务",
                steps=[],
            )
            executor = PlanExecutor(session_id=session_id, trace_id=trace_id, task_id=task_id)
            steps = executor.plan(plan_message, intent_info)

            # 防御：plan() 返回空步骤但实际有 followup action + 搜索结果 → 直接生成博客
            if not steps and article_request.get("kind") == "followup_action" and article_request.get("action_targets"):
                action_targets = article_request.get("action_targets", [])
                if "blog" in action_targets and preloaded_search_results:
                    from agents.plan_executor_agent import PlanStep
                    steps = [PlanStep(
                        step_id=0, agent="blog", action="generate_blog",
                        params={"query": article_request.get("search_query") or plan_message},
                        needs_content=True,
                        description="基于已有搜索结果生成博客",
                    )]
                    log.info(f"[master] plan() 返回空步骤，手动注入 blog step")

            if preloaded_search_results and steps:
                executor.step_results[-1] = {
                    "search_results": preloaded_search_results,
                    "query": article_request.get("search_query") or plan_message,
                }
                first_step = steps[0]
                first_step.params["search_results"] = preloaded_search_results
                if first_step.action == "save_to_feishu":
                    first_step.params["query"] = article_request.get("search_query") or plan_message
                elif first_step.action == "save_to_knowledge":
                    first_step.params["query"] = article_request.get("search_query") or plan_message
                elif first_step.action == "generate_blog":
                    first_step.params["query"] = article_request.get("search_query") or plan_message
                elif first_step.action == "send_email":
                    first_step.params["query"] = article_request.get("search_query") or plan_message

            if len(steps) > 1 or (steps and steps[0].agent != "chat"):
                log.info(f"[master] Plan-Execute: {len(steps)} steps")
                exec_result = executor.execute(steps)
                duration_ms = int((time.time() - t0) * 1000)
                search_results_meta = []

                if exec_result["success"]:
                    parts = []
                    latest_search_result = None
                    rendered_parts = []
                    for s in exec_result.get("steps", []):
                        if s.get("status") == "done":
                            r = s.get("result", {})
                            if r.get("message"):
                                rendered_parts.append(r["message"])
                            elif r.get("doc_url"):
                                rendered_parts.append(f"已保存到飞书：[{r['doc_url']}]({r['doc_url']})")
                            elif r.get("url"):
                                rendered_parts.append(f"博客已生成：[{r.get('title', '')}]({r['url']})")
                            elif r.get("search_results"):
                                latest_search_result = r
                            elif r.get("email_sent"):
                                rendered_parts.append(f"邮件已发送至 {r.get('to', '')}")

                    if latest_search_result:
                        search_results_meta = latest_search_result.get("search_results", [])
                        lines = [f"找到 {latest_search_result['count']} 条相关文章："]
                        for idx, item in enumerate(latest_search_result.get("search_results", [])[:5], 1):
                            title = item.get("title") or "未命名"
                            url = item.get("url") or ""
                            snippet = escape_markdown_text(item.get("snippet") or "")
                            line = f"{idx}. [{title}]({url})" if url else f"{idx}. {title}"
                            if snippet:
                                line += f"\n   {snippet[:120]}"
                            lines.append(line)
                        parts.append("\n".join(lines))

                    parts.extend(rendered_parts)
                    response_text = "\n\n".join(parts) if parts else "操作完成"
                else:
                    response_text = f"操作失败：{exec_result.get('error', '未知错误')}"

                user_msg_id = new_id("msg-")
                asst_msg_id = new_id("msg-")
                now = now_iso()
                user_tokens = count_tokens(message)
                asst_tokens = count_tokens(response_text)
                meta_sides = {
                    "plan_result": exec_result,
                    "task_id": task_id,
                    "search_query": plan_message if search_results_meta else None,
                    "search_results": search_results_meta if search_results_meta else None,
                }
                db_exec(
                    """INSERT INTO messages (message_id, session_id, role, content, trace_id, tokens, created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    [user_msg_id, session_id, "user", message, trace_id, user_tokens, now],
                )
                db_exec(
                    """INSERT INTO messages (message_id, session_id, role, content, trace_id, tokens, meta, created_at)
                       VALUES (?,?,?,?,?,?,?,?)""",
                    [asst_msg_id, session_id, "assistant", response_text, trace_id, asst_tokens,
                     json.dumps(meta_sides, ensure_ascii=False), now],
                )
                chat_agent._update_session_activity(session_id, user_tokens + asst_tokens, 2)
                if auto_title:
                    chat_agent._auto_title(session_id, message)

                result = {
                    "session_id": session_id,
                    "user_message_id": user_msg_id,
                    "assistant_message_id": asst_msg_id,
                    "response": response_text,
                    "intent": intent_name,
                    "trace_id": trace_id,
                    "duration_ms": duration_ms,
                    "plan_steps": len(steps),
                    "plan_result": exec_result,
                    "task_id": task_id,
                }
                _update_trace(trace_id, t0)
                return result
        except ImportError as e:
            log.warning(f"[master] Plan-Executor 不可用: {e}")
        except Exception as e:
            log.error(f"[master] Plan-Execute 失败: {e}，回退到传统路由")
            if task_id:
                try:
                    fail_task(task_id, str(e), detail="计划执行失败")
                except Exception:
                    pass

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
