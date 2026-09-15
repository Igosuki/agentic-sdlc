import json
import os
import subprocess
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
from test_tasks import BdRepoTestCase, run  # noqa: E402

SCRIPTS_DIR = os.path.join(TESTS_DIR, "..", "skills", "dispatch", "scripts")
LOGS_PY = os.path.join(SCRIPTS_DIR, "logs.py")


class TestLogs(BdRepoTestCase):
    def setUp(self):
        super().setUp()
        common_dir = run(self.repo, "git", "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        self.logs_dir = os.path.join(common_dir, "sdlc", "logs")
        os.makedirs(self.logs_dir, exist_ok=True)

    def logs(self, *args, check=True, stdin=None):
        return run(self.repo, sys.executable, LOGS_PY, *args, check=check, input=stdin)

    def log_path(self, task_id, session):
        return os.path.join(self.logs_dir, f"{task_id}-{session}.jsonl")

    def write_log(self, task_id, session, lines):
        with open(self.log_path(task_id, session), "w") as f:
            for line in lines:
                f.write(json.dumps(line) + "\n")

    def dispatch(self, task_id, session):
        self.bd("update", task_id, "--claim", "--set-metadata", f"dispatch_session={session}")

    def test_never_dispatched(self):
        task = self.create("create", "--title", "Task", "--type", "task")
        result = self.logs(task, check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("never dispatched", result.stdout)

    def test_unknown_task_exits_2(self):
        result = self.logs("no-such-task", check=False)
        self.assertEqual(result.returncode, 2)

    def test_follow_without_a_terminal_is_refused(self):
        task = self.create("create", "--title", "Task", "--type", "task")
        self.dispatch(task, "s1")
        self.write_log(task, "s1", [{"type": "dispatch_run", "started": "t0"}])
        result = self.logs(task, "--follow", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("terminal", result.stderr)

    def test_multiline_text_and_tool_input_become_one_line_each(self):
        task = self.create("create", "--title", "Task", "--type", "task")
        self.dispatch(task, "s1")
        self.write_log(
            task,
            "s1",
            [
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "line one\nline two"}]}},
                {
                    "type": "assistant",
                    "message": {
                        "content": [{"type": "tool_use", "name": "Bash", "input": {"command": "echo a\necho b"}}]
                    },
                },
            ],
        )
        result = self.logs(task)
        body_lines = [line for line in result.stdout.splitlines() if not line.startswith("═══")]
        self.assertEqual(len(body_lines), 2)
        self.assertEqual(body_lines[0], "● line one line two")
        self.assertEqual(body_lines[1], "→ Bash echo a echo b")

    def test_cost_is_labelled_as_running_total(self):
        task = self.create("create", "--title", "Task", "--type", "task")
        self.dispatch(task, "s1")
        self.write_log(task, "s1", [{"type": "result", "subtype": "success", "total_cost_usd": 0.4, "num_turns": 2}])
        result = self.logs(task)
        self.assertIn("running total $0.4", result.stdout)

    def test_missing_jsonl_prints_the_wt_error(self):
        task = self.create("create", "--title", "Task", "--type", "task")
        self.dispatch(task, "s1")
        with open(self.log_path(task, "s1") + ".wt", "w") as f:
            f.write("worktree already exists\n")
        result = self.logs(task)
        self.assertIn(self.log_path(task, "s1") + ".wt", result.stdout)
        self.assertIn("worktree already exists", result.stdout)

    def test_last_n_reports_omitted_count_and_repeats_the_header(self):
        task = self.create("create", "--title", "Task", "--type", "task")
        self.dispatch(task, "s1")
        self.write_log(
            task,
            "s1",
            [{"type": "assistant", "message": {"content": [{"type": "text", "text": f"msg {i}"}]}} for i in range(5)],
        )
        full = self.logs(task).stdout.splitlines()
        result = self.logs(task, "--last", "2")
        lines = result.stdout.splitlines()
        self.assertEqual(lines[0], f"({len(full) - 2} earlier lines omitted)")
        self.assertEqual(lines[1], full[0])  # the session header is repeated
        self.assertEqual(lines[2:], full[-2:])

    def test_rolled_back_session_falls_back_to_the_wt_file(self):
        task = self.create("create", "--title", "Task", "--type", "task")
        session = "s1"
        with open(self.log_path(task, session) + ".wt", "w") as f:
            f.write("could not create the worktree\n")
        result = self.logs(task)
        self.assertIn("could not create the worktree", result.stdout)
        self.assertNotIn("never dispatched", result.stdout)

    def test_rolled_back_session_fallback_does_not_match_a_longer_task_id(self):
        task = self.create("create", "--title", "Task", "--type", "task")
        with open(self.log_path(task, "s1") + ".wt", "w") as f:
            f.write("this task's error\n")
        with open(self.log_path(f"{task}9", "s2") + ".wt", "w") as f:
            f.write("a different task's error\n")
        result = self.logs(task)
        self.assertIn("this task's error", result.stdout)
        self.assertNotIn("a different task's error", result.stdout)

    def test_raw_lists_the_log_files(self):
        task = self.create("create", "--title", "Task", "--type", "task")
        self.dispatch(task, "s1")
        self.write_log(task, "s1", [{"type": "dispatch_run", "started": "t0"}])
        result = self.logs(task, "--raw")
        self.assertEqual(result.stdout.strip(), self.log_path(task, "s1"))

    def test_raw_help_describes_listing_not_printing(self):
        result = subprocess.run([sys.executable, LOGS_PY, "--help"], capture_output=True, text=True)
        self.assertIn("list the log files of each attempt", result.stdout)


if __name__ == "__main__":
    unittest.main()
