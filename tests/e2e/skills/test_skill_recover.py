import os
import subprocess
import sys
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILLS_DIR)
sys.path.insert(0, os.path.dirname(SKILLS_DIR))
from sandbox import dispatched, new_project, task  # noqa: E402
from session import Session  # noqa: E402
from helpers import bd_json, branch_exists  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"

STOPPED_COMMENT = "Stopped partway through: needs another look at the parser."


def _add_comment(project, task_id, text):
    result = subprocess.run(["bd", "comments", "add", task_id, text], cwd=project.repo, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"bd comments add failed: {result.stderr}")


def _stopped_task(project):
    task_id = task(project, "Fix the parser")
    d = dispatched(project, task_id, "stopped")
    _add_comment(project, task_id, STOPPED_COMMENT)
    return task_id, d


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillRecover(unittest.TestCase):
    def test_recover_start_over(self):
        project = new_project("recover")
        task_id, d = _stopped_task(project)

        session = Session(project.repo, "recover", answers={r".*": r"(?i)^start over"})
        result = session.run(f"/sdlc:recover {task_id}")

        ran_reset = any(
            t["name"] == "Bash" and "reset-task.sh" in str((t["input"] or {}).get("command", ""))
            for t in result.tools
        )
        self.assertTrue(ran_reset, "reset-task.sh did not run")

        info = bd_json(project.repo, "show", task_id)[0]
        self.assertEqual(info["status"], "open")
        self.assertNotIn("dispatch_branch", info.get("metadata") or {})
        self.assertFalse(branch_exists(project.repo, d.branch), f"branch {d.branch} should be gone")

    def test_recover_headless_lists_options(self):
        project = new_project("recover-headless")
        task_id, d = _stopped_task(project)

        session = Session(project.repo, "recover-headless", interactive=False)
        result = session.run(f"/sdlc:recover {task_id}")

        for t in result.tools:
            if t["name"] != "Bash":
                continue
            command = str((t["input"] or {}).get("command", ""))
            for script in ("resume-task.sh", "finish-task.sh", "reset-task.sh"):
                self.assertNotIn(script, command, f"{script} ran in a headless session")

        for option in (r"(?i)resume", r"(?i)finish", r"(?i)start over", r"(?i)split"):
            self.assertRegex(result.said, option)


if __name__ == "__main__":
    unittest.main()
