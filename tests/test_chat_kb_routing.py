from __future__ import annotations

import unittest

from agents.chat_agent import _should_use_kb


class ChatKbRoutingTests(unittest.TestCase):
    def test_kb_used_for_engineering_question(self):
        self.assertTrue(_should_use_kb("如何设计一个带缓存和重试的 Agent 服务"))

    def test_kb_skipped_for_latest_news(self):
        self.assertFalse(_should_use_kb("帮我找最新的 AI 新闻"))

    def test_kb_skipped_when_search_results_already_present(self):
        self.assertFalse(_should_use_kb("RAG 怎么做", has_search_results=True))


if __name__ == "__main__":
    unittest.main()
