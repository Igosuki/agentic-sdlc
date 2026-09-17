import os
import sys
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SKILLS_DIR))
from sandbox import dispatched, new_project, task  # noqa: E402
from session import Session  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillLogs(unittest.TestCase):
    """/sdlc:logs runs logs.py through its `!` line, so the model makes no tool call."""

    @classmethod
    def setUpClass(cls):
        cls.project = new_project("logs")
        cls.task = task(cls.project, "Logged task")
        dispatched(cls.project, cls.task, "stopped")

        cls.session = Session(cls.project.repo, "logs")
        cls.result = cls.session.run(f"/sdlc:logs {cls.task}")

    def test_prompt_is_expanded_with_no_tool_calls(self):
        self.assertEqual(self.result.tools, [])
        self.assertEqual(self.result.prompts, [])
        self.assertEqual(self.result.skills, ["logs"])

    def test_reply_shows_the_log_and_points_at_fork_session(self):
        self.assertIn("run started", self.result.text)
        self.assertIn("--fork-session", self.result.text)


if __name__ == "__main__":
    unittest.main()
