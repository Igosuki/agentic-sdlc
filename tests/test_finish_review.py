import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(TESTS_DIR, "..", "scripts")
FINISH_TASK_SH = os.path.join(SCRIPTS_DIR, "finish-task.sh")
MERGE_QUEUE_SH = os.path.join(SCRIPTS_DIR, "merge-queue.sh")

FAKE_CLAUDE = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "$FAKE_CLAUDE_LOG"
jq -cn --arg v "${FAKE_CLAUDE_VERDICT:-approve}" --arg s "${FAKE_CLAUDE_SUMMARY:-looks fine}" \\
  '{total_cost_usd: 0.01, structured_output: {verdict: $v, summary: $s, findings: []}}'
"""


def run(cwd, *args, env=None, check=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True, env=env)
    if check is not None and result.returncode != check:
        raise AssertionError(f"{args} exited {result.returncode} (expected {check})\n{result.stdout}\n{result.stderr}")
    return result


class TestFinishAgentReview(unittest.TestCase):
    """A real bd repo, a real git worktree, and a fake claude on PATH."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="finish-review-test-")
        run(self.repo, "git", "init", "-q", "-b", "main")
        run(self.repo, "git", "config", "user.email", "test@test.com")
        run(self.repo, "git", "config", "user.name", "test")
        with open(os.path.join(self.repo, "README.md"), "w") as f:
            f.write("hi\n")
        run(self.repo, "git", "add", "README.md")
        run(self.repo, "git", "commit", "-q", "-m", "init")
        run(self.repo, "bd", "init", "-q")
        run(self.repo, MERGE_QUEUE_SH, "ensure", "main", check=0)

        self.bin = tempfile.mkdtemp(prefix="finish-review-bin-")
        claude_path = os.path.join(self.bin, "claude")
        with open(claude_path, "w") as f:
            f.write(FAKE_CLAUDE)
        st = os.stat(claude_path)
        os.chmod(claude_path, st.st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

        self.claude_log = os.path.join(self.bin, "claude.log")
        self.env = dict(
            os.environ,
            PATH=f"{self.bin}:{os.environ['PATH']}",
            FAKE_CLAUDE_LOG=self.claude_log,
        )

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)
        shutil.rmtree(self.bin, ignore_errors=True)

    def bd(self, *args, check=0):
        return run(self.repo, "bd", *args, check=check)

    def show(self, bead_id):
        return json.loads(self.bd("show", bead_id, "--json").stdout)[0]

    def claude_calls(self):
        if not os.path.exists(self.claude_log):
            return []
        with open(self.claude_log) as f:
            return [line for line in f.read().splitlines() if line]

    def dispatch_task(self, review="agent"):
        """Creates a task claimed on its own worktree, with one commit to review."""
        task = self.bd(
            "create", "--title", "T", "--description", "d", "--acceptance", "a", "--type", "task",
            "--metadata", json.dumps({"review": review, "scope": "s", "verify": "true"}), "--silent",
        ).stdout.strip()
        session = "sess-1"
        self.bd(
            "update", task, "--claim",
            "--set-metadata", f"dispatch_session={session}",
            "--set-metadata", "dispatch_base=main",
            "--set-metadata", f"dispatch_branch={task}",
            "--set-metadata", "dispatch_role=worker",
        )
        run(self.repo, "wt", "switch", "--create", task, "--base", "main", "--no-cd", "--format", "json", check=0)
        wt_path = os.path.join(self.repo, ".worktrees", task)
        with open(os.path.join(wt_path, "README.md"), "a") as f:
            f.write("change\n")
        run(wt_path, "git", "add", "README.md")
        run(wt_path, "git", "commit", "-q", "-m", "change")
        return task

    def finish(self, task_id, verdict=None, summary=None, check=None):
        env = dict(self.env)
        if verdict is not None:
            env["FAKE_CLAUDE_VERDICT"] = verdict
        if summary is not None:
            env["FAKE_CLAUDE_SUMMARY"] = summary
        return run(self.repo, FINISH_TASK_SH, task_id, env=env, check=check)

    def test_prompt_names_the_review_skill(self):
        task = self.dispatch_task()

        self.finish(task, verdict="approve")

        calls = self.claude_calls()
        self.assertEqual(len(calls), 1)
        self.assertTrue(
            calls[0].endswith(f"/sdlc:review {task}") or "SKILL.md body" in calls[0],
            calls[0],
        )
        self.assertIn("--json-schema", calls[0])

    def test_approve_merges_and_closes_the_task(self):
        task = self.dispatch_task()

        result = self.finish(task, verdict="approve")

        self.assertEqual(result.returncode, 0)
        self.assertIn(f"merged {task} into main", result.stdout)
        info = self.show(task)
        self.assertEqual(info["status"], "closed")
        self.assertEqual(info["metadata"]["dispatch_review"], "approved")

    def test_requested_changes_records_verdict_and_exits_for_the_worker_to_fix(self):
        task = self.dispatch_task()

        result = self.finish(task, verdict="changes", summary="needs work", check=1)

        self.assertIn("review round 1 requested changes", result.stdout)
        info = self.show(task)
        self.assertEqual(info["status"], "in_progress")
        self.assertEqual(info["metadata"]["dispatch_review"], "changes")
        self.assertEqual(info["metadata"]["dispatch_review_rounds"], 1)
        comments = json.loads(self.bd("comments", task, "--json").stdout)
        self.assertTrue(any("needs work" in c["text"] for c in comments))

    def test_three_rounds_of_changes_needs_a_person(self):
        task = self.dispatch_task()

        self.finish(task, verdict="changes", check=1)
        self.finish(task, verdict="changes", check=1)
        result = self.finish(task, verdict="changes", check=3)

        self.assertIn("needs a person", result.stdout)
        info = self.show(task)
        self.assertEqual(info["metadata"]["dispatch_review_rounds"], 3)

    def test_review_none_never_calls_claude(self):
        task = self.dispatch_task(review="none")

        result = self.finish(task, check=0)

        self.assertEqual(result.returncode, 0)
        self.assertEqual(self.claude_calls(), [])


if __name__ == "__main__":
    unittest.main()
