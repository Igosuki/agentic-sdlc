import json
import os
import sys
import time
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
from test_tasks import BdRepoTestCase, run  # noqa: E402

SCRIPTS_DIR = os.path.join(TESTS_DIR, "..", "skills", "dispatch", "scripts")
STATS_PY = os.path.join(SCRIPTS_DIR, "stats.py")


class TestStats(BdRepoTestCase):
    def stats(self, *args, check=True):
        return run(self.repo, sys.executable, STATS_PY, *args, check=check)

    def record_event(self, task_id, kind, session, cost, seconds, model="sonnet", agents=None):
        payload = json.dumps(
            {"session": session, "cost_usd": cost, "duration_s": seconds, "model": model, "agents": agents or []}
        )
        event = self.create(
            "create", f"{task_id} {kind}", "--type", "event", "--event-target", task_id,
            "--event-category", f"dispatch.{kind}", "--event-actor", "implementer", "--event-payload", payload,
            "--description", "final message",
        )
        self.bd("close", event)
        time.sleep(1.1)  # created_at has second resolution; events must sort by time.
        return event

    def test_no_recorded_attempts(self):
        result = self.stats()
        self.assertEqual(result.stdout.strip(), "no recorded attempts")

    def test_credits_a_nested_task_to_the_real_epic(self):
        epic = self.create("create", "--title", "Epic", "--type", "epic")
        parent = self.create("create", "--title", "Parent", "--type", "task", "--parent", epic)
        leaf = self.create(
            "create", "--title", "Leaf", "--type", "task", "--parent", parent, "--metadata", '{"verify": "true"}'
        )
        self.record_event(leaf, "merged", "s1", 0.5, 60)

        result = self.stats()
        self.assertIn(f"epic {epic}", result.stdout)
        self.assertNotIn(f"epic {parent}", result.stdout)

    def test_keeps_only_the_latest_event_per_session(self):
        task = self.create("create", "--title", "Task", "--type", "task", "--metadata", '{"verify": "true"}')
        self.record_event(task, "stopped", "s1", 0.10, 30)
        self.record_event(task, "merged", "s1", 0.40, 90)  # cumulative total for the resumed session

        result = self.stats()
        self.assertIn("1 attempt ", result.stdout)  # not 2
        self.assertIn("$0.40", result.stdout)  # not $0.50
        self.assertNotIn("$0.50", result.stdout)

    def test_includes_review_cost(self):
        task = self.create("create", "--title", "Task", "--type", "task", "--metadata", '{"verify": "true"}')
        self.bd("update", task, "--set-metadata", "dispatch_review_cost=0.75")
        self.record_event(task, "merged", "s1", 0.25, 10)

        result = self.stats()
        self.assertIn("review $0.75", result.stdout)
        self.assertIn("total: 1 tasks, $1.00,", result.stdout)

    def test_epic_as_plain_argument_and_as_flag_agree(self):
        epic = self.create("create", "--title", "Epic", "--type", "epic")
        task = self.create(
            "create", "--title", "Task", "--type", "task", "--parent", epic, "--metadata", '{"verify": "true"}'
        )
        self.record_event(task, "merged", "s1", 0.10, 5)

        by_position = self.stats(epic).stdout
        by_flag = self.stats("--epic", epic).stdout
        self.assertEqual(by_position, by_flag)
        self.assertIn(task, by_position)

    def test_both_positional_and_flag_is_an_error(self):
        result = self.stats("epic-a", "--epic", "epic-b", check=False)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
