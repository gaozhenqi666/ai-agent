"""
agents/plan_executor.py
==========================================================
Plan-Execute 执行引擎 + Agent 生命周期管理

核心机制：
1. **Plan 阶段**：根据用户消息和意图，生成执行步骤列表
   每个步骤指定：哪个 agent、什么操作、依赖哪个步骤的输出
2. **Execute 阶段**：按序执行步骤，管理 agent 的 wake/sleep 生命周期
3. **内容接地**：需要文章内容的操作，必须先 scrape 再执行，
   爬不到内容 → 拒绝执行，绝不把 snippet 当正文喂给 LLM

Agent 生命周期：
  wake → execute(step) → sleep
  - wake:   lazy import agent 模块，加载专属 system prompt
  - sleep:  释放 agent 上下文，token 不残留
==========================================================
"""

from __future__ import annotations
import json
import time
import threading
import sys
from pathlib import Path
from dataclasses import dataclass, field
import re
from tools.agent_protocol_tool import (
    build_agent_result,
    ensure_step_params,
    normalize_search_results,
)
from tools.article_request_tool import (
    build_refined_search_message,
    detect_action_targets,
    extract_requested_count,
    normalize_search_query,
)

try:
    from common import log, db_query_one, new_id, now_iso
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common import log, db_query_one, new_id, now_iso
from tools.task_tracker_tool import update_task_step, complete_task, fail_task


# ---------- 1. 数据结构 ----------

@dataclass
class PlanStep:
    """执行计划中的一个步骤"""
    step_id: int
    agent: str          # "search" | "knowledge" | "blog" | "feishu" | "chat"
    action: str         # 具体操作名
    params: dict = field(default_factory=dict)
    depends_on: int | None = None   # 依赖的上一步 step_id
    needs_content: bool = False     # 是否需要先爬取原文
    description: str = ""


@dataclass
class AgentContext:
    """Agent 运行时上下文（wake → 持有 → sleep）"""
    name: str
    module: object | None = None
    prompt: str = ""
    woken_at: float = 0.0
    
    def wake(self):
        """唤醒 agent：lazy import + 加载 prompt"""
        self.woken_at = time.time()
        # lazy import：只有用到才加载对应模块
        agent_module_map = {
            "search":    "agents.chat_agent",       # 搜索在 chat_agent 里
            "knowledge": "agents.chat_agent",       # 知识库在 chat_agent 里
            "blog":      "agents.chat_agent",       # 博客在 chat_agent 里
            "feishu":    "tools.feishu_doc_tool",   # 飞书独立
            "chat":      "agents.chat_agent",
        }
        mod_name = agent_module_map.get(self.name)
        if mod_name:
            import importlib
            self.module = importlib.import_module(mod_name)
        log.info(f"[executor] Agent '{self.name}' woken ({self.module is not None})")

    def sleep(self):
        """休眠 agent：释放引用"""
        self.module = None
        self.prompt = ""
        elapsed = time.time() - self.woken_at
        log.info(f"[executor] Agent '{self.name}' → sleep (活跃 {elapsed:.1f}s)")


class PlanExecutor:
    """Plan-Execute 引擎"""

    def __init__(self, session_id: str, trace_id: str, task_id: str | None = None):
        self.session_id = session_id
        self.trace_id = trace_id
        self.task_id = task_id
        self.agent_registry: dict[str, AgentContext] = {}
        self.step_results: dict[int, dict] = {}  # step_id → result

    def plan(self, message: str, intent: dict) -> list[PlanStep]:
        """
        分析用户消息，生成执行步骤。

        规则：
        - "搜索X并生成博客" → [kb_search, web_search?, blog]
        - "搜索X并存知识库" → [kb_search, web_search?, knowledge]
        - "搜索X并存飞书"   → [kb_search, web_search?, feishu]
        - "生成博客"         → [blog(needs_content=True)]
        - "存飞书"           → [feishu(needs_content=True)]  ← 需要爬内容做摘要
        - 多意图混合         → 顺序组合
        - 纯聊天             → [chat]
        """
        steps: list[PlanStep] = []
        step_id = 0
        intent_name = intent.get("intent", "chat")

        if intent_name == "followup_action":
            source_query = intent.get("source_query") or message
            action_targets = intent.get("action_targets", [])

            if "blog" in action_targets or _has_blog_intent(message):
                steps.append(PlanStep(
                    step_id=step_id, agent="blog", action="generate_blog",
                    params={"query": source_query},
                    needs_content=True,
                    description="基于已有搜索结果生成博客"
                ))
                step_id += 1
            if "knowledge" in action_targets or _has_knowledge_intent(message):
                steps.append(PlanStep(
                    step_id=step_id, agent="knowledge", action="save_to_knowledge",
                    params={"query": source_query},
                    needs_content=True,
                    description="将已有搜索结果存入知识库"
                ))
                step_id += 1
            if "feishu" in action_targets or _has_feishu_intent(message):
                steps.append(PlanStep(
                    step_id=step_id, agent="feishu", action="save_to_feishu",
                    params={"query": source_query},
                    needs_content=True,
                    description="将已有搜索结果保存到飞书云文档"
                ))
                step_id += 1
            if "email" in action_targets or _has_email_intent(message):
                steps.append(PlanStep(
                    step_id=step_id, agent="email", action="send_email",
                    params={"query": source_query},
                    needs_content=True,
                    description="将已有搜索结果推送到邮箱"
                ))
                step_id += 1
            return steps

        # === 搜索意图 ===
        if intent_name == "search":
            steps.append(PlanStep(
                step_id=step_id, agent="knowledge", action="search_knowledge_articles",
                params={"query": message},
                description=f"先查知识库：{message[:50]}"
            ))
            step_id += 1

            steps.append(PlanStep(
                step_id=step_id, agent="search", action="search_web_if_needed",
                params={"query": message},
                depends_on=step_id - 1,
                description="知识库不足时联网搜索"
            ))
            step_id += 1

            action_targets = intent.get("action_targets", [])
            search_dep_step_id = step_id - 1  # 搜索步骤的 step_id

            # 只在 action_targets 中有对应目标时才创建 blog/feishu/knowledge 步骤
            # _analyze_article_request 已经排除了搜索语境下的误判（如"生成5篇文章"≠写博客）
            if "blog" in action_targets:
                steps.append(PlanStep(
                    step_id=step_id, agent="blog", action="generate_blog",
                    params={"query": message},
                    depends_on=search_dep_step_id,  # 依赖搜索结果
                    needs_content=True,       # 需要爬取原文
                    description="基于搜索结果生成博客"
                ))
                step_id += 1

            # "搜索并存知识库" → 追加 knowledge 步骤
            if "knowledge" in action_targets:
                steps.append(PlanStep(
                    step_id=step_id, agent="knowledge", action="save_to_knowledge",
                    depends_on=search_dep_step_id,
                    needs_content=True,
                    description="爬取搜索结果并存入知识库"
                ))
                step_id += 1

            # "搜索并存飞书" → 追加 feishu 步骤
            if "feishu" in action_targets:
                steps.append(PlanStep(
                    step_id=step_id, agent="feishu", action="save_to_feishu",
                    params={"query": message},
                    depends_on=search_dep_step_id,
                    needs_content=True,       # 关键：飞书需要爬内容做摘要
                    description="将搜索结果保存到飞书云文档（含摘要和总结）"
                ))
                step_id += 1

            if "email" in action_targets:
                steps.append(PlanStep(
                    step_id=step_id, agent="email", action="send_email",
                    params={"query": message},
                    depends_on=search_dep_step_id,
                    needs_content=True,
                    description="将搜索结果推送到邮箱"
                ))
                step_id += 1

            # 纯搜索，无后续操作 → 返回文章列表
            return steps

        # === 博客意图（无搜索） ===
        if intent_name == "blog":
            steps.append(PlanStep(
                step_id=step_id, agent="blog", action="generate_blog",
                params={"query": message},
                needs_content=True,
                description="生成博客"
            ))
            return steps

        # === 知识库意图 ===
        if intent_name == "knowledge":
            steps.append(PlanStep(
                step_id=step_id, agent="knowledge", action="save_to_knowledge",
                needs_content=True,
                description="存入知识库"
            ))
            return steps

        # === 飞书意图 ===
        if intent_name == "feishu":
            steps.append(PlanStep(
                step_id=step_id, agent="feishu", action="save_to_feishu",
                needs_content=True,
                description="保存到飞书"
            ))
            return steps

        # === 聊天 ===
        steps.append(PlanStep(
            step_id=step_id, agent="chat", action="chat",
            params={"message": message},
            description="对话"
        ))
        return steps

    def _wake_agent(self, name: str) -> AgentContext:
        """唤醒指定 agent（如果还没醒）"""
        if name not in self.agent_registry:
            ctx = AgentContext(name=name)
            ctx.wake()
            self.agent_registry[name] = ctx
        return self.agent_registry[name]

    def _sleep_all(self):
        """休眠所有 agent"""
        for ctx in self.agent_registry.values():
            ctx.sleep()
        self.agent_registry.clear()

    def execute(self, steps: list[PlanStep]) -> dict:
        """
        按序执行步骤，管理 agent 生命周期。

        关键：需要内容的操作（blog/knowledge/feishu），
        会先 scrape 原文，scrape 失败则拒绝执行并返回错误。
        """
        results: dict = {"steps": [], "success": True, "error": None}
        agents_woken: set[str] = set()

        for step in steps:
            log.info(f"[executor] 执行 Step {step.step_id}: {step.agent}.{step.action}")
            self._mark_step(step, "running", step.description or f"{step.agent}.{step.action}")

            # --- 内容接地检查 ---
            if step.needs_content:
                # 获取上一步的搜索结果
                existing_results = normalize_search_results(step.params.get("search_results"))
                prev_result = self.step_results.get(step.depends_on) if step.depends_on is not None else None
                search_results = existing_results or (prev_result.get("search_results", []) if prev_result else [])

                if not search_results:
                    # 尝试从最近的 assistant 消息 meta 中获取
                    last_asst = db_query_one(
                        """SELECT meta FROM messages
                           WHERE session_id=? AND role='assistant'
                           ORDER BY created_at DESC LIMIT 1""",
                        [self.session_id],
                    )
                    if last_asst and last_asst.get("meta"):
                        try:
                            meta = json.loads(last_asst["meta"])
                            sr = meta.get("search_results") or meta.get("feishu_search_results")
                            if sr:
                                search_results = sr
                                step.params["search_results"] = normalize_search_results(sr)
                                step.params["search_query"] = meta.get("search_query") or meta.get("feishu_search_query", "")
                        except Exception:
                            pass

                if not search_results and step.action in ("generate_blog", "save_to_knowledge", "save_to_feishu"):
                    results["success"] = False
                    results["error"] = "没有可用的搜索结果，无法执行需要内容基础的操作。"
                    results["steps"].append({
                        "step_id": step.step_id, "status": "skipped",
                        "reason": "no_search_results"
                    })
                    self._mark_step(step, "failed", "没有可用的搜索结果")
                    continue

                # 注入搜索结果到参数
                step.params["search_results"] = normalize_search_results(search_results)

            step.params = ensure_step_params(step.action, step.params)

            # --- 操作级安全护栏 ---
            try:
                from tools.operation_guard_tool import guard_operation
                guard_result = guard_operation(
                    user_message=step.params.get("query", ""),
                    operation=step.action,
                    params=step.params,
                    agent_name=step.agent,
                )
                if not guard_result.get("allowed"):
                    results["steps"].append({
                        "step_id": step.step_id, "status": "blocked",
                        "reason": guard_result.get("reason", "被安全护栏拦截")
                    })
                    results["success"] = False
                    results["error"] = guard_result.get("reason")
                    continue
            except ImportError:
                pass

            # --- 唤醒 agent 并执行 ---
            ctx = self._wake_agent(step.agent)
            agents_woken.add(step.agent)

            try:
                step_result = self._dispatch_step(step, ctx)
                if step_result.get("ok") is False:
                    raise RuntimeError(step_result.get("error") or f"{step.action} 执行失败")
                self.step_results[step.step_id] = step_result
                results["steps"].append({
                    "step_id": step.step_id,
                    "status": "done",
                    "agent": step.agent,
                    "action": step.action,
                    "result": step_result,
                })
                self._mark_step(step, "completed", self._describe_result(step_result), step_result)
            except Exception as e:
                log.error(f"[executor] Step {step.step_id} 失败: {e}")
                results["steps"].append({
                    "step_id": step.step_id,
                    "status": "error",
                    "agent": step.agent,
                    "error": str(e),
                })
                results["success"] = False
                results["error"] = str(e)
                self._mark_step(step, "failed", str(e))
                break  # 步骤失败则停止后续步骤

        # --- 休眠所有 agent ---
        self._sleep_all()
        if self.task_id:
            if results["success"]:
                complete_task(self.task_id, detail="任务已完成", result=results)
            else:
                fail_task(self.task_id, results.get("error", "任务失败"), detail="任务执行中断")

        return results

    def _mark_step(self, step: PlanStep, status: str, detail: str, result: dict | None = None):
        if not self.task_id:
            return
        url = ""
        title = ""
        if result:
            url = result.get("url") or result.get("doc_url") or ""
            title = result.get("title") or result.get("message") or ""
        update_task_step(
            self.task_id,
            step_key=f"step-{step.step_id}",
            label=step.description or f"{step.agent}.{step.action}",
            status=status,
            detail=detail,
            agent=step.agent,
            url=url,
            title=title,
        )

    @staticmethod
    def _describe_result(step_result: dict) -> str:
        if step_result.get("message"):
            return step_result["message"][:120]
        if step_result.get("doc_url"):
            return "已写入飞书文档"
        if step_result.get("url"):
            return "已生成可打开的结果"
        if step_result.get("count") is not None:
            return f"找到 {step_result['count']} 条结果"
        return "步骤完成"

    def _dispatch_step(self, step: PlanStep, ctx: AgentContext) -> dict:
        """分发步骤到对应 agent 执行"""
        action = step.action

        if action == "search_knowledge_articles":
            return self._exec_knowledge_search(step)
        elif action == "search_web_if_needed":
            return self._exec_search(step)
        elif action == "save_to_knowledge":
            return self._exec_knowledge(step)
        elif action == "generate_blog":
            return self._exec_blog(step)
        elif action == "save_to_feishu":
            return self._exec_feishu(step)
        elif action == "send_email":
            return self._exec_email(step)
        elif action == "chat":
            return self._exec_chat(step)
        else:
            raise ValueError(f"未知操作: {action}")

    # ---- 各操作的具体执行 ----

    @staticmethod
    def _extract_requested_count(query: str, default: int = 5) -> int:
        return extract_requested_count(query, default) or default

    @staticmethod
    def _normalize_search_query(query: str) -> str:
        return normalize_search_query(query)

    @staticmethod
    def _merge_search_results(*groups: list[dict], limit: int = 5) -> list[dict]:
        merged = []
        seen = set()
        for group in groups:
            for item in group or []:
                url = (item.get("url") or "").strip()
                title = (item.get("title") or "").strip()
                key = url or title
                if not key or key in seen:
                    continue
                seen.add(key)
                merged.append(item)
                if len(merged) >= limit:
                    return merged
        return merged

    @staticmethod
    def _query_tokens(query: str) -> set[str]:
        text = normalize_search_query(query).lower()
        tokens = set(re.findall(r"[a-z0-9][a-z0-9_\-\.]{1,}|[\u4e00-\u9fff]{2,8}", text))
        generic = {"文章", "论文", "资料", "教程", "博客", "article", "articles", "paper", "papers", "blog", "blogs"}
        return {token for token in tokens if token not in generic}

    def _is_knowledge_result_relevant(self, query: str, item: dict) -> bool:
        score = float(item.get("score") or 0.0)
        if score < 0.72:
            return False
        q_tokens = self._query_tokens(query)
        if not q_tokens:
            return score >= 0.76
        haystack = " ".join([
            item.get("title", ""),
            item.get("snippet", ""),
            item.get("source", ""),
        ]).lower()
        overlap = sum(1 for token in q_tokens if token in haystack)
        if overlap == 0:
            return False
        if len(q_tokens) >= 2:
            return overlap >= 2
        return overlap >= 1 and score >= 0.78

    def _exec_knowledge_search(self, step: PlanStep) -> dict:
        from tools.retriever_tool import hybrid_search

        query = step.params.get("query", "")
        normalized_query = self._normalize_search_query(query)
        limit = self._extract_requested_count(query)
        raw_hits = hybrid_search(
            query=normalized_query,
            top_k=max(limit, 5),
            vector_weight=0.55,
            keyword_weight=0.45,
            return_articles=True,
        )
        deduped = []
        seen = set()
        for item in raw_hits:
            article = item.get("article") or {}
            article_id = article.get("article_id") or item.get("article_id")
            if not article_id or article_id in seen:
                continue
            seen.add(article_id)
            deduped.append({
                "title": article.get("title", ""),
                "url": article.get("url", ""),
                "snippet": item.get("chunk_text", "")[:300],
                "article_id": article_id,
                "source": article.get("source", ""),
                "score": float(item.get("score") or 0.0),
            })
        filtered = [item for item in deduped if self._is_knowledge_result_relevant(query, item)]
        final_results = filtered[:limit]
        return build_agent_result("search_results", query=query, search_results=final_results, count=len(final_results))

    def _exec_search(self, step: PlanStep) -> dict:
        from agents.chat_agent import _search_tavily
        query = step.params.get("query", "")
        normalized_query = self._normalize_search_query(query)
        limit = self._extract_requested_count(query)
        prev_result = self.step_results.get(step.depends_on) if step.depends_on is not None else None
        previous = normalize_search_results((prev_result or {}).get("search_results"))
        if len(previous) >= limit:
            return build_agent_result("search_results", query=query, search_results=previous[:limit], count=min(len(previous), limit))

        web_results = normalize_search_results(_search_tavily(normalized_query, max_results=limit))
        merged = self._merge_search_results(previous, web_results, limit=limit)
        return build_agent_result("search_results", query=query, search_results=merged, count=len(merged))

    def _exec_knowledge(self, step: PlanStep) -> dict:
        from agents.chat_agent import _execute_knowledge_op
        results = step.params.get("search_results", [])
        msg = _execute_knowledge_op(results)
        return build_agent_result(
            "knowledge_saved",
            message=msg,
            saved_items=sum(1 for line in msg.splitlines() if line.startswith("✅")),
        )

    @staticmethod
    def _scrape_for_content(search_results: list[dict]) -> dict[str, dict]:
        """
        爬取搜索结果中的原文，供博客/飞书使用。
        返回 {url: {"success": True, "content": "...", "title": "..."} | {"success": False, "error": "..."}}
        """
        from tools.scraper_tool import scrape_url
        scraped: dict[str, dict] = {}
        for r in search_results:
            url = r.get("url", "")
            if not url:
                continue
            scrape_result = scrape_url(url)
            scraped[url] = scrape_result
        return scraped

    def _exec_blog(self, step: PlanStep) -> dict:
        from agents.chat_agent import _generate_blog_from_content, _add_to_knowledge
        from common import new_id, now_iso, db_exec
        from agents.chat_agent import _execute_blog_op
        from tools.article_request_tool import normalize_search_query

        search_results = step.params.get("search_results", [])
        raw_query = step.params.get("query", "")
        # 提取真实搜索主题（如"AI"），避免把用户原话当博客主题
        topic = normalize_search_query(raw_query) or raw_query[:30]

        # 先爬取内容
        scraped = self._scrape_for_content(search_results)
        available_content = [
            v["content"] for v in scraped.values()
            if v.get("success") and len(v.get("content", "")) > 500
        ]
        failed_urls = [k for k, v in scraped.items() if not v.get("success")]
        scraped_count = len(available_content)
        snippet_count = 0

        # 爬不到正文 → 用 search snippet 兜底
        if not available_content:
            parts: list[str] = []
            for r in search_results[:5]:
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                url = r.get("url", "")
                if not snippet:
                    continue
                parts.append(f"### {title}\n> 来源: {url}\n\n{snippet[:1500]}")
                snippet_count += 1
            if parts:
                material = "\n\n---\n\n".join(parts)
            else:
                return build_agent_result(
                    "blog_article",
                    ok=False,
                    error="所有文章都无法爬取，且无 snippet 可用，无法生成博客。",
                    article_id="",
                    title="",
                    url="",
                )
        else:
            material = "\n\n---\n\n".join(available_content[:3])

        blog_result = _generate_blog_from_content(
            content=material,
            title=f"「{topic}」综合博客",
            topic=topic,
        )

        if blog_result.get("success"):
            article_id = new_id("art-")
            now = now_iso()
            db_exec(
                """INSERT INTO articles (article_id, title, content, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?)""",
                [article_id, blog_result["title"], blog_result["content"], "draft", now, now],
            )
            warnings: list[str] = []
            if scraped_count == 0 and snippet_count > 0:
                warnings.append(f"所有文章均无法爬取，基于 {snippet_count} 篇文章的搜索摘要生成。")
            elif failed_urls:
                warnings.append(f"以下URL无法爬取（已跳过）: {failed_urls}")
            return {
                **build_agent_result(
                    "blog_article",
                    article_id=article_id,
                    title=blog_result["title"],
                    url=f"editor.html?id={article_id}",
                ),
                "scrape_warnings": warnings if warnings else None,
            }
        else:
            return build_agent_result(
                "blog_article",
                ok=False,
                error=blog_result.get("error", "博客生成失败"),
                article_id="",
                title="",
                url="",
            )

    def _exec_feishu(self, step: PlanStep) -> dict:
        from tools.feishu_doc_tool import save_search_to_feishu
        from tools.article_request_tool import normalize_search_query

        search_results = step.params.get("search_results", [])
        raw_query = step.params.get("query", "")
        # 提取真实搜索主题，避免把用户原话当标题
        query = normalize_search_query(raw_query) or raw_query[:30]

        # 爬取内容用于生成真实摘要
        scraped = self._scrape_for_content(search_results)

        # 用真实内容更新 snippet
        enriched = []
        for r in search_results:
            url = r.get("url", "")
            sc = scraped.get(url, {})
            if sc.get("success") and len(sc.get("content", "")) > 200:
                # 用爬到的前500字作为摘要
                enriched.append({
                    **r,
                    "snippet": sc["content"][:500],
                    "full_content": sc["content"],
                })
            else:
                # 爬不到就保留原 snippet，但标记
                enriched.append({**r, "scrape_warning": True})

        result = save_search_to_feishu(search_results=enriched, query=query)
        if result.get("success"):
            return build_agent_result(
                "feishu_doc",
                doc_id=result.get("doc_id", ""),
                doc_url=result.get("doc_url", ""),
                article_count=result.get("article_count", len(enriched)),
            )
        return build_agent_result(
            "feishu_doc",
            ok=False,
            error=result.get("error", "保存到飞书失败"),
            doc_id="",
            doc_url="",
            article_count=0,
        )

    def _exec_email(self, step: PlanStep) -> dict:
        """发送搜索结果到邮箱"""
        from agents.email_agent import send_email
        from tools.article_request_tool import normalize_search_query
        from tools.agent_protocol_tool import normalize_search_results

        params = step.params
        to = params.get("to", "")
        raw_query = params.get("query", "")
        topic = normalize_search_query(raw_query) or raw_query[:30]

        # 收件人固定为后台配置的默认邮箱
        if not to:
            to = "3556045497@qq.com"

        if not to:
            return build_agent_result("email_delivery", ok=False, error="缺少收件人地址", to="")

        # 从搜索结果构造邮件正文
        search_results = step.params.get("search_results", [])
        prev = self.step_results.get(step.depends_on) if step.depends_on is not None else None
        all_results = search_results or normalize_search_results((prev or {}).get("search_results"))

        if not all_results:
            return build_agent_result("email_delivery", ok=False, error="没有可推送的文章", to=to)

        body = f"主题：{topic}\n\n找到 {len(all_results)} 篇相关文章：\n\n"
        for i, r in enumerate(all_results):
            title = r.get("title", "无标题")
            url = r.get("url", "")
            snippet = r.get("snippet", "")[:200]
            body += f"{i + 1}. {title}\n   {url}\n   {snippet}\n\n"

        body += "---\n此邮件由 Harness 自动生成，请勿回复。"

        subject = f"Harness 推送 — 「{topic}」相关文章 ({len(all_results)}篇)"
        result = send_email(to=to, subject=subject, body=body)
        return build_agent_result(
            "email_delivery",
            ok=result.get("success", False),
            email_sent=result.get("success", False),
            to=to,
            provider=result.get("provider", ""),
            article_count=len(all_results),
            error=result.get("error", ""),
        )

    @staticmethod
    def _get_user_email() -> str:
        """获取用户默认邮箱：订阅表 > .env > 默认值"""
        try:
            from common import db_exec
            rows = db_exec("SELECT email FROM digest_subscriptions WHERE enabled=1 ORDER BY rowid LIMIT 1")
            if rows and rows[0][0]:
                return rows[0][0]
        except Exception:
            pass
        return "3556045497@qq.com"

    def _exec_chat(self, step: PlanStep) -> dict:
        return build_agent_result("chat_response", message="chat handled by main flow")


# ---------- 辅助函数 ----------

def _has_blog_intent(message: str) -> bool:
    import re
    return bool(re.search(r'(生成|写|创作|撰写|来一篇|出一篇).*(博客|文章|blog|总结)', message))


def _has_knowledge_intent(message: str) -> bool:
    import re
    return bool(re.search(r'(存|加入|存入|保存到|收藏到)\s*(知识库|knowledge)', message))


def _has_feishu_intent(message: str) -> bool:
    return "feishu" in detect_action_targets(message)


def _has_email_intent(message: str) -> bool:
    return "email" in detect_action_targets(message)


# ---------- 测试 ----------
if __name__ == "__main__":
    executor = PlanExecutor(session_id="test", trace_id="trace-test")

    # 测试 plan 生成
    test_cases = [
        ("帮我搜索两篇关于AI的论文并生成博客", {"intent": "search", "confidence": 1.0}),
        ("搜索Transformer论文并放到飞书上", {"intent": "search", "confidence": 1.0}),
        ("帮我生成一篇关于Python的博客", {"intent": "blog", "confidence": 1.0}),
        ("你好", {"intent": "chat", "confidence": 1.0}),
    ]

    for msg, intent in test_cases:
        steps = executor.plan(msg, intent)
        print(f"\n[{intent['intent']}] {msg[:50]}")
        for s in steps:
            dep = f" (depends on step {s.depends_on})" if s.depends_on is not None else ""
            nc = " [NEEDS_CONTENT]" if s.needs_content else ""
            print(f"  Step {s.step_id}: {s.agent}.{s.action}{dep}{nc} — {s.description}")
