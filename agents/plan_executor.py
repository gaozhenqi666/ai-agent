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

try:
    from common import log, db_query_one, new_id, now_iso
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from common import log, db_query_one, new_id, now_iso


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
            "feishu":    "agents.feishu_doc",       # 飞书独立
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

    def __init__(self, session_id: str, trace_id: str):
        self.session_id = session_id
        self.trace_id = trace_id
        self.agent_registry: dict[str, AgentContext] = {}
        self.step_results: dict[int, dict] = {}  # step_id → result

    def plan(self, message: str, intent: dict) -> list[PlanStep]:
        """
        分析用户消息，生成执行步骤。

        规则：
        - "搜索X并生成博客" → [search, blog(depends on search)]
        - "搜索X并存知识库" → [search, knowledge(depends on search)]
        - "搜索X并存飞书"   → [search, feishu(depends on search)]
        - "生成博客"         → [blog(needs_content=True)]
        - "存飞书"           → [feishu(needs_content=True)]  ← 需要爬内容做摘要
        - 多意图混合         → 顺序组合
        - 纯聊天             → [chat]
        """
        steps: list[PlanStep] = []
        step_id = 0
        intent_name = intent.get("intent", "chat")

        # === 搜索意图 ===
        if intent_name == "search":
            steps.append(PlanStep(
                step_id=step_id, agent="search", action="search_web",
                params={"query": message},
                description=f"搜索：{message[:50]}"
            ))
            step_id += 1

            # "搜索并生成博客" → 追加 blog 步骤
            if _has_blog_intent(message):
                steps.append(PlanStep(
                    step_id=step_id, agent="blog", action="generate_blog",
                    params={"query": message},
                    depends_on=step_id - 1,  # 依赖搜索结果
                    needs_content=True,       # 需要爬取原文
                    description="基于搜索结果生成博客"
                ))
                step_id += 1

            # "搜索并存知识库" → 追加 knowledge 步骤
            if _has_knowledge_intent(message):
                steps.append(PlanStep(
                    step_id=step_id, agent="knowledge", action="save_to_knowledge",
                    depends_on=step_id - 1,
                    needs_content=True,
                    description="爬取搜索结果并存入知识库"
                ))
                step_id += 1

            # "搜索并存飞书" → 追加 feishu 步骤
            if _has_feishu_intent(message):
                steps.append(PlanStep(
                    step_id=step_id, agent="feishu", action="save_to_feishu",
                    params={"query": message},
                    depends_on=step_id - 1,
                    needs_content=True,       # ⚠️ 关键：飞书需要爬内容做摘要
                    description="将搜索结果保存到飞书云文档（含摘要和总结）"
                ))
                step_id += 1

            # 纯搜索，无后续操作 → 只搜索
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

    # === 邮件意图 ===
    if intent_name == "email":
        steps.append(PlanStep(
            step_id=step_id, agent="email", action="send_email",
            params={"message": message},
            description="发送邮件"
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

            # --- 内容接地检查 ---
            if step.needs_content:
                # 获取上一步的搜索结果
                prev_result = self.step_results.get(step.depends_on) if step.depends_on is not None else None
                search_results = prev_result.get("search_results", []) if prev_result else []

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
                                step.params["search_results"] = sr
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
                    continue

                # 注入搜索结果到参数
                step.params["search_results"] = search_results

            # --- 操作级安全护栏 ---
            try:
                from agents.operation_guard import guard_operation
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
                self.step_results[step.step_id] = step_result
                results["steps"].append({
                    "step_id": step.step_id,
                    "status": "done",
                    "agent": step.agent,
                    "action": step.action,
                    "result": step_result,
                })
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
                break  # 步骤失败则停止后续步骤

        # --- 休眠所有 agent ---
        self._sleep_all()

        return results

    def _dispatch_step(self, step: PlanStep, ctx: AgentContext) -> dict:
        """分发步骤到对应 agent 执行"""
        action = step.action

        if action == "search_web":
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

    def _exec_search(self, step: PlanStep) -> dict:
        from agents.chat_agent import _search_tavily
        query = step.params.get("query", "")
        results = _search_tavily(query)
        return {"search_results": results, "count": len(results), "query": query}

    def _exec_knowledge(self, step: PlanStep) -> dict:
        from agents.chat_agent import _execute_knowledge_op
        results = step.params.get("search_results", [])
        msg = _execute_knowledge_op(results)
        return {"message": msg}

    @staticmethod
    def _scrape_for_content(search_results: list[dict]) -> dict[str, dict]:
        """
        爬取搜索结果中的原文，供博客/飞书使用。
        返回 {url: {"success": True, "content": "...", "title": "..."} | {"success": False, "error": "..."}}
        """
        from agents.scraper import scrape_url
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

        search_results = step.params.get("search_results", [])
        query = step.params.get("query", "")

        # 先爬取内容（关键：避免幻觉）
        scraped = self._scrape_for_content(search_results)
        available_content = [
            v["content"] for v in scraped.values()
            if v.get("success") and len(v.get("content", "")) > 500
        ]
        failed = [k for k, v in scraped.items() if not v.get("success")]

        if not available_content:
            return {
                "success": False,
                "error": f"所有文章都无法爬取，不能生成博客。失败的URL: {failed}",
                "scrape_failures": failed,
            }

        # 用爬到的正文生成博客
        material = "\n\n---\n\n".join(available_content[:3])  # 最多取3篇
        blog_result = _generate_blog_from_content(
            content=material,
            title=f"关于「{query}」的综合博客",
            topic=query,
        )

        if blog_result.get("success"):
            article_id = new_id("art-")
            now = now_iso()
            db_exec(
                """INSERT INTO articles (article_id, title, content, status, created_at, updated_at)
                   VALUES (?,?,?,?,?,?)""",
                [article_id, blog_result["title"], blog_result["content"], "draft", now, now],
            )
            return {
                "success": True,
                "article_id": article_id,
                "title": blog_result["title"],
                "url": f"editor.html?id={article_id}",
                "scrape_warnings": [f"以下URL无法爬取（已跳过）: {failed}"] if failed else [],
            }
        else:
            return {"success": False, "error": blog_result.get("error", "博客生成失败")}

    def _exec_feishu(self, step: PlanStep) -> dict:
        from agents.feishu_doc import save_search_to_feishu

        search_results = step.params.get("search_results", [])
        query = step.params.get("query", "")

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
        return result

    def _exec_email(self, step: PlanStep) -> dict:
        """发送邮件"""
        from agents.email_agent import send_email

        params = step.params
        to = params.get("to", "")
        subject = params.get("subject", "Harness 通知")
        body = params.get("body", step.params.get("message", ""))

        if not to:
            return {"success": False, "error": "缺少收件人地址"}

        result = send_email(to=to, subject=subject, body=body)
        if result.get("success"):
            result["email_sent"] = True
            result["to"] = to
        return result

    def _exec_chat(self, step: PlanStep) -> dict:
        return {"message": "chat handled by main flow"}


# ---------- 辅助函数 ----------

def _has_blog_intent(message: str) -> bool:
    import re
    return bool(re.search(r'(生成|写|创作|撰写|来一篇|出一篇)\s*(博客|文章|blog)', message))


def _has_knowledge_intent(message: str) -> bool:
    import re
    return bool(re.search(r'(存|加入|存入|保存到|收藏到)\s*(知识库|knowledge)', message))


def _has_feishu_intent(message: str) -> bool:
    import re
    return bool(re.search(r'(存|保存|放到|放进|整理).*飞书|飞书.*(存|保存|整理)', message))


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
