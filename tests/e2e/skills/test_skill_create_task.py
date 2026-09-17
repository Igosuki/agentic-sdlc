import os
import sys
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILLS_DIR)
sys.path.insert(0, os.path.dirname(SKILLS_DIR))
from sandbox import new_project  # noqa: E402
from session import Session  # noqa: E402
from helpers import bd_json, create_task  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"

CLI_PY = """import argparse


def main():
    parser = argparse.ArgumentParser(prog="cli")
    parser.add_argument("command")
    parser.parse_args()


if __name__ == "__main__":
    main()
"""


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillCreateTask(unittest.TestCase):
    def test_create_task_waits_on_overlapping_scope(self):
        project = new_project("create-task", files={"src/cli.py": CLI_PY})
        epic_id = create_task(
            project.repo, "--type", "epic", "--title", "CLI", "--description", "Small CLI tool"
        )
        open_task_id = create_task(
            project.repo,
            "--parent", epic_id,
            "--title", "Add subcommands to src/cli.py",
            "--description", "Wire up the add/list/done subcommands.",
            "--acceptance", "cli.py has add, list and done subcommands",
            "--scope", "src/",
            "--verify", "python3 -m py_compile src/cli.py",
            "--complexity", "small",
        )
        before_ids = {b["id"] for b in bd_json(project.repo, "list")}

        session = Session(project.repo, "create-task")
        session.run(f"/sdlc:create-task add a --version flag to src/cli.py --parent {epic_id}")

        after = bd_json(project.repo, "list")
        new_beads = [b for b in after if b["id"] not in before_ids]
        self.assertEqual(len(new_beads), 1, f"expected exactly one new bead, got {new_beads}")
        new_task = new_beads[0]

        self.assertEqual(new_task["issue_type"], "task")
        self.assertTrue(new_task.get("acceptance_criteria"), "new task missing acceptance_criteria")
        meta = new_task.get("metadata") or {}
        for field in ("scope", "verify", "complexity", "review"):
            self.assertTrue(meta.get(field), f"new task missing metadata.{field}")

        shown = bd_json(project.repo, "show", new_task["id"])[0]
        self.assertEqual(shown.get("parent"), epic_id, "new task is not under the epic")

        deps = [d["id"] for d in shown.get("dependencies") or []]
        self.assertIn(open_task_id, deps, "new task doesn't wait on the overlapping open task")


if __name__ == "__main__":
    unittest.main()
