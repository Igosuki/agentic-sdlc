#!/usr/bin/env python3
"""One supervisor: decides start, resume, record, and wakes a person when needed."""
import argparse
import contextlib
import fcntl
import json
import os
import select
import signal
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPT_DIR)
import tasks  # noqa: E402
import workers  # noqa: E402

DESCRIPTION = """Decides everything about dispatched tasks: starts ready work, resumes or
records crashed workers, resumes reviewed tasks, closes merged pull requests,
and wakes this session only when a person is needed.

Sleeps on the wake pipe <git-common-dir>/sdlc/wake, written by the beads hooks
and the worker wrapper, and on a sweep timer. Exits printing wake lines:
  blocked <task> awaiting-review: <gate>
  blocked <task> stopped: <comment>
  blocked <task> failed: <comment>
  blocked <task> pr-opened: <pr>
  blocked <task> not started: <reason>
  new-work <task> <task>...    (only with --under: ready work outside scope)
  taken over                   (another supervisor started; this one exits)

--under ID        limit which ready tasks this starts; repeatable. Everything
                   else covers every dispatched task in the repository.
--parallel N       workers at a time, default settings.sh parallel
--sweep SECONDS    seconds after the last round before a sweep event, default 60
--running          print whether a supervisor is running, and exit

Exit codes: 0 exited to wake the session, 2 invalid arguments, 3 couldn't take
over the lock."""

NO_OUTCOME = ("", "running")
NEEDS_PERSON_STATES = ("awaiting-review", "stopped", "failed", "pr-opened")


class Brain:
    """Pure: no bd/git/process calls. Tests build `look` and `event` by hand."""

    def __init__(self, parallel, under_ids):
        self.parallel = parallel
        self.under_ids = list(under_ids or [])
        self.first_look_done = False
        self.reported = set()  # needs-person tasks already woken for
        self.refused = {}  # task -> updated_at, refused starts (this round or a prior one)
        self.acted = {}  # (kind, task) -> updated_at, decision 1/2 targets this round
        self.new_work_baseline = set()  # outside-scope ready ids at the first look
        self.new_work_reported = set()  # outside-scope ready ids already woken for

    def decide(self, look, event):
        if event.get("kind") != "settle":
            self.acted = {}

        actions = []
        wake_lines = []

        # Pre-register this round's refusals so decision 4 (starts) skips them right away.
        for refusal in event.get("refused", []):
            task = look["by_id"].get(refusal["task"])
            if task is not None:
                self.refused[refusal["task"]] = task.get("updated_at")

        self._decide_crashes(look, actions)
        self._decide_reviewed(look, actions)
        self._decide_pull_requests(look, event, actions)
        self._decide_starts(look, actions)
        self._decide_refused_wake(event, actions, wake_lines)
        self._decide_blocked_wake(look, wake_lines)
        self._decide_new_work(look, wake_lines)

        self.first_look_done = True
        return actions, wake_lines

    def _decide_crashes(self, look, actions):
        for task in look["all_tasks"]:
            meta = task.get("metadata") or {}
            session = meta.get("dispatch_session")
            if not session:
                continue
            if tasks.worker_running(task, look["lines"]):
                continue
            state = meta.get("dispatch_state") or ""
            if state not in NO_OUTCOME:
                continue
            tid = task["id"]
            info = look["crash_info"].get(tid, {})
            if task.get("status") == "closed" and not info.get("has_result"):
                continue  # finish-task.sh closed it; its code merged, don't resume or fail it

            updated_at = task.get("updated_at")
            if self.acted.get(("crash", tid)) == updated_at:
                continue
            self.acted[("crash", tid)] = updated_at

            if info.get("has_result"):
                actions.append({"kind": "record", "task": tid})
            elif meta.get("dispatch_branch") not in look["worktrees"]:
                actions.append({"kind": "fail", "task": tid, "reason": "crashed, and its worktree is gone"})
            elif not info.get("transcript"):
                actions.append({"kind": "fail", "task": tid, "reason": "crashed, and its transcript is gone"})
            elif info.get("runs_since_result", 0) >= 4:
                actions.append({"kind": "fail", "task": tid, "reason": "crashed again after 3 resumes"})
            else:
                actions.append({"kind": "resume", "task": tid})

    def _decide_reviewed(self, look, actions):
        for task in look["all_tasks"]:
            meta = task.get("metadata") or {}
            if task.get("status") != "in_progress" or meta.get("dispatch_state") != "awaiting-review":
                continue
            if tasks.worker_running(task, look["lines"]):
                continue
            gate = look["by_id"].get(meta.get("dispatch_review_gate"))
            if gate is None or gate.get("status") != "closed":
                continue
            tid = task["id"]
            updated_at = task.get("updated_at")
            if self.acted.get(("reviewed", tid)) == updated_at:
                continue
            self.acted[("reviewed", tid)] = updated_at
            actions.append({"kind": "resume_reviewed", "task": tid})

    def _decide_pull_requests(self, look, event, actions):
        if event.get("kind") not in ("sweep", "start"):
            return
        pr_tasks = [
            t for t in look["all_tasks"]
            if t.get("status") == "in_progress" and (t.get("metadata") or {}).get("dispatch_state") == "pr-opened"
        ]
        if not pr_tasks:
            return
        actions.append({"kind": "gate_check"})
        for t in pr_tasks:
            actions.append({"kind": "close_pr", "task": t["id"]})

    def _decide_starts(self, look, actions):
        order = tasks.dispatch_order(look["all_tasks"], look["ready_tasks"], under_ids=self.under_ids)
        live = sum(
            1 for t in look["all_tasks"]
            if (t.get("metadata") or {}).get("dispatch_session") and tasks.worker_running(t, look["lines"])
        )
        for entry in order:
            task = entry["task"]
            tid = task["id"]
            if self.refused.get(tid) == task.get("updated_at"):
                continue
            if live >= self.parallel:
                break
            actions.append({"kind": "start", "task": tid})
            live += 1

    def _decide_refused_wake(self, event, actions, wake_lines):
        for refusal in event.get("refused", []):
            tid = refusal["task"]
            reason = refusal["reason"]
            expected = f"not started: {reason}"
            if refusal.get("last_comment") == expected:
                continue
            actions.append({"kind": "comment", "task": tid, "text": expected})
            wake_lines.append(f"blocked {tid} not started: {reason}")

    def _decide_blocked_wake(self, look, wake_lines):
        needs_person = {}
        for task in look["all_tasks"]:
            meta = task.get("metadata") or {}
            if not meta.get("dispatch_session") or task.get("status") != "in_progress":
                continue
            state = meta.get("dispatch_state") or ""
            if state not in NEEDS_PERSON_STATES:
                continue
            if tasks.worker_running(task, look["lines"]):
                continue
            needs_person[task["id"]] = (state, task)

        if not self.first_look_done:
            self.reported |= set(needs_person)
            return

        for tid, (state, task) in needs_person.items():
            if tid in self.reported:
                continue
            self.reported.add(tid)
            wake_lines.append(_blocked_line(tid, state, task, look))
        self.reported = {tid for tid in self.reported if tid in needs_person}

    def _decide_new_work(self, look, wake_lines):
        if not self.under_ids:
            return
        all_order = tasks.dispatch_order(look["all_tasks"], look["ready_tasks"], under_ids=None)
        scoped_order = tasks.dispatch_order(look["all_tasks"], look["ready_tasks"], under_ids=self.under_ids)
        outside_now = {e["task"]["id"] for e in all_order} - {e["task"]["id"] for e in scoped_order}

        if not self.first_look_done:
            self.new_work_baseline = set(outside_now)
            return

        newly = outside_now - self.new_work_baseline - self.new_work_reported
        if newly:
            wake_lines.append("new-work " + " ".join(sorted(newly)))
            self.new_work_reported |= newly
        self.new_work_reported &= outside_now


def _blocked_line(tid, state, task, look):
    meta = task.get("metadata") or {}
    if state == "awaiting-review":
        return f"blocked {tid} awaiting-review: {meta.get('dispatch_review_gate', '')}"
    if state == "pr-opened":
        return f"blocked {tid} pr-opened: {meta.get('dispatch_pr', '')}"
    comment = (look.get("comments") or {}).get(tid) or ""
    return f"blocked {tid} {state}: {comment}"


class LookFailed(Exception):
    """bd (embedded Dolt) refused a call, e.g. while a worker writes; the caller retries later."""


def bd_json(*args):
    result = subprocess.run(["bd", *args, "--json"], capture_output=True, text=True)
    if result.returncode != 0:
        raise LookFailed(result.stderr.strip() or f"bd {' '.join(args)} failed")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as e:
        raise LookFailed(f"bd {' '.join(args)} returned invalid JSON: {e}") from e


def read_crash_info(logs_directory, task_id, session):
    log_path = os.path.join(logs_directory, f"{task_id}-{session}.jsonl")
    entries = []
    if os.path.exists(log_path):
        with open(log_path, errors="replace") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entries.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
    has_result = False
    last_result_idx = -1
    for i, entry in enumerate(entries):
        if entry.get("type") == "result":
            has_result = True
            last_result_idx = i
    runs_since_result = sum(1 for e in entries[last_result_idx + 1:] if e.get("type") == "dispatch_run")
    return {
        "has_result": has_result,
        "runs_since_result": runs_since_result,
        "transcript": workers.find_transcript(session),
    }


def take_look(logs_directory):
    all_tasks = bd_json("list", "--all", "--include-gates", "--limit", "0")
    ready_tasks = bd_json("ready", "--limit", "0")
    by_id = tasks.index_by_id(all_tasks)
    lines = tasks.pgrep_lines()
    worktrees = workers.worktree_paths_by_branch()

    crash_info = {}
    comments = {}
    for task in all_tasks:
        meta = task.get("metadata") or {}
        session = meta.get("dispatch_session")
        if not session or tasks.worker_running(task, lines):
            continue
        state = meta.get("dispatch_state") or ""
        if state in NO_OUTCOME:
            crash_info[task["id"]] = read_crash_info(logs_directory, task["id"], session)
        elif state in ("stopped", "failed") and task.get("status") == "in_progress":
            comments[task["id"]] = workers.last_comment(task["id"])

    return {
        "all_tasks": all_tasks,
        "ready_tasks": ready_tasks,
        "by_id": by_id,
        "lines": lines,
        "worktrees": worktrees,
        "crash_info": crash_info,
        "comments": comments,
    }


def summarize(look):
    task_state = {
        t["id"]: (t.get("status"), (t.get("metadata") or {}).get("dispatch_state") or "", tasks.worker_running(t, look["lines"]))
        for t in look["all_tasks"]
    }
    ready_ids = {t["id"] for t in look["ready_tasks"]}
    return task_state, ready_ids


def _last_line(text):
    lines = [line for line in (text or "").splitlines() if line.strip()]
    return lines[-1].strip() if lines else ""


def execute_action(action, logf):
    kind = action["kind"]
    task = action.get("task")

    def run(*args):
        result = subprocess.run(args, capture_output=True, text=True)
        log(logf, f"arm {' '.join(args)} -> rc={result.returncode}")
        return result

    if kind == "record":
        run(os.path.join(SCRIPT_DIR, "record-task.sh"), task)
        return None
    if kind == "fail":
        run(os.path.join(SCRIPT_DIR, "record-task.sh"), task, "--failed", action["reason"])
        return None
    if kind == "resume":
        result = run(os.path.join(SCRIPT_DIR, "resume-task.sh"), task)
        if result.returncode != 0:
            reason = _last_line(result.stderr) or _last_line(result.stdout) or "resume-task.sh failed"
            run(os.path.join(SCRIPT_DIR, "record-task.sh"), task, "--failed", reason)
        return None
    if kind == "resume_reviewed":
        run(os.path.join(SCRIPT_DIR, "resume-reviewed.sh"), task)
        return None
    if kind == "gate_check":
        run("bd", "gate", "check")
        return None
    if kind == "close_pr":
        run(os.path.join(SCRIPT_DIR, "close-prs.sh"), task)
        return None
    if kind == "start":
        result = run(os.path.join(SCRIPT_DIR, "run-task.sh"), task)
        if result.returncode != 0:
            reason = _last_line(result.stderr) or _last_line(result.stdout) or "run-task.sh failed"
            return {"task": task, "reason": reason, "last_comment": workers.last_comment(task)}
        return None
    if kind == "comment":
        run("bd", "comments", "add", task, action["text"])
        return None
    raise ValueError(f"unknown action kind {kind}")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def log(logf, text):
    with contextlib.suppress(OSError):
        with open(logf, "a") as f:
            f.write(f"{now_iso()} {text}\n")


def log_decide(logf, event, actions, look, prev_summary):
    lines = event.get("lines") or []
    pipe_part = f" [{', '.join(lines)}]" if lines else ""
    if actions:
        actions_part = ", ".join(f"{a['kind']} {a.get('task', '')}".strip() for a in actions)
    else:
        actions_part = "nothing"
    log(logf, f"{event['kind']}{pipe_part} -> {actions_part}")

    cur_summary = summarize(look)
    if event["kind"] == "sweep" and prev_summary is not None:
        prev_tasks, prev_ready = prev_summary
        cur_tasks, cur_ready = cur_summary
        changed = sorted(
            tid for tid in set(prev_tasks) | set(cur_tasks)
            if prev_tasks.get(tid) != cur_tasks.get(tid)
        )
        if prev_ready != cur_ready:
            changed = sorted(set(changed) | (prev_ready ^ cur_ready))
        if changed:
            log(logf, f"missed: {' '.join(changed)}")
    return cur_summary


def lock_paths(sdlc_dir):
    return os.path.join(sdlc_dir, "supervise.lock")


def acquire_lock(lock_path):
    os.makedirs(os.path.dirname(lock_path), exist_ok=True)
    f = open(lock_path, "a+")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.seek(0)
        content = f.read().strip()
        pid_str = content.split()[0] if content else ""
        if pid_str.isdigit():
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(int(pid_str), signal.SIGTERM)
        deadline = time.monotonic() + 60
        acquired = False
        while time.monotonic() < deadline:
            try:
                fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
                break
            except OSError:
                time.sleep(0.5)
        if not acquired:
            print("error: could not take over the supervisor lock", file=sys.stderr)
            f.close()
            sys.exit(3)
    f.seek(0)
    f.truncate()
    f.write(f"{os.getpid()} {' '.join(sys.argv[1:])}\n")
    f.flush()
    return f


def print_running_status(lock_path):
    if not os.path.exists(lock_path):
        print("no supervisor running")
        return 0
    f = open(lock_path, "a+")
    try:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.seek(0)
        content = f.read().strip()
        parts = content.split(None, 1)
        pid = parts[0] if parts else "?"
        rest = parts[1] if len(parts) > 1 else ""
        print(f"supervisor running: pid {pid}, {rest}")
    else:
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        print("no supervisor running")
    finally:
        f.close()
    return 0


def open_wake_pipe(wake_path):
    if os.path.exists(wake_path):
        if not stat.S_ISFIFO(os.stat(wake_path).st_mode):
            print(f"error: {wake_path} exists and isn't a FIFO", file=sys.stderr)
            sys.exit(2)
    else:
        os.mkfifo(wake_path)
    return os.open(wake_path, os.O_RDWR | os.O_NONBLOCK)


def drain_pipe(fd):
    chunks = []
    while True:
        try:
            chunk = os.read(fd, 65536)
        except BlockingIOError:
            break
        except OSError:
            break
        if not chunk:
            break
        chunks.append(chunk)
    if not chunks:
        return []
    text = b"".join(chunks).decode(errors="replace")
    return [line for line in text.splitlines() if line]


def git_common_dir():
    result = subprocess.run(
        ["git", "rev-parse", "--path-format=absolute", "--git-common-dir"], capture_output=True, text=True
    )
    if result.returncode != 0:
        print(result.stderr.strip() or "error: not a git repository", file=sys.stderr)
        sys.exit(1)
    return result.stdout.strip()


def parallel_default():
    result = subprocess.run([os.path.join(SCRIPT_DIR, "settings.sh"), "parallel"], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr.strip() or "error: settings.sh parallel failed", file=sys.stderr)
        sys.exit(1)
    return int(result.stdout.strip())


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="supervise.py", description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--under", action="append", default=[], dest="under_ids", metavar="ID",
        help="only starts tasks under that id, at any depth; repeatable",
    )
    parser.add_argument("--parallel", default=None, help="workers at a time, default settings.sh parallel")
    parser.add_argument("--sweep", default=None, help="seconds after the last round before a sweep event, default 60")
    parser.add_argument("--running", action="store_true", help="print whether a supervisor is running, and exit")
    args = parser.parse_args(argv)

    common_dir = git_common_dir()
    sdlc_dir = os.path.join(common_dir, "sdlc")
    lock_path = lock_paths(sdlc_dir)

    if args.running:
        return print_running_status(lock_path)

    parallel = args.parallel
    if parallel is None:
        parallel = parallel_default()
    else:
        if not str(parallel).isdigit() or int(parallel) < 1:
            print("error: --parallel must be a positive number", file=sys.stderr)
            return 2
        parallel = int(parallel)

    sweep_seconds = args.sweep
    if sweep_seconds is None:
        sweep_seconds = 60.0
    else:
        try:
            sweep_seconds = float(sweep_seconds)
            if sweep_seconds <= 0:
                raise ValueError
        except ValueError:
            print("error: --sweep must be a positive number", file=sys.stderr)
            return 2

    os.makedirs(sdlc_dir, exist_ok=True)
    lock_file = acquire_lock(lock_path)
    os.environ["SDLC_SUPERVISOR"] = "1"

    logs_directory = os.path.join(sdlc_dir, "logs")
    log_path = os.path.join(sdlc_dir, "supervise.log")
    wake_path = os.path.join(sdlc_dir, "wake")
    wake_fd = open_wake_pipe(wake_path)

    brain = Brain(parallel, args.under_ids)
    term_flag = [False]

    def on_term(signum, frame):
        term_flag[0] = True

    signal.signal(signal.SIGTERM, on_term)

    state = {"prev_summary": None, "wake_lines": [], "last_round_end": time.monotonic()}

    def check_term():
        if term_flag[0]:
            for line in state["wake_lines"]:
                print(line)
            print("taken over")
            sys.exit(0)

    def handle_event(event):
        while True:
            check_term()
            event["lines"] = list(set(event.get("lines", []) + drain_pipe(wake_fd)))
            try:
                look = take_look(logs_directory)
            except LookFailed as e:
                log(log_path, f"look failed: {e}")
                state["last_round_end"] = time.monotonic()
                return
            actions, wake_lines = brain.decide(look, event)
            state["prev_summary"] = log_decide(log_path, event, actions, look, state["prev_summary"])
            state["wake_lines"].extend(wake_lines)

            outcomes = []
            for action in actions:
                check_term()
                outcome = execute_action(action, log_path)
                if outcome is not None:
                    outcomes.append(outcome)
            check_term()

            if actions or outcomes:
                event = {"kind": "settle", "refused": outcomes}
                continue
            state["last_round_end"] = time.monotonic()
            return

    handle_event({"kind": "start", "lines": []})
    if state["wake_lines"]:
        for line in state["wake_lines"]:
            print(line)
        return 0

    while True:
        # The select wait is capped well under --sweep so SIGTERM (takeover) is noticed
        # promptly: PEP 475 retries an interrupted select() for the full timeout otherwise.
        event = None
        while event is None:
            check_term()
            remaining = sweep_seconds - (time.monotonic() - state["last_round_end"])
            if remaining <= 0:
                event = {"kind": "sweep", "lines": []}
                break
            r, _, _ = select.select([wake_fd], [], [], min(remaining, 1.0))
            check_term()
            if r:
                event = {"kind": "pipe", "lines": drain_pipe(wake_fd)}
        handle_event(event)
        if state["wake_lines"]:
            for line in state["wake_lines"]:
                print(line)
            return 0


if __name__ == "__main__":
    sys.exit(main())
