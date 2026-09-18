import json
import os
import shutil
import subprocess
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(TESTS_DIR, "..", "scripts")
MARK_BRANCH_SH = os.path.join(SCRIPTS_DIR, "mark-branch.sh")

STATE_MARKERS = {
    "running": "🚧",
    "awaiting-review": "👀",
    "merged": "✅",
    "pr-opened": "📬",
    "failed": "❌",
    "stopped": "🛑",
    "crashed": "💥",
}


def run(cwd, *args, check=None, env=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env)
    if check is not None and result.returncode != check:
        raise AssertionError(f"{args} exited {result.returncode} (expected {check})\n{result.stdout}\n{result.stderr}")
    return result


class TestMarkBranch(unittest.TestCase):
    """A real git repo with a real wt on PATH; no bd or worktree needed."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="mark-branch-test-")
        run(self.repo, "git", "init", "-q", "-b", "main", check=0)
        run(self.repo, "git", "config", "user.email", "test@test.com", check=0)
        run(self.repo, "git", "config", "user.name", "test", check=0)
        with open(os.path.join(self.repo, "README.md"), "w") as f:
            f.write("hi\n")
        run(self.repo, "git", "add", "README.md", check=0)
        run(self.repo, "git", "commit", "-q", "-m", "init", check=0)
        run(self.repo, "git", "branch", "feature", check=0)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def mark(self, *args, check=None, env=None):
        return run(self.repo, MARK_BRANCH_SH, *args, check=check, env=env)

    def marker_for(self, branch):
        result = run(self.repo, "git", "config", "--get", f"worktrunk.state.{branch}.marker", check=None)
        if result.returncode != 0:
            return None
        return json.loads(result.stdout)["marker"]

    def test_each_state_sets_the_branchs_marker(self):
        for state, emoji in STATE_MARKERS.items():
            with self.subTest(state=state):
                self.mark("feature", state, check=0)
                self.assertEqual(self.marker_for("feature"), emoji)

    def test_clear_removes_the_marker(self):
        self.mark("feature", "running", check=0)
        self.assertIsNotNone(self.marker_for("feature"))

        self.mark("feature", "clear", check=0)

        self.assertIsNone(self.marker_for("feature"))

    def test_unknown_state_exits_2(self):
        result = self.mark("feature", "bogus", check=2)
        self.assertNotEqual(result.stderr.strip(), "")

    def test_wrong_argument_count_exits_2(self):
        self.mark("feature", check=2)
        self.mark(check=2)

    def test_exits_0_when_wt_is_not_on_path(self):
        env = dict(os.environ)
        env["PATH"] = "/usr/bin:/bin"
        result = self.mark("feature", "running", check=0, env=env)
        self.assertEqual(result.stdout, "")


if __name__ == "__main__":
    unittest.main()
