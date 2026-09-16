import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "scripts", "close-prs.sh"
)

FAKE_GH = """#!/usr/bin/env bash
if [[ "$1" == pr && "$2" == view ]]; then
  echo "${FAKE_GH_STATE:-OPEN}"
  exit 0
fi
exit 1
"""


def run(cwd, *args, env=None, check=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env)
    if check is not None and result.returncode != check:
        raise AssertionError(f"{args} exited {result.returncode} (expected {check})\n{result.stdout}\n{result.stderr}")
    return result


class BdRepoTestCase(unittest.TestCase):
    """A real bd repository in a throwaway git repo, with a fake gh on PATH."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="close-prs-test-")
        run(self.repo, "git", "init", "-q")
        run(self.repo, "git", "config", "user.email", "test@test.com")
        run(self.repo, "git", "config", "user.name", "test")
        run(self.repo, "bd", "init", "-q")

        self.bin = tempfile.mkdtemp(prefix="close-prs-bin-")
        gh_path = os.path.join(self.bin, "gh")
        with open(gh_path, "w") as f:
            f.write(FAKE_GH)
        st = os.stat(gh_path)
        os.chmod(gh_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.bin, ignore_errors=True)

    def bd(self, *args, check=0):
        return run(self.repo, "bd", *args, check=check)

    def bd_id(self, *args):
        return self.bd(*args, "--silent").stdout.strip()

    def show(self, bead_id):
        return json.loads(self.bd("show", bead_id, "--json").stdout)[0]

    def comments(self, bead_id):
        return json.loads(self.bd("comments", bead_id, "--json").stdout)

    def close_prs(self, *args, gh_state=None, check=0):
        env = dict(self.env)
        if gh_state is not None:
            env["FAKE_GH_STATE"] = gh_state
        return run(self.repo, SCRIPT, *args, env=env, check=check)

    def make_pr_task(self, blocked, pr="https://github.com/x/y/pull/1"):
        epic = self.bd_id("create", "--title", "Epic", "--type", "epic")
        task = self.bd_id(
            "create", "--title", "Task", "--type", "task", "--parent", epic, "--metadata", '{"verify": "true"}'
        )
        self.bd(
            "update", task, "--claim",
            "--set-metadata", "dispatch_state=pr-opened",
            "--set-metadata", f"dispatch_pr={pr}",
        )
        if blocked:
            self.bd("gate", "create", "--type=gh:pr", "--blocks", task, "--await-id=1", "--reason", "pull request test")
        return epic, task


class TestMergedPr(BdRepoTestCase):
    def test_merged_pr_closes_task_and_epic(self):
        epic, task = self.make_pr_task(blocked=False)

        result = self.close_prs(task)

        self.assertIn(f"closed {task}", result.stdout)
        self.assertIn(f"closed {epic}", result.stdout)
        self.assertEqual(self.show(task)["status"], "closed")
        self.assertEqual(self.show(task)["metadata"]["dispatch_state"], "merged")
        self.assertEqual(self.show(epic)["status"], "closed")


class TestOpenPr(BdRepoTestCase):
    def test_open_pr_changes_nothing(self):
        epic, task = self.make_pr_task(blocked=True)

        result = self.close_prs(task, gh_state="OPEN")

        self.assertEqual(result.stdout, "")
        bead = self.show(task)
        self.assertEqual(bead["status"], "in_progress")
        self.assertEqual(bead["metadata"]["dispatch_state"], "pr-opened")
        self.assertEqual(self.show(epic)["status"], "open")
        self.assertEqual(self.comments(task), [])


class TestClosedUnmergedPr(BdRepoTestCase):
    def test_closed_unmerged_pr_stops_task(self):
        epic, task = self.make_pr_task(blocked=True, pr="https://github.com/x/y/pull/9")

        result = self.close_prs(task, gh_state="CLOSED")

        self.assertIn(f"stopped {task}", result.stdout)
        bead = self.show(task)
        self.assertEqual(bead["status"], "in_progress")
        self.assertEqual(bead["metadata"]["dispatch_state"], "stopped")
        self.assertEqual(self.show(epic)["status"], "open")
        comments = self.comments(task)
        self.assertEqual(len(comments), 1)
        self.assertIn("https://github.com/x/y/pull/9", comments[0]["text"])


class TestArguments(BdRepoTestCase):
    def test_no_argument_exits_2(self):
        result = self.close_prs(check=2)
        self.assertEqual(result.stdout, "")

    def test_two_arguments_exits_2(self):
        result = self.close_prs("a", "b", check=2)
        self.assertEqual(result.stdout, "")

    def test_help_exits_0(self):
        result = self.close_prs("-h", check=0)
        self.assertIn("Usage: close-prs.sh", result.stdout)


class TestWrongState(BdRepoTestCase):
    def test_task_not_pr_opened_exits_2(self):
        task = self.bd_id("create", "--title", "T", "--type", "task", "--metadata", '{"verify": "true"}')

        result = self.close_prs(task, check=2)

        self.assertEqual(result.stdout, "")
        self.assertIn(task, result.stderr)


if __name__ == "__main__":
    unittest.main()
