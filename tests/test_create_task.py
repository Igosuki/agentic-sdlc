import json
import os
import shutil
import subprocess
import tempfile
import unittest

SCRIPT = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "skills", "create-task", "scripts", "create-task.sh"
)

REQUIRED_TASK_ARGS = [
    "--title", "T", "--description", "d",
    "--acceptance", "a", "--scope", "s", "--verify", "true", "--complexity", "small",
]


def run(cwd, *args, check=None):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check is not None and result.returncode != check:
        raise AssertionError(f"{args} exited {result.returncode} (expected {check})\n{result.stdout}\n{result.stderr}")
    return result


class BdRepoTestCase(unittest.TestCase):
    """A real bd repository in a throwaway git repo, no stubs."""

    def setUp(self):
        self.repo = tempfile.mkdtemp(prefix="create-task-test-")
        run(self.repo, "git", "init", "-q")
        run(self.repo, "git", "config", "user.email", "test@test.com")
        run(self.repo, "git", "config", "user.name", "test")
        run(self.repo, "bd", "init", "-q")

    def tearDown(self):
        shutil.rmtree(self.repo, ignore_errors=True)

    def bd(self, *args, check=0):
        return run(self.repo, "bd", *args, check=check)

    def create(self, *args, check=0):
        return run(self.repo, SCRIPT, *args, check=check)

    def show(self, bead_id):
        return json.loads(self.bd("show", bead_id, "--json").stdout)[0]


class TestValidation(BdRepoTestCase):
    def test_missing_required_fields_lists_every_problem(self):
        result = self.create("--title", "T", check=2)
        self.assertIn("--description is required", result.stderr)
        self.assertIn("--acceptance is required for tasks", result.stderr)
        self.assertIn("--scope is required for tasks", result.stderr)
        self.assertIn("--verify is required for tasks", result.stderr)
        self.assertIn("--complexity is required for tasks", result.stderr)

    def test_domain_is_not_a_known_option(self):
        result = self.create(*REQUIRED_TASK_ARGS, "--domain", "backend", check=2)
        self.assertIn("error: unknown option --domain", result.stderr)

    def test_unknown_after_id_is_rejected(self):
        result = self.create(*REQUIRED_TASK_ARGS, "--after", "nope-1", check=2)
        self.assertIn("no bead nope-1", result.stderr)

    def test_epic_type_does_not_require_task_fields(self):
        result = self.create("--title", "E", "--description", "d", "--type", "epic", check=0)
        self.assertIn("created", result.stdout)


class TestDeps(BdRepoTestCase):
    def test_after_wires_a_blocking_dependency_in_the_create_call(self):
        first = self.create(*REQUIRED_TASK_ARGS, check=0).stdout.split()[1]
        result = self.create(
            "--title", "T2", "--description", "d", "--acceptance", "a", "--scope", "s",
            "--verify", "true", "--complexity", "small", "--after", first, check=0,
        )
        second = result.stdout.split()[1]
        deps = self.show(second)["dependencies"]
        self.assertEqual([d["id"] for d in deps], [first])
        self.assertEqual(deps[0]["dependency_type"], "blocks")
        # bd ready must never see the new task before its dependency closes.
        ready_ids = [t["id"] for t in json.loads(self.bd("ready", "--limit", "0", "--json").stdout)]
        self.assertNotIn(second, ready_ids)


class TestParentEpic(BdRepoTestCase):
    def setUp(self):
        super().setUp()
        self.epic = self.bd("create", "--title", "Epic", "--type", "epic", "--silent").stdout.strip()

    def test_direct_mode_epic_with_no_integration_task_accepts_children(self):
        result = self.create("--parent", self.epic, *REQUIRED_TASK_ARGS, check=0)
        self.assertIn("created", result.stdout)

    def test_closed_epic_is_rejected(self):
        self.bd("close", self.epic)
        result = self.create("--parent", self.epic, *REQUIRED_TASK_ARGS, check=2)
        self.assertIn(f"epic {self.epic} is closed", result.stderr)

    def test_open_integration_task_gets_a_new_dependency(self):
        integration = self.bd(
            "create", "--title", "Integrate", "--type", "task", "--parent", self.epic,
            "--metadata", '{"dispatch_role": "integration"}', "--silent",
        ).stdout.strip()
        self.bd("update", self.epic, "--set-metadata", f"dispatch_integration_task={integration}")

        result = self.create("--parent", self.epic, *REQUIRED_TASK_ARGS, check=0)
        new_id = result.stdout.split()[1]

        deps = self.show(integration)["dependencies"]
        self.assertIn(new_id, [d["id"] for d in deps])

    def test_in_progress_integration_task_is_rejected(self):
        integration = self.bd(
            "create", "--title", "Integrate", "--type", "task", "--parent", self.epic,
            "--metadata", '{"dispatch_role": "integration"}', "--silent",
        ).stdout.strip()
        self.bd("update", self.epic, "--set-metadata", f"dispatch_integration_task={integration}")
        self.bd("update", integration, "--claim")

        result = self.create("--parent", self.epic, *REQUIRED_TASK_ARGS, check=2)
        self.assertIn(f"epic {self.epic} is already integrating", result.stderr)

    def test_closed_integration_task_is_rejected(self):
        integration = self.bd(
            "create", "--title", "Integrate", "--type", "task", "--parent", self.epic,
            "--metadata", '{"dispatch_role": "integration"}', "--silent",
        ).stdout.strip()
        self.bd("update", self.epic, "--set-metadata", f"dispatch_integration_task={integration}")
        self.bd("close", integration)

        result = self.create("--parent", self.epic, *REQUIRED_TASK_ARGS, check=2)
        self.assertIn(f"epic {self.epic} is already integrating", result.stderr)

    def test_parent_is_a_task_under_the_epic_finds_the_same_epic(self):
        integration = self.bd(
            "create", "--title", "Integrate", "--type", "task", "--parent", self.epic,
            "--metadata", '{"dispatch_role": "integration"}', "--silent",
        ).stdout.strip()
        self.bd("update", self.epic, "--set-metadata", f"dispatch_integration_task={integration}")
        child = self.bd("create", "--title", "Child", "--type", "task", "--parent", self.epic, "--silent").stdout.strip()

        result = self.create("--parent", child, *REQUIRED_TASK_ARGS, check=0)
        new_id = result.stdout.split()[1]

        deps = self.show(integration)["dependencies"]
        self.assertIn(new_id, [d["id"] for d in deps])


if __name__ == "__main__":
    unittest.main()
