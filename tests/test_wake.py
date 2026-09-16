import contextlib
import json
import os
import select
import stat
import subprocess
import sys
import tempfile
import time
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
from test_tasks import BdRepoTestCase, run  # noqa: E402

REPO_ROOT = os.path.join(TESTS_DIR, "..")
SCRIPTS_DIR = os.path.join(REPO_ROOT, "scripts")
INIT_SH = os.path.join(REPO_ROOT, "skills", "init", "scripts", "init.sh")
START_WORKER_SH = os.path.join(SCRIPTS_DIR, "start-worker.sh")

HOOK_NAMES = ("on_create", "on_update", "on_close")
HOOK_MARKER = "# sdlc: wake the supervisor"

FAKE_CLAUDE = """#!/usr/bin/env bash
echo '{"type":"result","is_error":false,"subtype":"success","result":"done","total_cost_usd":0.01,"num_turns":1,"duration_ms":10}'
"""


class WakeRepoTestCase(BdRepoTestCase):
    """A BdRepoTestCase with an initial commit, since init.sh requires one."""

    def setUp(self):
        super().setUp()
        run(self.repo, "git", "commit", "-q", "--allow-empty", "-m", "init")

    def init(self, *args, check=True):
        return run(self.repo, "bash", INIT_SH, *args, check=check)

    def hook_path(self, name):
        return os.path.join(self.repo, ".beads", "hooks", name)

    def common_dir(self):
        return run(self.repo, "git", "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()


class TestInitInstallsHooks(WakeRepoTestCase):
    def test_installs_three_executable_hooks(self):
        result = self.init()
        for name in HOOK_NAMES:
            path = self.hook_path(name)
            self.assertTrue(os.path.isfile(path))
            mode = os.stat(path).st_mode
            self.assertTrue(mode & stat.S_IXUSR and mode & stat.S_IXGRP and mode & stat.S_IXOTH)
            self.assertIn(f"created .beads/hooks/{name}", result.stdout)
            with open(path) as f:
                lines = f.read().splitlines()
            self.assertEqual(lines[1], HOOK_MARKER)

    def test_second_run_keeps_hooks(self):
        self.init()
        result = self.init()
        for name in HOOK_NAMES:
            self.assertIn(f"kept .beads/hooks/{name}", result.stdout)

    def test_foreign_hook_left_untouched_and_reported(self):
        os.makedirs(os.path.join(self.repo, ".beads", "hooks"), exist_ok=True)
        foreign_path = self.hook_path("on_update")
        foreign_body = "#!/usr/bin/env bash\necho custom\n"
        with open(foreign_path, "w") as f:
            f.write(foreign_body)
        os.chmod(foreign_path, 0o755)

        result = self.init()

        with open(foreign_path) as f:
            self.assertEqual(f.read(), foreign_body)
        self.assertIn("kept .beads/hooks/on_update (not ours", result.stdout)
        self.assertIn("created .beads/hooks/on_create", result.stdout)
        self.assertIn("created .beads/hooks/on_close", result.stdout)


class WakePipeTestCase(WakeRepoTestCase):
    """Hooks installed, with a FIFO wake pipe held open read-write non-blocking, as supervise.py would."""

    def setUp(self):
        super().setUp()
        self.init()
        self.sdlc_dir = os.path.join(self.common_dir(), "sdlc")
        os.makedirs(self.sdlc_dir, exist_ok=True)
        self.wake_path = os.path.join(self.sdlc_dir, "wake")
        os.mkfifo(self.wake_path)
        self.wake_fd = os.open(self.wake_path, os.O_RDWR | os.O_NONBLOCK)

    def tearDown(self):
        with contextlib.suppress(OSError):
            os.close(self.wake_fd)
        super().tearDown()

    def read_line(self, timeout):
        deadline = time.time() + timeout
        buf = b""
        while time.time() < deadline and b"\n" not in buf:
            remaining = deadline - time.time()
            r, _, _ = select.select([self.wake_fd], [], [], max(0, min(0.2, remaining)))
            if r:
                with contextlib.suppress(BlockingIOError):
                    buf += os.read(self.wake_fd, 4096)
        return buf.decode() if buf else None

    def drain(self):
        with contextlib.suppress(BlockingIOError):
            while os.read(self.wake_fd, 4096):
                pass


class TestBdWritesWakeLine(WakePipeTestCase):
    def setUp(self):
        super().setUp()
        self.task = self.create("create", "--title", "T", "--type", "task")
        self.drain()

    def test_bd_update_wakes_within_5s(self):
        self.bd("update", self.task, "--set-metadata", "x=1")
        self.assertEqual(self.read_line(5), f"update {self.task}\n")

    def test_supervisor_env_produces_nothing_within_2s(self):
        env = dict(os.environ, SDLC_SUPERVISOR="1")
        subprocess.run(
            ["bd", "update", self.task, "--set-metadata", "y=2"],
            cwd=self.repo, env=env, capture_output=True, text=True, check=True,
        )
        self.assertIsNone(self.read_line(2))


class TestBdUpdateWithoutPipe(WakeRepoTestCase):
    def test_update_still_succeeds_with_no_pipe(self):
        self.init()
        task = self.create("create", "--title", "T", "--type", "task")
        result = self.bd("update", task, "--set-metadata", "x=1", check=False)
        self.assertEqual(result.returncode, 0)


class TestStartWorkerWrapperWakes(WakeRepoTestCase):
    """Real bd, real git worktree (wt), a fake claude on PATH. See test_finish_review.py's
    BdWorktreeTestCase for the same pattern."""

    def setUp(self):
        super().setUp()
        self.init()
        self.sdlc_dir = os.path.join(self.common_dir(), "sdlc")
        os.makedirs(self.sdlc_dir, exist_ok=True)
        self.wake_path = os.path.join(self.sdlc_dir, "wake")
        os.mkfifo(self.wake_path)
        self.wake_fd = os.open(self.wake_path, os.O_RDWR | os.O_NONBLOCK)

        self.bin = tempfile.mkdtemp(prefix="start-worker-bin-")
        claude_path = os.path.join(self.bin, "claude")
        with open(claude_path, "w") as f:
            f.write(FAKE_CLAUDE)
        os.chmod(claude_path, 0o755)
        self.env = dict(os.environ, PATH=f"{self.bin}:{os.environ['PATH']}")

    def tearDown(self):
        with contextlib.suppress(OSError):
            os.close(self.wake_fd)
        super().tearDown()

    def read_line(self, timeout):
        deadline = time.time() + timeout
        buf = b""
        while time.time() < deadline and b"\n" not in buf:
            remaining = deadline - time.time()
            r, _, _ = select.select([self.wake_fd], [], [], max(0, min(0.2, remaining)))
            if r:
                with contextlib.suppress(BlockingIOError):
                    buf += os.read(self.wake_fd, 4096)
        return buf.decode() if buf else None

    def drain(self):
        with contextlib.suppress(BlockingIOError):
            while os.read(self.wake_fd, 4096):
                pass

    def test_wrapper_writes_ended_after_worker(self):
        task = self.create(
            "create", "--title", "T", "--type", "task",
            "--metadata", json.dumps({"dispatch_role": "worker"}),
        )
        self.bd(
            "update", task, "--claim",
            "--set-metadata", "dispatch_session=sess-1",
            "--set-metadata", f"dispatch_branch={task}",
        )
        subprocess.run(
            ["wt", "switch", "--create", task, "--base", "master", "--no-cd", "--format", "json"],
            cwd=self.repo, env=self.env, capture_output=True, text=True, check=True,
        )
        self.drain()
        result = subprocess.run(
            [START_WORKER_SH, task, "--prompt", "hi"],
            cwd=self.repo, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

        # record-task.sh's own bd writes (update, event create/close) land on the pipe first;
        # the wrapper's "ended" line is written only once record-task.sh has finished.
        deadline = time.time() + 15
        lines = []
        while time.time() < deadline:
            line = self.read_line(max(0, deadline - time.time()))
            if line is None:
                break
            lines.append(line)
            if line == f"ended {task}\n":
                break
        self.assertIn(f"ended {task}\n", lines)


if __name__ == "__main__":
    unittest.main()
