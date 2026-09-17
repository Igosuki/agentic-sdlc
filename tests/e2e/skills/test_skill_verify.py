import os
import sys
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(SKILLS_DIR))
from sandbox import new_project, verify_break  # noqa: E402
from session import Session  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillVerify(unittest.TestCase):
    """verify_break's task has no children, so verify.sh runs its own metadata.verify
    directly: no epic is needed, only the task id (see bd comment on sdlc-260)."""

    @classmethod
    def setUpClass(cls):
        cls.project = new_project("verify")
        cls.task_id, cls.sha = verify_break(cls.project)

        cls.session = Session(cls.project.repo, "verify")
        cls.result = cls.session.run(f"/sdlc:verify {cls.task_id}")

    def test_reply_names_the_task_and_the_breaking_commit(self):
        self.assertIn(self.task_id, self.result.text)
        self.assertIn(self.sha[:7], self.result.text)


if __name__ == "__main__":
    unittest.main()
