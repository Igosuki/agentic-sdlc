import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
from test_tasks import BdRepoTestCase, run  # noqa: E402

SCRIPTS_DIR = os.path.join(TESTS_DIR, "..", "scripts")
WORKERS_PY = os.path.join(SCRIPTS_DIR, "workers.py")

sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))
import workers  # noqa: E402


class TestWorkers(BdRepoTestCase):
    def setUp(self):
        super().setUp()
        self.processes = []

    def tearDown(self):
        for p in self.processes:
            with contextlib.suppress(Exception):
                p.send_signal(signal.SIGKILL)
                p.wait(timeout=5)
        super().tearDown()

    def workers(self, *args, check=True):
        return run(self.repo, sys.executable, WORKERS_PY, *args, check=check)

    def spawn(self, *extra_argv):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", *extra_argv], cwd=self.repo)
        self.processes.append(p)
        time.sleep(0.3)
        return p

    def claim(self, task, session, **metadata):
        args = ["update", task, "--claim", "--set-metadata", f"dispatch_session={session}"]
        for key, value in metadata.items():
            args += ["--set-metadata", f"dispatch_{key}={value}"]
        self.bd(*args)

    def test_no_dispatched_task(self):
        result = self.workers()
        self.assertEqual(result.stdout.strip(), "no dispatched task in progress")

    def test_alive_count_zero_when_nothing_dispatched(self):
        self.assertEqual(self.workers("--alive-count").stdout.strip(), "0")

    def test_running_task(self):
        task = self.create("create", "--title", "Task", "--type", "task", "--metadata", '{"verify": "true"}')
        self.claim(task, "session-a", host="myhost")
        self.spawn("run-task.sh", task)

        result = self.workers()
        self.assertIn(f"{task}  running  on myhost", result.stdout)
        self.assertEqual(self.workers("--alive-count").stdout.strip(), "1")

    def test_alive_count_counts_closed_task_with_live_process(self):
        task = self.create("create", "--title", "Task", "--type", "task", "--metadata", '{"verify": "true"}')
        self.claim(task, "session-g", host="myhost")
        self.spawn("run-task.sh", task)
        self.bd("close", task)

        self.assertEqual(self.workers("--alive-count").stdout.strip(), "1")

    def test_crashed_task_shows_evidence(self):
        task = self.create("create", "--title", "Task", "--type", "task", "--metadata", '{"verify": "true"}')
        self.claim(task, "no-such-session", host="myhost", base="main", branch=task)

        result = self.workers()
        self.assertIn(f"{task}  crashed  on myhost", result.stdout)
        self.assertIn("session: no-such-session", result.stdout)
        self.assertIn("transcript: missing", result.stdout)
        self.assertIn("worktree: missing", result.stdout)
        self.assertIn("log: missing", result.stdout)
        self.assertIn("machine booted:", result.stdout)
        self.assertEqual(self.workers("--alive-count").stdout.strip(), "0")

    def test_stopped_task_shows_last_comment(self):
        task = self.create("create", "--title", "Task", "--type", "task", "--metadata", '{"verify": "true"}')
        self.claim(task, "session-b", host="myhost", state="stopped")
        self.bd("comments", "add", task, "hit a snag")

        result = self.workers()
        self.assertIn(f"{task}  stopped  on myhost", result.stdout)
        self.assertIn("last comment: hit a snag", result.stdout)

    def test_awaiting_review_shows_the_review_skill(self):
        task = self.create("create", "--title", "Task", "--type", "task", "--metadata", '{"verify": "true"}')
        self.claim(
            task, "session-c", host="myhost", state="awaiting-review", review_gate="gate-1",
            base="main", branch=task,
        )

        result = self.workers()
        self.assertIn("gate: gate-1", result.stdout)
        self.assertIn(f"review: /sdlc:review {task}", result.stdout)

    def test_pr_opened_shows_pull_request(self):
        task = self.create("create", "--title", "Task", "--type", "task", "--metadata", '{"verify": "true"}')
        self.claim(task, "session-d", host="myhost", state="pr-opened", pr="https://example/pr/1")

        result = self.workers()
        self.assertIn("pull request: https://example/pr/1, waiting for its merge", result.stdout)

    def test_under_option_selects_leaf_parent_epic_and_multiple_ids(self):
        epic = self.create("create", "--title", "Epic", "--type", "epic")
        parent = self.create("create", "--title", "Parent", "--type", "task", "--parent", epic)
        leaf = self.create(
            "create", "--title", "Leaf", "--type", "task", "--parent", parent, "--metadata", '{"verify": "true"}'
        )
        self.claim(leaf, "session-e", host="myhost", state="stopped")

        other_epic = self.create("create", "--title", "Other", "--type", "epic")
        other_task = self.create(
            "create", "--title", "OtherTask", "--type", "task", "--parent", other_epic,
            "--metadata", '{"verify": "true"}',
        )
        self.claim(other_task, "session-f", host="myhost", state="stopped")

        result = self.workers("--under", leaf)  # a leaf task
        self.assertIn(leaf, result.stdout)
        self.assertNotIn(other_task, result.stdout)

        result = self.workers("--under", parent)  # a parent task
        self.assertIn(leaf, result.stdout)
        self.assertNotIn(other_task, result.stdout)

        result = self.workers("--under", epic)  # an epic
        self.assertIn(leaf, result.stdout)
        self.assertNotIn(other_task, result.stdout)
        self.assertEqual(self.workers("--under", epic, "--alive-count").stdout.strip(), "0")

        result = self.workers("--under", epic, "--under", other_epic)  # two ids
        self.assertIn(leaf, result.stdout)
        self.assertIn(other_task, result.stdout)

    def test_unknown_argument_exits_2(self):
        result = self.workers("--bogus", check=False)
        self.assertEqual(result.returncode, 2)


class TestLastComment(unittest.TestCase):
    def test_failed_lookup_does_not_raise(self):
        # a failed `bd comments` call (no beads database here) returns None instead of
        # aborting the caller's loop over every dispatched task.
        tmp = tempfile.mkdtemp(prefix="workers-py-no-bd-")
        cwd = os.getcwd()
        try:
            os.chdir(tmp)
            self.assertIsNone(workers.last_comment("no-such-task-id"))
        finally:
            os.chdir(cwd)
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
