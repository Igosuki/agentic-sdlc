import os
import re
import sys
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILLS_DIR)
sys.path.insert(0, os.path.dirname(SKILLS_DIR))
from sandbox import dispatched, new_project, task  # noqa: E402
from session import Session  # noqa: E402
from helpers import bd_json  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"

DIVIDE_PY = "def divide(a, b):\n    return a / b\n"
BD_WRITE_RE = re.compile(r"\bbd\s+(update|comments\s+add|gate\s+resolve|close)\b")


def _review_task(project):
    return task(project, "Add divide", acceptance="divide by zero returns an error", scope="src/")


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillReview(unittest.TestCase):
    def test_review_headless_agent_verdict(self):
        project = new_project("review-headless")
        task_id = _review_task(project)
        dispatched(project, task_id, "awaiting-review", gate=False, commits=[{"src/divide.py": DIVIDE_PY}])

        session = Session(project.repo, "review-headless", interactive=False)
        result = session.run(f"/sdlc:review {task_id}")

        self.assertRegex(result.said, r"(?i)request changes")
        self.assertRegex(result.said, r"(?i)divide by zero|ZeroDivisionError")

        for t in result.tools:
            if t["name"] != "Bash":
                continue
            command = str((t["input"] or {}).get("command", ""))
            self.assertNotRegex(command, BD_WRITE_RE, f"headless review wrote to bd: {command}")

    def test_review_gate_approve(self):
        project = new_project("review-gate")
        task_id = _review_task(project)
        d = dispatched(project, task_id, "awaiting-review", commits=[{"src/divide.py": DIVIDE_PY}])
        self.assertIsNotNone(d.gate, "fixture should have opened a human review gate")

        session = Session(project.repo, "review-gate", answers={r".*": r"(?i)^approve"})
        result = session.run(f"/sdlc:review {task_id}")

        resolved = any(
            t["name"] == "Bash" and "bd gate resolve" in str((t["input"] or {}).get("command", "")) and d.gate in str(
                (t["input"] or {}).get("command", "")
            )
            for t in result.tools
        )
        self.assertTrue(resolved, "no `bd gate resolve` call for the open gate")

        gate = bd_json(project.repo, "show", d.gate)[0]
        self.assertEqual(gate["status"], "closed", f"gate {d.gate} was not resolved")


if __name__ == "__main__":
    unittest.main()
