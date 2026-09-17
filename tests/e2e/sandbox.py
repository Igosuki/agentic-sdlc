import inspect
import os
import subprocess
import time
import uuid
from dataclasses import dataclass

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SANDBOX_PY = os.path.abspath(__file__)


@dataclass
class Project:
    path: str
    repo: str
    logs: str
    name: str


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
