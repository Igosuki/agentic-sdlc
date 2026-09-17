import os
import sys
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILLS_DIR)
sys.path.insert(0, os.path.dirname(SKILLS_DIR))
from sandbox import new_project  # noqa: E402
from session import Session  # noqa: E402
from helpers import git_log_subjects, setting  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"

ANSWERS = {
    r"(?i)integrat": r"^epic-merge",
    r"[Tt]arget": r"\bmain\b",
    r"build": r"^Yes",
    r"[Cc]ommit": r"^Yes",
}


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillInit(unittest.TestCase):
    def test_init_first_time(self):
        project = new_project("init", init=False)
        session = Session(project.repo, "init", answers=ANSWERS)

        session.run("/sdlc:init")

        self.assertTrue(os.path.isdir(os.path.join(project.repo, ".beads")))
        self.assertEqual(setting(project.repo, "integration"), "epic-merge")
        self.assertEqual(setting(project.repo, "target"), "main")
        self.assertEqual(setting(project.repo, "workflow"), "build")

        with open(os.path.join(project.repo, ".gitignore")) as f:
            gitignore = f.read()
        self.assertIn(".claude/*.local.md", gitignore)
        self.assertIn(".worktrees/", gitignore)

        subjects = git_log_subjects(project.repo)
        self.assertEqual(subjects[0], "Ignore sdlc local files")

    def test_init_again_headless_keeps_settings(self):
        project = new_project("init-again", integration="epic-merge")
        before = git_log_subjects(project.repo)

        session = Session(project.repo, "init-again", interactive=False)
        session.run("/sdlc:init --parallel 3")

        self.assertEqual(setting(project.repo, "integration"), "epic-merge")
        self.assertEqual(setting(project.repo, "parallel"), "3")
        self.assertEqual(git_log_subjects(project.repo), before)


if __name__ == "__main__":
    unittest.main()
