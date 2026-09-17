import json
import os
import re
import subprocess
import sys
import time
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
E2E_DIR = os.path.dirname(SKILLS_DIR)
sys.path.insert(0, E2E_DIR)
from sandbox import new_project  # noqa: E402
from session import PLUGIN_DIR, Session  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"
INTEGRATION = os.environ.get("SDLC_INTEGRATION", "epic-merge")
TIMEOUT = float(os.environ.get("SDLC_E2E_TIMEOUT", 60 * 60))

SCRIPTS_DIR = os.path.join(PLUGIN_DIR, "scripts")
CREATE_TASK_SH = os.path.join(SCRIPTS_DIR, "create-task.sh")
WORKERS_PY = os.path.join(SCRIPTS_DIR, "workers.py")
NEXT_TASKS_PY = os.path.join(SCRIPTS_DIR, "next-tasks.py")
STOP_TASK_SH = os.path.join(SCRIPTS_DIR, "stop-task.sh")

CREATED_RE = re.compile(r"^created (\S+) \S+")


def _run(repo, *args, check=True):
    result = subprocess.run(args, cwd=repo, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise AssertionError(f"{args} failed: {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result


def _bd_json(repo, *args):
    return json.loads(_run(repo, "bd", *args, "--json").stdout)


def _show(repo, bead_id):
    return _bd_json(repo, "show", bead_id)[0]


def _create(repo, *args):
    result = _run(repo, CREATE_TASK_SH, *args)
    m = CREATED_RE.match(result.stdout.strip())
    if not m:
        raise AssertionError(f"create-task.sh {args} printed unexpected output: {result.stdout}")
    return m.group(1)


def _stop_workers(repo, epic_id):
    if epic_id:
        subprocess.run([STOP_TASK_SH, epic_id], cwd=repo, capture_output=True, text=True)


def _wait_for_workers(repo, epic_id, seconds=300):
    # finish-task.sh closes a task while its worker still records the attempt and removes the worktree.
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        alive = _run(repo, WORKERS_PY, "--under", epic_id, "--alive-count").stdout.strip()
        if alive == "0":
            return
        time.sleep(5)


class DispatchWaiter:
    """`until` for dispatching one task: stops on epic close, or two idle polls once dispatch has done anything."""

    STALL = "nothing running and nothing ready: a person would be needed"

    def __init__(self, repo, epic_id):
        self.repo = repo
        self.epic_id = epic_id
        self.seen_activity = False
        self.idle_polls = 0
        self.reason = None

    def __call__(self):
        if _show(self.repo, self.epic_id).get("status") == "closed":
            self.reason = "epic closed"
            return True

        running = _run(self.repo, WORKERS_PY, "--under", self.epic_id, "--alive-count").stdout.strip()
        ready = _run(self.repo, NEXT_TASKS_PY, "--under", self.epic_id, "--ids").stdout.strip()

        if running != "0" or ready:
            self.seen_activity = True
            self.idle_polls = 0
            return False

        # Before dispatch has queued anything, idle is the normal state; only count idle
        # polls once dispatch has actually started or scheduled a task.
        if not self.seen_activity:
            return False

        self.idle_polls += 1
        if self.idle_polls >= 2:
            self.reason = self.STALL
            return True
        return False


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillDispatch(unittest.TestCase):
    def test_dispatch_blocker_then_run(self):
        project = new_project("dispatch", integration=INTEGRATION)

        epic_id = _create(project.repo, "--type", "epic", "--title", "E2E dispatch fixture",
                           "--description", "Fixture epic for the dispatch skill e2e test")
        task_a = _create(
            project.repo,
            "--title", "Create hello.txt",
            "--description", "Create hello.txt containing hello",
            "--acceptance", "hello.txt exists and contains hello",
            "--scope", "hello.txt",
            "--verify", "grep -q hello hello.txt",
            "--complexity", "small",
            "--review", "none",
            "--parent", epic_id,
        )
        task_b = _create(
            project.repo,
            "--title", "Append a second line to hello.txt",
            "--description", "Append a second line to hello.txt",
            "--acceptance", "hello.txt has a second line",
            "--scope", "hello.txt",
            "--verify", '[ "$(wc -l < hello.txt)" -ge 2 ] && grep -q hello hello.txt',
            "--complexity", "small",
            "--review", "none",
            "--parent", epic_id,
            "--after", task_a,
        )

        session = Session(project.repo, "dispatch", answers={"": r"(?i)^(yes|confirm|dispatch|start)"})
        waiter = DispatchWaiter(project.repo, epic_id)
        try:
            result = session.run(f"/sdlc:dispatch {task_b}", until=waiter, timeout=TIMEOUT)
        except BaseException:
            _stop_workers(project.repo, epic_id)
            raise

        if waiter.reason == "epic closed":
            _wait_for_workers(project.repo, epic_id)
        else:
            _stop_workers(project.repo, epic_id)

        if waiter.reason == DispatchWaiter.STALL:
            self.fail(f"dispatch stalled: {waiter.reason}")
        self.assertEqual(waiter.reason, "epic closed", "the session ended before the epic closed")

        self.assertGreaterEqual(len(result.questions), 2, f"expected a blocker question and a confirmation, got {result.questions}")
        blocker_question = result.questions[0]
        self.assertIn(task_a, blocker_question["question"], "the first question didn't name task A")
        self.assertRegex(blocker_question["answer"], r"(?i)yes")

        confirm_question = result.questions[1]
        self.assertRegex(confirm_question["answer"], r"(?i)(yes|confirm|dispatch|start)")

        supervise_calls = [
            t["input"].get("command", "")
            for t in result.tools
            if t["name"] == "Bash" and (t["input"] or {}).get("run_in_background") and "supervise.py" in str((t["input"] or {}).get("command", ""))
        ]
        self.assertTrue(supervise_calls, "supervise.py was never started in the background")
        self.assertTrue(
            any(f"--under {task_a}" in c and f"--under {task_b}" in c for c in supervise_calls),
            f"no supervise.py call carried --under for both {task_a} and {task_b}: {supervise_calls}",
        )

        for task_id in (task_a, task_b):
            info = _show(project.repo, task_id)
            self.assertEqual(info["status"], "closed", f"{task_id} is not closed ({info['status']})")
            state = (info.get("metadata") or {}).get("dispatch_state")
            self.assertNotIn(state, ("stopped", "failed"), f"{task_id} dispatch_state={state}")

        hello = _run(project.repo, "git", "show", "main:hello.txt").stdout
        self.assertIn("hello", hello.lower())
        lines = [line for line in hello.splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 2, f"hello.txt on main has fewer than 2 lines: {hello!r}")


if __name__ == "__main__":
    unittest.main()
