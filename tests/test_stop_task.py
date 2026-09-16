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

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
from test_tasks import BdRepoTestCase, run  # noqa: E402

SCRIPTS_DIR = os.path.join(TESTS_DIR, "..", "scripts")
STOP_TASK_SH = os.path.join(SCRIPTS_DIR, "stop-task.sh")


class TestStopTask(BdRepoTestCase):
    def setUp(self):
        super().setUp()
        self.processes = []

    def tearDown(self):
        for p in self.processes:
            with contextlib.suppress(Exception):
                p.send_signal(signal.SIGKILL)
                p.wait(timeout=5)
        super().tearDown()

    def stop(self, *args, check=True):
        return run(self.repo, STOP_TASK_SH, *args, check=check)

    def show(self, bead_id):
        return json.loads(self.bd("show", bead_id, "--json").stdout)[0]

    def claim(self, task, session, **metadata):
        args = ["update", task, "--claim", "--set-metadata", f"dispatch_session={session}"]
        for key, value in metadata.items():
            args += ["--set-metadata", f"dispatch_{key}={value}"]
        self.bd(*args)

    def spawn(self, script, *extra_argv):
        p = subprocess.Popen([sys.executable, "-c", script, *extra_argv], cwd=self.repo)
        self.processes.append(p)
        time.sleep(0.3)
        return p

    def spawn_worker(self, task):
        return self.spawn("import time; time.sleep(30)", "run-task.sh", task)

    def alive(self, p):
        return p.poll() is None

    def queue_holder(self, base):
        lock = self.bd("kv", "get", f"dispatch.queue.{base}", check=False).stdout.strip()
        if not lock:
            return None
        info = json.loads(self.bd("show", lock, "--json").stdout)[0]
        return info["status"], info.get("assignee") or ""

    def acquire_queue(self, base, holder):
        run(self.repo, os.path.join(SCRIPTS_DIR, "merge-queue.sh"), "ensure", base)
        run(self.repo, os.path.join(SCRIPTS_DIR, "merge-queue.sh"), "acquire", base, holder)

    def test_task_with_no_running_worker_is_reported_not_changed(self):
        task = self.create("create", "--title", "Task", "--type", "task")

        result = self.stop(task)

        self.assertIn("no running worker", result.stdout)
        info = self.show(task)
        self.assertEqual(info["status"], "open")
        self.assertNotIn("dispatch_state", info.get("metadata") or {})
        self.assertEqual(self.bd("comments", task, "--json").stdout.strip(), "[]")

    def test_stopping_a_task_ends_worker_releases_queue_and_records_stopped(self):
        task = self.create("create", "--title", "Task", "--type", "task")
        self.claim(task, "session-a", host="myhost", base="main", branch=task)
        self.acquire_queue("main", task)
        worker = self.spawn_worker(task)

        result = self.stop(task)

        self.assertIn(f"stopped {task}", result.stdout)
        worker.wait(timeout=5)
        self.assertFalse(self.alive(worker))

        info = self.show(task)
        self.assertEqual(info["metadata"]["dispatch_state"], "stopped")

        comments = json.loads(self.bd("comments", task, "--json").stdout)
        self.assertTrue(any("stopped by a person" in c["text"].lower() for c in comments))

        status, assignee = self.queue_holder("main")
        self.assertEqual(status, "open")
        self.assertEqual(assignee, "")

    def test_epic_stops_every_running_worker_under_it_at_any_depth(self):
        epic = self.create("create", "--title", "Epic", "--type", "epic")
        parent = self.create("create", "--title", "Parent", "--type", "task", "--parent", epic)
        deep_leaf = self.create("create", "--title", "Deep", "--type", "task", "--parent", parent)
        direct_leaf = self.create("create", "--title", "Direct", "--type", "task", "--parent", epic)

        other_epic = self.create("create", "--title", "OtherEpic", "--type", "epic")
        other_task = self.create("create", "--title", "OtherTask", "--type", "task", "--parent", other_epic)

        self.claim(deep_leaf, "session-deep", host="myhost", base="main", branch=deep_leaf)
        self.claim(direct_leaf, "session-direct", host="myhost", base="main", branch=direct_leaf)
        self.claim(other_task, "session-other", host="myhost", base="main", branch=other_task)

        w_deep = self.spawn_worker(deep_leaf)
        w_direct = self.spawn_worker(direct_leaf)
        w_other = self.spawn_worker(other_task)

        result = self.stop(epic)

        w_deep.wait(timeout=5)
        w_direct.wait(timeout=5)

        self.assertIn(f"stopped {deep_leaf}", result.stdout)
        self.assertIn(f"stopped {direct_leaf}", result.stdout)
        self.assertNotIn(other_task, result.stdout)

        self.assertFalse(self.alive(w_deep))
        self.assertFalse(self.alive(w_direct))
        self.assertTrue(self.alive(w_other))

        self.assertEqual(self.show(deep_leaf)["metadata"]["dispatch_state"], "stopped")
        self.assertEqual(self.show(direct_leaf)["metadata"]["dispatch_state"], "stopped")
        self.assertNotIn("dispatch_state", self.show(other_task).get("metadata") or {})

    def test_epic_with_no_running_worker_is_reported_not_changed(self):
        epic = self.create("create", "--title", "Epic", "--type", "epic")
        task = self.create("create", "--title", "Task", "--type", "task", "--parent", epic)

        result = self.stop(epic)

        self.assertIn("no running worker", result.stdout)
        self.assertEqual(self.show(task)["status"], "open")

    def test_final_state_is_stopped_even_when_something_races_it_to_failed(self):
        # Simulates start-worker.sh's own record-task.sh call landing around the same
        # time as the stop: whichever writes dispatch_state last, it must read stopped.
        task = self.create("create", "--title", "Task", "--type", "task")
        self.claim(task, "session-race", host="myhost", base="main", branch=task)
        self.acquire_queue("main", task)

        racer = f"""
import signal, subprocess, sys, time
def handler(signum, frame):
    subprocess.run(["bd", "update", {task!r}, "--set-metadata", "dispatch_state=failed"])
    sys.exit(0)
signal.signal(signal.SIGTERM, handler)
time.sleep(30)
"""
        worker = self.spawn(racer, "--session-id", "session-race")

        result = self.stop(task)

        worker.wait(timeout=5)
        self.assertIn(f"stopped {task}", result.stdout)
        self.assertEqual(self.show(task)["metadata"]["dispatch_state"], "stopped")


if __name__ == "__main__":
    unittest.main()
