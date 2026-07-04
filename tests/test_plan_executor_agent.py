from __future__ import annotations

import unittest
from unittest.mock import patch

from agents.plan_executor_agent import PlanExecutor, PlanStep
from tools.article_request_tool import (
    build_refined_search_message,
    build_context_clarification,
    select_followup_context,
)


class PlanExecutorAgentTests(unittest.TestCase):
    def test_followup_action_plan_skips_search_steps(self):
        executor = PlanExecutor(session_id="sess-test", trace_id="trace-test")
        steps = executor.plan(
            "帮我存到飞书里",
            {"intent": "followup_action", "source_query": "帮我找5篇关于RAG的文章"},
        )
        self.assertEqual([step.action for step in steps], ["save_to_feishu"])

    def test_normalize_search_query_removes_followup_actions(self):
        query = "现在帮我找5篇关于RAG的文章存到飞书里"
        self.assertEqual(PlanExecutor._normalize_search_query(query), "RAG 文章")

    @patch("agents.chat_agent._search_tavily")
    def test_search_web_if_needed_supplements_knowledge_results_to_requested_count(self, mock_search_tavily):
        mock_search_tavily.return_value = [
            {"title": "Web A", "url": "https://example.com/a", "snippet": "a"},
            {"title": "Web B", "url": "https://example.com/b", "snippet": "b"},
            {"title": "Web C", "url": "https://example.com/c", "snippet": "c"},
            {"title": "Web D", "url": "https://example.com/d", "snippet": "d"},
            {"title": "Web E", "url": "https://example.com/e", "snippet": "e"},
        ]

        executor = PlanExecutor(session_id="sess-test", trace_id="trace-test")
        executor.step_results[0] = {
            "search_results": [
                {"title": "KB 1", "url": "https://kb.local/1", "snippet": "x"},
                {"title": "KB 2", "url": "https://kb.local/2", "snippet": "y"},
            ]
        }
        step = PlanStep(
            step_id=1,
            agent="search",
            action="search_web_if_needed",
            params={"query": "现在帮我找5篇关于RAG的文章存到飞书里"},
            depends_on=0,
        )

        result = executor._exec_search(step)

        mock_search_tavily.assert_called_once_with("RAG 文章", max_results=5)
        self.assertEqual(result["count"], 5)
        self.assertEqual(len(result["search_results"]), 5)
        self.assertEqual(result["search_results"][0]["title"], "KB 1")
        self.assertEqual(result["search_results"][1]["title"], "KB 2")

    def test_count_refinement_reuses_latest_topic(self):
        message = build_refined_search_message("我要5篇", "帮我找两篇关于RAG的文章")
        self.assertEqual(message, "帮我找5篇关于RAG的文章")

    def test_followup_context_requires_clarification_for_multiple_topics(self):
        contexts = [
            {"search_query": "帮我找5篇关于RAG的文章", "search_results": [{}, {}, {}, {}, {}], "normalized_query": "RAG 文章"},
            {"search_query": "帮我找两篇关于AI的文章", "search_results": [{}, {}], "normalized_query": "AI 文章"},
        ]
        selected = select_followup_context("帮我存到飞书里", contexts)
        self.assertEqual(selected["status"], "ambiguous")
        clarification = build_context_clarification(selected["contexts"])
        self.assertIn("我需要确认你要操作哪一组文章", clarification)

    def test_followup_context_uses_latest_for_explicit_recent_reference(self):
        contexts = [
            {"search_query": "帮我找5篇关于RAG的文章", "search_results": [{}, {}, {}, {}, {}], "normalized_query": "RAG 文章"},
            {"search_query": "帮我找两篇关于AI的文章", "search_results": [{}, {}], "normalized_query": "AI 文章"},
        ]
        selected = select_followup_context("把刚刚那组存到飞书", contexts)
        self.assertEqual(selected["status"], "reuse")
        self.assertEqual(selected["context"]["search_query"], "帮我找5篇关于RAG的文章")


if __name__ == "__main__":
    unittest.main()
