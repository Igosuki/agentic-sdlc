import contextlib
import json
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
SCRIPTS_DIR = os.path.join(TESTS_DIR, "..", "scripts")

FAKE_RESUME_TASK = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_RESUME_LOG"
if [[ "${FAKE_RESUME_FAIL:-}" == 1 ]]; then
  echo "boom: resume-task failed" >&2
  exit 2
fi
echo "resumed $1 /worktree /log"
"""


def run(cwd, *args, env=None, check=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env)
    if check is not None and result.returncode != check:
        raise AssertionError(f"{args} exited {result.returncode} (expected {check})\n{result.stdout}\n{result.stderr}")
    return result


class BdRepoTestCase(unittest.TestCase):
    """A real bd repository, with resume-reviewed.sh run next to a fake resume-task.sh
    (resume-reviewed.sh finds it by its own directory, not PATH), so a resume never
    starts a real worker."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="resume-reviewed-test-")
        run(self.repo, "git", "init", "-q")
        run(self.repo, "git", "config", "user.email", "test@test.com")
        run(self.repo, "git", "config", "user.name", "test")
        run(self.repo, "bd", "init", "-q")

        self.scripts = tempfile.mkdtemp(prefix="resume-reviewed-scripts-")
        self.script = os.path.join(self.scripts, "resume-reviewed.sh")
        shutil.copy(os.path.join(SCRIPTS_DIR, "resume-reviewed.sh"), self.script)
        os.chmod(self.script, os.stat(self.script).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        fake_resume = os.path.join(self.scripts, "resume-task.sh")
        with open(fake_resume, "w") as f:
            f.write(FAKE_RESUME_TASK)
        os.chmod(fake_resume, os.stat(fake_resume).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        self.resume_log = os.path.join(self.scripts, "resume.log")
        self.env = dict(os.environ, FAKE_RESUME_LOG=self.resume_log)
        self.processes = []

    def tearDown(self):
        for p in self.processes:
            with contextlib.suppress(Exception):
                p.send_signal(signal.SIGKILL)
                p.wait(timeout=5)
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.scripts, ignore_errors=True)

    def bd(self, *args, check=0):
        return run(self.repo, "bd", *args, check=check)

    def bd_id(self, *args):
        return self.bd(*args, "--silent").stdout.strip()

    def show(self, bead_id):
        return json.loads(self.bd("show", bead_id, "--json").stdout)[0]

    def resume_reviewed(self, *args, env=None, check=0):
        full_env = dict(self.env)
        if env:
            full_env.update(env)
        return run(self.repo, self.script, *args, env=full_env, check=check)

    def resume_calls(self):
        if not os.path.exists(self.resume_log):
            return []
        with open(self.resume_log) as f:
            return [line for line in f.read().splitlines() if line]

    def spawn_worker(self, *extra_argv):
        p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", *extra_argv])
        self.processes.append(p)
        time.sleep(0.3)
        return p

    def make_task(self, session="sess-1"):
        """A claimed task awaiting review, blocked by a fresh (open) human gate."""
        task = self.bd_id("create", "--title", "T", "--type", "task", "--metadata", '{"verify": "true"}')
        gate = json.loads(
            self.bd("gate", "create", "--type=human", "--blocks", task, "--reason", "human review", "--json").stdout
        )["id"]
        self.bd(
            "update", task, "--claim",
            "--set-metadata", f"dispatch_session={session}",
            "--set-metadata", "dispatch_state=awaiting-review",
            "--set-metadata", f"dispatch_review_gate={gate}",
        )
        return task, gate


class TestArguments(BdRepoTestCase):
    def test_no_argument_exits_2(self):
        result = self.resume_reviewed(check=2)
        self.assertEqual(result.stdout, "")

    def test_two_arguments_exits_2(self):
        result = self.resume_reviewed("a", "b", check=2)
        self.assertEqual(result.stdout, "")

    def test_help_exits_0(self):
        result = self.resume_reviewed("-h", check=0)
        self.assertIn("Usage: resume-reviewed.sh", result.stdout)


class TestNotAwaitingReview(BdRepoTestCase):
    def test_open_task_exits_2(self):
        task = self.bd_id("create", "--title", "T", "--type", "task", "--metadata", '{"verify": "true"}')

        result = self.resume_reviewed(task, check=2)

        self.assertEqual(result.stdout, "")
        self.assertIn(task, result.stderr)

    def test_in_progress_without_awaiting_review_exits_2(self):
        task = self.bd_id("create", "--title", "T", "--type", "task", "--metadata", '{"verify": "true"}')
        self.bd("update", task, "--claim", "--set-metadata", "dispatch_session=sess-1")

        result = self.resume_reviewed(task, check=2)

        self.assertEqual(result.stdout, "")
        self.assertEqual(self.resume_calls(), [])


class TestGateOpen(BdRepoTestCase):
    def test_open_gate_prints_nothing_and_exits_0(self):
        task, gate = self.make_task()

        result = self.resume_reviewed(task)

        self.assertEqual(result.stdout, "")
        self.assertEqual(self.resume_calls(), [])
        self.assertEqual(self.show(task)["metadata"]["dispatch_state"], "awaiting-review")


class TestWorkerRunning(BdRepoTestCase):
    def test_running_worker_prints_nothing_and_exits_0(self):
        task, gate = self.make_task(session="session-race")
        self.bd("gate", "resolve", gate)
        self.spawn_worker("--session-id", "session-race")

        result = self.resume_reviewed(task)

        self.assertEqual(result.stdout, "")
        self.assertEqual(self.resume_calls(), [])
        self.assertEqual(self.show(task)["metadata"]["dispatch_state"], "awaiting-review")


class TestResumes(BdRepoTestCase):
    def test_closed_gate_resumes_with_the_review_prompt(self):
        task, gate = self.make_task()
        self.bd("gate", "resolve", gate)

        result = self.resume_reviewed(task)

        self.assertIn(f"resumed {task}", result.stdout)
        calls = self.resume_calls()
        self.assertEqual(len(calls), 1)
        self.assertIn(f"{task} --ended --prompt", calls[0])
        self.assertIn(gate, calls[0])
        self.assertIn(f"finish-task.sh {task}", calls[0])
        self.assertNotIn("dispatch_state", self.show(task)["metadata"])

    def test_failed_resume_restores_awaiting_review(self):
        task, gate = self.make_task()
        self.bd("gate", "resolve", gate)

        result = self.resume_reviewed(task, env={"FAKE_RESUME_FAIL": "1"})

        self.assertIn(f"not resumed {task}: boom: resume-task failed", result.stdout)
        self.assertEqual(self.show(task)["metadata"]["dispatch_state"], "awaiting-review")


if __name__ == "__main__":
    unittest.main()
