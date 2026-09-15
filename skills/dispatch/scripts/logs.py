#!/usr/bin/env python3
"""Shows what a task's workers did, from their logs in .git/sdlc/logs."""
import argparse
import glob
import json
import os
import re
import subprocess
import sys

DESCRIPTION = """Shows what a task's workers did, from their logs in .git/sdlc/logs: every
attempt, oldest first, as readable lines. Messages, tool calls, tool results
(shortened), and each run's running-total cost.

To open a worker's whole conversation in Claude Code, without changing it:
  claude --resume <session> --fork-session

Exit codes: 0 shown, 1 no log, 2 invalid arguments."""


def run_capture(args):
    result = subprocess.run(args, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr.strip() or f"error: {' '.join(args)} failed", file=sys.stderr)
        sys.exit(result.returncode or 1)
    return result.stdout.strip()


def bd_json(*args):
    result = subprocess.run(["bd", *args, "--json"], capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stderr.strip() or f"error: bd {' '.join(args)} failed", file=sys.stderr)
        sys.exit(result.returncode or 1)
    return json.loads(result.stdout)


def bd_show(task_id):
    result = subprocess.run(["bd", "show", task_id, "--json"], capture_output=True, text=True)
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)[0]
    except (json.JSONDecodeError, IndexError, TypeError):
        return None


def oneline(text, limit=None):
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:limit] if limit else text


def render_line(entry):
    """The display lines for one parsed log-line JSON object."""
    kind = entry.get("type")
    lines = []
    if kind == "dispatch_run":
        lines.append(f"── run started {entry.get('started')}")
    elif kind == "assistant":
        indent = "    " if entry.get("parent_tool_use_id") else ""
        for item in (entry.get("message") or {}).get("content") or []:
            if item.get("type") == "text":
                lines.append(f"{indent}● {oneline(item.get('text'))}")
            elif item.get("type") == "tool_use":
                inp = item.get("input") or {}
                detail = (
                    inp.get("command")
                    or inp.get("file_path")
                    or inp.get("pattern")
                    or inp.get("skill")
                    or inp.get("description")
                    or ""
                )
                lines.append(f"{indent}→ {item.get('name')} {oneline(str(detail), 300)}")
    elif kind == "user":
        indent = "    " if entry.get("parent_tool_use_id") else ""
        for item in (entry.get("message") or {}).get("content") or []:
            if item.get("type") != "tool_result":
                continue
            mark = "✗" if item.get("is_error") else "←"
            content = item.get("content")
            if isinstance(content, list):
                text = " ".join(c.get("text") or "" for c in content if isinstance(c, dict))
            else:
                text = "" if content is None else str(content)
            lines.append(f"{indent}  {mark} {oneline(text, 200)}")
    elif kind == "result":
        lines.append(
            f"── result {entry.get('subtype')} · running total ${entry.get('total_cost_usd')} · "
            f"{entry.get('num_turns')} turns"
        )
    return lines


def render_file(path):
    """The display lines for a whole log file, or None if it can't be read.

    Parses line by line: a line a killed worker cut off mid-write doesn't break the rest.
    """
    lines = []
    try:
        with open(path, errors="replace") as f:
            for raw in f:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    entry = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                lines.extend(render_line(entry))
    except OSError:
        return None
    return lines


def read_lines(path):
    try:
        with open(path, errors="replace") as f:
            return f.read().splitlines()
    except OSError:
        return []


def session_block(task_id, session, log_path):
    header = f"═══ {task_id} · session {session}"
    lines = [header]
    if os.path.exists(log_path):
        rendered = render_file(log_path)
        if rendered is None:
            lines.append(f"(unreadable log {log_path})")
        else:
            lines.extend(rendered)
        err_path = log_path + ".err"
        if os.path.exists(err_path) and os.path.getsize(err_path) > 0:
            lines.append("── stderr")
            lines.extend(read_lines(err_path))
        record_path = log_path + ".record"
        if os.path.exists(record_path) and os.path.getsize(record_path) > 0:
            lines.append("── recorded")
            lines.extend(read_lines(record_path))
    else:
        # run-task.sh sets dispatch_session before `wt switch`; if that fails, only
        # <log>.wt (its stderr) exists.
        wt_path = log_path + ".wt"
        if os.path.exists(wt_path) and os.path.getsize(wt_path) > 0:
            lines.append(f"(no log at {log_path}, the worktree failed: {wt_path})")
            lines.extend(read_lines(wt_path))
        else:
            lines.append(f"(no log at {log_path})")
    return header, lines


def collect_sessions(events, task_id, current_session):
    sessions = []
    seen = set()
    targeting = [e for e in events if e.get("target") == task_id]
    for event in sorted(targeting, key=lambda e: e.get("created_at") or ""):
        try:
            payload = json.loads(event.get("payload") or "{}")
        except json.JSONDecodeError:
            payload = {}
        session = payload.get("session")
        if session and session not in seen:
            seen.add(session)
            sessions.append(session)
    if current_session and current_session not in seen:
        sessions.append(current_session)
    return sessions


def truncate_last(all_lines, line_sessions, headers, n):
    """Keeps the last n lines, noting how many were left out and repeating the
    header of the session the first kept line belongs to."""
    if n is None or len(all_lines) <= n:
        return all_lines
    omitted = len(all_lines) - n
    kept = all_lines[-n:]
    first_session = line_sessions[-n:][0]
    noun = "line" if omitted == 1 else "lines"
    prefix = [f"({omitted} earlier {noun} omitted)"]
    if not kept or kept[0] != headers.get(first_session):
        prefix.append(headers[first_session])
    return prefix + kept


def follow_file(path):
    proc = subprocess.Popen(["tail", "-n", "0", "-F", path], stdout=subprocess.PIPE, text=True, bufsize=1)
    try:
        for raw in proc.stdout:
            raw = raw.strip()
            if not raw:
                continue
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for line in render_line(entry):
                print(line, flush=True)
    except KeyboardInterrupt:
        pass
    finally:
        proc.terminate()


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="logs.py", description=DESCRIPTION, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("task_id", metavar="task-id")
    parser.add_argument(
        "--follow", action="store_true", help="after the history, keep printing what the current worker writes"
    )
    parser.add_argument("--raw", action="store_true", help="list the log files of each attempt instead")
    parser.add_argument(
        "--last",
        type=int,
        default=None,
        metavar="N",
        help="print only the last N lines, noting how many were left out and repeating the session header",
    )
    args = parser.parse_args(argv)

    if args.follow and not sys.stdout.isatty():
        print("error: --follow needs a terminal", file=sys.stderr)
        return 2

    task = bd_show(args.task_id)
    if task is None:
        print(f"error: no bead {args.task_id}", file=sys.stderr)
        return 2
    current_session = (task.get("metadata") or {}).get("dispatch_session") or None

    common_dir = run_capture(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"])
    logs_dir = os.path.join(common_dir, "sdlc", "logs")

    events = bd_json("list", "--type", "event", "--all", "--limit", "0")
    sessions = collect_sessions(events, args.task_id, current_session)
    if not sessions:
        print(f"{args.task_id} was never dispatched")
        return 1

    if args.raw:
        for session in sessions:
            log_path = os.path.join(logs_dir, f"{args.task_id}-{session}.jsonl")
            matches = sorted(glob.glob(log_path + "*"))
            if matches:
                for match in matches:
                    print(match)
            else:
                print(f"missing: {log_path}")
        return 0

    all_lines = []
    line_sessions = []
    headers = {}
    for session in sessions:
        log_path = os.path.join(logs_dir, f"{args.task_id}-{session}.jsonl")
        header, lines = session_block(args.task_id, session, log_path)
        headers[session] = header
        all_lines.extend(lines)
        line_sessions.extend([session] * len(lines))

    print("\n".join(truncate_last(all_lines, line_sessions, headers, args.last)))

    if args.follow and current_session:
        current_log = os.path.join(logs_dir, f"{args.task_id}-{current_session}.jsonl")
        print(f"═══ following {args.task_id} · session {current_session} (Ctrl-C to stop)")
        follow_file(current_log)
    return 0


if __name__ == "__main__":
    sys.exit(main())
