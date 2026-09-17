import json
import os
import subprocess
import sys

SKILLS_DIR = os.path.dirname(os.path.abspath(__file__))
E2E_DIR = os.path.dirname(SKILLS_DIR)
sys.path.insert(0, E2E_DIR)
from session import PLUGIN_DIR  # noqa: E402

SCRIPTS = os.path.join(PLUGIN_DIR, "scripts")
SETTINGS_SH = os.path.join(SCRIPTS, "settings.sh")
CREATE_TASK_SH = os.path.join(SCRIPTS, "create-task.sh")


def bd_json(repo, *args):
    # --all only applies to `bd list`; `bd show` has no such flag and always
    # returns the issue regardless of status.
    extra = ["--all"] if args and args[0] == "list" else []
    result = subprocess.run(["bd", *args, *extra, "--json"], cwd=repo, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"bd {args} failed: {result.stderr}")
    return json.loads(result.stdout or "[]")


def descendants(repo, root_id):
    out = []
    frontier = [root_id]
    while frontier:
        next_frontier = []
        for parent_id in frontier:
            children = bd_json(repo, "list", "--parent", parent_id)
            out.extend(children)
            next_frontier.extend(c["id"] for c in children)
        frontier = next_frontier
    return out


def setting(repo, key):
    result = subprocess.run([SETTINGS_SH, key], cwd=repo, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"settings.sh {key} failed: {result.stderr}")
    return result.stdout.strip()


def create_task(repo, *args):
    result = subprocess.run([CREATE_TASK_SH, *args], cwd=repo, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"create-task.sh {args} failed: {result.stdout}\n{result.stderr}")
    return result.stdout.split()[1]


def git_status(repo):
    result = subprocess.run(
        ["git", "status", "--porcelain", "--", ".", ":!.beads"], cwd=repo, capture_output=True, text=True
    )
    return result.stdout


def git_head(repo):
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True)
    return result.stdout.strip()


def git_log_subjects(repo):
    result = subprocess.run(["git", "log", "--format=%s"], cwd=repo, capture_output=True, text=True)
    return result.stdout.splitlines()


def worktree_branches(repo):
    result = subprocess.run(["wt", "list", "--format", "json"], cwd=repo, capture_output=True, text=True)
    if result.returncode != 0:
        raise AssertionError(f"wt list failed: {result.stderr}")
    items = json.loads(result.stdout or "{}").get("items", [])
    return {i["branch"] for i in items}


def branch_exists(repo, branch):
    result = subprocess.run(
        ["git", "rev-parse", "--verify", "--quiet", f"refs/heads/{branch}"], cwd=repo, capture_output=True, text=True
    )
    return result.returncode == 0



def transcript_events(logfile):
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
