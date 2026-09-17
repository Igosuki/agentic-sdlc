import os
import subprocess
import sys
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILLS_DIR)
sys.path.insert(0, os.path.dirname(SKILLS_DIR))
from sandbox import new_project  # noqa: E402
from session import Session  # noqa: E402
from helpers import bd_json, git_head, git_status  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"

README = """# things

A small command-line tool for tracking things, backed by a JSON file.

## Commands

- `things add <text>`: add a thing
- `things list`: print every thing, one per line
- `things done <id>`: mark a thing done

See docs/usage.md for details.
"""
USAGE_MD = """# Usage

## things list

Prints every stored thing, one per line, in the order they were added.
Done things are shown with a leading `x`.

## things add <text>

Appends a new thing to the JSON store.

## things done <id>

Marks the thing with the given id as done.
"""


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillDesign(unittest.TestCase):
    def test_design_add_json_flag(self):
        project = new_project(
            "design", files={"README.md": README, "docs/usage.md": USAGE_MD}
        )
        before_head = git_head(project.repo)
        before_status = set(git_status(project.repo).splitlines())
        before_branches = self._branches(project.repo)

        session = Session(project.repo, "design")
        result = session.run("/sdlc:design add a --json flag to the list command")

        # The design is stated mid-conversation and the final turn is only a short report.
        reply = result.said
        self.assertIn("Prior art", reply)
        self.assertIn("Open questions", reply)

        self.assertEqual(bd_json(project.repo, "list"), [], "design must not create beads")
        self.assertEqual(git_head(project.repo), before_head, "design must not commit")
        self.assertEqual(self._branches(project.repo), before_branches, "design must not create branches")

        after_status = set(git_status(project.repo).splitlines())
        new_lines = after_status - before_status
        for line in new_lines:
            self.assertFalse(line.startswith("??"), f"design created a new file: {line}")
            path = line[3:].strip()
            self.assertTrue(path.endswith(".md"), f"design changed a non-markdown file: {line}")

    def _branches(self, repo):
        result = subprocess.run(
            ["git", "branch", "--format=%(refname:short)"], cwd=repo, capture_output=True, text=True
        )
        return set(result.stdout.split())


if __name__ == "__main__":
    unittest.main()
