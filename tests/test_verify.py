import json
import os
import shutil
import subprocess
import tempfile
import unittest

TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
SCRIPTS_DIR = os.path.join(TESTS_DIR, "..", "scripts")
VERIFY_SH = os.path.join(SCRIPTS_DIR, "verify.sh")
FINISH_TASK_SH = os.path.join(SCRIPTS_DIR, "finish-task.sh")
MERGE_QUEUE_SH = os.path.join(SCRIPTS_DIR, "merge-queue.sh")


def run(cwd, *args, check=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check is not None and result.returncode != check:
        raise AssertionError(f"{args} exited {result.returncode} (expected {check})\n{result.stdout}\n{result.stderr}")
    return result


class BdWorktreeTestCase(unittest.TestCase):
    """A real bd repo and real git worktrees, no stubs."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="verify-test-")
        run(self.repo, "git", "init", "-q", "-b", "main")
        run(self.repo, "git", "config", "user.email", "test@test.com")
        run(self.repo, "git", "config", "user.name", "test")
        with open(os.path.join(self.repo, "README.md"), "w") as f:
            f.write("hi\n")
        run(self.repo, "git", "add", "README.md")
        run(self.repo, "git", "commit", "-q", "-m", "init")
        run(self.repo, "bd", "init", "-q")
        run(self.repo, MERGE_QUEUE_SH, "ensure", "main", check=0)

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def bd(self, *args, check=0):
        return run(self.repo, "bd", *args, check=check)

    def show(self, bead_id):
        return json.loads(self.bd("show", bead_id, "--json").stdout)[0]

    def comments(self, bead_id):
        return json.loads(self.bd("comments", bead_id, "--json").stdout)

    def verify(self, target, check=None):
        return run(self.repo, VERIFY_SH, target, check=check)

    def finish(self, task_id, check=None):
        return run(self.repo, FINISH_TASK_SH, task_id, check=check)

    def create_task(self, verify=None, parent=None, review="none"):
        metadata = {"review": review}
        if verify is not None:
            metadata["verify"] = verify
        args = [
            "create", "--title", "T", "--description", "d", "--acceptance", "a", "--type", "task",
            "--metadata", json.dumps(metadata), "--silent",
        ]
        if parent:
            args += ["--parent", parent]
        return self.bd(*args).stdout.strip()

    def wt_path(self, branch):
        return os.path.join(self.repo, ".worktrees", branch)

    def claim_and_switch(self, task, base="main"):
        self.bd(
            "update", task, "--claim",
            "--set-metadata", "dispatch_session=sess-1",
            "--set-metadata", f"dispatch_base={base}",
            "--set-metadata", f"dispatch_branch={task}",
            "--set-metadata", "dispatch_role=worker",
        )
        run(self.repo, "wt", "switch", "--create", task, "--base", base, "--no-cd", "--format", "json", check=0)

    def dispatch_task(self, verify="true", parent=None, review="none", base="main"):
        """Creates a task claimed on its own worktree, based on `base`."""
        task = self.create_task(verify=verify, parent=parent, review=review)
        self.claim_and_switch(task, base=base)
        return task

    def commit(self, branch, filename, content):
        path = self.wt_path(branch)
        with open(os.path.join(path, filename), "w") as f:
            f.write(content)
        run(path, "git", "add", filename)
        run(path, "git", "commit", "-q", "-m", f"change {filename}")

    def remove_and_commit(self, branch, filename):
        path = self.wt_path(branch)
        os.remove(os.path.join(path, filename))
        run(path, "git", "rm", "-q", filename)
        run(path, "git", "commit", "-q", "-m", f"remove {filename}")


class TestVerifyTask(BdWorktreeTestCase):
    def test_passes_in_the_tasks_worktree(self):
        task = self.dispatch_task(verify="test -f README.md")

        result = self.verify(task, check=0)

        self.assertIn(f"{task} passed", result.stdout)

    def test_fails_and_prints_the_commands_output(self):
        task = self.dispatch_task(verify="echo boom && false")

        result = self.verify(task, check=1)

        self.assertIn("boom", result.stdout)
        self.assertIn(f"verify {task} failed", result.stdout)

    def test_no_verify_command_is_an_error(self):
        task = self.create_task()

        result = self.verify(task, check=2)

        self.assertIn("no metadata.verify", result.stderr)

    def test_no_worktree_is_an_error(self):
        task = self.create_task(verify="true")
        self.bd("update", task, "--set-metadata", f"dispatch_branch={task}")

        result = self.verify(task, check=2)

        self.assertIn("no worktree", result.stderr)

    def test_unknown_bead_is_an_error(self):
        result = self.verify("nope-1", check=2)

        self.assertIn("no bead", result.stderr)


class TestVerifyParent(BdWorktreeTestCase):
    def test_runs_every_open_child_and_skips_closed_ones(self):
        parent = self.create_task(verify=None)
        open_child = self.dispatch_task(verify="test -f README.md", parent=parent)
        closed_child = self.create_task(verify="false", parent=parent)
        self.bd("close", closed_child, "--reason", "done")

        result = self.verify(parent, check=0)

        self.assertIn(f"verify {open_child}", result.stdout)
        self.assertNotIn(closed_child, result.stdout)

    def test_checks_a_grandchild_too(self):
        parent = self.create_task(verify=None)
        child = self.create_task(verify=None, parent=parent)
        grandchild = self.dispatch_task(verify="test -f README.md", parent=child)

        result = self.verify(parent, check=0)

        self.assertIn(f"verify {grandchild}", result.stdout)

    def test_a_failing_descendant_stops_and_fails(self):
        parent = self.create_task(verify=None)
        failing = self.dispatch_task(verify="false", parent=parent)

        result = self.verify(parent, check=1)

        self.assertIn(f"verify {failing} failed", result.stdout)


class TestVerifyEpic(BdWorktreeTestCase):
    def make_epic(self, metadata=None):
        args = [
            "create", "--title", "E", "--description", "d", "--acceptance", "a", "--type", "epic", "--silent",
        ]
        if metadata:
            args += ["--metadata", json.dumps(metadata)]
        return self.bd(*args).stdout.strip()

    def test_direct_mode_runs_closed_tasks_checks_on_the_target_then_pre_merge_checks(self):
        epic = self.make_epic()
        task = self.create_task(verify="test -f README.md", parent=epic)
        self.bd("close", task, "--reason", "done")

        result = self.verify(epic, check=0)

        self.assertIn(f"verify {task}", result.stdout)
        self.assertIn("pre-merge checks", result.stdout)
        self.assertIn(f"{epic} passed", result.stdout)

    def test_direct_mode_skips_a_task_not_yet_merged(self):
        epic = self.make_epic()
        open_task = self.create_task(verify="false", parent=epic)

        result = self.verify(epic, check=0)

        self.assertNotIn(f"verify {open_task}", result.stdout)

    def test_direct_mode_reports_a_broken_check_from_an_earlier_task(self):
        epic = self.make_epic()
        task = self.create_task(verify="test -f gone.txt", parent=epic)
        self.bd("close", task, "--reason", "done")

        result = self.verify(epic, check=1)

        self.assertIn(f"verify {task} failed", result.stdout)

    def test_epic_merge_mode_runs_on_the_epic_branch(self):
        epic = self.make_epic({"dispatch_integration": "epic-merge"})
        run(self.repo, "git", "branch", epic, "main")
        run(self.repo, MERGE_QUEUE_SH, "ensure", epic, check=0)
        run(self.repo, "wt", "switch", epic, "--no-cd", "--format", "json", check=0)
        self.commit(epic, "extra.txt", "x\n")
        task = self.create_task(verify="test -f extra.txt", parent=epic)
        self.bd("close", task, "--reason", "done")

        result = self.verify(epic, check=0)

        self.assertIn(f"verify {task}", result.stdout)

    def test_epic_mode_with_no_worktree_is_an_error(self):
        epic = self.make_epic({"dispatch_integration": "epic-merge"})

        result = self.verify(epic, check=2)

        self.assertIn("no worktree", result.stderr)

    def test_direct_mode_checks_a_task_nested_under_a_parent_task(self):
        epic = self.make_epic()
        parent = self.create_task(verify=None, parent=epic)
        grandchild = self.create_task(verify="test -f README.md", parent=parent)
        self.bd("close", grandchild, "--reason", "done")

        result = self.verify(epic, check=0)

        self.assertIn(f"verify {grandchild}", result.stdout)

    def test_no_pre_merge_flag_skips_the_pre_merge_checks(self):
        epic = self.make_epic()

        result = run(self.repo, VERIFY_SH, "--no-pre-merge", epic, check=0)

        self.assertNotIn("pre-merge checks", result.stdout)


class TestFinishTaskUsesVerifySh(BdWorktreeTestCase):
    def test_success_merges_the_task(self):
        task = self.dispatch_task(verify="test -f README.md")
        self.commit(task, "note.txt", "x\n")

        result = self.finish(task, check=0)

        self.assertIn(f"merged {task} into main", result.stdout)

    def test_a_failing_verify_is_a_problem_for_the_worker_to_fix(self):
        task = self.dispatch_task(verify="echo boom && false")
        self.commit(task, "note.txt", "x\n")

        result = self.finish(task, check=1)

        self.assertIn(f"verify for {task} failed", result.stdout)
        self.assertIn("boom", result.stdout)
        info = self.show(task)
        self.assertEqual(info["status"], "in_progress")

    def test_direct_mode_epic_close_reruns_every_tasks_verify_and_comments_a_failure(self):
        epic = self.bd(
            "create", "--title", "E", "--description", "d", "--acceptance", "a", "--type", "epic", "--silent",
        ).stdout.strip()
        task1 = self.create_task(verify="test -f keep.txt", parent=epic)
        task2 = self.create_task(verify="true", parent=epic)

        self.claim_and_switch(task1)
        self.commit(task1, "keep.txt", "keep me\n")
        self.finish(task1, check=0)
        self.assertEqual(self.show(epic)["status"], "open")

        self.claim_and_switch(task2)
        self.remove_and_commit(task2, "keep.txt")
        result = self.finish(task2, check=0)

        self.assertIn(f"closed epic {epic}", result.stdout)
        self.assertEqual(self.show(epic)["status"], "closed")
        comments = self.comments(epic)
        self.assertTrue(
            any("verify failed after closing" in c["text"] and task1 in c["text"] for c in comments),
            comments,
        )

    def test_direct_mode_epic_close_with_everything_passing_adds_no_comment(self):
        epic = self.bd(
            "create", "--title", "E", "--description", "d", "--acceptance", "a", "--type", "epic", "--silent",
        ).stdout.strip()
        task = self.dispatch_task(verify="test -f README.md", parent=epic)
        self.commit(task, "note.txt", "x\n")

        result = self.finish(task, check=0)

        self.assertIn(f"closed epic {epic}", result.stdout)
        comments = self.comments(epic)
        self.assertFalse(any("verify failed" in c["text"] for c in comments))


if __name__ == "__main__":
    unittest.main()
