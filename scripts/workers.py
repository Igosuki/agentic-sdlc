#!/usr/bin/env python3
"""Lists dispatched tasks that aren't closed, with where their worker runs."""
import argparse
import glob
import json
import os
import subprocess
import sys
import time

import tasks

DESCRIPTION = """Lists dispatched tasks that aren't closed, with where their worker runs:
  running   the worker's process is alive
  crashed   claimed, no outcome recorded, and no process runs its session; followed by
            the evidence to decide on resuming: worktree, commits, uncommitted
            files, transcript, log runs and result, last events, stderr
  stopped / failed   the worker ended without closing the task; followed by
            the task's last comment
  awaiting-review    a human review gate blocks the task; followed by the
            gate id and the commands a person uses to review and resolve it
  pr-opened   a pull request is open, waiting for its merge

Options:
  --epic EPIC     only tasks under that epic, at any depth
  --alive-count   print only the number of live workers on this machine

Exit codes: 0 listed, 2 invalid arguments."""

NO_OUTCOME = ("", "running")  # "running" is a legacy value, kept as a synonym for unset.


def bd_json(*args):
    result = subprocess.run(["bd", *args, "--json"], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr.strip() or f"error: bd {' '.join(args)} failed", file=sys.stderr)
        sys.exit(result.returncode or 1)
    return json.loads(result.stdout)


def run_capture(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr.strip() or f"error: {' '.join(args)} failed", file=sys.stderr)
        sys.exit(result.returncode or 1)
    return result.stdout.strip()


def soft_capture(args):
    try:
        result = subprocess.run(args, capture_output=True, text=True)
    except OSError:
        return None
    return result.stdout.strip() if result.returncode == 0 else None


def logs_dir():
    common_dir = run_capture(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"])
    return os.path.join(common_dir, "sdlc", "logs")


def worktree_paths_by_branch():
    try:
        result = subprocess.run(["wt", "list", "--format", "json"], capture_output=True, text=True)
        data = json.loads(result.stdout) if result.returncode == 0 else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    paths = {}
    for item in data.get("items", []):
        branch = item.get("branch")
        path = (item.get("worktree") or {}).get("path")
        if branch and path:
            paths[branch] = path
    return paths


def ago(seconds):
    seconds = int(seconds)
    if seconds < 120:
        return f"{seconds}s"
    if seconds < 7200:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def mtime_ago(path, now):
    if not path:
        return None
    try:
        return ago(now - os.stat(path).st_mtime)
    except OSError:
        return None


def find_transcript(session):
    matches = glob.glob(os.path.expanduser(f"~/.claude/projects/**/{session}.jsonl"), recursive=True)
    return matches[0] if matches else None


def last_comment(task_id):
    """None on any failure (a deleted task, a down server): a comment lookup that fails
    must not stop the rest of the listing."""
    try:
        result = subprocess.run(["bd", "comments", task_id, "--json"], capture_output=True, text=True)
        if result.returncode != 0:
            return None
        comments = json.loads(result.stdout)
        text = (comments[-1].get("text") or "").replace("\n", " ")
        return text[:300] or None
    except (OSError, json.JSONDecodeError, IndexError, AttributeError, TypeError):
        return None


def git_commit_count(worktree, base):
    result = subprocess.run(["git", "-C", worktree, "rev-list", "--count", f"{base}..HEAD"], capture_output=True, text=True)
    return result.stdout.strip() if result.returncode == 0 else "unknown"


def git_uncommitted(worktree):
    result = subprocess.run(["git", "-C", worktree, "status", "--porcelain"], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    files = [line[3:] for line in result.stdout.splitlines() if line]
    return " ".join(files) if files else "none"


def read_jsonl(path):
    entries = []
    try:
        with open(path, errors="replace") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entries.append(json.loads(raw))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return entries


def _oneline(text, limit=160):
    return " ".join((text or "").split())[:limit]


def crash_log_evidence(path):
    """Worker runs, last result, and the last events from a task's log, drawn from
    tool calls, text and tool results."""
    entries = read_jsonl(path)
    runs = sum(1 for e in entries if e.get("type") == "dispatch_run")
    result = None
    for e in entries:
        if e.get("type") == "result":
            result = f"{e.get('subtype')} (error: {json.dumps(e.get('is_error'))})"

    events = []
    for entry in entries:
        if entry.get("type") not in ("assistant", "user"):
            continue
        for item in (entry.get("message") or {}).get("content") or []:
            kind = item.get("type")
            if kind == "tool_use":
                inp = item.get("input") or {}
                detail = inp.get("command") or inp.get("file_path") or inp.get("description") or ""
                text = f"tool call {item.get('name')}: {detail}"
            elif kind == "text":
                text = f"text: {item.get('text')}"
            elif kind == "tool_result":
                content = item.get("content")
                if isinstance(content, list):
                    joined = " ".join(c.get("text") or "" for c in content if isinstance(c, dict))
                else:
                    joined = "" if content is None else str(content)
                mark = " (error)" if item.get("is_error") else ""
                text = f"tool result{mark}: {joined}"
            else:
                continue
            events.append(_oneline(text))
    return runs, result, events[-6:]


def print_crashed(task, host, title, log_path, wt_path, base, now):
    metadata = task.get("metadata") or {}
    session = metadata.get("dispatch_session", "")
    started = mtime_ago(log_path + ".wt" if log_path else None, now)
    output = mtime_ago(log_path, now)
    print(f'{task["id"]}  crashed  on {host}  started {started or "?"} ago  last output {output or "never"} ago  "{title}"')
    print(f"  session: {session}")
    print(f"  transcript: {find_transcript(session) or 'missing'}")
    if wt_path and os.path.isdir(wt_path):
        print(f"  worktree: {wt_path}")
        print(f"  commits since {base}: {git_commit_count(wt_path, base)}")
        print(f"  uncommitted: {git_uncommitted(wt_path) or 'none'}")
    else:
        print("  worktree: missing")
    if log_path and os.path.exists(log_path):
        print(f"  log: {log_path}")
        runs, result, events = crash_log_evidence(log_path)
        print(f"  worker runs: {runs}")
        print(f"  result: {result or 'none'}")
        print("  last events:")
        for line in events:
            print(f"    {line}")
    else:
        print("  log: missing")
    err_path = f"{log_path}.err" if log_path else None
    if err_path and os.path.exists(err_path) and os.path.getsize(err_path) > 0:
        print("  stderr:")
        with open(err_path, errors="replace") as f:
            for line in f.read().splitlines()[-5:]:
                print(f"    {line}")
    print(f"  machine booted: {soft_capture(['uptime', '-s']) or 'unknown'}")


def print_task(task, logs_directory, worktree_paths, now):
    metadata = task.get("metadata") or {}
    tid = task["id"]
    branch = metadata.get("dispatch_branch", "")
    base = metadata.get("dispatch_base", "")
    host = metadata.get("dispatch_host", "")
    title = task.get("title", "")
    log_path = os.path.join(logs_directory, f'{tid}-{metadata.get("dispatch_session", "")}.jsonl')
    wt_path = worktree_paths.get(branch)

    if tasks.worker_running(task):
        started = mtime_ago(log_path + ".wt", now)
        output = mtime_ago(log_path, now)
        print(f'{tid}  running  on {host}  started {started or "?"} ago  last output {output or "never"} ago  "{title}"')
        return

    state = metadata.get("dispatch_state") or ""
    if state in NO_OUTCOME:
        print_crashed(task, host, title, log_path, wt_path, base, now)
        return

    comment = last_comment(tid)
    print(f'{tid}  {state}  on {host}  worktree {wt_path or "missing"}  "{title}"')
    if state == "pr-opened":
        print(f"  pull request: {metadata.get('dispatch_pr', '')}, waiting for its merge")
    elif state == "awaiting-review":
        gate = metadata.get("dispatch_review_gate", "")
        print(f"  gate: {gate}")
        print(f"  review:         git -C {wt_path} diff {base}...{branch}")
        print(f'  request changes: bd comments add {tid} "<what to change>"')
        print(f"  done:            bd gate resolve {gate}")
    else:
        print(f"  last comment: {comment or 'none'}")


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="workers.py", description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--epic", default="", help="only tasks under that epic, at any depth")
    parser.add_argument(
        "--alive-count", action="store_true", dest="alive_count",
        help="print only the number of live workers on this machine",
    )
    args = parser.parse_args(argv)

    all_tasks = bd_json("list", "--all", "--limit", "0")
    by_id = tasks.index_by_id(all_tasks)
    dispatched = [
        t for t in all_tasks if t.get("status") == "in_progress" and (t.get("metadata") or {}).get("dispatch_session")
    ]
    if args.epic:
        dispatched = [t for t in dispatched if tasks.epic_of(by_id, t["id"]) == args.epic]

    if args.alive_count:
        print(sum(1 for t in dispatched if tasks.worker_running(t)))
        return 0

    if not dispatched:
        print("no dispatched task in progress")
        return 0

    logs_directory = logs_dir()
    worktree_paths = worktree_paths_by_branch()
    now = time.time()
    for task in dispatched:
        print_task(task, logs_directory, worktree_paths, now)
    return 0


if __name__ == "__main__":
    sys.exit(main())
