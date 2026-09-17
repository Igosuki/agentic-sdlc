import json
import os
import shutil
import subprocess
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(TESTS_DIR, "..", "scripts")
RUN_TASK_SH = os.path.join(SCRIPTS_DIR, "run-task.sh")


def run(cwd, *args, env=None, check=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env)
    if check is not None and result.returncode != check:
        raise AssertionError(f"{args} exited {result.returncode} (expected {check})\n{result.stdout}\n{result.stderr}")
    return result


class TestRunTaskApproval(unittest.TestCase):
    """An unapproved wt.toml hook, with a throwaway HOME so the real
    ~/.config/worktrunk/approvals.toml is never read or written."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="run-task-test-")
        self.home = tempfile.mkdtemp(prefix="run-task-home-")
        self.env = {**os.environ, "HOME": self.home}
        run(self.repo, "git", "init", "-q", "-b", "main", env=self.env, check=0)
        run(self.repo, "git", "config", "user.email", "test@test.com", env=self.env, check=0)
        run(self.repo, "git", "config", "user.name", "test", env=self.env, check=0)
        with open(os.path.join(self.repo, "README.md"), "w") as f:
            f.write("hi\n")
        run(self.repo, "git", "add", "README.md", env=self.env, check=0)
        run(self.repo, "git", "commit", "-q", "-m", "init", env=self.env, check=0)
        run(self.repo, "bd", "init", "-q", env=self.env, check=0)
        os.makedirs(os.path.join(self.repo, ".config"), exist_ok=True)
        with open(os.path.join(self.repo, ".config", "wt.toml"), "w") as f:
            f.write('[pre-start]\nsetup = "touch started"\n')

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.home, ignore_errors=True)

    def bd(self, *args, check=0):
        return run(self.repo, "bd", *args, env=self.env, check=check)

    def show(self, bead_id):
        return json.loads(self.bd("show", bead_id, "--json").stdout)[0]

    def create_task(self):
        return self.bd(
            "create", "--title", "T", "--description", "d", "--acceptance", "a", "--type", "task",
            "--metadata", '{"verify": "true"}', "--silent",
        ).stdout.strip()

    def main_root(self):
        common_dir = run(
            self.repo, "git", "rev-parse", "--path-format=absolute", "--git-common-dir", env=self.env, check=0,
        ).stdout.strip()
        return os.path.dirname(common_dir)

    def run_task(self, task, check=None):
        return run(self.repo, RUN_TASK_SH, task, env=self.env, check=check)

    def test_unapproved_pre_start_hook_gives_the_approval_message(self):
        task = self.create_task()

        result = self.run_task(task, check=1)

        self.assertEqual(
            result.stderr.strip().splitlines()[-1],
            f"error: the project's hooks aren't approved on this machine; "
            f"a person runs wt config approvals add in {self.main_root()}",
        )

    def test_unapproved_pre_start_hook_leaves_the_task_open(self):
        task = self.create_task()

        self.run_task(task, check=1)

        info = self.show(task)
        self.assertEqual(info["status"], "open")
        for key in info.get("metadata") or {}:
            self.assertFalse(key.startswith("dispatch_"), key)


if __name__ == "__main__":
    unittest.main()
