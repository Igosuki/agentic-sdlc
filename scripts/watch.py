#!/usr/bin/env python3
"""Watches beads and the worker processes, one line per change, for the Monitor tool."""
import argparse
import json
import os
import re
import subprocess
import sys
import time

import tasks

DESCRIPTION = """Watches beads and the worker processes, and prints one line per change, for
the Monitor tool:
  ready <task>            a task can be dispatched (tasks.dispatch_order)
  ended <task> <state>    a worker ended: merged, pr-opened, awaiting-review, stopped or
                          failed; also printed the first time a later round sees a task
                          that already ended, in case it ended between two rounds
  crashed <task>          claimed, no outcome recorded, no process runs its session
  closed <epic>           an epic was closed
  idle                    no worker runs and no task is ready; the watch ends

The first round reports every ready and crashed task, but no "ended", so a task
that finished before the watch started isn't reported as ending just now. Each
round also runs bd gate check, so gates that can resolve on their own do, then
close-prs.sh and resume-reviewed.sh.

Options:
  --epic EPIC          only that epic's tasks, at any depth
  --interval SECONDS   time between rounds, default 10
  --once               one round, then exit

Exit codes: 0 ended (idle or --once), 2 invalid arguments."""

NO_OUTCOME = ("", "running")  # "running" is a legacy value, kept as a synonym for unset.


def bd_json(*args):
    result = subprocess.run(["bd", *args, "--json"], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr.strip() or f"error: bd {' '.join(args)} failed", file=sys.stderr)
        sys.exit(result.returncode or 1)
    return json.loads(result.stdout)


def run_round_hooks(script_dir):
    subprocess.run(["bd", "gate", "check"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([os.path.join(script_dir, "close-prs.sh")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run([os.path.join(script_dir, "resume-reviewed.sh")], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def new_state():
    return {"ready": set(), "state": {}, "crash": set(), "closed": set()}


def step(all_tasks, ready_tasks, epic, state, round_num):
    """One round: classifies every dispatched task and epic, updates `state` in place,
    and returns (lines, idle). `round_num` is 0 on the first round."""
    by_id = tasks.index_by_id(all_tasks)
    order = tasks.dispatch_order(all_tasks, ready_tasks, only_epic=epic or None)
    ready_ids = [entry["task"]["id"] for entry in order]

    lines = []
    for tid in ready_ids:
        if tid not in state["ready"]:
            lines.append(f"ready {tid}")
    state["ready"] = set(ready_ids)

    alive = 0
    for task in all_tasks:
        tid = task["id"]
        if task.get("issue_type") == "epic":
            if epic and tid != epic and task.get("parent") != epic:
                continue
            if task.get("status") == "closed":
                if tid not in state["closed"]:
                    if round_num > 0:
                        lines.append(f"closed {tid}")
                    state["closed"].add(tid)
            continue

        metadata = task.get("metadata") or {}
        session = metadata.get("dispatch_session")
        if not session:
            continue
        if epic and tasks.epic_of(by_id, tid) != epic:
            continue

        raw_state = metadata.get("dispatch_state") or ""
        if raw_state in NO_OUTCOME:
            current = "running" if tasks.worker_running(task) else "crashed"
        else:
            current = raw_state

        first_seen = tid not in state["state"]
        previous = state["state"].get(tid)
        state["state"][tid] = current

        if current == "running":
            alive += 1
            state["crash"].discard(tid)
        elif current == "crashed":
            if tid not in state["crash"]:
                lines.append(f"crashed {tid}")
                state["crash"].add(tid)
        else:
            if (first_seen and round_num > 0) or (not first_seen and previous in ("running", "crashed")):
                lines.append(f"ended {tid} {current}")
            state["crash"].discard(tid)

    idle = alive == 0 and not ready_ids
    return lines, idle


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="watch.py", description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--epic", default="", help="only that epic's tasks, at any depth")
    parser.add_argument("--interval", default="10", help="time between rounds, default 10")
    parser.add_argument("--once", action="store_true", help="one round, then exit")
    args = parser.parse_args(argv)

    if not re.match(r"^[1-9][0-9]*$", args.interval):
        print("error: --interval must be a positive number", file=sys.stderr)
        return 2
    interval = int(args.interval)

    script_dir = os.path.dirname(os.path.abspath(__file__))
    state = new_state()
    round_num = 0
    while True:
        run_round_hooks(script_dir)
        all_tasks = bd_json("list", "--all", "--limit", "0")
        ready_tasks = bd_json("ready", "--limit", "0")
        lines, idle = step(all_tasks, ready_tasks, args.epic, state, round_num)
        for line in lines:
            print(line, flush=True)

        round_num += 1
        if args.once:
            return 0
        if idle:
            print("idle")
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    sys.exit(main())
