# Development

## Layout

```text
.claude-plugin/        plugin.json, marketplace.json
agents/                 worker.md (owns one task), integrator.md (owns an epic's
                        integration task)
hooks/                 hooks.json and the worker hooks
scripts/               every executable: supervision (supervise.py), worker lifecycle,
                        task creation, project checks
skills/
  design/              design documents
  split/               task graphs, from a doc, a plan, a prompt or an existing bead
  build/, dispatch/, create-task/,
  setup/, init/, hooks/, status/, stats/, logs/
                        entry points, one SKILL.md each
tests/e2e/             end-to-end suites, driven through real Claude sessions
docs/                  this documentation
```

## Conventions

- **One skill at a time, scripts only when a skill needs them.** Scripts live in `scripts/` at the plugin root; skills, hooks and workers call them as `${CLAUDE_PLUGIN_ROOT}/scripts/<name>`.
- **Bash + `jq`** for a script that runs commands and reads a few fields from JSON. **Python 3.9+, standard library only,** for a script that walks the task graph, sorts, totals, keeps state across rounds or renders logs. Shared task-graph logic lives in `scripts/tasks.py`, reached the way `status` and `logs` already call dispatch's scripts. Bead data is never passed as a command-line argument: Linux caps a single argument at 128 KiB, so scripts read `bd`'s JSON through a pipe instead.
- **Scripts explain themselves:** `--help` prints the usage, and invalid input lists every problem, prints the usage and exits 2. Skills don't document the scripts they call.
- **Skills call scripts** through `${CLAUDE_PLUGIN_ROOT}`, pre-approved in `allowed-tools`, so the script's source never enters the context.
- **Headless-aware skills:** ask with AskUserQuestion when it is available. Otherwise decide, and record the assumption. Never ask in plain text and stop.
- **Planning skills use `model: opus`** and gather information with the skills, agents and MCP tools the user installed. Workers run on Sonnet; the supervisor is a script, with no model.
- **Nothing named "sdlc"** in bead statuses or labels. Runtime keys are prefixed `dispatch_`.

## Tests

Unit tests run against real `bd`, git and `wt`, with no model:

```bash
python3 -m pytest tests
```

Every e2e module is skipped unless `SDLC_E2E=1`, so this command never calls a model.

Three end-to-end suites drive real Claude sessions against the plugin, under `tests/e2e/`:
- **build** (`tests/e2e/test_build.py`): `/sdlc:build` from request to merged code, interactive and headless.
- **skills** (`tests/e2e/skills/`): every skill alone, each on its own prepared project.
- **flow** (`tests/e2e/test_flow.py`): every skill one after another on one project, without `/sdlc:build`.

```bash
SDLC_E2E=1 python3 -m pytest tests/e2e/test_fixtures.py                    # prepared states, no model
SDLC_E2E=1 python3 -m pytest tests/e2e/skills -v                           # every skill alone
SDLC_E2E=1 python3 -m pytest tests/e2e/skills/test_skill_clean.py         # one skill
SDLC_E2E=1 python3 -m pytest tests/e2e/test_flow.py -v                     # skills one by one
SDLC_E2E=1 python3 -m pytest tests/e2e/test_build.py -v                    # /sdlc:build
```

A session is driven through `claude -p` with stream-json input and output: it answers AskUserQuestion and approves plans, so a skill's interactive branch is tested. `interactive=False` leaves out the permission-prompt tool, so the skill takes its headless branch instead.

Sandboxes are created under `SDLC_SANDBOX` and kept after the run. Each session's transcript lands at `<sandbox>/logs/<name>.jsonl`, and its cost and turns are appended to `<sandbox>/logs/summary.md`.

Environment variables:
- `SDLC_E2E`: set to `1` to run the e2e suites; unset skips them.
- `SDLC_SANDBOX`: where sandboxes are created, `~/dev/sdlc-sandbox` by default.
- `SDLC_MODEL`: the model sessions run on, `sonnet` by default.
- `SDLC_INTEGRATION`: the integration mode build and flow use, `epic-merge` by default.
- `SDLC_E2E_REQUEST`: the request build and flow send, "create a command-line todo list in Python with add, list and done commands, stored in a JSON file" by default.
- `SDLC_E2E_TIMEOUT`: seconds before a run gives up waiting, 3600 (60 minutes) by default.

To try the plugin by hand, start a session in a sandbox project with `claude --plugin-dir /path/to/claude-sdlc`.


## Iterating on the plugin

I advise testing plugin changes on a completely separate empty test repository.
Once the repo is created and you have used some skills (setup, init, build or design) and you would like to test plugin changes, ideally you should fork both the repository and the claude chat.

First, create a new worktree : 
```sh
   git worktree add .claude/worktrees/plugin-test-1 -b plugin-test-1
```

Then, resume the claude session :
```sh
   claude --resume <session-id> --fork-session --plugin-dir <path-to-sdlc-plugin-dir> "Enter the worktree plugin-test-1 at .claude/worktrees/plugin-test-1"
```
