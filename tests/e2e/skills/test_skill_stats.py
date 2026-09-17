import os
import re
import sys
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SKILLS_DIR))
from sandbox import dispatched, new_project, task  # noqa: E402
from session import Session  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"
COST_RE = re.compile(r"\$\d+\.\d{2}")


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillStats(unittest.TestCase):
    """/sdlc:stats runs stats.py through its `!` line, so the model makes no tool call."""

    @classmethod
    def setUpClass(cls):
        cls.project = new_project("stats")
        cls.epic = task(cls.project, "Stats epic", type="epic")
        cls.task_a = task(cls.project, "Task A", parent=cls.epic)
        cls.task_b = task(cls.project, "Task B", parent=cls.epic)
        dispatched(cls.project, cls.task_a, "stopped")
        dispatched(cls.project, cls.task_b, "failed")

        cls.session = Session(cls.project.repo, "stats")
        cls.result = cls.session.run(f"/sdlc:stats {cls.epic}")

    def test_prompt_is_expanded_with_no_tool_calls(self):
        self.assertEqual(self.result.tools, [])
        self.assertEqual(self.result.prompts, [])
        self.assertEqual(self.result.skills, ["stats"])

    def test_reply_lists_both_tasks_with_a_cost(self):
        self.assertIn(self.task_a, self.result.text)
        self.assertIn(self.task_b, self.result.text)
        self.assertRegex(self.result.text, COST_RE)


if __name__ == "__main__":
    unittest.main()
