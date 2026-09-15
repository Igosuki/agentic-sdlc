import os
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
from test_tasks import BdRepoTestCase, run  # noqa: E402

SCRIPTS_DIR = os.path.join(TESTS_DIR, "..", "skills", "dispatch", "scripts")
NEXT_TASKS_PY = os.path.join(SCRIPTS_DIR, "next-tasks.py")


class TestNextTasks(BdRepoTestCase):
    def next_tasks(self, *args, check=True):
        return run(self.repo, sys.executable, NEXT_TASKS_PY, *args, check=check)

    def test_no_ready_task(self):
        result = self.next_tasks()
        self.assertEqual(result.stdout.strip(), "no ready task to dispatch")

    def test_lists_a_ready_task_with_epic_and_unblock_count(self):
        epic = self.create("create", "--title", "Epic", "--type", "epic")
        blocker = self.create(
            "create", "--title", "Blocker", "--type", "task", "--parent", epic, "--metadata", '{"verify": "true"}'
        )
        blocked = self.create(
            "create", "--title", "Blocked", "--type", "task", "--parent", epic, "--metadata", '{"verify": "true"}'
        )
        self.bd("dep", "add", blocked, blocker)

        result = self.next_tasks()
        line = result.stdout.strip()
        self.assertIn(blocker, line)
        self.assertIn("unblocks 1", line)
        self.assertIn(f"epic {epic}", line)
        self.assertIn("Blocker", line)
        self.assertNotIn(blocked, line)  # not ready yet: still depends on blocker

    def test_ids_option_prints_only_ids(self):
        solo = self.create("create", "--title", "Solo", "--type", "task", "--metadata", '{"verify": "true"}')
        result = self.next_tasks("--ids")
        self.assertEqual(result.stdout.split(), [solo])

    def test_epic_option_filters(self):
        epic1 = self.create("create", "--title", "Epic1", "--type", "epic")
        t1 = self.create(
            "create", "--title", "T1", "--type", "task", "--parent", epic1, "--metadata", '{"verify": "true"}'
        )
        epic2 = self.create("create", "--title", "Epic2", "--type", "epic")
        self.create("create", "--title", "T2", "--type", "task", "--parent", epic2, "--metadata", '{"verify": "true"}')

        result = self.next_tasks("--epic", epic1, "--ids")
        self.assertEqual(result.stdout.split(), [t1])

    def test_unknown_argument_exits_2(self):
        result = self.next_tasks("--bogus", check=False)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
