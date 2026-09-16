# Configuration

Settings live in two places, depending on who has to agree on them. `/sdlc:init` creates both with sensible defaults, and changes them when you run it again with options, for example `/sdlc:init --integration epic-merge --parallel 3`.

## Per project, per machine: `.claude/sdlc.local.md`

YAML frontmatter in the main checkout. It is personal, so keep it out of git.

```markdown
---
parallel: 3
workflow: build
---
```

| Key | Default | Meaning |
|---|---|---|
| `parallel` | `2` | workers running at a time on this machine |
| `workflow` | none | `build`: a SessionStart hook tells new sessions in this project to start new work with `/sdlc:build` |

`scripts/settings.sh` prints the effective values. `/sdlc:status` shows them.

## Shared by the repository: beads config

Stored in the beads database, so every machine and person dispatching the repository sees the same values.

```bash
bd config set custom.dispatch.integration epic-merge
bd config set custom.dispatch.target main
bd config set custom.dispatch.review agent
```

| Key | Default | Meaning |
|---|---|---|
| `custom.dispatch.integration` | `direct` | `direct`, `epic-merge` or `epic-pr` (see [workflow](workflow.md#integration-modes)) |
| `custom.dispatch.target` | the main checkout's current branch | branch the work ends up in |
| `custom.dispatch.review` | `none` | `none`, `agent` or `human`: review level for tasks with no `review` metadata of their own (see [workflow](workflow.md#review-levels)) |

An epic can use a different mode: `bd update <epic> --set-metadata dispatch_integration=epic-pr`, set before its first dispatch. A task can use a different review level: `create-task.sh --review agent`, or `bd update <task> --set-metadata review=human`.

An epic can also carry its own `review` metadata (`bd update <epic> --set-metadata review=human`): the integration task's `finish-task.sh` applies it to the epic diff before integrating, the same way a task's review applies to its own diff. It defaults to `none`, not to the task default or `custom.dispatch.review`, so an epic with no `review` metadata skips review.

## Per task: execution hints

```bash
bd update <task> --set-metadata execution_agent_type=react-specialist
bd update <task> --set-metadata execution_suggested_model=opus
bd update <task> --set-metadata execution_reasoning_effort=high
```

Or at creation, with `create-task.sh --agent --model --effort`. Without hints, the worker is a plain Sonnet session, and your own configuration (`CLAUDE.md`, installed agents) decides whether it delegates.

## Project checks: `.config/wt.toml`

The project's own checks run as `wt` pre-merge hooks, so they gate every merge the same way regardless of who or what runs it:

```toml
[pre-merge]
lint = "npm run lint"
typecheck = "npm run typecheck"
test = "npm test"
```

`/sdlc:init` proposes these from `scripts/checks.sh`, which scans the repository (`package.json`, Makefile, justfile, `pyproject.toml`, `Cargo.toml`, `go.mod`) and lists the commands already configured. Adding one by hand: `init.sh --pre-merge lint="npm run lint"` (repeatable; an existing key is kept, not overwritten).

The first time a machine runs one of these commands, `wt` asks for approval; non-interactively (a worker) it fails instead, and `finish-task.sh` reports that a person is needed. A person approves once, in the main checkout:

```bash
wt config approvals add
```

## Hooks

The plugin ships `hooks/hooks.json`. The worker hooks only act in worker sessions, which `start-worker.sh` starts with `DISPATCH_TASK=<task>` and the plugin loaded:

| Hook | In a worker session | Elsewhere |
|---|---|---|
| SessionStart | nothing: the lifecycle is the `sdlc:worker` and `sdlc:integrator` system prompt, which a resume or a compaction keeps | with `workflow: build`, routes new work to `/sdlc:build` |
| PreToolUse (Bash) | denies `bd close`, `bd update --status closed`, `wt merge`, `git <options> push`, `gh pr merge`, `bd gate resolve`/`bd gate close`, and setting `review` or `dispatch_review*` metadata: `finish-task.sh` does those | nothing |
| Stop | blocks the first attempt to end while the task is open and the worker hasn't commented since it was dispatched | nothing |

`worker-guard.sh` is a guardrail, not a security boundary: it matches specific command shapes, so a worker set on evading it can still push, merge or close directly.

## Worker permissions

Workers run with `--permission-mode auto`, Claude Code's classifier for unattended sessions, and never `--dangerously-skip-permissions`. Allowing `finish-task.sh` explicitly is the only extra permission.

Because beads runs on Dolt and is shared, anyone who can write to it can run commands on the machine that dispatches: worker prompts are built from a task's title, description and acceptance (bead text), workers run in `--permission-mode auto`, and `finish-task.sh` runs a task's `verify` metadata through `bash -c`. This is by design — sdlc trusts whoever can write to the project's beads database as much as it trusts the machine it dispatches on.

## Logs

- Worker logs: `.git/sdlc/logs/<task>-<session>.jsonl`, with `.err`, `.record`, `.wt` and `.remove` next to them. They survive worktree removal and reboots.
- Claude transcripts: `~/.claude/projects/<worktree path>/<session>.jsonl`, and subagents under `<session>/subagents/`.
