# Development

## Layout

```text
.claude-plugin/        plugin.json, marketplace.json
hooks/                 hooks.json and the worker hooks
skills/
  setup/               machine check and recommended companions
  init/                project preparation
  build/               design + split in plan mode, then dispatch
  design/              design documents
  split-plan/          task graphs
  split-task/          splitting one bead
  create-task/         one task; scripts/create-task.sh is used by all three planning skills
  dispatch/            supervisor; scripts/ holds the worker lifecycle
  status/ stats/ logs/ read-only views
tests/wild/            end-to-end runs in a sandbox
docs/                  this documentation
```

## Conventions

- **One skill at a time, scripts only when a skill needs them.** Scripts live in `skills/<skill>/scripts/`.
- **Bash for command-line work, `jq` for JSON.** Python only once the logic gets complex.
- **Scripts explain themselves:** `--help` prints the usage, and invalid input lists every problem, prints the usage and exits 2. Skills don't document the scripts they call.
- **Skills call scripts** through `${CLAUDE_SKILL_DIR}` or `${CLAUDE_PLUGIN_ROOT}`, pre-approved in `allowed-tools`, so the script's source never enters the context.
- **Headless-aware skills:** ask with AskUserQuestion when it is available. Otherwise decide, and record the assumption. Never ask in plain text and stop.
- **Planning skills use `model: opus`** and delegate every read to a cheap reading agent. The supervisor and workers run on Sonnet.
- **Nothing named "sdlc"** in bead statuses or labels. Runtime keys are prefixed `dispatch_`.

## Tests

Every test runs in a sandbox outside this repository, `~/dev/sdlc-sandbox` by default (`SDLC_SANDBOX`). Workers run on Sonnet (`SDLC_MODEL`).

```bash
tests/wild/run.sh          # design and split on a new repository, then split-task on a hand-made epic
tests/wild/dispatch.sh     # the whole flow on a new project, until no work is left
SDLC_INTEGRATION=direct tests/wild/dispatch.sh "create a todo list web app"
```

Both write per-step transcripts and a `summary.md` with costs. The output isn't deterministic: the point is to watch the plugin work on a real sequence.

To try the plugin by hand, start a session in a sandbox project with `claude --plugin-dir /path/to/claude-sdlc`.
