#!/usr/bin/env python3
"""Reports dispatched work per task and per epic, from the recorded worker-attempt events."""
import argparse
import json
import math
import subprocess
import sys

import tasks

DESCRIPTION = """Reports dispatched work from the event beads that record each worker attempt
(record-task.sh): per task its latest state, attempts, cost, duration, models
and agents, plus the task's review cost (dispatch_review_cost metadata, an
agent review level); per epic and overall the totals, review cost included.
A crashed run that was never recorded isn't counted.

Exit codes: 0 reported, 2 invalid arguments."""


def bd_json(*args):
    result = subprocess.run(["bd", *args, "--json"], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr.strip() or f"error: bd {' '.join(args)} failed", file=sys.stderr)
        sys.exit(result.returncode or 1)
    return json.loads(result.stdout)


def money(amount):
    cents = math.floor(amount * 100 + 0.5)
    dollars, remainder = divmod(cents, 100)
    return f"${dollars}.{remainder:02d}"


def dur(seconds):
    seconds = int(seconds)
    return f"{seconds // 60}m{seconds % 60:02d}s"


def dispatch_events(events):
    """dispatch.* events as flat entries, one per worker attempt recorded."""
    entries = []
    for event in events:
        kind = event.get("event_kind") or ""
        if not kind.startswith("dispatch."):
            continue
        try:
            payload = json.loads(event.get("payload") or "{}")
        except json.JSONDecodeError:
            payload = {}
        entries.append(
            {
                "task": event.get("target"),
                "state": kind[len("dispatch.") :],
                "created": event.get("created_at") or "",
                "cost": payload.get("cost_usd") or 0,
                "seconds": payload.get("duration_s") or 0,
                "model": payload.get("model") or "",
                "agents": payload.get("agents") or [],
                "session": payload.get("session"),
                "event_id": event.get("id"),
            }
        )
    return entries


def latest_per_session(entries):
    """Keeps the latest event per session: a resumed session's cost is cumulative
    within each event, so an earlier event for the same session double-counts it."""
    latest = {}
    for entry in entries:
        key = entry["session"] or ("event", entry["event_id"])
        current = latest.get(key)
        if current is None or entry["created"] > current["created"]:
            latest[key] = entry
    return list(latest.values())


def task_reports(entries, by_id):
    by_task = {}
    for entry in entries:
        by_task.setdefault(entry["task"], []).append(entry)

    reports = []
    for task_id, task_entries in by_task.items():
        task = by_id.get(task_id) or {}
        latest_state = max(task_entries, key=lambda e: e["created"])["state"]
        try:
            review_cost = float((task.get("metadata") or {}).get("dispatch_review_cost") or 0)
        except (TypeError, ValueError):
            review_cost = 0
        models = sorted({m for e in task_entries for m in (e["model"].split(",") if e["model"] else []) if m})
        agents = sorted({a for e in task_entries for a in e["agents"]})
        reports.append(
            {
                "task": task_id,
                "title": task.get("title") or "",
                "epic": tasks.epic_of(by_id, task_id),
                "state": latest_state,
                "attempts": len(task_entries),
                "cost": sum(e["cost"] for e in task_entries),
                "seconds": sum(e["seconds"] for e in task_entries),
                "review_cost": review_cost,
                "models": ",".join(models),
                "agents": ",".join(agents),
            }
        )
    return reports


def group_by_epic(reports):
    groups = {}
    order = []
    for report in reports:
        key = report["epic"]
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(report)
    return [(key, groups[key]) for key in order]


def render(reports, by_id):
    if not reports:
        return "no recorded attempts"

    reports = sorted(reports, key=lambda t: (t["epic"] or "", t["task"]))
    lines = []
    for epic_id, group in group_by_epic(reports):
        total_cost = sum(t["cost"] + t["review_cost"] for t in group)
        total_seconds = sum(t["seconds"] for t in group)
        if epic_id:
            epic_task = by_id.get(epic_id) or {}
            lines.append(
                f'epic {epic_id} "{epic_task.get("title", "")}" ({epic_task.get("status", "?")}): '
                f"{len(group)} tasks, {money(total_cost)}, {dur(total_seconds)}"
            )
        else:
            lines.append(f"no epic: {len(group)} tasks, {money(total_cost)}, {dur(total_seconds)}")
        for t in group:
            attempt_word = "attempt" if t["attempts"] == 1 else "attempts"
            line = f'  {t["task"]}  {t["state"]}  {t["attempts"]} {attempt_word}  {money(t["cost"])}  {dur(t["seconds"])}'
            if t["review_cost"] > 0:
                line += f'  review {money(t["review_cost"])}'
            line += f'  {t["models"]}'
            if t["agents"]:
                line += f'  agents: {t["agents"]}'
            line += f'  {t["title"]}'
            lines.append(line)

    total_cost = sum(t["cost"] + t["review_cost"] for t in reports)
    total_seconds = sum(t["seconds"] for t in reports)
    lines.append(f"total: {len(reports)} tasks, {money(total_cost)}, {dur(total_seconds)}")
    return "\n".join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="stats.py", description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("id", nargs="?", default=None, help="only tasks under that id, at any depth")
    parser.add_argument(
        "--under", dest="under_ids", action="append", default=[], metavar="ID",
        help="only tasks under that id, at any depth; repeatable",
    )
    args = parser.parse_args(argv)

    if args.id is not None and args.under_ids:
        print("error: give the id once, as an argument or as --under", file=sys.stderr)
        return 2
    under_ids = args.under_ids or ([args.id] if args.id else [])

    all_tasks = bd_json("list", "--all", "--limit", "0")
    events = bd_json("list", "--type", "event", "--all", "--limit", "0")
    by_id = tasks.index_by_id(all_tasks)

    entries = latest_per_session(dispatch_events(events))
    reports = task_reports(entries, by_id)
    if under_ids:
        reports = [r for r in reports if tasks.under(by_id, r["task"], under_ids)]

    print(render(reports, by_id))
    return 0


if __name__ == "__main__":
    sys.exit(main())
