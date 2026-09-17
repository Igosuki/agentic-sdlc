import os
import sys
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SKILLS_DIR))
from sandbox import dispatched, new_project, task  # noqa: E402
from session import Session  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillStatus(unittest.TestCase):
    """/sdlc:status is pure display: its `!` lines run workers.py, next-tasks.py and
    settings.sh before the model sees the turn, so the model makes no tool call."""

    @classmethod
    def setUpClass(cls):
        cls.project = new_project("status")
        cls.stopped = task(cls.project, "Stopped task")
        cls.failed = task(cls.project, "Failed task")
        cls.review = task(cls.project, "Awaiting review task")
        cls.ready = task(cls.project, "Ready task")
        dispatched(cls.project, cls.stopped, "stopped")
        dispatched(cls.project, cls.failed, "failed")
        dispatched(cls.project, cls.review, "awaiting-review")

        cls.session = Session(cls.project.repo, "status")
        cls.result = cls.session.run("/sdlc:status")

    def test_prompt_is_expanded_with_no_tool_calls(self):
        self.assertEqual(self.result.tools, [])
        self.assertEqual(self.result.prompts, [])
        self.assertEqual(self.result.skills, ["status"])

    def test_reply_points_at_recovering_the_stopped_and_failed_tasks(self):
        self.assertIn(f"/sdlc:recover {self.stopped}", self.result.text)
        self.assertIn(f"/sdlc:recover {self.failed}", self.result.text)

    def test_reply_carries_the_ready_task(self):
        self.assertIn(self.ready, self.result.text)


if __name__ == "__main__":
    unittest.main()
