# Plan: end-to-end tests

Three suites that run real Claude sessions on the plugin and pass or fail on what they leave behind:
1. **build:** `/sdlc:build` from request to merged code.
2. **skills:** every skill alone, each on its own prepared project.
3. **flow:** every skill one after another on one project, without `/sdlc:build`.

## What exists

- `tests/test_*.py`: unit tests for the scripts, on real `bd`, git and `wt`, with no model. They stay as they are.
- `tests/wild/run.sh` and `tests/wild/dispatch.sh`: headless runs with no checks ("the point is to watch the plugin work"). They use plain `claude -p`, so every skill takes its headless branch. `dispatch.sh` runs `supervise.py` itself instead of `/sdlc:dispatch`. Nothing covers `/sdlc:build`, a skill's interactive branch, or review, verify, recover, stop, clean, hooks, create-task, init and setup as skills.

## Verified on 2026-09-17 (Claude Code 2.1.274)

Each fact was checked with a Haiku or Sonnet session in the scratchpad.

- **Plain `claude -p` can't run dispatch.** AskUserQuestion isn't in its tool list. The process exits when the turn ends, even while a background Bash command runs: a 20 s background command, and the process exited after 12 s. So `/sdlc:dispatch` can start `supervise.py` but never hears it exit.
- **`claude -p --input-format stream-json --output-format stream-json --permission-prompt-tool stdio` can.** This is how the Agent SDK drives the CLI.
  - AskUserQuestion is available and arrives on stdout as a `control_request` (`can_use_tool`). Replying `allow` with `updatedInput.answers` (question text → option label) gives the model that answer.
  - ExitPlanMode arrives the same way, with the plan text. `allow` approves the plan.
  - Any other tool call that would prompt a person arrives the same way.
  - While stdin stays open, the session wakes when a background Bash command ends (`task_notification`, then a second `result`). `background_tasks_changed` lists the ones still running.
- **`claude plugin eval` doesn't fit.**
  - Its graders only check a regex, which tools were called and in what order, files the session created, or an LLM verdict. None can check beads or git state.
  - A case sends one prompt. A second turn needs a saved transcript.
  - Its sandbox limits writes to the case directory, hides `~/.config` (where `wt`, `bd` and `gh` keep their config) and passes only allowlisted environment variables.
  - By default it runs each case 3 times, plus a run without the plugin.

  It could grade the prose of design or split later. That's out of scope here.

## Shape

One driver and three suites, in Python `unittest` under `tests/e2e/`. They are skipped unless `SDLC_E2E=1`, so `pytest tests` never calls a model.

| File | What it does |
|---|---|
| `tests/e2e/session.py` | Runs one Claude session on the plugin the way a person at the terminal would. It sends prompts, answers AskUserQuestion, approves plans, keeps the session open while its background commands run, and records what happened. |
| `tests/e2e/sandbox.py` | Creates a new project under `$SDLC_SANDBOX`, and the prepared states the skills suite starts from. |
| `tests/e2e/test_fixtures.py` | Checks, without a model, that each prepared state reads back through the scripts as intended. |
| `tests/e2e/test_build.py` | Suite 1. |
| `tests/e2e/skills/test_skill_<name>.py` | Suite 2, one file per skill, so tasks adding skills don't edit the same file. |
| `tests/e2e/test_flow.py` | Suite 3. |

`tests/wild/` is deleted: flow covers `run.sh`, and build and flow cover `dispatch.sh`.

### `session.py`

`Session(repo, name, interactive=True, answers=None, resume=None)` starts `claude -p` with the stream-json flags above, `--plugin-dir <this repo>` and `--model $SDLC_MODEL` (default `sonnet`). `run(prompt, until=None, timeout=...)` returns:

- `text`: the last result, and `results`: every result, one per wake
- `session_id`, `cost_usd`, `turns`, `is_error`
- `skills`: the skills started, in order
- `tools`: every tool call, as name and input
- `questions`: each question, its options and the answer given
- `plans`: the plans sent to ExitPlanMode
- `prompts`: every other permission request, meaning a tool call that neither the skill's `allowed-tools` nor this machine's settings allowed

How it answers:
- **Questions:** `answers` maps a regex on the question to a regex on the option label. Anything unmatched gets the option marked "(Recommended)", or else the first one.
- **Plans:** approved.
- **Other permission requests:** allowed, and recorded in `prompts`.

When it ends:
- **Normally:** a result arrives and no background command runs. It closes stdin.
- **`until`:** a function checked every 15 s. When it returns true, the driver closes stdin, kills the supervisor (its pid from `supervise.py --running`) and ends the session.
- **`timeout`:** the same as `until`, and the test fails.

`interactive=False` leaves out `--permission-prompt-tool stdio`, so the skill takes its headless branch. Stdin still stays open, so dispatch keeps working.

Each session writes its transcript to `<sandbox>/logs/<name>.jsonl` and a line with its cost and turns to `<sandbox>/logs/summary.md`.

Sessions run with this machine's Claude configuration: installed skills, agents, hooks and allow rules, as the wild runs do. design and split are meant to use those. As a result, `prompts` shows the `allowed-tools` gaps as seen from this machine's settings.

### `sandbox.py`

- **`new_project(name, integration="epic-merge", files={}, init=True)`** creates `$SDLC_SANDBOX/e2e-<suite>-<timestamp>/<name>/` with `repo/` and `logs/`. In `repo/` it runs `git init -b main`, writes a README and the given files, commits them, and then runs `skills/init/scripts/init.sh --integration <mode>` unless `init=False`.
- **`task(...)`** creates a task with `create-task.sh`.
- **`dispatched(task, state, ...)`** puts a task in the state a worker leaves it in: `stopped`, `failed`, `awaiting-review`, `running` or `closed`.
  - It sets the metadata the scripts read: `dispatch_session`, `dispatch_base`, `dispatch_branch`, `dispatch_state` and the review gate.
  - It creates the branch and worktree with `wt`, with the given commits.
  - It writes a short worker log to `.git/sdlc/logs/<task>-<session>.jsonl` and records the attempt with `record-task.sh`.
  - For `running`, it starts a placeholder process whose command line carries `--session-id <session>`, which is what `tasks.worker_running` looks for.

  It is built from what `tests/test_stop_task.py`, `test_logs.py`, `test_stats.py` and `test_clean.py` already set up.

Why prepared states instead of real workers: they are the same on every run and cost nothing. Real states come from the flow suite.

Sandboxes are kept after the run, and their path is printed.

## What the checks look at

- **State:** `bd … --json`, git, files, and the output of the plugin's scripts: `verify.sh`, `clean.sh`, `workers.py`, `stats.py`, `settings.sh`.
- **The session record:** skills started, tool calls, questions, plans and permission requests.
- **Reply text:** only for markers the skill must print: ids, command names, section headings.

No LLM judge: it would make checks flaky and cost money on every run.

## Suite 1: build (`test_build.py`)

**Setup.** The request is fixed: `$SDLC_E2E_REQUEST`, by default "create a command-line todo list in Python with add, list and done commands, stored in a JSON file". The integration mode comes from `$SDLC_INTEGRATION`: `epic-merge` by default, or `direct`. `epic-pr` needs a GitHub remote and isn't covered. The project is created with `new_project`, so init has run, as build assumes.

**Tests.**
- `test_build_interactive` runs `/sdlc:build <request>` with the default answers.
- `test_build_headless` runs the same with `interactive=False`, which follows build's Headless section.

**When a run ends.** `until` is true once the epic is closed, or when nothing runs and nothing is ready on two polls in a row (as in `dispatch.sh`). The second case fails the test, since a person would be needed. `timeout` is `$SDLC_E2E_TIMEOUT`, 60 minutes by default. Any `blocked … stopped` or `failed` line the session relays fails the test and shows the comment.

**Checks, both tests:**
- The skills started are design, split and dispatch, in that order.
- There is exactly one top-level epic. Each of its tasks has acceptance, scope, verify, complexity and review.
- The epic and every bead under it are closed. None has `dispatch_state` `stopped` or `failed`.
- `main` has the epic's merge, and `scripts/verify.sh <epic>` exits 0 on `main`.
- `scripts/clean.sh` prints nothing, `scripts/stats.py --under <epic>` lists every task, and `main` has no uncommitted changes.

**Interactive only:**
- There is one plan, and it names the integration mode and the target branch.
- Split's approval question comes before `supervise.py` starts, and dispatch asks nothing after it.

**Headless only:** no questions and no plan.

## Suite 2: each skill alone (`tests/e2e/skills/`)

Each skill has its own file, `test_skill_<name>.py`, and each class starts from a new project. The sessions are interactive unless the table says headless.

| Skill | Prepared project | Prompt and answers | Checks |
|---|---|---|---|
| setup | none | headless `/sdlc:setup` | `setup-checks.sh` ran; no install command ran (no `apt`, `pip`, `npm`, `brew`, `cargo` or `curl` in Bash calls); the reply names `/sdlc:init` |
| init | git repo, `init=False` | `/sdlc:init`: epic-merge, target main, workflow build, commit yes | `.beads/` exists; `settings.sh` shows epic-merge, main and build; `.gitignore` has the local files; the last commit is "Ignore sdlc local files" |
| init, again | project already set to epic-merge | headless `/sdlc:init --parallel 3` | integration is still epic-merge, parallel is 3, no new commit |
| hooks | `package.json`, `package-lock.json`, `.github/workflows/ci.yml` running `npm test` | `/sdlc:hooks`, select all | `.config/wt.toml` has a pre-start with `npm ci` and a pre-merge with `npm test`; no pre-commit, post-merge or switch hooks; `wt hook show` exits 0; nothing committed |
| design | README for a small Python CLI, `docs/usage.md` | `/sdlc:design add a --json flag to the list command` | reply has "Prior art" and "Open questions"; no beads, commits or branches; no new files; only existing `.md` files changed |
| split | committed `docs/design/todo.md` | `/sdlc:split docs/design/todo.md`, approve | at least one epic and two tasks; each task has acceptance, scope, verify, complexity and review; `bd swarm validate` passes on each epic; no files changed, no commits; the approval question came after the last bead was created |
| create-task | epic with an open task scoped to `src/` | `/sdlc:create-task add a --version flag to src/cli.py --parent <epic>` | exactly one new bead, under the epic, with every field, waiting on the open task (overlapping scope) |
| dispatch | epic with task A (`hello.txt`), and task B after A, both small, review none | `/sdlc:dispatch <B>`: add the blocker yes, confirm yes; `until` the epic is closed | asked about A, then asked to confirm; `supervise.py` started in the background with `--under` for A and B; both closed; `hello.txt` on `main` |
| status | tasks stopped, failed, awaiting-review, and one ready | `/sdlc:status` | no tool calls, no prompts; reply has `/sdlc:recover <stopped>`, `/sdlc:recover <failed>` and the ready id |
| stats | two tasks with recorded attempts | `/sdlc:stats <epic>` | no tool calls; reply has both ids and a cost |
| logs | task with a worker log | `/sdlc:logs <task>` | no tool calls; reply has lines from the log and `--fork-session` |
| verify | closed task verifying `grep -q v1 VERSION`, then a later commit on main that writes `v2` | `/sdlc:verify <epic>` | reply names the task and the breaking commit |
| review | awaiting-review task, acceptance "divide by zero returns an error"; the branch leaves the check out | headless `/sdlc:review <task>` (what `finish-task.sh` runs for `review=agent`) | verdict "request changes" with a finding about division by zero; no `bd` writes (`update`, `comments add`, `gate resolve`, `close`) |
| review, gate | same, with an open human review gate | `/sdlc:review <task>`, approve | `bd gate resolve <gate>` ran; the gate is closed |
| recover | stopped task with worktree, log and comment | `/sdlc:recover <task>`, start over | `reset-task.sh` ran; the task is open with no `dispatch_branch`; the branch is gone |
| recover, headless | same | headless | none of `resume-task.sh`, `finish-task.sh` or `reset-task.sh` ran; the reply lists the four options |
| stop | running task | `/sdlc:stop <task>`, yes | `stop-task.sh` ran; `dispatch_state` is stopped; the placeholder process is gone |
| stop, headless | same | headless | nothing ran; the process is still alive |
| clean | closed task with its worktree and branch left behind | `/sdlc:clean`, yes | `clean.sh --apply` ran; the worktree and branch are gone |
| clean, headless | same | headless | still there; the reply mentions `--apply` |

A second row for a skill tests the other branch only where running the wrong one does damage (recover, stop, clean) or where the plugin itself relies on it (init keeping saved settings, review with a gate).

## Suite 3: skills one by one (`test_flow.py`)

One project and one test class. The steps are test methods run in order. Once a step fails, the steps after it are skipped. The request is the same as build's.

| Step | Prompt | Checks |
|---|---|---|
| 1 | headless `/sdlc:setup` | as in the skills suite |
| 2 | `/sdlc:init --integration epic-merge` on a bare git repo | `.beads/` exists; settings show epic-merge |
| 3 | `/sdlc:design <request>`, session A | "Prior art" in the reply; no beads |
| 4 | `/sdlc:split` resuming session A, approve | one epic; every task has every field; `bd swarm validate` passes |
| 5 | (test) commit doc changes, if any, as build would | |
| 6 | `/sdlc:create-task add a README section listing the commands --parent <epic>` | one new task under the epic |
| 7 | `/sdlc:dispatch <epic> --parallel 2`, confirm, session D in a thread | `supervise.py` started |
| 8 | once `workers.py --under <epic>` shows a running task: `/sdlc:status` | reply lists it as running |
| 9 | `/sdlc:logs <task>` | reply shows its log |
| 10 | `/sdlc:stop <task>`, yes | the task is stopped; session D relays `blocked <task> stopped` |
| 11 | `/sdlc:recover <task>`, resume | its worker runs again, or it closes |
| 12 | wait for session D's `until`: the epic is closed | every bead closed; `main` has the merge |
| 13 | `/sdlc:verify <epic>` | passes |
| 14 | headless `/sdlc:review <epic>` | a verdict is stated; no `bd` writes |
| 15 | `/sdlc:stats <epic>` | every task listed with a cost |
| 16 | `/sdlc:hooks`, default answers | `wt hook show` exits 0 |
| 17 | `/sdlc:clean`, yes | `clean.sh` prints nothing afterwards |

Steps 8 to 11 are skipped, with the reason given, if no worker was still running by the time the step began.

## Running

```bash
SDLC_E2E=1 python3 -m pytest tests/e2e/test_fixtures.py                    # prepared states, no model
SDLC_E2E=1 python3 -m pytest tests/e2e/skills -v                           # every skill alone
SDLC_E2E=1 python3 -m pytest tests/e2e/skills/test_skill_clean.py         # one skill
SDLC_E2E=1 python3 -m pytest tests/e2e/test_flow.py -v                     # skills one by one
SDLC_E2E=1 python3 -m pytest tests/e2e/test_build.py -v                    # /sdlc:build
```

Environment: `SDLC_SANDBOX`, `SDLC_MODEL`, `SDLC_INTEGRATION`, `SDLC_E2E_REQUEST`, `SDLC_E2E_TIMEOUT`.

Each run prints its sandbox path. `logs/summary.md` holds the cost of each session, plus the workers' costs from `stats.py`. Cost isn't measured yet. The first run of each suite puts its numbers in `docs/development.md`.

## Open points

- **To check in T1:** that `interactive=False` hides AskUserQuestion while stdin stays open. If it doesn't, add `--disallowedTools AskUserQuestion`.
- **To check in T1:** how a `/sdlc:<skill>` prompt shows in the transcript (a Skill tool call or an injected message). `skills` records both.
- Model output varies, so build and flow can fail on a bad run. A failed run keeps its sandbox and transcripts for `/sdlc:logs` and `claude --resume`. No retries are built in.
- `epic-pr` isn't covered.

## Tasks

| # | Task | Waits for | Model-free check |
|---|---|---|---|
| T1 | `session.py`, `sandbox.new_project`, and a smoke test: `/sdlc:status` on a new project | — | `pytest tests/e2e --collect-only` without `SDLC_E2E` skips everything |
| T2 | `sandbox.dispatched` and `test_fixtures.py` | T1 | `SDLC_E2E=1 pytest tests/e2e/test_fixtures.py` |
| T3 | skills suite: setup, init, hooks, design, split, create-task | T1 | collect-only |
| T4a | skills suite: status, stats, logs, verify | T2 | collect-only |
| T4b | skills suite: review, recover, stop, clean | T2 | collect-only |
| T5 | skills suite: dispatch | T1 | collect-only |
| T6 | flow suite | T1 | collect-only |
| T7 | build suite | T1 | collect-only |
| T8 | delete `tests/wild/`, rewrite the Tests section of `docs/development.md` | T6, T7 | `grep -r tests/wild` finds nothing |

Task verify commands stay model-free, because they run on every merge. Each suite's paid run happens once, after its task merges.
