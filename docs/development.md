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
tests/wild/            end-to-end runs in a sandbox
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

Every test runs in a sandbox outside this repository, `~/dev/sdlc-sandbox` by default (`SDLC_SANDBOX`). Workers run on Sonnet (`SDLC_MODEL`).

```bash
tests/wild/run.sh          # design and split on a new repository, then split on a hand-made epic
tests/wild/dispatch.sh     # the whole flow on a new project, until no work is left
SDLC_INTEGRATION=direct tests/wild/dispatch.sh "create a todo list web app"
```

Both write per-step transcripts and a `summary.md` with costs. The output isn't deterministic: the point is to watch the plugin work on a real sequence.

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
