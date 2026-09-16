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
sys.path.insert(0, SCRIPTS_DIR)
import tasks  # noqa: E402

TASKS_PY = os.path.join(SCRIPTS_DIR, "tasks.py")


def run(cwd, *args, input=None, check=True):
    result = subprocess.run(args, cwd=cwd, input=input, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise AssertionError(f"{args} failed: {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result


class BdRepoTestCase(unittest.TestCase):
    """A real bd repository in a throwaway git repo, no stubs."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="tasks-py-test-")
        run(self.repo, "git", "init", "-q")
        run(self.repo, "git", "config", "user.email", "test@test.com")
        run(self.repo, "git", "config", "user.name", "test")
        run(self.repo, "bd", "init", "-q")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def bd(self, *args, check=True):
        return run(self.repo, "bd", *args, check=check)

    def create(self, *args):
        return self.bd(*args, "--silent").stdout.strip()

    def all_tasks(self):
        return json.loads(self.bd("list", "--all", "--limit", "0", "--json").stdout)

    def ready_tasks(self):
        return json.loads(self.bd("ready", "--limit", "0", "--json").stdout)

    def tasks_py(self, *args, stdin_json=None, check=True):
        input_text = json.dumps(stdin_json) if stdin_json is not None else None
        return run(self.repo, sys.executable, TASKS_PY, *args, input=input_text, check=check)


class TestEpicAndParentsToClose(BdRepoTestCase):
    def setUp(self):
        super().setUp()
        self.epic = self.create("create", "--title", "Epic", "--type", "epic")
        self.a = self.create("create", "--title", "A", "--type", "task", "--parent", self.epic)
        self.b = self.create("create", "--title", "B", "--type", "task", "--parent", self.a)
        self.c1 = self.create(
            "create", "--title", "C1", "--type", "task", "--parent", self.b, "--metadata", '{"verify": "true"}'
        )
        self.c2 = self.create(
            "create", "--title", "C2", "--type", "task", "--parent", self.b, "--metadata", '{"verify": "true"}'
        )

    def test_epic_of_nested_task(self):
        by_id = tasks.index_by_id(self.all_tasks())
        self.assertEqual(tasks.epic_of(by_id, self.c1), self.epic)
        self.assertEqual(tasks.epic_of(by_id, self.b), self.epic)
        self.assertIsNone(tasks.epic_of(by_id, self.epic))

    def test_epic_cli_reads_stdin(self):
        result = self.tasks_py("epic", self.c1, stdin_json=self.all_tasks())
        self.assertEqual(result.stdout.strip(), self.epic)

    def test_parents_to_close_walks_up_a_chain(self):
        self.bd("close", self.c1)
        self.bd("close", self.c2)
        by_id = tasks.index_by_id(self.all_tasks())
        # both C1 and C2 are closed, so B closes; B was A's only child, so A closes too.
        self.assertEqual(tasks.parents_to_close(by_id, self.c1), [self.b, self.a])

    def test_parents_to_close_stops_when_a_sibling_is_open(self):
        self.bd("close", self.c1)
        by_id = tasks.index_by_id(self.all_tasks())
        self.assertEqual(tasks.parents_to_close(by_id, self.c1), [])

    def test_parents_to_close_never_returns_an_epic(self):
        self.bd("close", self.c1)
        self.bd("close", self.c2)
        by_id = tasks.index_by_id(self.all_tasks())
        self.assertNotIn(self.epic, tasks.parents_to_close(by_id, self.c1))

    def test_parents_to_close_cli(self):
        self.bd("close", self.c1)
        self.bd("close", self.c2)
        result = self.tasks_py("parents-to-close", self.c1, stdin_json=self.all_tasks())
        self.assertEqual(result.stdout.split(), [self.b, self.a])


class TestDispatchOrder(BdRepoTestCase):
    def test_skips_parents_and_orders_started_epics_first(self):
        epic1 = self.create("create", "--title", "Epic1", "--type", "epic")
        parent = self.create("create", "--title", "Parent", "--type", "task", "--parent", epic1)
        leaf = self.create(
            "create", "--title", "Leaf", "--type", "task", "--parent", parent, "--metadata", '{"verify": "true"}'
        )
        other = self.create(
            "create", "--title", "Other", "--type", "task", "--parent", epic1, "--metadata", '{"verify": "true"}'
        )
        # a second epic, not yet started, so its task is ordered after epic1's once epic1 starts.
        epic2 = self.create("create", "--title", "Epic2", "--type", "epic")
        solo = self.create(
            "create", "--title", "Solo", "--type", "task", "--parent", epic2, "--metadata", '{"verify": "true"}'
        )
        # claim "other" so epic1 counts as started.
        self.bd("update", other, "--claim")

        order = tasks.dispatch_order(self.all_tasks(), self.ready_tasks())
        ids = [e["task"]["id"] for e in order]

        self.assertNotIn(parent, ids)  # a task with children is never dispatched
        self.assertNotIn(other, ids)  # claimed, no longer ready
        self.assertIn(leaf, ids)
        self.assertIn(solo, ids)
        self.assertLess(ids.index(leaf), ids.index(solo))  # epic1 is started, epic2 isn't

    def test_epic_filter(self):
        epic1 = self.create("create", "--title", "Epic1", "--type", "epic")
        t1 = self.create(
            "create", "--title", "T1", "--type", "task", "--parent", epic1, "--metadata", '{"verify": "true"}'
        )
        epic2 = self.create("create", "--title", "Epic2", "--type", "epic")
        self.create("create", "--title", "T2", "--type", "task", "--parent", epic2, "--metadata", '{"verify": "true"}')

        order = tasks.dispatch_order(self.all_tasks(), self.ready_tasks(), only_epic=epic1)
        self.assertEqual([e["task"]["id"] for e in order], [t1])

    def test_no_verify_command_is_not_dispatchable(self):
        self.create("create", "--title", "NoVerify", "--type", "task")
        order = tasks.dispatch_order(self.all_tasks(), self.ready_tasks())
        self.assertEqual(order, [])

    def test_integration_role_is_dispatchable_without_verify(self):
        epic = self.create("create", "--title", "Epic", "--type", "epic")
        integration = self.create(
            "create", "--title", "Integrate", "--type", "task", "--parent", epic,
            "--metadata", '{"dispatch_role": "integration"}'
        )
        order = tasks.dispatch_order(self.all_tasks(), self.ready_tasks())
        self.assertEqual([e["task"]["id"] for e in order], [integration])


class TestLargeBeadSet(BdRepoTestCase):
    def test_more_than_128kib_of_beads(self):
        epic = self.create("create", "--title", "Big epic", "--type", "epic")
        target = self.create(
            "create", "--title", "Target task", "--type", "task", "--parent", epic,
            "--metadata", '{"verify": "true"}'
        )
        # pad the database past the 128 KiB argv limit with long-titled siblings.
        for i in range(400):
            self.create(
                "create", "--title", f"padding task {i} " + ("x" * 200), "--type", "task", "--parent", epic
            )

        all_tasks = self.all_tasks()
        payload = json.dumps(all_tasks)
        self.assertGreater(len(payload.encode()), 128 * 1024)

        result = self.tasks_py("epic", target, stdin_json=all_tasks)
        self.assertEqual(result.stdout.strip(), epic)


class TestLogTotals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="tasks-py-log-")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_log(self, lines):
        path = os.path.join(self.tmp, "task-session.jsonl")
        with open(path, "w") as f:
            for line in lines:
                f.write(line + "\n")
        return path

    def test_resumed_session_does_not_double_count_cost(self):
        # first run: two results, cumulative cost within the run; a resume starts a new run.
        log = self.write_log([
            '{"type": "dispatch_run", "started": "t0"}',
            '{"type": "result", "total_cost_usd": 0.10, "num_turns": 3, "duration_ms": 1000}',
            '{"type": "result", "total_cost_usd": 0.25, "num_turns": 2, "duration_ms": 2000}',
            'not json at all',
            '{"type": "dispatch_run", "started": "t1"}',
            '{"type": "result", "total_cost_usd": 0.05, "num_turns": 1, "duration_ms": 500}',
        ])
        cost, turns, seconds = tasks.log_totals(log)
        # cost: last of run 0 (0.25) + last of run 1 (0.05); turns/seconds: every result.
        self.assertAlmostEqual(cost, 0.30)
        self.assertEqual(turns, 6)
        self.assertEqual(seconds, 3)

    def test_skips_broken_lines(self):
        log = self.write_log([
            '{"type": "result", "total_cost_usd": 0.01, "num_turns": 1, "duration_ms": 100}',
            '{"broken truncated line',
            '',
        ])
        cost, turns, seconds = tasks.log_totals(log)
        self.assertAlmostEqual(cost, 0.01)
        self.assertEqual(turns, 1)
        self.assertEqual(seconds, 0)

    def test_no_results_is_all_zero(self):
        log = self.write_log(['{"type": "dispatch_run", "started": "t0"}'])
        self.assertEqual(tasks.log_totals(log), (0, 0, 0))

    def test_cli(self):
        log = self.write_log([
            '{"type": "result", "total_cost_usd": 1.5, "num_turns": 4, "duration_ms": 60000}',
        ])
        result = run(self.tmp, sys.executable, TASKS_PY, "log-totals", log)
        cost, turns, seconds = result.stdout.strip().split("\t")
        self.assertEqual(float(cost), 1.5)
        self.assertEqual(turns, "4")
        self.assertEqual(seconds, "60")


class TestWorkerRunning(BdRepoTestCase):
    def setUp(self):
        super().setUp()
        self.task = self.create("create", "--title", "Task", "--type", "task", "--metadata", '{"verify": "true"}')
        self.processes = []

    def tearDown(self):
        for p in self.processes:
            with contextlib.suppress(Exception):
                p.send_signal(signal.SIGKILL)
                p.wait(timeout=5)
        super().tearDown()

    def spawn(self, *extra_argv):
        # a real process whose argv contains extra_argv verbatim, for pgrep -f to match.
        # (bash -c "sleep 30" extra... won't do: bash execs straight into sleep, dropping
        # the extra args from the process's actual argv.)
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", *extra_argv])
        self.processes.append(p)
        time.sleep(0.3)
        return p

    def claim(self, session, state=None):
        args = ["update", self.task, "--claim", "--set-metadata", f"dispatch_session={session}"]
        if state is not None:
            args += ["--set-metadata", f"dispatch_state={state}"]
        self.bd(*args)

    def get_task(self):
        return json.loads(self.bd("show", self.task, "--json").stdout)[0]

    def test_not_claimed_is_not_running(self):
        self.assertFalse(tasks.worker_running(self.get_task()))

    def test_claimed_with_no_process_is_not_running(self):
        self.claim("no-such-session")
        self.assertFalse(tasks.worker_running(self.get_task()))

    def test_claimed_with_run_task_process_is_running(self):
        self.claim("session-a")
        self.spawn("run-task.sh", self.task)
        self.assertTrue(tasks.worker_running(self.get_task()))

    def test_claimed_with_worker_session_process_is_running(self):
        self.claim("session-b")
        self.spawn("--session-id", "session-b")
        self.assertTrue(tasks.worker_running(self.get_task()))

    def test_fork_session_process_does_not_count(self):
        self.claim("session-c")
        self.spawn("--resume", "session-c", "--fork-session")
        self.assertFalse(tasks.worker_running(self.get_task()))

    def test_recorded_outcome_is_not_running_even_if_process_alive(self):
        self.claim("session-d", state="failed")
        self.spawn("run-task.sh", self.task)
        self.assertFalse(tasks.worker_running(self.get_task()))

    def test_cli(self):
        self.claim("session-e")
        self.spawn("run-task.sh", self.task)
        result = self.tasks_py("worker", self.task, stdin_json=self.all_tasks())
        self.assertEqual(result.stdout.strip(), "true")


if __name__ == "__main__":
    unittest.main()
