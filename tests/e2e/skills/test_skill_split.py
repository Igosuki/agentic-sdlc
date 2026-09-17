import os
import subprocess
import sys
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILLS_DIR)
sys.path.insert(0, os.path.dirname(SKILLS_DIR))
from sandbox import new_project  # noqa: E402
from session import Session  # noqa: E402
from helpers import bd_json, descendants, git_head, transcript_events  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"

DESIGN_DOC = """# Todo CLI

A command-line todo list in Python, storing its state in a JSON file.

## Goals and non-goals

Goals: add, list and done commands. Non-goals: editing or removing entries.

## Contracts

- Storage: `todo.json` in the current directory, a JSON array of
  `{"id": int, "text": str, "done": bool}`.
- `todo add <text>`: appends a new entry, `done: false`, prints its id.
- `todo list`: prints every entry, one per line, `[x]` or `[ ]` then the text.
- `todo done <id>`: sets `done: true` for the entry with that id.

## Decisions

Plain `argparse` and the standard library `json` module: no dependencies to install.
"""

ANSWERS = {r".*": r"[Yy]es|[Aa]pprove"}


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillSplit(unittest.TestCase):
    def test_split_design_doc(self):
        project = new_project("split", files={"docs/design/todo.md": DESIGN_DOC})
        before_head = git_head(project.repo)

        session = Session(project.repo, "split", answers=ANSWERS)
        session.run("/sdlc:split docs/design/todo.md")

        self.assertEqual(git_head(project.repo), before_head, "split must not commit")

        epics = bd_json(project.repo, "list", "--type", "epic", "--no-parent")
        self.assertEqual(len(epics), 1, f"expected one top-level epic, got {epics}")
        epic_id = epics[0]["id"]

        tasks = [b for b in descendants(project.repo, epic_id) if b["issue_type"] != "epic"]
        self.assertGreaterEqual(len(tasks), 2, f"expected at least two tasks, got {tasks}")
        for t in tasks:
            self.assertTrue(t.get("acceptance_criteria"), f"{t['id']} missing acceptance_criteria")
            meta = t.get("metadata") or {}
            for field in ("scope", "verify", "complexity", "review"):
                self.assertTrue(meta.get(field), f"{t['id']} missing metadata.{field}")

        validate = subprocess.run(
            ["bd", "swarm", "validate", epic_id], cwd=project.repo, capture_output=True, text=True
        )
        self.assertEqual(validate.returncode, 0, f"bd swarm validate {epic_id} failed:\n{validate.stdout}\n{validate.stderr}")

        logfile = os.path.join(project.logs, "split.jsonl")
        events = transcript_events(logfile)
        create_idx = [
            i
            for i, e in enumerate(events)
            if e[0] == "tool" and e[1] == "Bash" and "create-task.sh" in str(e[2].get("command", ""))
        ]
        question_idx = [i for i, e in enumerate(events) if e[0] == "question"]
        self.assertTrue(create_idx, "no beads were created")
        self.assertTrue(question_idx, "no approval question was asked")
        self.assertLess(
            max(create_idx), max(question_idx), "the approval question came before the last bead was created"
        )


if __name__ == "__main__":
    unittest.main()
