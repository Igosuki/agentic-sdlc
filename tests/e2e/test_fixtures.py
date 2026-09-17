import contextlib
import json
import os
import subprocess
import sys
import unittest

E2E_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, E2E_DIR)
from sandbox import SCRIPTS_DIR, dispatched, new_project, task, verify_break  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"

WORKERS_PY = os.path.join(SCRIPTS_DIR, "workers.py")
STATS_PY = os.path.join(SCRIPTS_DIR, "stats.py")
LOGS_PY = os.path.join(SCRIPTS_DIR, "logs.py")
CLEAN_SH = os.path.join(SCRIPTS_DIR, "clean.sh")
VERIFY_SH = os.path.join(SCRIPTS_DIR, "verify.sh")


def _call(repo, *args):
    return subprocess.run(args, cwd=repo, capture_output=True, text=True)


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run e2e fixture checks")
class TestWorkerStates(unittest.TestCase):
    """stopped, failed, awaiting-review, running and one ready task, as workers.py,
    stats.py and logs.py read them back, with no model involved."""

    @classmethod
    def setUpClass(cls):
        cls.project = new_project("fixtures-workers")
        cls.stopped = task(cls.project, "Stopped task")
        cls.failed = task(cls.project, "Failed task")
        cls.review = task(cls.project, "Awaiting review task")
        cls.running = task(cls.project, "Running task")
        cls.ready = task(cls.project, "Ready task")
        dispatched(cls.project, cls.stopped, "stopped")
        dispatched(cls.project, cls.failed, "failed")
        cls.d_review = dispatched(cls.project, cls.review, "awaiting-review")
        cls.d_running = dispatched(cls.project, cls.running, "running")

    @classmethod
    def tearDownClass(cls):
        with contextlib.suppress(Exception):
            cls.d_running.process.terminate()
            cls.d_running.process.wait(timeout=5)

    def workers(self):
        return _call(self.project.repo, sys.executable, WORKERS_PY)

    def test_stopped_and_failed_show_their_state(self):
        out = self.workers().stdout
        self.assertIn(f"{self.stopped}  stopped  on e2e-sandbox", out)
        self.assertIn(f"{self.failed}  failed  on e2e-sandbox", out)

    def test_awaiting_review_shows_the_open_gate(self):
        out = self.workers().stdout
        self.assertIn(f"gate: {self.d_review.gate}", out)
        self.assertIn(f"review: /sdlc:review {self.review}", out)

    def test_running_task_shows_as_running_while_its_process_is_alive(self):
        self.assertIsNone(self.d_running.process.poll())
        out = self.workers().stdout
        self.assertIn(f"{self.running}  running  on e2e-sandbox", out)

    def test_ready_task_is_not_a_dispatched_worker(self):
        out = self.workers().stdout
        self.assertNotIn(self.ready, out)

    def test_stats_lists_every_recorded_attempt(self):
        out = _call(self.project.repo, sys.executable, STATS_PY).stdout
        self.assertIn(self.stopped, out)
        self.assertIn(self.failed, out)
        self.assertIn(self.review, out)
        self.assertNotIn(self.running, out)  # no result yet: nothing recorded

    def test_logs_prints_the_stopped_tasks_log(self):
        out = _call(self.project.repo, sys.executable, LOGS_PY, self.stopped).stdout
        self.assertIn("── run started", out)
        self.assertIn("running total $0.05", out)


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run e2e fixture checks")
class TestClosedLeftover(unittest.TestCase):
    """A closed task whose worktree and branch record-task.sh couldn't remove
    (an untracked file left in the worktree), as clean.sh reads it back."""

    @classmethod
    def setUpClass(cls):
        cls.project = new_project("fixtures-clean")
        cls.task = task(cls.project, "Leftover task")
        cls.d = dispatched(cls.project, cls.task, "closed")

    def test_clean_lists_the_worktree_and_branch(self):
        out = _call(self.project.repo, CLEAN_SH).stdout
        self.assertIn(f"worktree {self.d.branch}  closed task, worktree and branch left behind", out)


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run e2e fixture checks")
class TestVerifyBreak(unittest.TestCase):
    """A closed task whose metadata.verify held on main, broken by a later commit."""

    @classmethod
    def setUpClass(cls):
        cls.project = new_project("fixtures-verify")
        cls.task_id, cls.sha = verify_break(cls.project)

    def test_verify_fails_on_the_broken_fixture(self):
        result = _call(self.project.repo, VERIFY_SH, self.task_id)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f"verify {self.task_id} failed", result.stdout)

    def test_the_breaking_commit_landed_on_main(self):
        out = _call(self.project.repo, "git", "cat-file", "-t", self.sha).stdout.strip()
        self.assertEqual(out, "commit")
        branch_head = _call(self.project.repo, "git", "rev-parse", "main").stdout.strip()
        self.assertEqual(branch_head, self.sha)


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run e2e fixture checks")
class TestReviewFixture(unittest.TestCase):
    """A task branch for /sdlc:review: acceptance names the zero check, the
    branch leaves it out. No model call here; that's sdlc-260.5's job."""

    @classmethod
    def setUpClass(cls):
        cls.project = new_project("fixtures-review")
        cls.task_id = task(
            cls.project, "Add divide", acceptance="divide by zero returns an error", scope="src/"
        )
        cls.d = dispatched(
            cls.project, cls.task_id, "awaiting-review", gate=False,
            commits=[{"src/divide.py": "def divide(a, b):\n    return a / b\n"}],
        )

    def test_branch_leaves_out_the_zero_check(self):
        out = _call(self.project.repo, "git", "show", f"{self.d.branch}:src/divide.py").stdout
        self.assertNotIn("ZeroDivisionError", out)
        self.assertNotIn("== 0", out)

    def test_acceptance_names_the_gap(self):
        info = json.loads(_call(self.project.repo, "bd", "show", self.task_id, "--json").stdout)[0]
        self.assertIn("divide by zero", info["acceptance_criteria"])

    def test_no_gate_was_opened(self):
        self.assertIsNone(self.d.gate)


if __name__ == "__main__":
    unittest.main()
