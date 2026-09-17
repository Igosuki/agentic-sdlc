import inspect
import json
import os
import re
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SANDBOX_PY = os.path.abspath(__file__)
SCRIPTS_DIR = os.path.join(PLUGIN_DIR, "scripts")
CREATE_TASK_SH = os.path.join(SCRIPTS_DIR, "create-task.sh")
RECORD_TASK_SH = os.path.join(SCRIPTS_DIR, "record-task.sh")

STATES = ("stopped", "failed", "awaiting-review", "running", "closed")

DEFAULT_GITIGNORE = """__pycache__/
*.py[cod]
.pytest_cache/
.venv/
venv/
*.egg-info/
build/
dist/
.mypy_cache/
.ruff_cache/
node_modules/
coverage/
"""


@dataclass
class Project:
    path: str
    repo: str
    logs: str
    name: str


@dataclass
class Dispatched:
    task: str
    session: str
    branch: str
    base: str
    log: str
    gate: str = None
    process: subprocess.Popen = None


def _run(cwd, *args, check=True):
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        raise AssertionError(f"{args} failed: {result.returncode}\n{result.stdout}\n{result.stderr}")
    return result


def _suite_name():
    for f in inspect.stack()[1:]:
        if os.path.abspath(f.filename) != SANDBOX_PY:
            module = inspect.getmodulename(f.filename) or "e2e"
            return module[len("test_"):] if module.startswith("test_") else module
    return "e2e"


def new_project(name, integration="epic-merge", files=None, init=True):
    base = os.environ.get("SDLC_SANDBOX") or os.path.join(os.path.expanduser("~"), "dev", "sdlc-sandbox")
    stamp = time.strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:6]
    project_dir = os.path.join(base, f"e2e-{_suite_name()}-{stamp}", name)
    repo = os.path.join(project_dir, "repo")
    logs = os.path.join(project_dir, "logs")
    os.makedirs(repo)
    os.makedirs(logs)

    _run(repo, "git", "init", "-q", "-b", "main")
    with open(os.path.join(repo, "README.md"), "w") as f:
        f.write(f"# {name}\n")
    with open(os.path.join(repo, ".gitignore"), "w") as f:
        f.write(DEFAULT_GITIGNORE)
    for relpath, content in (files or {}).items():
        full = os.path.join(repo, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w") as f:
            f.write(content)
    _run(repo, "git", "add", "-A")
    _run(repo, "git", "commit", "-q", "-m", "Initial commit")

    if init:
        _run(repo, os.path.join(PLUGIN_DIR, "skills", "init", "scripts", "init.sh"), "--integration", integration)

    print(f"sandbox: {project_dir}")
    return Project(path=project_dir, repo=repo, logs=logs, name=name)


def task(project, title, *, type="task", description=None, parent=None, acceptance="done",
         scope="src/", verify="true", complexity="small", design=None, after=None,
         priority=None, agent=None, model=None, effort=None, review=None):
    """Creates one bead with create-task.sh and returns its id. Defaults fill the
    fields a task requires (acceptance, scope, verify, complexity) so callers only
    need to override what the fixture cares about."""
    args = ["--title", title, "--description", description or title, "--type", type]
    if type == "task":
        args += ["--acceptance", acceptance, "--scope", scope, "--verify", verify, "--complexity", complexity]
    if parent:
        args += ["--parent", parent]
    if design:
        args += ["--design", design]
    for dep in after or ():
        args += ["--after", dep]
    if priority is not None:
        args += ["--priority", str(priority)]
    if agent:
        args += ["--agent", agent]
    if model:
        args += ["--model", model]
    if effort:
        args += ["--effort", effort]
    if review:
        args += ["--review", review]
    result = _run(project.repo, CREATE_TASK_SH, *args)
    m = re.search(r"created (\S+)", result.stdout)
    if not m:
        raise AssertionError(f"create-task.sh did not report a created id: {result.stdout}")
    return m.group(1)


def _logs_dir(repo):
    common_dir = _run(repo, "git", "rev-parse", "--path-format=absolute", "--git-common-dir").stdout.strip()
    path = os.path.join(common_dir, "sdlc", "logs")
    os.makedirs(path, exist_ok=True)
    return path


def _write_log(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")


def _dispatch_run_line():
    return {"type": "dispatch_run", "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}


def _result_line(is_error, summary):
    return {
        "type": "result",
        "subtype": "error_during_execution" if is_error else "success",
        "is_error": is_error,
        "total_cost_usd": 0.05,
        "num_turns": 2,
        "duration_ms": 5000,
        "result": summary,
        "modelUsage": {"claude-sonnet-4-5": {}},
    }


def dispatched(project, task_id, state, *, session=None, host="e2e-sandbox", base="main",
                branch=None, commits=None, gate=None, summary=None):
    """Leaves task_id the way a worker would after ending in `state`: claimed, with a
    worktree and branch, a worker log at .git/sdlc/logs/<task>-<session>.jsonl, and (for
    every state but running and closed) a recorded attempt from record-task.sh. For
    "closed", the task is closed directly, as if record-task.sh crashed before running,
    leaving the worktree and branch behind for clean.sh to find.

    commits: a list of {relpath: content}, one dict per commit, applied in the worktree.
    gate: for awaiting-review, whether to open a human review gate (default: yes).
    Returns a Dispatched with the process to kill for state="running".
    """
    if state not in STATES:
        raise ValueError(f"unknown state {state!r}: expected one of {STATES}")
    session = session or f"s-{uuid.uuid4().hex[:8]}"
    branch = branch or task_id
    if gate is None:
        gate = state == "awaiting-review"

    _run(
        project.repo, "bd", "update", task_id, "--claim",
        "--set-metadata", f"dispatch_session={session}",
        "--set-metadata", f"dispatch_base={base}",
        "--set-metadata", f"dispatch_branch={branch}",
        "--set-metadata", f"dispatch_host={host}",
    )
    created = json.loads(
        _run(project.repo, "wt", "switch", "--create", branch, "--base", base, "--no-cd", "--format", "json").stdout
    )
    wt_path = created["path"]

    for i, files in enumerate(commits or ()):
        for relpath, content in files.items():
            full = os.path.join(wt_path, relpath)
            os.makedirs(os.path.dirname(full) or wt_path, exist_ok=True)
            with open(full, "w") as f:
                f.write(content)
        _run(wt_path, "git", "add", "-A")
        _run(wt_path, "git", "commit", "-q", "-m", f"commit {i + 1} for {task_id}")

    log_path = os.path.join(_logs_dir(project.repo), f"{task_id}-{session}.jsonl")

    if state == "running":
        _write_log(log_path, [_dispatch_run_line()])
        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(600)", "--session-id", session], cwd=project.repo
        )
        time.sleep(0.3)
        return Dispatched(task=task_id, session=session, branch=branch, base=base, log=log_path, process=process)

    gate_id = None
    if state == "awaiting-review":
        _run(project.repo, "bd", "update", task_id, "--set-metadata", "dispatch_state=awaiting-review")
        if gate:
            created_gate = json.loads(_run(
                project.repo, "bd", "gate", "create", "--type=human", "--blocks", task_id,
                "--reason", f"review {task_id}: git diff {base}...{branch} in {wt_path}", "--json",
            ).stdout)
            gate_id = created_gate["id"]
            _run(project.repo, "bd", "update", task_id, "--set-metadata", f"dispatch_review_gate={gate_id}")

    _write_log(log_path, [_dispatch_run_line(), _result_line(state == "failed", summary or state)])

    if state == "closed":
        _run(project.repo, "bd", "close", task_id)
        # The worker merged and the task closed, but record-task.sh never ran (a crash
        # between merge and record), so the worktree and branch stay behind uncleaned.
        return Dispatched(task=task_id, session=session, branch=branch, base=base, log=log_path, gate=gate_id)

    _run(project.repo, RECORD_TASK_SH, task_id)

    return Dispatched(task=task_id, session=session, branch=branch, base=base, log=log_path, gate=gate_id)


def verify_break(project, path="VERSION", good="v1", bad="v2"):
    """A closed task whose metadata.verify checks <path> for `good`, on the main branch
    (no worktree of its own), broken by a later commit on main that writes `bad`.
    Returns (task_id, breaking commit sha)."""
    task_id = task(project, f"Add {path}", verify=f"grep -q {good} {path}", scope=path)
    with open(os.path.join(project.repo, path), "w") as f:
        f.write(good + "\n")
    _run(project.repo, "git", "add", "-A")
    _run(project.repo, "git", "commit", "-q", "-m", f"Add {path} {good}")
    _run(project.repo, "bd", "update", task_id, "--set-metadata", "dispatch_branch=main")
    _run(project.repo, "bd", "close", task_id)

    with open(os.path.join(project.repo, path), "w") as f:
        f.write(bad + "\n")
    _run(project.repo, "git", "add", "-A")
    _run(project.repo, "git", "commit", "-q", "-m", f"Bump {path} to {bad}")
    sha = _run(project.repo, "git", "rev-parse", "HEAD").stdout.strip()
    return task_id, sha
