import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "scripts")
CLEAN_SH = os.path.join(SCRIPTS_DIR, "clean.sh")
MERGE_QUEUE_SH = os.path.join(SCRIPTS_DIR, "merge-queue.sh")


def run(cwd, *args, check=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check is not None and result.returncode != check:
        raise AssertionError(f"{args} exited {result.returncode} (expected {check})\n{result.stdout}\n{result.stderr}")
    return result


class BdRepoTestCase(unittest.TestCase):
    """A real bd/git/wt repository in a throwaway directory, no stubs."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="clean-test-")
        run(self.repo, "git", "init", "-q", check=0)
        run(self.repo, "git", "config", "user.email", "test@test.com", check=0)
        run(self.repo, "git", "config", "user.name", "test", check=0)
        (open(os.path.join(self.repo, "README.md"), "w")).write("x")
        run(self.repo, "git", "add", "README.md", check=0)
        run(self.repo, "git", "commit", "-q", "-m", "init", check=0)
        self.base = run(self.repo, "git", "branch", "--show-current", check=0).stdout.strip()
        run(self.repo, "bd", "init", "-q", check=0)
        self.processes = []

    def tearDown(self):
        for p in self.processes:
            with contextlib.suppress(Exception):
                p.send_signal(signal.SIGKILL)
                p.wait(timeout=5)
        shutil.rmtree(self.repo, ignore_errors=True)

    def bd(self, *args, check=0):
        return run(self.repo, "bd", *args, check=check)

    def create(self, **metadata):
        args = ["create", "--title", "T", "--type", "task", "--silent"]
        if metadata:
            args += ["--metadata", json.dumps(metadata)]
        return self.bd(*args).stdout.strip()

    def claim(self, task, session, **metadata):
        args = ["update", task, "--claim", "--set-metadata", f"dispatch_session={session}"]
        for key, value in metadata.items():
            args += ["--set-metadata", f"dispatch_{key}={value}"]
        self.bd(*args)

    def worktree(self, branch):
        run(self.repo, "wt", "switch", "--create", branch, "--base", self.base, "--no-cd", "--format", "json", check=0)

    def branch_only(self, branch):
        run(self.repo, "git", "branch", branch, self.base, check=0)

    def branches(self):
        out = run(self.repo, "git", "branch", "--format=%(refname:short)", check=0).stdout
        return out.split()

    def worktree_branches(self):
        data = json.loads(run(self.repo, "wt", "list", "--format", "json", check=0).stdout)
        return [i["branch"] for i in data["items"] if not i["worktree"]["main"]]

    def merge_queue_ensure(self, branch):
        return run(self.repo, MERGE_QUEUE_SH, "ensure", branch, check=0).stdout.strip()

    def merge_queue_acquire(self, branch, holder):
        run(self.repo, MERGE_QUEUE_SH, "acquire", branch, holder, check=0)

    def spawn(self, *extra_argv):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", *extra_argv], cwd=self.repo)
        self.processes.append(p)
        time.sleep(0.3)
        return p

    def clean(self, *args, check=0):
        return run(self.repo, CLEAN_SH, *args, check=check)


class TestNothingToClean(BdRepoTestCase):
    def test_empty_repo_lists_nothing(self):
        result = self.clean()
        self.assertEqual(result.stdout, "")

    def test_apply_on_empty_repo_lists_nothing(self):
        result = self.clean("--apply")
        self.assertEqual(result.stdout, "")


class TestClosedTaskWorktree(BdRepoTestCase):
    def setUp(self):
        super().setUp()
        self.task = self.create(verify="true")
        self.worktree(self.task)
        self.claim(self.task, "s1", branch=self.task, base=self.base)
        self.bd("close", self.task)

    def test_listed_with_reason(self):
        result = self.clean()
        self.assertIn(f"worktree {self.task}", result.stdout)
        self.assertIn("closed task", result.stdout)

    def test_apply_removes_worktree_and_branch(self):
        self.clean("--apply")
        self.assertNotIn(self.task, self.worktree_branches())
        self.assertNotIn(self.task, self.branches())

    def test_second_run_after_apply_lists_nothing(self):
        self.clean("--apply")
        result = self.clean()
        self.assertEqual(result.stdout, "")


class TestResetTaskWorktree(BdRepoTestCase):
    def setUp(self):
        super().setUp()
        self.task = self.create(verify="true")
        self.worktree(self.task)
        # open, never claimed (or claimed then reset): no dispatch_branch set.

    def test_listed_as_reset(self):
        result = self.clean()
        self.assertIn(f"worktree {self.task}", result.stdout)
        self.assertIn("reset", result.stdout)

    def test_apply_removes_it(self):
        self.clean("--apply")
        self.assertNotIn(self.task, self.worktree_branches())
        self.assertNotIn(self.task, self.branches())
        self.assertEqual(self.clean().stdout, "")


class TestProtectedTasks(BdRepoTestCase):
    def test_claimed_task_worktree_is_never_listed(self):
        task = self.create(verify="true")
        self.worktree(task)
        self.claim(task, "s1", branch=task, base=self.base)

        result = self.clean()
        self.assertEqual(result.stdout, "")
        self.clean("--apply")
        self.assertIn(task, self.worktree_branches())

    def test_stopped_task_worktree_is_never_listed(self):
        task = self.create(verify="true")
        self.worktree(task)
        self.claim(task, "s1", branch=task, base=self.base, state="stopped")

        self.assertEqual(self.clean().stdout, "")
        self.clean("--apply")
        self.assertIn(task, self.worktree_branches())

    def test_failed_task_worktree_is_never_listed(self):
        task = self.create(verify="true")
        self.worktree(task)
        self.claim(task, "s1", branch=task, base=self.base, state="failed")

        self.assertEqual(self.clean().stdout, "")

    def test_awaiting_review_task_worktree_is_never_listed(self):
        task = self.create(verify="true")
        self.worktree(task)
        self.claim(task, "s1", branch=task, base=self.base, state="awaiting-review")

        self.assertEqual(self.clean().stdout, "")

    def test_main_checkout_is_never_listed(self):
        result = self.clean()
        self.assertNotIn(self.base, result.stdout)


class TestClosedTaskBranchOnly(BdRepoTestCase):
    def setUp(self):
        super().setUp()
        self.task = self.create(verify="true")
        self.branch_only(self.task)
        self.claim(self.task, "s1", branch=self.task, base=self.base)
        self.bd("close", self.task)

    def test_listed_as_branch_with_no_worktree(self):
        result = self.clean()
        self.assertIn(f"branch {self.task}", result.stdout)
        self.assertIn("no worktree", result.stdout)

    def test_apply_deletes_the_branch(self):
        self.clean("--apply")
        self.assertNotIn(self.task, self.branches())
        self.assertEqual(self.clean().stdout, "")


class TestMergeQueues(BdRepoTestCase):
    def test_queue_held_by_a_dead_session_is_listed_and_released(self):
        holder = self.create(verify="true")
        self.claim(holder, "sdead")
        self.merge_queue_ensure("target")
        self.merge_queue_acquire("target", holder)

        result = self.clean()
        self.assertIn("queue target", result.stdout)
        self.assertIn(holder, result.stdout)

        self.clean("--apply")
        lock = run(self.repo, "bd", "kv", "get", "dispatch.queue.target", check=0).stdout.strip()
        status = json.loads(run(self.repo, "bd", "show", lock, "--json", check=0).stdout)[0]["status"]
        self.assertEqual(status, "open")
        self.assertEqual(self.clean().stdout, "")

    def test_queue_held_by_a_running_worker_is_never_listed(self):
        holder = self.create(verify="true")
        self.claim(holder, "salive")
        self.merge_queue_ensure("target")
        self.merge_queue_acquire("target", holder)
        self.spawn("run-task.sh", holder)

        result = self.clean()
        self.assertEqual(result.stdout, "")

        self.clean("--apply")
        lock = run(self.repo, "bd", "kv", "get", "dispatch.queue.target", check=0).stdout.strip()
        status = json.loads(run(self.repo, "bd", "show", lock, "--json", check=0).stdout)[0]["status"]
        self.assertEqual(status, "in_progress")

    def test_unheld_queue_is_never_listed(self):
        self.merge_queue_ensure("target")
        result = self.clean()
        self.assertEqual(result.stdout, "")


class TestArguments(BdRepoTestCase):
    def test_unknown_argument_exits_2(self):
        result = self.clean("--bogus", check=None)
        self.assertEqual(result.returncode, 2)

    def test_extra_argument_exits_2(self):
        result = self.clean("--apply", "extra", check=None)
        self.assertEqual(result.returncode, 2)


if __name__ == "__main__":
    unittest.main()
