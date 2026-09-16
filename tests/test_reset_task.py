import json
import os
import shutil
import subprocess
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(TESTS_DIR, "..", "scripts")
RESET_TASK_SH = os.path.join(SCRIPTS_DIR, "reset-task.sh")
MERGE_QUEUE_SH = os.path.join(SCRIPTS_DIR, "merge-queue.sh")


def run(cwd, *args, check=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check is not None and result.returncode != check:
        raise AssertionError(f"{args} exited {result.returncode} (expected {check})\n{result.stdout}\n{result.stderr}")
    return result


class BdWorktreeTestCase(unittest.TestCase):
    """A real bd repo and, per test, a real git worktree for the dispatched task."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="reset-task-test-")
        run(self.repo, "git", "init", "-q", "-b", "main")
        run(self.repo, "git", "config", "user.email", "test@test.com")
        run(self.repo, "git", "config", "user.name", "test")
        with open(os.path.join(self.repo, "README.md"), "w") as f:
            f.write("hi\n")
        run(self.repo, "git", "add", "README.md")
        run(self.repo, "git", "commit", "-q", "-m", "init")
        run(self.repo, "bd", "init", "-q")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def bd(self, *args, check=0):
        return run(self.repo, "bd", *args, check=check)

    def show(self, bead_id):
        return json.loads(self.bd("show", bead_id, "--json").stdout)[0]

    def reset(self, *args, check=None):
        return run(self.repo, RESET_TASK_SH, *args, check=check)

    def dispatch_task(self, state="failed"):
        """A task claimed and worktreed as a dispatch would leave it, in state."""
        task = self.bd(
            "create", "--title", "T", "--description", "d", "--acceptance", "a", "--type", "task",
            "--metadata", '{"scope": "s", "verify": "true"}', "--silent",
        ).stdout.strip()
        self.bd(
            "update", task, "--claim",
            "--set-metadata", "dispatch_session=sess-1",
            "--set-metadata", "dispatch_host=myhost",
            "--set-metadata", "dispatch_base=main",
            "--set-metadata", f"dispatch_branch={task}",
            "--set-metadata", "dispatch_started=2026-01-01T00:00:00Z",
            "--set-metadata", f"dispatch_state={state}",
        )
        run(self.repo, MERGE_QUEUE_SH, "ensure", "main", check=0)
        run(self.repo, MERGE_QUEUE_SH, "acquire", "main", task, check=0)
        run(self.repo, "wt", "switch", "--create", task, "--base", "main", "--no-cd", "--format", "json", check=0)
        return task

    def queue_holder(self, base):
        lock = self.bd("kv", "get", f"dispatch.queue.{base}", check=False).stdout.strip()
        if not lock:
            return None
        info = self.show(lock)
        return info["status"], info.get("assignee") or ""

    def worktree_exists(self, branch):
        items = json.loads(run(self.repo, "wt", "list", "--format", "json", check=0).stdout)["items"]
        return any(item["branch"] == branch for item in items)


class TestResetTask(BdWorktreeTestCase):
    def test_reopens_the_task_with_no_dispatch_keys_left(self):
        task = self.dispatch_task()

        result = self.reset(task, check=0)

        self.assertEqual(result.stdout.strip(), f"reset {task}")
        info = self.show(task)
        self.assertEqual(info["status"], "open")
        for key in info.get("metadata") or {}:
            self.assertFalse(key.startswith("dispatch_"), key)

    def test_removes_the_worktree_and_branch(self):
        task = self.dispatch_task()
        self.assertTrue(self.worktree_exists(task))

        self.reset(task, check=0)

        self.assertFalse(self.worktree_exists(task))
        branches = run(self.repo, "git", "branch", "--list", task, check=0).stdout
        self.assertEqual(branches.strip(), "")

    def test_releases_the_merge_queue(self):
        task = self.dispatch_task()
        self.assertEqual(self.queue_holder("main"), ("in_progress", task))

        self.reset(task, check=0)

        self.assertEqual(self.queue_holder("main"), ("open", ""))

    def test_a_task_with_no_worktree_or_queue_is_just_reopened(self):
        task = self.bd(
            "create", "--title", "T", "--description", "d", "--acceptance", "a", "--type", "task",
            "--metadata", '{"scope": "s", "verify": "true"}', "--silent",
        ).stdout.strip()
        self.bd(
            "update", task, "--claim",
            "--set-metadata", "dispatch_session=sess-1",
            "--set-metadata", "dispatch_state=failed",
        )

        result = self.reset(task, check=0)

        self.assertEqual(result.stdout.strip(), f"reset {task}")
        info = self.show(task)
        self.assertEqual(info["status"], "open")
        self.assertNotIn("dispatch_session", info.get("metadata") or {})
        self.assertNotIn("dispatch_state", info.get("metadata") or {})

    def test_a_task_never_dispatched_is_unchanged_but_reported(self):
        task = self.bd("create", "--title", "T", "--description", "d", "--acceptance", "a", "--type", "task",
                        "--metadata", '{"scope": "s", "verify": "true"}', "--silent").stdout.strip()

        result = self.reset(task, check=0)

        self.assertEqual(result.stdout.strip(), f"reset {task}")
        self.assertEqual(self.show(task)["status"], "open")

    def test_no_such_bead_is_an_error(self):
        result = self.reset("nope-1", check=2)
        self.assertIn("no bead nope-1", result.stderr)

    def test_finish_task_accepts_the_task_once_recover_clears_dispatch_state(self):
        # The acceptance recover relies on: finish-task.sh only refuses a dispatch_state
        # of stopped or failed, so clearing it (without a full reset) hands the task back.
        task = self.dispatch_task(state="failed")
        self.bd("update", task, "--unset-metadata", "dispatch_state")

        finish = run(
            self.repo, os.path.join(SCRIPTS_DIR, "finish-task.sh"), task, check=None,
        )
        self.assertNotIn("no dispatched worker", finish.stderr)


if __name__ == "__main__":
    unittest.main()
