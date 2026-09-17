import json
import os
import re
import subprocess
import sys
import time
import unittest

E2E_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, E2E_DIR)
from sandbox import new_project  # noqa: E402
from session import PLUGIN_DIR, Session  # noqa: E402

SDLC_E2E = os.environ.get("SDLC_E2E") == "1"
REQUEST = os.environ.get(
    "SDLC_E2E_REQUEST",
    "create a command-line todo list in Python with add, list and done commands, stored in a JSON file",
)
INTEGRATION = os.environ.get("SDLC_INTEGRATION", "epic-merge")
TIMEOUT = int(os.environ.get("SDLC_E2E_TIMEOUT", 60 * 60))
BLOCKED_RE = re.compile(r"blocked \S+ (?:stopped|failed): .+")

SCRIPTS = os.path.join(PLUGIN_DIR, "scripts")
VERIFY_SH = os.path.join(SCRIPTS, "verify.sh")
CLEAN_SH = os.path.join(SCRIPTS, "clean.sh")
STATS_PY = os.path.join(SCRIPTS, "stats.py")
WORKERS_PY = os.path.join(SCRIPTS, "workers.py")
NEXT_TASKS_PY = os.path.join(SCRIPTS, "next-tasks.py")
SETTINGS_SH = os.path.join(SCRIPTS, "settings.sh")
STOP_TASK_SH = os.path.join(SCRIPTS, "stop-task.sh")
SDLC_SKILLS = set(os.listdir(os.path.join(PLUGIN_DIR, "skills")))


def _bd_json(repo, *args):
    # --all only applies to `bd list`; `bd show` has no such flag and always
    # returns the issue regardless of status.
    extra = ["--all"] if args and args[0] == "list" else []
    result = subprocess.run(["bd", *args, *extra, "--json"], cwd=repo, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"bd {args} failed: {result.stderr}")
    return json.loads(result.stdout or "[]")


def _descendants(repo, root_id):
    out = []
    frontier = [root_id]
    while frontier:
        next_frontier = []
        for parent_id in frontier:
            children = _bd_json(repo, "list", "--parent", parent_id)
            out.extend(children)
            next_frontier.extend(c["id"] for c in children)
        frontier = next_frontier
    return out


def _setting(repo, key):
    result = subprocess.run([SETTINGS_SH, key], cwd=repo, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"settings.sh {key} failed: {result.stderr}")
    return result.stdout.strip()


def _transcript_events(logfile):
    # Replays the raw transcript to recover the order of questions vs. tool calls:
    # SessionResult keeps them in separate lists with no shared index.
    events = []
    with open(logfile) as f:
        for line in f:
            if line.startswith(">> ") or not line.strip():
                continue
            msg = json.loads(line)
            mtype = msg.get("type")
            if mtype == "control_request" and msg.get("request", {}).get("subtype") == "can_use_tool":
                req = msg["request"]
                if req.get("tool_name") == "AskUserQuestion":
                    for q in (req.get("input") or {}).get("questions", []):
                        events.append(("question", q.get("question", "")))
            elif mtype == "assistant":
                for c in msg.get("message", {}).get("content", []):
                    if c.get("type") == "tool_use":
                        events.append(("tool", c.get("name"), c.get("input") or {}))
    return events


def _stop_workers(repo, epic_id):
    if epic_id:
        subprocess.run([STOP_TASK_SH, epic_id], cwd=repo, capture_output=True, text=True)


def _wait_for_workers(repo, epic_id, seconds=300):
    # finish-task.sh closes a task while its worker still records the attempt and removes the worktree.
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        alive = subprocess.run([WORKERS_PY, "--under", epic_id, "--alive-count"], cwd=repo, capture_output=True, text=True)
        if alive.stdout.strip() == "0":
            return
        time.sleep(5)


class BuildWaiter:
    """`until` for a build run: stops on epic close, or two idle polls after dispatch has done anything."""

    STALL = "nothing running and nothing ready: a person would be needed"

    def __init__(self, repo):
        self.repo = repo
        self.epic = None
        self.seen_activity = False
        self.idle_polls = 0
        self.reason = None

    def _epic_id(self):
        if self.epic is None:
            epics = _bd_json(self.repo, "list", "--type", "epic", "--no-parent")
            if epics:
                self.epic = epics[0]["id"]
        return self.epic

    def __call__(self):
        epic_id = self._epic_id()
        if epic_id is None:
            return False

        shown = _bd_json(self.repo, "show", epic_id)
        if shown and shown[0].get("status") == "closed":
            self.reason = "epic closed"
            return True

        running = subprocess.run(
            [WORKERS_PY, "--under", epic_id, "--alive-count"], cwd=self.repo, capture_output=True, text=True
        ).stdout.strip()
        ready = subprocess.run(
            [NEXT_TASKS_PY, "--under", epic_id, "--ids"], cwd=self.repo, capture_output=True, text=True
        ).stdout.strip()

        if running != "0" or ready:
            self.seen_activity = True
            self.idle_polls = 0
            return False

        # Before dispatch has started anything, idle is the normal state (design/split still
        # running); only count idle polls once dispatch has actually run or queued a task.
        if not self.seen_activity:
            return False

        self.idle_polls += 1
        if self.idle_polls >= 2:
            self.reason = self.STALL
            return True
        return False


@unittest.skipUnless(SDLC_E2E, "set SDLC_E2E=1 to run end-to-end Claude sessions")
class TestBuild(unittest.TestCase):
    def _run_build(self, name, interactive):
        project = new_project(name, integration=INTEGRATION)
        target = _setting(project.repo, "target")
        integration = _setting(project.repo, "integration")

        session = Session(project.repo, name, interactive=interactive)
        waiter = BuildWaiter(project.repo)
        try:
            result = session.run(f"/sdlc:build {REQUEST}", until=waiter, timeout=TIMEOUT)
        except BaseException:
            _stop_workers(project.repo, waiter.epic)
            raise
        if waiter.reason == "epic closed":
            _wait_for_workers(project.repo, waiter.epic)
        else:
            _stop_workers(project.repo, waiter.epic)

        if waiter.reason == BuildWaiter.STALL:
            self.fail(f"build stalled: {waiter.reason}")
        self.assertIsNotNone(waiter.reason, "the session ended before the epic closed")

        blocked = BLOCKED_RE.findall("\n".join(result.results))
        self.assertEqual(blocked, [], f"a worker needed a person: {blocked}")

        plugin_skills = [s for s in result.skills if s in SDLC_SKILLS]
        self.assertEqual(plugin_skills, ["build", "design", "split", "dispatch"])

        epic_id = waiter.epic
        self.assertIsNotNone(epic_id, "no epic was ever created")

        top_level_epics = _bd_json(project.repo, "list", "--type", "epic", "--no-parent")
        self.assertEqual(len(top_level_epics), 1, f"expected one top-level epic, got {top_level_epics}")
        self.assertEqual(top_level_epics[0]["id"], epic_id)

        descendants = _descendants(project.repo, epic_id)
        tasks = [b for b in descendants if b["issue_type"] != "epic"]
        self.assertTrue(tasks, "epic has no tasks")
        for t in tasks:
            if (t.get("metadata") or {}).get("dispatch_role") == "integration":
                continue
            self.assertTrue(t.get("acceptance_criteria"), f"{t['id']} missing acceptance_criteria")
            meta = t.get("metadata") or {}
            for field in ("scope", "verify", "complexity", "review"):
                self.assertTrue(meta.get(field), f"{t['id']} missing metadata.{field}")

        for bead in [top_level_epics[0]] + descendants:
            self.assertEqual(bead["status"], "closed", f"{bead['id']} is not closed ({bead['status']})")
            state = (bead.get("metadata") or {}).get("dispatch_state")
            self.assertNotIn(state, ("stopped", "failed"), f"{bead['id']} dispatch_state={state}")

        log = subprocess.run(["git", "log", "--oneline", "main"], cwd=project.repo, capture_output=True, text=True)
        self.assertGreater(
            len(log.stdout.strip().splitlines()), 1, "main has no commits beyond the initial one"
        )

        verify = subprocess.run([VERIFY_SH, epic_id], cwd=project.repo, capture_output=True, text=True)
        self.assertEqual(verify.returncode, 0, f"verify.sh {epic_id} failed:\n{verify.stdout}\n{verify.stderr}")

        clean = subprocess.run([CLEAN_SH], cwd=project.repo, capture_output=True, text=True)
        self.assertEqual(clean.stdout.strip(), "", f"clean.sh found leftovers:\n{clean.stdout}")

        stats = subprocess.run([STATS_PY, "--under", epic_id], cwd=project.repo, capture_output=True, text=True)
        for t in tasks:
            self.assertIn(t["id"], stats.stdout, f"stats.py --under {epic_id} is missing {t['id']}")

        status = subprocess.run(
            ["git", "status", "--porcelain", "--", ".", ":!.beads"], cwd=project.repo, capture_output=True, text=True
        )
        self.assertEqual(status.stdout.strip(), "", "main has uncommitted changes")

        return project, target, integration, result

    def test_build_interactive(self):
        project, target, integration, result = self._run_build("interactive", interactive=True)

        self.assertEqual(len(result.plans), 1, f"expected exactly one plan, got {len(result.plans)}")
        plan_text = result.plans[0]
        self.assertIn(integration, plan_text, "plan doesn't name the integration mode")
        self.assertIn(target, plan_text, "plan doesn't name the target branch")

        logfile = os.path.join(project.logs, "interactive.jsonl")
        events = _transcript_events(logfile)
        question_idx = [i for i, e in enumerate(events) if e[0] == "question"]
        supervise_idx = [
            i
            for i, e in enumerate(events)
            if e[0] == "tool" and e[1] == "Bash" and "supervise.py" in str(e[2].get("command", ""))
        ]
        self.assertTrue(question_idx, "no questions were asked")
        self.assertTrue(supervise_idx, "supervise.py was never started")
        self.assertLess(
            max(question_idx), min(supervise_idx), "a question was asked after supervise.py started"
        )

    def test_build_headless(self):
        _project, _target, _integration, result = self._run_build("headless", interactive=False)

        self.assertEqual(result.questions, [])
        self.assertEqual(result.plans, [])


if __name__ == "__main__":
    unittest.main()
