from __future__ import annotations

import unittest
from datetime import datetime, timezone

from agents.digest_agent import evaluate_subscription_schedule, find_due_slot


class DigestAgentTests(unittest.TestCase):
    def test_find_due_slot_matches_same_minute_in_timezone(self):
        now_utc = datetime(2026, 7, 3, 23, 30, tzinfo=timezone.utc)
        due = find_due_slot("30 7 * * *", "Asia/Shanghai", now_utc=now_utc, lookback_minutes=0)
        self.assertIsNotNone(due)
        self.assertEqual(due.hour, 7)
        self.assertEqual(due.minute, 30)

    def test_find_due_slot_uses_lookback_window(self):
        now_utc = datetime(2026, 7, 3, 23, 37, tzinfo=timezone.utc)
        due = find_due_slot("30 7 * * *", "Asia/Shanghai", now_utc=now_utc, lookback_minutes=10)
        self.assertIsNotNone(due)
        self.assertEqual(due.minute, 30)

    def test_evaluate_subscription_schedule_not_due_when_outside_window(self):
        subscription = {
            "subscription_id": "sub-test",
            "enabled": 1,
            "schedule_cron": "30 7 * * *",
            "timezone": "Asia/Shanghai",
        }
        now_utc = datetime(2026, 7, 3, 23, 50, tzinfo=timezone.utc)
        result = evaluate_subscription_schedule(subscription, now_utc=now_utc, lookback_minutes=10)
        self.assertFalse(result["due"])
        self.assertEqual(result["reason"], "not_due")


if __name__ == "__main__":
    unittest.main()
