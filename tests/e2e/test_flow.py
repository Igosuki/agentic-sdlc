import functools
import json
import os
import re
import subprocess
import sys
import threading
import time
import unittest

E2E_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, E2E_DIR)
from sandbox import new_project  # noqa: E402
from session import PLUGIN_DIR, Session, kill_supervisor  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"
SCRIPTS_DIR = os.path.join(PLUGIN_DIR, "scripts")

REQUEST = os.environ.get(
    "SDLC_E2E_REQUEST",
    "create a command-line todo list in Python with add, list and done commands, stored in a JSON file",
)
INTEGRATION = os.environ.get("SDLC_INTEGRATION", "epic-merge")
TIMEOUT = float(os.environ.get("SDLC_E2E_TIMEOUT", 60 * 60))

SUPERVISE_START_TIMEOUT = 300
WORKER_RUNNING_TIMEOUT = 600
STOP_RELAY_TIMEOUT = 300

INSTALL_COMMAND_RE = re.compile(r"\b(apt|apt-get|pip|pip3|npm|brew|cargo|curl)\b")
BD_WRITE_RE = re.compile(r"\bbd\s+(update\b|comments\s+add\b|gate\s+resolve\b|close\b)")


def _run(repo, *args, check=True):
    result = subprocess.run(args, cwd=repo, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise AssertionError(f"{args} failed: {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result


def _bd_json(repo, *args):
    return json.loads(_run(repo, "bd", *args, "--json").stdout)


def _show(repo, bead_id):
    return _bd_json(repo, "show", bead_id)[0]


def _children(repo, bead_id):
    rows = _bd_json(repo, "list", "--parent", bead_id, "--all", "--limit", "0")
    return [r for r in rows if r.get("issue_type") != "event"]


def _descendants(repo, bead_id):
    found = []
    queue = [bead_id]
    while queue:
        head = queue.pop(0)
        for child in _children(repo, head):
            found.append(child)
            queue.append(child["id"])
    return found


def _wait_for(condition, timeout, interval=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(interval)
    return condition()


def _find_running_task(repo, epic_id):
    out = _run(repo, os.path.join(SCRIPTS_DIR, "workers.py"), "--under", epic_id, check=False).stdout
    m = re.search(r"^(\S+)\s+running\b", out, re.MULTILINE)
    return m.group(1) if m else None


def ordered_step(fn):
    @functools.wraps(fn)
    def wrapper(self):
        cls = type(self)
        if cls.failed_step:
            self.skipTest(f"{cls.failed_step} failed")
        try:
            fn(self)
        except unittest.SkipTest:
            raise
        except Exception:
            cls.failed_step = fn.__name__
            raise
    return wrapper


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestFlow(unittest.TestCase):
    """Every skill, one after another, on one project. No /sdlc:build."""

    failed_step = None
    epic_id = None
    readme_task_id = None
    worker_task = None
    session_a_id = None
    session_d = None
    session_d_thread = None
    session_d_result = None

    @classmethod
    def setUpClass(cls):
        cls.project = new_project("flow", integration=INTEGRATION, init=False)

    @classmethod
    def tearDownClass(cls):
        if cls.session_d_thread and cls.session_d_thread.is_alive():
            kill_supervisor(cls.project.repo)
            cls.session_d_thread.join(timeout=60)

    @ordered_step
    def test_01_setup(self):
        session = Session(self.project.repo, "setup", interactive=False)
        result = session.run("/sdlc:setup")

        self.assertEqual(result.skills, ["setup"])
        for t in result.tools:
            if t["name"] == "Bash":
                self.assertNotRegex((t["input"] or {}).get("command", ""), INSTALL_COMMAND_RE)
        self.assertIn("/sdlc:init", result.text)
        self.assertRegex(result.text, r"(?i)git|jq|python")

    @ordered_step
    def test_02_init(self):
        session = Session(self.project.repo, "init")
        session.run(f"/sdlc:init --integration {INTEGRATION}")

        self.assertTrue(os.path.isdir(os.path.join(self.project.repo, ".beads")))
        settings = _run(self.project.repo, os.path.join(SCRIPTS_DIR, "settings.sh")).stdout
        self.assertIn(f"integration={INTEGRATION}", settings)

    @ordered_step
    def test_03_design(self):
        cls = type(self)
        cls.session_a = Session(self.project.repo, "design")
        result = cls.session_a.run(f"/sdlc:design {REQUEST}")
        cls.session_a_id = result.session_id

        self.assertRegex(result.text, r"Prior art")
        self.assertEqual(_bd_json(self.project.repo, "list", "--all", "--limit", "0"), [])

    @ordered_step
    def test_04_split(self):
        cls = type(self)
        session = Session(self.project.repo, "split", resume=cls.session_a_id, answers={"": r"(?i)^approve"})
        session.run("/sdlc:split")

        epics = _bd_json(self.project.repo, "list", "--type", "epic", "--all", "--limit", "0")
        self.assertEqual(len(epics), 1, epics)
        cls.epic_id = epics[0]["id"]

        tasks = [b for b in _descendants(self.project.repo, cls.epic_id) if b["issue_type"] == "task"]
        self.assertTrue(tasks)
        for t in tasks:
            self.assertTrue(t.get("acceptance_criteria"), t["id"])
            meta = t.get("metadata") or {}
            for field in ("scope", "verify", "complexity", "review"):
                self.assertTrue(meta.get(field), f"{t['id']} missing metadata.{field}")

        validate = _run(self.project.repo, "bd", "swarm", "validate", cls.epic_id, check=False)
        self.assertEqual(validate.returncode, 0, validate.stdout + validate.stderr)

    @ordered_step
    def test_05_commit_doc_changes(self):
        # Mirrors build's Create step 2: design's only side effect is doc edits, and
        # workers branch from committed code, so uncommitted edits are invisible to them.
        status = _run(self.project.repo, "git", "status", "--porcelain", "--", "*.md").stdout
        if status.strip():
            _run(self.project.repo, "git", "add", "--", "*.md")
            _run(self.project.repo, "git", "commit", "-q", "-m", "Doc edits from design")

        remaining = _run(self.project.repo, "git", "status", "--porcelain", "--", "*.md").stdout
        self.assertEqual(remaining.strip(), "")

    @ordered_step
    def test_06_create_task(self):
        cls = type(self)
        before = {b["id"] for b in _descendants(self.project.repo, cls.epic_id)}
        session = Session(self.project.repo, "create-task")
        session.run(f"/sdlc:create-task add a README section listing the commands --parent {cls.epic_id}")

        after = _descendants(self.project.repo, cls.epic_id)
        new = [b for b in after if b["id"] not in before]
        self.assertEqual(len(new), 1, new)
        self.assertEqual(new[0]["issue_type"], "task")
        cls.readme_task_id = new[0]["id"]

    @ordered_step
    def test_07_dispatch(self):
        cls = type(self)

        def epic_closed():
            try:
                return _show(self.project.repo, cls.epic_id).get("status") == "closed"
            except Exception:
                return False

        cls.session_d = Session(self.project.repo, "dispatch", answers={"": r"(?i)^(yes|confirm|dispatch|start)"})
        cls.session_d_result = {}

        def run_session_d():
            try:
                cls.session_d_result["value"] = cls.session_d.run(
                    f"/sdlc:dispatch {cls.epic_id} --parallel 2", until=epic_closed, timeout=TIMEOUT
                )
            except Exception as exc:  # noqa: BLE001 - relayed to test_12
                cls.session_d_result["error"] = exc

        cls.session_d_thread = threading.Thread(target=run_session_d, daemon=True)
        cls.session_d_thread.start()

        started = _wait_for(
            lambda: any("supervise.py" in str(t.get("input")) for t in cls.session_d.tools),
            timeout=SUPERVISE_START_TIMEOUT,
        )
        self.assertTrue(started, "supervise.py did not start")

    @ordered_step
    def test_08_status_running(self):
        cls = type(self)
        found = _wait_for(lambda: _find_running_task(self.project.repo, cls.epic_id) is not None, WORKER_RUNNING_TIMEOUT)
        if not found:
            self.skipTest("no worker was still running under the epic")
        cls.worker_task = _find_running_task(self.project.repo, cls.epic_id)

        session = Session(self.project.repo, "status")
        result = session.run("/sdlc:status")

        self.assertIn(cls.worker_task, result.text)
        self.assertRegex(result.text, r"(?i)running")

    @ordered_step
    def test_09_logs(self):
        cls = type(self)
        if not cls.worker_task:
            self.skipTest("no worker was still running (step 8)")

        session = Session(self.project.repo, "logs")
        result = session.run(f"/sdlc:logs {cls.worker_task}")

        self.assertIn(cls.worker_task, result.text)
        self.assertIn("--fork-session", result.text)

    @ordered_step
    def test_10_stop(self):
        cls = type(self)
        if not cls.worker_task:
            self.skipTest("no worker was still running (step 8)")

        session = Session(self.project.repo, "stop", answers={"": r"(?i)^(yes|stop|confirm)"})
        session.run(f"/sdlc:stop {cls.worker_task}")

        info = _show(self.project.repo, cls.worker_task)
        self.assertEqual((info.get("metadata") or {}).get("dispatch_state"), "stopped")

        relayed = _wait_for(
            lambda: any(
                re.search(rf"blocked\s+{re.escape(cls.worker_task)}\s+stopped", r, re.I)
                for r in cls.session_d.results
            ),
            STOP_RELAY_TIMEOUT,
        )
        self.assertTrue(relayed, "session D did not relay the stop")

    @ordered_step
    def test_11_recover(self):
        cls = type(self)
        if not cls.worker_task:
            self.skipTest("no worker was still running (step 8)")

        session = Session(self.project.repo, "recover", answers={"": r"(?i)^resume"})
        session.run(f"/sdlc:recover {cls.worker_task}")

        info = _show(self.project.repo, cls.worker_task)
        # Resumed (worker runs again: dispatch_state cleared) or closed outright.
        self.assertNotEqual((info.get("metadata") or {}).get("dispatch_state"), "stopped")

    @ordered_step
    def test_12_dispatch_finishes(self):
        cls = type(self)
        cls.session_d_thread.join(TIMEOUT)
        self.assertFalse(cls.session_d_thread.is_alive(), "session D did not finish within the timeout")
        if "error" in cls.session_d_result:
            raise cls.session_d_result["error"]

        epic = _show(self.project.repo, cls.epic_id)
        self.assertEqual(epic["status"], "closed")
        for bead in _descendants(self.project.repo, cls.epic_id):
            self.assertEqual(bead["status"], "closed", bead["id"])
            self.assertNotIn((bead.get("metadata") or {}).get("dispatch_state"), ("stopped", "failed"))

        readme = _run(self.project.repo, "git", "show", "main:README.md").stdout
        self.assertRegex(readme, r"(?i)command")

    @ordered_step
    def test_13_verify(self):
        cls = type(self)
        session = Session(self.project.repo, "verify-skill")
        session.run(f"/sdlc:verify {cls.epic_id}")

        result = _run(self.project.repo, os.path.join(SCRIPTS_DIR, "verify.sh"), cls.epic_id, check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @ordered_step
    def test_14_review(self):
        cls = type(self)
        session = Session(self.project.repo, "review", interactive=False)
        result = session.run(f"/sdlc:review {cls.epic_id}")

        self.assertRegex(result.text, r"(?i)approve|request changes")
        for t in result.tools:
            if t["name"] == "Bash":
                self.assertNotRegex((t["input"] or {}).get("command", ""), BD_WRITE_RE)

    @ordered_step
    def test_15_stats(self):
        cls = type(self)
        session = Session(self.project.repo, "stats")
        result = session.run(f"/sdlc:stats {cls.epic_id}")

        for bead in _descendants(self.project.repo, cls.epic_id):
            if bead["issue_type"] == "task":
                self.assertIn(bead["id"], result.text)
        self.assertRegex(result.text, r"\$\d")

    @ordered_step
    def test_16_hooks(self):
        session = Session(self.project.repo, "hooks")
        session.run("/sdlc:hooks")

        result = _run(self.project.repo, "wt", "hook", "show", check=False)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @ordered_step
    def test_17_clean(self):
        session = Session(self.project.repo, "clean", answers={"": r"(?i)^yes"})
        session.run("/sdlc:clean")

        result = _run(self.project.repo, os.path.join(SCRIPTS_DIR, "clean.sh"), check=False)
        self.assertEqual(result.stdout.strip(), "", result.stdout)


if __name__ == "__main__":
    unittest.main()
