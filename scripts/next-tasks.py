#!/usr/bin/env python3
"""Lists ready tasks in dispatch order (tasks.dispatch_order)."""
import argparse
import json
import subprocess
import sys

import tasks

DESCRIPTION = """Lists ready tasks that can be dispatched, in work order:
  1. tasks of epics already in progress (a task claimed or closed), by epic priority
  2. then tasks of other epics and tasks without an epic, by priority
  3. within an epic: tasks that unblock the most others first, then priority, then oldest

A task can be dispatched when it is ready, is not an epic, has no children,
and has a verify command (metadata.verify) or is an integration task.

Exit codes: 0 listed (possibly nothing), 2 invalid arguments."""


def bd_json(*args):
    result = subprocess.run(["bd", *args, "--json"], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr.strip() or f"error: bd {' '.join(args)} failed", file=sys.stderr)
        sys.exit(result.returncode or 1)
    return json.loads(result.stdout)


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="next-tasks.py", description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--under", action="append", default=[], dest="under_ids", metavar="ID",
        help="only tasks under that id, at any depth; repeatable",
    )
    parser.add_argument("--ids", action="store_true", help="print only task ids, one per line")
    args = parser.parse_args(argv)

    all_tasks = bd_json("list", "--all", "--limit", "0")
    ready_tasks = bd_json("ready", "--limit", "0")

    order = tasks.dispatch_order(all_tasks, ready_tasks, under_ids=args.under_ids or None)

    if args.ids:
        for entry in order:
            print(entry["task"]["id"])
    elif not order:
        print("no ready task to dispatch")
    else:
        for entry in order:
            task = entry["task"]
            epic = entry["epic"]
            if epic:
                label = f"epic {epic}" + (" (in progress)" if entry["epic_started"] else "")
            else:
                label = "no epic"
            print(
                f"{task['id']}  P{task.get('priority', 2)}  "
                f"unblocks {task.get('dependent_count') or 0}  {label}  {task.get('title', '')}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
