import contextlib
import os
import shutil
import signal
import stat
import subprocess
import sys
import tempfile
import time
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
from test_tasks import BdRepoTestCase, run  # noqa: E402

SCRIPTS_DIR = os.path.join(TESTS_DIR, "..", "scripts")
SUPERVISE_PY = os.path.join(SCRIPTS_DIR, "supervise.py")

sys.path.insert(0, os.path.abspath(SCRIPTS_DIR))
import supervise  # noqa: E402
import tasks  # noqa: E402


def task(id, status="in_progress", dispatch_session=None, dispatch_state=None, dispatch_branch=None,
         dispatch_review_gate=None, dispatch_pr=None, updated_at="t0", issue_type="task",
         parent=None, extra_metadata=None):
    meta = {}
    if dispatch_session is not None:
        meta["dispatch_session"] = dispatch_session
    if dispatch_state is not None:
        meta["dispatch_state"] = dispatch_state
    if dispatch_branch is not None:
        meta["dispatch_branch"] = dispatch_branch
    if dispatch_review_gate is not None:
        meta["dispatch_review_gate"] = dispatch_review_gate
    if dispatch_pr is not None:
        meta["dispatch_pr"] = dispatch_pr
    if extra_metadata:
        meta.update(extra_metadata)
    return {
        "id": id, "status": status, "issue_type": issue_type, "updated_at": updated_at,
        "metadata": meta, "priority": 2, "created_at": "c0", "dependent_count": 0,
        "dependencies": [], "parent": parent,
    }


def ready_task(id):
    return task(id, status="open", extra_metadata={"verify": "true"})


def running_line(session):
    return f"1 --session-id {session}"


def build_look(all_tasks, ready_tasks=None, lines=None, worktrees=None, crash_info=None, comments=None):
    return {
        "all_tasks": all_tasks,
        "ready_tasks": ready_tasks if ready_tasks is not None else [],
        "by_id": tasks.index_by_id(all_tasks),
        "lines": lines if lines is not None else [],
        "worktrees": worktrees if worktrees is not None else {},
        "crash_info": crash_info if crash_info is not None else {},
        "comments": comments if comments is not None else {},
    }


class TestClosedWithLiveProcess(unittest.TestCase):
    def test_no_action_no_wake(self):
        t = task("t1", status="closed", dispatch_session="s1", dispatch_branch="b1")
        look = build_look([t], lines=[running_line("s1")], worktrees={"b1": "/wt"})
        brain = supervise.Brain(parallel=2, under_ids=[])
        actions, wake = brain.decide(look, {"kind": "start"})
        self.assertEqual(actions, [])
        self.assertEqual(wake, [])


class TestCrashRecording(unittest.TestCase):
    def test_result_in_log_is_recorded(self):
        t = task("t2", dispatch_session="s2", dispatch_branch="b2")
        look = build_look(
            [t], worktrees={"b2": "/wt2"},
            crash_info={"t2": {"has_result": True, "runs_since_result": 0, "transcript": "/tr"}},
        )
        brain = supervise.Brain(parallel=2, under_ids=[])
        actions, wake = brain.decide(look, {"kind": "start"})
        self.assertEqual(actions, [{"kind": "record", "task": "t2"}])
        self.assertEqual(wake, [])

    def test_no_result_resumes_then_fails_after_three_resumes(self):
        t = task("t3", dispatch_session="s3", dispatch_branch="b3")
        look = build_look(
            [t], worktrees={"b3": "/wt3"},
            crash_info={"t3": {"has_result": False, "runs_since_result": 1, "transcript": "/tr3"}},
        )
        brain = supervise.Brain(parallel=2, under_ids=[])
        actions, wake = brain.decide(look, {"kind": "start"})
        self.assertEqual(actions, [{"kind": "resume", "task": "t3"}])

        look2 = build_look(
            [t], worktrees={"b3": "/wt3"},
            crash_info={"t3": {"has_result": False, "runs_since_result": 4, "transcript": "/tr3"}},
        )
        actions, wake = brain.decide(look2, {"kind": "pipe"})
        self.assertEqual(actions, [{"kind": "fail", "task": "t3", "reason": "crashed again after 3 resumes"}])

    def test_missing_worktree_fails(self):
        t = task("t4", dispatch_session="s4", dispatch_branch="b4")
        look = build_look(
            [t], worktrees={},
            crash_info={"t4": {"has_result": False, "runs_since_result": 1, "transcript": "/tr4"}},
        )
        brain = supervise.Brain(parallel=2, under_ids=[])
        actions, _ = brain.decide(look, {"kind": "start"})
        self.assertEqual(actions, [{"kind": "fail", "task": "t4", "reason": "crashed, and its worktree is gone"}])

    def test_missing_transcript_fails(self):
        t = task("t5", dispatch_session="s5", dispatch_branch="b5")
        look = build_look(
            [t], worktrees={"b5": "/wt5"},
            crash_info={"t5": {"has_result": False, "runs_since_result": 1, "transcript": None}},
        )
        brain = supervise.Brain(parallel=2, under_ids=[])
        actions, _ = brain.decide(look, {"kind": "start"})
        self.assertEqual(actions, [{"kind": "fail", "task": "t5", "reason": "crashed, and its transcript is gone"}])

    def test_closed_task_with_no_result_is_never_resumed_or_failed(self):
        # finish-task.sh's bd close and record-task.sh's state write are two calls; a worker
        # that dies between them leaves a closed task with no outcome, but its code merged.
        t = task("t6", status="closed", dispatch_session="s6", dispatch_branch="b6")
        look = build_look(
            [t], worktrees={"b6": "/wt6"},
            crash_info={"t6": {"has_result": False, "runs_since_result": 1, "transcript": "/tr6"}},
        )
        brain = supervise.Brain(parallel=2, under_ids=[])
        actions, wake = brain.decide(look, {"kind": "start"})
        self.assertEqual(actions, [])
        self.assertEqual(wake, [])

    def test_closed_task_with_a_result_is_still_recorded(self):
        t = task("t7", status="closed", dispatch_session="s7", dispatch_branch="b7")
        look = build_look(
            [t], worktrees={"b7": "/wt7"},
            crash_info={"t7": {"has_result": True, "runs_since_result": 0, "transcript": "/tr7"}},
        )
        brain = supervise.Brain(parallel=2, under_ids=[])
        actions, _ = brain.decide(look, {"kind": "start"})
        self.assertEqual(actions, [{"kind": "record", "task": "t7"}])


class TestStarts(unittest.TestCase):
    def test_work_order_up_to_parallel_counts_other_scope_workers(self):
        epic = task("epic1", issue_type="epic")
        a = ready_task("a1"); a["parent"] = "epic1"
        b = ready_task("a2"); b["parent"] = "epic1"
        other = task("other", dispatch_session="s-other", dispatch_branch="ob")

        all_tasks = [epic, a, b, other]
        ready = [{"id": "a1"}, {"id": "a2"}]
        look = build_look(all_tasks, ready_tasks=ready, lines=[running_line("s-other")], worktrees={"ob": "/wt"})

        brain = supervise.Brain(parallel=2, under_ids=["epic1"])
        actions, _ = brain.decide(look, {"kind": "start"})
        starts = [a for a in actions if a["kind"] == "start"]
        self.assertEqual(len(starts), 1)
        self.assertEqual(starts[0]["task"], "a1")


class TestRefusedStart(unittest.TestCase):
    def test_comment_and_wake_once_then_next_task_gets_slot(self):
        a = ready_task("ra"); a["created_at"] = "c0"
        b = ready_task("rb"); b["created_at"] = "c1"
        all_tasks = [a, b]
        ready = [{"id": "ra"}, {"id": "rb"}]
        look = build_look(all_tasks, ready_tasks=ready)
        brain = supervise.Brain(parallel=1, under_ids=[])

        actions, wake = brain.decide(look, {"kind": "start"})
        self.assertEqual(actions, [{"kind": "start", "task": "ra"}])
        self.assertEqual(wake, [])

        event = {"kind": "settle", "refused": [{"task": "ra", "reason": "boom", "last_comment": None}]}
        actions, wake = brain.decide(look, event)
        self.assertIn({"kind": "comment", "task": "ra", "text": "not started: boom"}, actions)
        self.assertIn({"kind": "start", "task": "rb"}, actions)
        self.assertEqual(wake, ["blocked ra not started: boom"])

        event2 = {"kind": "settle", "refused": [{"task": "ra", "reason": "boom", "last_comment": "not started: boom"}]}
        actions, wake = brain.decide(look, event2)
        self.assertNotIn({"kind": "comment", "task": "ra", "text": "not started: boom"}, actions)
        self.assertEqual(wake, [])


class TestBlockedWake(unittest.TestCase):
    def test_first_look_baseline_then_new_block_then_unblock_then_block_again(self):
        x = task("x", dispatch_session="sx", dispatch_state="stopped")
        look = build_look([x], comments={"x": "boom"})
        brain = supervise.Brain(parallel=2, under_ids=[])

        actions, wake = brain.decide(look, {"kind": "start"})
        self.assertEqual(wake, [])

        y = task("y", dispatch_session="sy", dispatch_state="stopped")
        look2 = build_look([x, y], comments={"x": "boom", "y": "oops"})
        actions, wake = brain.decide(look2, {"kind": "pipe"})
        self.assertEqual(wake, ["blocked y stopped: oops"])

        y_running = task("y", dispatch_session="sy", dispatch_state=None)
        look3 = build_look([x, y_running], lines=[running_line("sy")], comments={"x": "boom"})
        actions, wake = brain.decide(look3, {"kind": "pipe"})
        self.assertEqual(wake, [])

        y_stopped_again = task("y", dispatch_session="sy", dispatch_state="stopped")
        look4 = build_look([x, y_stopped_again], comments={"x": "boom", "y": "again"})
        actions, wake = brain.decide(look4, {"kind": "pipe"})
        self.assertEqual(wake, ["blocked y stopped: again"])


class TestNewWork(unittest.TestCase):
    def test_new_work_only_reported_with_under_and_only_when_it_became_ready(self):
        epic = task("epic1", issue_type="epic")
        in_scope = ready_task("in1"); in_scope["parent"] = "epic1"
        outside = task("out1", status="open")

        all_tasks_before = [epic, in_scope]
        ready_before = [{"id": "in1"}]
        look_before = build_look(all_tasks_before, ready_tasks=ready_before)

        brain = supervise.Brain(parallel=2, under_ids=["epic1"])
        actions, wake = brain.decide(look_before, {"kind": "start"})
        self.assertEqual(wake, [])

        outside_ready = ready_task("out1")
        all_tasks_after = [epic, in_scope, outside_ready]
        ready_after = [{"id": "in1"}, {"id": "out1"}]
        look_after = build_look(all_tasks_after, ready_tasks=ready_after)
        actions, wake = brain.decide(look_after, {"kind": "pipe"})
        self.assertEqual(wake, ["new-work out1"])

    def test_no_new_work_line_without_under(self):
        outside_ready = ready_task("out1")
        look_before = build_look([], ready_tasks=[])
        look_after = build_look([outside_ready], ready_tasks=[{"id": "out1"}])
        brain = supervise.Brain(parallel=2, under_ids=[])
        brain.decide(look_before, {"kind": "start"})
        actions, wake = brain.decide(look_after, {"kind": "pipe"})
        self.assertEqual(wake, [])


class TestReviewGate(unittest.TestCase):
    def test_closed_gate_resumes(self):
        gate = task("g1", issue_type="gate", status="closed")
        t = task("rt", dispatch_session="srt", dispatch_state="awaiting-review", dispatch_review_gate="g1")
        look = build_look([t, gate])
        brain = supervise.Brain(parallel=2, under_ids=[])
        actions, _ = brain.decide(look, {"kind": "pipe"})
        self.assertIn({"kind": "resume_reviewed", "task": "rt"}, actions)

    def test_open_gate_does_not_resume(self):
        gate = task("g2", issue_type="gate", status="open")
        t = task("rt2", dispatch_session="srt2", dispatch_state="awaiting-review", dispatch_review_gate="g2")
        look = build_look([t, gate])
        brain = supervise.Brain(parallel=2, under_ids=[])
        actions, _ = brain.decide(look, {"kind": "pipe"})
        self.assertEqual([a for a in actions if a["kind"] == "resume_reviewed"], [])

    def test_not_redecided_across_settle_looks_when_unchanged(self):
        # resume-task.sh can fail and restore dispatch_state=awaiting-review, or its own
        # pgrep check can race, without the task's updated_at changing; a settling round
        # must not keep deciding resume_reviewed for it.
        gate = task("g3", issue_type="gate", status="closed")
        t = task("rt3", dispatch_session="srt3", dispatch_state="awaiting-review", dispatch_review_gate="g3")
        look = build_look([t, gate])
        brain = supervise.Brain(parallel=2, under_ids=[])

        actions, _ = brain.decide(look, {"kind": "pipe"})
        self.assertIn({"kind": "resume_reviewed", "task": "rt3"}, actions)

        actions, _ = brain.decide(look, {"kind": "settle"})
        self.assertEqual([a for a in actions if a["kind"] == "resume_reviewed"], [])

        actions, _ = brain.decide(look, {"kind": "pipe"})
        self.assertIn({"kind": "resume_reviewed", "task": "rt3"}, actions)


class TestPullRequestGate(unittest.TestCase):
    def test_gate_check_and_close_pr_only_on_sweep_or_start(self):
        t = task("pt", dispatch_session="spt", dispatch_state="pr-opened", dispatch_pr="https://x/pr/1")
        look = build_look([t])
        brain = supervise.Brain(parallel=2, under_ids=[])

        actions, _ = brain.decide(look, {"kind": "pipe"})
        self.assertEqual([a for a in actions if a["kind"] in ("gate_check", "close_pr")], [])

        actions, _ = brain.decide(look, {"kind": "sweep"})
        self.assertEqual(actions[0], {"kind": "gate_check"})
        self.assertIn({"kind": "close_pr", "task": "pt"}, actions)

        actions, _ = brain.decide(look, {"kind": "start"})
        self.assertEqual(actions[0], {"kind": "gate_check"})
        self.assertIn({"kind": "close_pr", "task": "pt"}, actions)


class SuperviseRepoTestCase(BdRepoTestCase):
    def setUp(self):
        super().setUp()
        self.procs = []
        self.common_dir = run(
            self.repo, "git", "rev-parse", "--path-format=absolute", "--git-common-dir"
        ).stdout.strip()
        self.sdlc_dir = os.path.join(self.common_dir, "sdlc")
        self.wake_path = os.path.join(self.sdlc_dir, "wake")
        self.log_path = os.path.join(self.sdlc_dir, "supervise.log")

    def tearDown(self):
        for p in self.procs:
            with contextlib.suppress(Exception):
                if p.poll() is None:
                    p.send_signal(signal.SIGTERM)
                    p.wait(timeout=10)
        for p in self.procs:
            with contextlib.suppress(Exception):
                p.kill()
        super().tearDown()

    def start_supervisor(self, *extra_args):
        p = subprocess.Popen(
            [sys.executable, SUPERVISE_PY, *extra_args],
            cwd=self.repo, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        self.procs.append(p)
        return p

    def wait_for(self, predicate, timeout):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.1)
        return False

    def wait_for_pipe(self, timeout=10):
        self.assertTrue(
            self.wait_for(lambda: os.path.exists(self.wake_path) and stat.S_ISFIFO(os.stat(self.wake_path).st_mode), timeout),
            "wake pipe never appeared",
        )

    def log_text(self):
        if not os.path.exists(self.log_path):
            return ""
        with open(self.log_path) as f:
            return f.read()

    def stop_and_read(self, p, timeout=10):
        p.send_signal(signal.SIGTERM)
        out, err = p.communicate(timeout=timeout)
        return out, err, p.returncode


class TestPipeWriteTriggersRound(SuperviseRepoTestCase):
    def test_write_wakes_a_round(self):
        p = self.start_supervisor("--sweep", "300")
        self.wait_for_pipe()
        self.assertTrue(self.wait_for(lambda: "start" in self.log_text(), 10), self.log_text())

        fd = os.open(self.wake_path, os.O_WRONLY | os.O_NONBLOCK)
        try:
            os.write(fd, b"update sometask\n")
        finally:
            os.close(fd)

        self.assertTrue(self.wait_for(lambda: "pipe [update sometask]" in self.log_text(), 10), self.log_text())

        out, err, rc = self.stop_and_read(p)
        self.assertEqual(out.strip(), "taken over")
        self.assertEqual(rc, 0)


class TestSweepFiresWithNoWrites(SuperviseRepoTestCase):
    def test_sweep_happens(self):
        p = self.start_supervisor("--sweep", "2")
        self.wait_for_pipe()
        self.assertTrue(self.wait_for(lambda: "sweep" in self.log_text(), 15), self.log_text())
        out, err, rc = self.stop_and_read(p)
        self.assertEqual(out.strip(), "taken over")
        self.assertEqual(rc, 0)


class TestTakeover(SuperviseRepoTestCase):
    def test_second_supervisor_takes_over_the_first(self):
        first = self.start_supervisor("--sweep", "300")
        self.wait_for_pipe()
        self.assertTrue(self.wait_for(lambda: "start" in self.log_text(), 10), self.log_text())

        second = self.start_supervisor("--sweep", "300")

        out, err = first.communicate(timeout=20)
        self.assertEqual(out.strip(), "taken over")
        self.assertEqual(first.returncode, 0)

        self.stop_and_read(second)


class TestRunningFlag(SuperviseRepoTestCase):
    def test_running_before_and_after(self):
        before = run(self.repo, sys.executable, SUPERVISE_PY, "--running")
        self.assertEqual(before.stdout.strip(), "no supervisor running")

        p = self.start_supervisor("--sweep", "300")
        self.wait_for_pipe()
        self.assertTrue(self.wait_for(lambda: "start" in self.log_text(), 10), self.log_text())

        during = run(self.repo, sys.executable, SUPERVISE_PY, "--running")
        self.assertIn("supervisor running: pid", during.stdout)

        out, err, rc = self.stop_and_read(p)
        self.assertEqual(rc, 0)

        after = run(self.repo, sys.executable, SUPERVISE_PY, "--running")
        self.assertEqual(after.stdout.strip(), "no supervisor running")


class TestFailedTaskWakes(SuperviseRepoTestCase):
    def test_failed_claimed_task_with_no_process_wakes_with_comment(self):
        # supervise.py never wakes for a needs-person state present at its first look
        # (that's the baseline); the task fails only after that first look settles.
        p = self.start_supervisor("--sweep", "2")
        self.wait_for_pipe()
        self.assertTrue(self.wait_for(lambda: "start" in self.log_text(), 10), self.log_text())

        t = self.create(
            "create", "--title", "T", "--type", "task", "--metadata", '{"verify": "true"}'
        )
        self.bd(
            "update", t, "--claim",
            "--set-metadata", "dispatch_session=no-such-session",
            "--set-metadata", "dispatch_state=failed",
        )
        self.bd("comments", "add", t, "it broke")

        out, err = p.communicate(timeout=20)
        self.assertIn(f"blocked {t} failed: it broke", out)
        self.assertEqual(p.returncode, 0)


if __name__ == "__main__":
    unittest.main()
