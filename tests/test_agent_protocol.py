from __future__ import annotations

import unittest

from tools.agent_protocol_tool import (
    build_agent_result,
    ensure_step_params,
    normalize_knowledge_hits,
    normalize_search_results,
)


class AgentProtocolToolTests(unittest.TestCase):
    def test_normalize_search_results_filters_invalid_rows(self):
        rows = normalize_search_results([
            {"title": "A", "url": "https://a.com", "snippet": "x"},
            {"title": "", "url": "https://b.com"},
            {"title": "C", "url": ""},
        ])
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["title"], "A")

    def test_ensure_step_params_requires_search_results_for_feishu(self):
        with self.assertRaises(ValueError):
            ensure_step_params("save_to_feishu", {"search_results": []})

    def test_build_agent_result_normalizes_hits(self):
        hits = normalize_knowledge_hits([{
            "article_id": "art-1",
            "chunk_id": "chunk-1",
            "chunk_text": "hello",
            "score": 0.88,
            "article": {"title": "KB", "url": "https://kb.local"},
        }])
        result = build_agent_result("knowledge_hits", knowledge_hits=hits)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["knowledge_hits"][0]["title"], "KB")


if __name__ == "__main__":
    unittest.main()
