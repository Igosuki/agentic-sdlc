import contextlib
import json
import os
import re
import select
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass, field

PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SUPERVISE_PY = os.path.join(PLUGIN_DIR, "scripts", "supervise.py")

POLL_SECONDS = 15
STOP_GRACE_SECONDS = 60
SKILL_PROMPT_RE = re.compile(r"^/sdlc:([a-zA-Z0-9_-]+)")
SUPERVISOR_RUNNING_RE = re.compile(r"^supervisor running: pid (\d+)")


@dataclass
class SessionResult:
    text: str
    results: list
    session_id: str
    cost_usd: float
    turns: int
    is_error: bool
    skills: list = field(default_factory=list)
    tools: list = field(default_factory=list)
    questions: list = field(default_factory=list)
    plans: list = field(default_factory=list)
    prompts: list = field(default_factory=list)


def _strip_skill_prefix(name):
    return name.split(":", 1)[1] if name.startswith("sdlc:") else name


def _skill_from_prompt(prompt):
    m = SKILL_PROMPT_RE.match(prompt.strip())
    return m.group(1) if m else None


def transcript_path(repo, session_id):
    # Matches Claude Code's own project-directory naming: the absolute cwd
    # with every non-alphanumeric character turned into a dash.
    sanitized = re.sub(r"[^a-zA-Z0-9]", "-", os.path.abspath(repo))
    return os.path.join(os.path.expanduser("~"), ".claude", "projects", sanitized, f"{session_id}.jsonl")


def supervisor_pid(repo):
    result = subprocess.run([SUPERVISE_PY, "--running"], cwd=repo, capture_output=True, text=True)
    m = SUPERVISOR_RUNNING_RE.match(result.stdout.strip())
    return int(m.group(1)) if m else None


def kill_supervisor(repo):
    pid = supervisor_pid(repo)
    if pid is not None:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.kill(pid, signal.SIGTERM)
    return pid


class Session:
    def __init__(self, repo, name, interactive=True, answers=None, resume=None):
        self.repo = repo
        self.name = name
        self.interactive = interactive
        self.answers = answers or {}
        self.resume = resume
        self.session_id = resume or str(uuid.uuid4())
        self.skills = []
        self.tools = []
        self.questions = []
        self.plans = []
        self.prompts = []
        self.results = []
        self.cost_usd = 0.0
        self.turns = 0
        self.is_error = False

    def _logs_dir(self):
        logs = os.path.join(os.path.dirname(self.repo), "logs")
        os.makedirs(logs, exist_ok=True)
        return logs

    def _build_cmd(self):
        cmd = [
            "claude", "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--plugin-dir", PLUGIN_DIR, "--model", os.environ.get("SDLC_MODEL", "sonnet"),
        ]
        # Without --permission-prompt-tool the model isn't offered AskUserQuestion, so skills take
        # their headless branch; auto mode runs calls that would prompt instead of denying them (not on Haiku).
        if self.interactive:
            cmd += ["--permission-prompt-tool", "stdio"]
        else:
            cmd += ["--permission-mode", "auto"]
        cmd += ["--resume", self.resume] if self.resume else ["--session-id", self.session_id]
        return cmd

    def _answer_question(self, question):
        options = question.get("options", [])
        labels = [o["label"] for o in options]
        for question_re, option_re in self.answers.items():
            if re.search(question_re, question["question"]):
                matched = [label for label in labels if re.search(option_re, label)]
                if matched:
                    return ", ".join(matched) if question.get("multiSelect") else matched[0]
        for label in labels:
            if "(Recommended)" in label:
                return label
        return labels[0] if labels else ""

    def _handle_control_request(self, msg, send):
        req = msg["request"]
        request_id = msg["request_id"]
        if req.get("subtype") != "can_use_tool":
            send({"type": "control_response", "response": {"subtype": "success", "request_id": request_id, "response": {}}})
            return
        tool_name = req.get("tool_name")
        tool_input = dict(req.get("input") or {})
        if tool_name == "AskUserQuestion":
            answers = {}
            for question in tool_input.get("questions", []):
                answer = self._answer_question(question)
                answers[question["question"]] = answer
                self.questions.append({
                    "question": question["question"],
                    "options": [o["label"] for o in question.get("options", [])],
                    "answer": answer,
                })
            updated_input = dict(tool_input, answers=answers)
            response = {"behavior": "allow", "updatedInput": updated_input}
        elif tool_name == "ExitPlanMode":
            self.plans.append(tool_input.get("plan", ""))
            response = {"behavior": "allow", "updatedInput": tool_input}
        else:
            self.prompts.append({"name": tool_name, "input": tool_input})
            response = {"behavior": "allow", "updatedInput": tool_input}
        send({"type": "control_response", "response": {"subtype": "success", "request_id": request_id, "response": response}})

    def _handle_assistant(self, msg):
        for c in msg.get("message", {}).get("content", []):
            if c.get("type") != "tool_use":
                continue
            name, tool_input = c.get("name"), c.get("input")
            self.tools.append({"name": name, "input": tool_input})
            if name == "Skill" and isinstance(tool_input, dict) and tool_input.get("skill"):
                self.skills.append(_strip_skill_prefix(tool_input["skill"]))

    def kill_supervisor(self):
        return kill_supervisor(self.repo)

    def run(self, prompt, until=None, timeout=None):
        cmd = self._build_cmd()
        logs = self._logs_dir()
        stderr_file = open(os.path.join(logs, f"{self.name}.stderr"), "w")
        transcript = open(os.path.join(logs, f"{self.name}.jsonl"), "a")
        proc = subprocess.Popen(cmd, cwd=self.repo, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                 stderr=stderr_file, text=True, bufsize=1)

        def send(obj):
            if proc.stdin.closed:
                return
            line = json.dumps(obj)
            transcript.write(">> " + line + "\n")
            proc.stdin.write(line + "\n")
            proc.stdin.flush()

        send({"type": "control_request", "request_id": "init1", "request": {"subtype": "initialize", "hooks": None}})
        skill = _skill_from_prompt(prompt)
        if skill:
            self.skills.append(skill)
        send({"type": "user", "message": {"role": "user", "content": prompt}})

        running_tasks = set()
        stdin_open = True
        start = time.monotonic()
        last_check = start

        def stop(kill_the_supervisor):
            nonlocal stdin_open
            if stdin_open:
                proc.stdin.close()
                stdin_open = False
            if kill_the_supervisor:
                self.kill_supervisor()

        timed_out = False
        stopped_at = None
        try:
            while True:
                if timeout is not None and time.monotonic() - start > timeout:
                    stop(kill_the_supervisor=True)
                    timed_out = True
                    break
                if stopped_at is not None and time.monotonic() - stopped_at > STOP_GRACE_SECONDS:
                    break

                wait_for = None
                if stopped_at is not None:
                    wait_for = max(0.0, STOP_GRACE_SECONDS - (time.monotonic() - stopped_at))
                elif (until is not None or timeout is not None) and stdin_open:
                    wait_for = max(0.0, POLL_SECONDS - (time.monotonic() - last_check))

                ready, _, _ = select.select([proc.stdout], [], [], wait_for)
                if not ready:
                    last_check = time.monotonic()
                    if stopped_at is None and until is not None and until():
                        stop(kill_the_supervisor=True)
                        stopped_at = time.monotonic()
                    continue

                line = proc.stdout.readline()
                if not line:
                    break
                transcript.write(line if line.endswith("\n") else line + "\n")
                msg = json.loads(line)
                mtype = msg.get("type")

                if mtype == "control_request":
                    self._handle_control_request(msg, send)
                elif mtype == "system" and msg.get("subtype") == "background_tasks_changed":
                    running_tasks = {t.get("id") or t.get("task_id") for t in msg.get("tasks", [])}
                elif mtype == "assistant":
                    self._handle_assistant(msg)
                elif mtype == "result":
                    self.results.append(msg.get("result") or "")
                    self.session_id = msg.get("session_id", self.session_id)
                    self.cost_usd = msg.get("total_cost_usd", self.cost_usd)
                    self.turns = msg.get("num_turns", self.turns)
                    self.is_error = msg.get("is_error", self.is_error)
                    if until is None and not running_tasks and stdin_open:
                        stop(kill_the_supervisor=False)

            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=10)
        finally:
            transcript.close()
            stderr_file.close()

        with open(os.path.join(logs, "summary.md"), "a") as f:
            f.write(f"{self.name}: ${self.cost_usd:.4f} - {self.turns} turns - error {self.is_error}\n")

        if timed_out:
            raise TimeoutError(f"{self.name}: timed out after {timeout}s waiting for `until`")

        return SessionResult(
            text=self.results[-1] if self.results else "",
            results=list(self.results),
            session_id=self.session_id,
            cost_usd=self.cost_usd,
            turns=self.turns,
            is_error=self.is_error,
            skills=list(self.skills),
            tools=list(self.tools),
            questions=list(self.questions),
            plans=list(self.plans),
            prompts=list(self.prompts),
        )
