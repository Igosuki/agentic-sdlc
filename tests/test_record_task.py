import json
import os
import sys
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, TESTS_DIR)
from test_tasks import BdRepoTestCase, run  # noqa: E402

SCRIPTS_DIR = os.path.join(TESTS_DIR, "..", "scripts")
RECORD_TASK_SH = os.path.join(SCRIPTS_DIR, "record-task.sh")


class TestRecordTaskFailed(BdRepoTestCase):
    def record(self, *args, check=True):
        return run(self.repo, RECORD_TASK_SH, *args, check=check)

    def show(self, task_id):
        return json.loads(self.bd("show", task_id, "--json").stdout)[0]

    def comments(self, task_id):
        return json.loads(self.bd("comments", task_id, "--json").stdout)

    def event_for(self, task_id):
        events = json.loads(self.bd("list", "--type", "event", "--all", "--json").stdout)
        return next(e for e in events if e.get("target") == task_id)

    def claim(self, task, session, **metadata):
        args = ["update", task, "--claim", "--set-metadata", f"dispatch_session={session}"]
        for key, value in metadata.items():
            args += ["--set-metadata", f"dispatch_{key}={value}"]
        self.bd(*args)

    def create_task(self):
        return self.create("create", "--title", "Task", "--type", "task", "--metadata", '{"verify": "true"}')

    def log_path(self, task_id, session):
        common_dir = run(self.repo, "git", "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
        return os.path.join(common_dir, "sdlc", "logs", f"{task_id}-{session}.jsonl")

    def write_log(self, task_id, session, lines):
        path = self.log_path(task_id, session)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            for line in lines:
                f.write(line + "\n")
        return path

    def test_records_failed_with_comment_and_event_bead(self):
        task = self.create_task()
        self.claim(task, "session-a")
        self.write_log(task, "session-a", ['{"type": "dispatch_run", "started": "t0"}'])

        result = self.record(task, "--failed", "crashed again after 3 resumes")
        self.assertEqual(result.returncode, 0)
        self.assertTrue(result.stdout.startswith(f"failed {task} "))
        self.assertIn(" event ", result.stdout)

        metadata = self.show(task)["metadata"]
        self.assertEqual(metadata["dispatch_state"], "failed")
        self.assertIn("dispatch_cost", metadata)

        self.assertEqual(self.comments(task)[-1]["text"], "crashed again after 3 resumes")

        event = self.event_for(task)
        self.assertEqual(event["event_kind"], "dispatch.failed")
        self.assertEqual(event["description"], "crashed again after 3 resumes")
        self.assertEqual(event["status"], "closed")
        self.assertEqual(json.loads(event["payload"])["result"], "crashed")

    def test_works_with_no_log_file(self):
        task = self.create_task()
        self.claim(task, "session-b")

        result = self.record(task, "--failed", "worktree gone")
        self.assertEqual(result.returncode, 0)

        metadata = self.show(task)["metadata"]
        self.assertEqual(metadata["dispatch_state"], "failed")
        self.assertEqual(float(metadata["dispatch_cost"]), 0)
        self.assertEqual(self.comments(task)[-1]["text"], "worktree gone")

    def test_refuses_task_with_an_outcome(self):
        task = self.create_task()
        self.claim(task, "session-c", state="merged")

        result = self.record(task, "--failed", "too late", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("already has an outcome recorded", result.stderr)

    def test_refuses_when_the_log_has_a_result(self):
        task = self.create_task()
        self.claim(task, "session-d")
        self.write_log(task, "session-d", [
            '{"type": "dispatch_run", "started": "t0"}',
            '{"type": "result", "subtype": "success", "is_error": false, "result": "done", '
            '"total_cost_usd": 0.1, "num_turns": 1, "duration_ms": 100}',
        ])

        result = self.record(task, "--failed", "actually it finished", check=False)
        self.assertEqual(result.returncode, 2)
        self.assertIn("run record-task.sh without --failed", result.stderr)

        # refused: no outcome, no comment, no event bead recorded.
        self.assertNotIn("dispatch_state", self.show(task)["metadata"])
        self.assertEqual(self.comments(task), [])


if __name__ == "__main__":
    unittest.main()
