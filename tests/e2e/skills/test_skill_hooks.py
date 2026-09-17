import os
import subprocess
import sys
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILLS_DIR)
sys.path.insert(0, os.path.dirname(SKILLS_DIR))
from sandbox import new_project  # noqa: E402
from session import Session  # noqa: E402
from helpers import git_head  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"

PACKAGE_JSON = """{
  "name": "hooks-fixture",
  "version": "1.0.0",
  "scripts": {
    "test": "node --test"
  }
}
"""
PACKAGE_LOCK = """{
  "name": "hooks-fixture",
  "lockfileVersion": 3
}
"""
CI_WORKFLOW = """name: CI
on: [push]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm ci
      - run: npm test
"""

# multiSelect: matching every option label selects all of them, per the "select all" row.
ANSWERS = {r".*": r".*"}


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillHooks(unittest.TestCase):
    def test_hooks_select_all(self):
        project = new_project(
            "hooks",
            files={
                "package.json": PACKAGE_JSON,
                "package-lock.json": PACKAGE_LOCK,
                ".github/workflows/ci.yml": CI_WORKFLOW,
            },
        )
        before_head = git_head(project.repo)
        session = Session(project.repo, "hooks", answers=ANSWERS)

        session.run("/sdlc:hooks")

        toml_path = os.path.join(project.repo, ".config", "wt.toml")
        self.assertTrue(os.path.isfile(toml_path), ".config/wt.toml was not written")
        with open(toml_path) as f:
            toml = f.read()

        self.assertIn("pre-start", toml)
        self.assertIn("npm ci", toml)
        self.assertIn("pre-merge", toml)
        self.assertIn("npm test", toml)
        for hook in ("pre-commit", "post-commit", "post-merge", "pre-switch", "post-switch"):
            self.assertNotIn(hook, toml, f"{hook} should never be suggested")

        show = subprocess.run(["wt", "hook", "show"], cwd=project.repo, capture_output=True, text=True)
        self.assertEqual(show.returncode, 0, f"wt hook show failed:\n{show.stdout}\n{show.stderr}")

        self.assertEqual(git_head(project.repo), before_head, "hooks should not commit")


if __name__ == "__main__":
    unittest.main()
