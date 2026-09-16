import contextlib
import os
import signal
import subprocess
import sys
import time
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
from test_tasks import BdRepoTestCase, run  # noqa: E402

SCRIPTS_DIR = os.path.join(TESTS_DIR, "..", "scripts")
WATCH_PY = os.path.join(SCRIPTS_DIR, "watch.py")

sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))
import watch  # noqa: E402


class TestWatchCli(BdRepoTestCase):
    def watch(self, *args, check=True):
        return run(self.repo, sys.executable, WATCH_PY, *args, check=check)

    def test_once_with_nothing_dispatched_prints_nothing_and_exits_0(self):
        result = self.watch("--once")
        self.assertEqual(result.stdout, "")

    def test_unknown_argument_exits_2(self):
        result = self.watch("--bogus", check=False)
        self.assertEqual(result.returncode, 2)

    def test_zero_interval_exits_2(self):
        result = self.watch("--once", "--interval", "0", check=False)
        self.assertEqual(result.returncode, 2)

    def test_non_numeric_interval_exits_2(self):
        result = self.watch("--once", "--interval", "soon", check=False)
        self.assertEqual(result.returncode, 2)

    def test_ready_task_is_reported(self):
        self.create("create", "--title", "Solo", "--type", "task", "--metadata", '{"verify": "true"}')
        result = self.watch("--once")
        self.assertIn("ready ", result.stdout)


class TestWatchStep(BdRepoTestCase):
    def setUp(self):
        super().setUp()
        self.processes = []

    def tearDown(self):
        for p in self.processes:
            with contextlib.suppress(Exception):
                p.send_signal(signal.SIGKILL)
                p.wait(timeout=5)
        super().tearDown()

    def spawn(self, *extra_argv):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", *extra_argv])
        self.processes.append(p)
        time.sleep(0.3)
        return p

    def claim(self, task, session, **metadata):
        args = ["update", task, "--claim", "--set-metadata", f"dispatch_session={session}"]
        for key, value in metadata.items():
            args += ["--set-metadata", f"dispatch_{key}={value}"]
        self.bd(*args)

    def round(self, epic, state, round_num):
        return watch.step(self.all_tasks(), self.ready_tasks(), epic, state, round_num)

    def test_ready_task_reported_once(self):
        self.create("create", "--title", "Solo", "--type", "task", "--metadata", '{"verify": "true"}')
        state = watch.new_state()

        lines, idle = self.round("", state, 0)
        self.assertEqual(len([line for line in lines if line.startswith("ready ")]), 1)
        self.assertFalse(idle)

        lines, idle = self.round("", state, 1)
        self.assertEqual(lines, [])

    def test_crashed_task_reported_once_even_on_first_round(self):
        task = self.create("create", "--title", "Task", "--type", "task", "--metadata", '{"verify": "true"}')
        self.claim(task, "no-such-session")
        state = watch.new_state()

        lines, idle = self.round("", state, 0)
        self.assertIn(f"crashed {task}", lines)
        self.assertTrue(idle)  # crashed isn't "alive": nothing left for this round to wait on

        lines, idle = self.round("", state, 1)
        self.assertEqual(lines, [])

    def test_task_that_ends_between_rounds_is_reported_the_first_time_seen(self):
        # simulates a worker that starts and finishes inside one interval: watch never
        # observes it "running", only ended - dispatch M2.
        task = self.create("create", "--title", "Task", "--type", "task", "--metadata", '{"verify": "true"}')
        state = watch.new_state()

        # round 0: task doesn't exist yet in the watched snapshot.
        lines, _ = watch.step([], [], "", state, 0)
        self.assertEqual(lines, [])

        self.claim(task, "session-a", state="stopped")
        lines, idle = self.round("", state, 1)
        self.assertEqual(lines, [f"ended {task} stopped"])
        self.assertTrue(idle)

        lines, idle = self.round("", state, 2)
        self.assertEqual(lines, [])  # not reported twice

    def test_first_round_never_reports_ended(self):
        # a task already finished before the watch started isn't reported as ending now.
        task = self.create("create", "--title", "Task", "--type", "task", "--metadata", '{"verify": "true"}')
        self.claim(task, "session-a", state="merged")
        state = watch.new_state()

        lines, _ = self.round("", state, 0)
        self.assertEqual(lines, [])

    def test_running_then_crashing_then_recorded_is_reported_as_ended(self):
        task = self.create("create", "--title", "Task", "--type", "task", "--metadata", '{"verify": "true"}')
        self.claim(task, "session-a")
        proc = self.spawn("run-task.sh", task)
        state = watch.new_state()

        lines, idle = self.round("", state, 0)
        self.assertEqual(lines, [])
        self.assertFalse(idle)

        proc.send_signal(signal.SIGKILL)
        proc.wait(timeout=5)
        lines, idle = self.round("", state, 1)
        self.assertIn(f"crashed {task}", lines)

        self.bd("update", task, "--set-metadata", "dispatch_state=failed")
        lines, idle = self.round("", state, 2)
        self.assertEqual(lines, [f"ended {task} failed"])
        self.assertTrue(idle)

    def test_epic_filter_at_any_depth_counts_subtask_towards_alive(self):
        epic = self.create("create", "--title", "Epic", "--type", "epic")
        parent = self.create("create", "--title", "Parent", "--type", "task", "--parent", epic)
        leaf = self.create(
            "create", "--title", "Leaf", "--type", "task", "--parent", parent, "--metadata", '{"verify": "true"}'
        )
        self.claim(leaf, "session-a")
        self.spawn("run-task.sh", leaf)
        state = watch.new_state()

        lines, idle = self.round(epic, state, 0)
        self.assertFalse(idle)  # the subtask keeps the epic's watch alive

    def test_closed_epic_reported_once(self):
        epic = self.create("create", "--title", "Epic", "--type", "epic")
        state = watch.new_state()

        lines, _ = self.round("", state, 0)
        self.assertEqual(lines, [])

        self.bd("close", epic)
        lines, _ = self.round("", state, 1)
        self.assertEqual(lines, [f"closed {epic}"])

        lines, _ = self.round("", state, 2)
        self.assertEqual(lines, [])


if __name__ == "__main__":
    unittest.main()
