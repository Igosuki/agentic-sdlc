import os
import sys
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILLS_DIR)
sys.path.insert(0, os.path.dirname(SKILLS_DIR))
from sandbox import dispatched, new_project, task  # noqa: E402
from session import Session  # noqa: E402
from helpers import branch_exists, worktree_branches  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"


def _leftover_task(project, title):
    task_id = task(project, title)
    return task_id, dispatched(project, task_id, "closed")


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillClean(unittest.TestCase):
    def test_clean_apply(self):
        project = new_project("clean")
        task_id, d = _leftover_task(project, "Leftover")
        self.assertIn(d.branch, worktree_branches(project.repo))

        session = Session(project.repo, "clean", answers={r".*": r"(?i)^yes"})
        result = session.run("/sdlc:clean")

        ran_apply = any(
            t["name"] == "Bash" and "clean.sh" in str((t["input"] or {}).get("command", "")) and "--apply" in str(
                (t["input"] or {}).get("command", "")
            )
            for t in result.tools
        )
        self.assertTrue(ran_apply, "clean.sh --apply did not run")

        self.assertNotIn(d.branch, worktree_branches(project.repo))
        self.assertFalse(branch_exists(project.repo, d.branch), f"branch {d.branch} should be gone")

    def test_clean_headless_lists_only(self):
        project = new_project("clean-headless")
        task_id, d = _leftover_task(project, "Leftover headless")
        self.assertIn(d.branch, worktree_branches(project.repo))

        session = Session(project.repo, "clean-headless", interactive=False)
        result = session.run("/sdlc:clean")

        for t in result.tools:
            if t["name"] != "Bash":
                continue
            command = str((t["input"] or {}).get("command", ""))
            self.assertNotIn("--apply", command, "clean.sh --apply ran in a headless session")

        self.assertIn(d.branch, worktree_branches(project.repo))
        self.assertTrue(branch_exists(project.repo, d.branch))
        self.assertIn("--apply", result.said)


if __name__ == "__main__":
    unittest.main()
