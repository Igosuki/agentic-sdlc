#!/usr/bin/env python3
"""Task-graph queries shared by the dispatch scripts.

epic, parents-to-close and worker read the array from `bd list --all --limit 0
--json` on stdin rather than as an argument: Linux caps a single command-line
argument at 128 KiB, which this project's bead history can exceed.
"""
import argparse
import json
import re
import subprocess
import sys


def index_by_id(tasks):
    return {t["id"]: t for t in tasks}


def epic_of(by_id, task_id):
    """Nearest epic above task_id, or None. Stops at the first epic found (no epic nests under another)."""
    seen = set()
    task = by_id.get(task_id)
    parent_id = task.get("parent") if task else None
    while parent_id and parent_id not in seen:
        seen.add(parent_id)
        parent = by_id.get(parent_id)
        if parent is None:
            return None
        if parent.get("issue_type") == "epic":
            return parent_id
        parent_id = parent.get("parent")
    return None


def _children(by_id, parent_id):
    return [t for t in by_id.values() if t.get("parent") == parent_id and t.get("issue_type") != "event"]


def parents_to_close(by_id, task_id):
    """Parent tasks (not epics) to close after task_id closes, innermost first.

    task_id counts as closed even if the input snapshot predates it, and so does
    each parent this returns, so a chain of parents closes in one call."""
    result = []
    closed = {tid for tid, t in by_id.items() if t.get("status") == "closed"}
    closed.add(task_id)
    parent_id = by_id.get(task_id, {}).get("parent")
    seen = set()
    while parent_id and parent_id not in seen:
        seen.add(parent_id)
        parent = by_id.get(parent_id)
        if parent is None or parent.get("issue_type") == "epic":
            break
        kids = _children(by_id, parent_id)
        if not kids or not all(k["id"] in closed for k in kids):
            break
        result.append(parent_id)
        closed.add(parent_id)
        parent_id = parent.get("parent")
    return result


def dispatch_order(all_tasks, ready_tasks, only_epic=None):
    """Epics already started first, then priority/age, then within an epic the tasks
    that unblock the most others."""
    by_id = index_by_id(all_tasks)
    parents = {t["parent"] for t in all_tasks if t.get("parent")}

    def epic_started(epic_id):
        return any(
            t.get("parent") == epic_id and t.get("status") in ("in_progress", "closed")
            for t in all_tasks
        )

    entries = []
    for ready in ready_tasks:
        task = by_id.get(ready["id"])
        if task is None:
            continue
        if task.get("issue_type") in ("epic", "event"):
            continue
        metadata = task.get("metadata") or {}
        if not metadata.get("verify") and metadata.get("dispatch_role") != "integration":
            continue
        if task["id"] in parents:
            continue
        epic = epic_of(by_id, task["id"])
        if only_epic and epic != only_epic:
            continue
        group = by_id.get(epic, task)
        started = epic_started(epic) if epic else False
        key = (
            0 if started else 1,
            group.get("priority", 2),
            group.get("created_at", ""),
            -(task.get("dependent_count") or 0),
            task.get("priority", 2),
            task.get("created_at", ""),
        )
        entries.append((key, task, epic, started))
    entries.sort(key=lambda e: e[0])
    return [{"task": t, "epic": e, "epic_started": s} for _, t, e, s in entries]


def _process_alive(task_id, session):
    # ignores --fork-session: a user inspecting the transcript, not the worker.
    pattern = rf"(run-task\.sh {re.escape(task_id)}\b|--(session-id|resume) {re.escape(session)}\b)"
    try:
        out = subprocess.run(["pgrep", "-af", pattern], capture_output=True, text=True)
    except FileNotFoundError:
        return False
    return any("--fork-session" not in line for line in out.stdout.splitlines())


def worker_running(task):
    """Claimed, a process exists, and no attempt outcome is recorded yet."""
    if task.get("status") != "in_progress":
        return False
    metadata = task.get("metadata") or {}
    session = metadata.get("dispatch_session")
    if not session:
        return False
    state = metadata.get("dispatch_state") or ""
    if state not in ("", "running"):  # a bead written before dispatch_state existed can still hold "running"
        return False
    return _process_alive(task.get("id"), session)


def log_totals(path):
    """record-task.sh's totals from a worker log, read line by line, skipping broken lines.
    cost: each run's last total_cost_usd (cumulative within the run), summed across runs.
    turns, seconds: summed across every result line."""
    run = 0
    cost_by_run = {}
    turns = 0
    duration_ms = 0
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            kind = entry.get("type")
            if kind == "dispatch_run":
                run += 1
            elif kind == "result":
                cost_by_run[run] = entry.get("total_cost_usd") or 0
                turns += entry.get("num_turns") or 0
                duration_ms += entry.get("duration_ms") or 0
    cost = sum(cost_by_run.values())
    seconds = int(duration_ms / 1000)
    return cost, turns, seconds


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Task-graph queries shared by the dispatch scripts. "
        "epic, parents-to-close and worker read `bd list --all --limit 0 --json` from stdin."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("epic", help="print the nearest epic above <id>")
    p.add_argument("id")

    p = sub.add_parser("parents-to-close", help="print the parent tasks to close after <id> closes, innermost first")
    p.add_argument("id")

    p = sub.add_parser("worker", help="print true or false: whether <id>'s worker is running")
    p.add_argument("id")

    p = sub.add_parser("log-totals", help="print cost, turns and seconds (tab-separated) for a worker log")
    p.add_argument("log")

    args = parser.parse_args(argv)

    if args.command == "log-totals":
        try:
            cost, turns, seconds = log_totals(args.log)
        except OSError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(f"{cost}\t{turns}\t{seconds}")
        return 0

    try:
        tasks = json.load(sys.stdin)
    except json.JSONDecodeError as e:
        print(f"error: invalid JSON on stdin: {e}", file=sys.stderr)
        return 2
    by_id = index_by_id(tasks)

    if args.command == "epic":
        print(epic_of(by_id, args.id) or "")
        return 0
    if args.command == "parents-to-close":
        for parent_id in parents_to_close(by_id, args.id):
            print(parent_id)
        return 0
    if args.command == "worker":
        task = by_id.get(args.id)
        if task is None:
            print(f"error: no task {args.id} in the piped data", file=sys.stderr)
            return 2
        print("true" if worker_running(task) else "false")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
