import contextlib
import os
import sys
import unittest

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILLS_DIR)
sys.path.insert(0, os.path.dirname(SKILLS_DIR))
from sandbox import dispatched, new_project, task  # noqa: E402
from session import Session  # noqa: E402
from helpers import bd_json  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestSkillStop(unittest.TestCase):
    def setUp(self):
        self._processes = []

    def tearDown(self):
        for process in self._processes:
            with contextlib.suppress(Exception):
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)

    def _running_task(self, project_name, title):
        project = new_project(project_name)
        task_id = task(project, title)
        d = dispatched(project, task_id, "running")
        self._processes.append(d.process)
        return project, task_id, d

    def test_stop_confirmed(self):
        project, task_id, d = self._running_task("stop", "Stop me")

        session = Session(project.repo, "stop", answers={r".*": r"(?i)^yes"})
        result = session.run(f"/sdlc:stop {task_id}")

        ran_stop = any(
            t["name"] == "Bash" and "stop-task.sh" in str((t["input"] or {}).get("command", ""))
            for t in result.tools
        )
        self.assertTrue(ran_stop, "stop-task.sh did not run")

        info = bd_json(project.repo, "show", task_id)[0]
        self.assertEqual((info.get("metadata") or {}).get("dispatch_state"), "stopped")
        self.assertIsNotNone(d.process.poll(), "the placeholder process is still running")

    def test_stop_headless_leaves_it_running(self):
        project, task_id, d = self._running_task("stop-headless", "Stop me headless")

        session = Session(project.repo, "stop-headless", interactive=False)
        result = session.run(f"/sdlc:stop {task_id}")

        for t in result.tools:
            if t["name"] != "Bash":
                continue
            command = str((t["input"] or {}).get("command", ""))
            self.assertNotIn("stop-task.sh", command, "stop-task.sh ran in a headless session")

        info = bd_json(project.repo, "show", task_id)[0]
        self.assertNotEqual((info.get("metadata") or {}).get("dispatch_state"), "stopped")
        self.assertIsNone(d.process.poll(), "the placeholder process should still be alive")


if __name__ == "__main__":
    unittest.main()
