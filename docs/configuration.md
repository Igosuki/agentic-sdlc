# Configuration

Settings live in two places, depending on who has to agree on them. `/sdlc:init` creates both with sensible defaults, and changes them when you run it again with options, for example `/sdlc:init --integration epic-merge --parallel 3`.

## Per project, per machine: `.claude/sdlc.local.md`

YAML frontmatter in the main checkout. It is personal, so keep it out of git.

```markdown
---
parallel: 3
design_dir: docs/specs
workflow: build
---
```

| Key | Default | Meaning |
|---|---|---|
| `parallel` | `2` | workers running at a time on this machine |
| `design_dir` | none | where `/sdlc:design` writes documents. Without it: the location the request names, the repository's convention, then `docs/design` |
| `workflow` | none | `build`: a SessionStart hook tells new sessions in this project to start new work with `/sdlc:build` |

`skills/dispatch/scripts/settings.sh` prints the effective values. `/sdlc:status` shows them.

## Shared by the repository: beads config

Stored in the beads database, so every machine and person dispatching the repository sees the same values.

```bash
bd config set custom.dispatch.integration epic-merge
bd config set custom.dispatch.target main
```

| Key | Default | Meaning |
|---|---|---|
| `custom.dispatch.integration` | `direct` | `direct`, `epic-merge` or `epic-pr` (see [workflow](workflow.md#integration-modes)) |
| `custom.dispatch.target` | `main` | branch the work ends up in |

An epic can use a different mode: `bd update <epic> --set-metadata dispatch_integration=epic-pr`, set before its first dispatch.

## Per task: execution hints

```bash
bd update <task> --set-metadata execution_agent_type=react-specialist
bd update <task> --set-metadata execution_suggested_model=opus
bd update <task> --set-metadata execution_reasoning_effort=high
```

Or at creation, with `create-task.sh --agent --model --effort`. Without hints, the worker is a plain Sonnet session, and your own configuration (`CLAUDE.md`, installed agents) decides whether it delegates.

## Hooks

The plugin ships `hooks/hooks.json`. The worker hooks only act in worker sessions, which `run-task.sh` and `resume-task.sh` start with `DISPATCH_TASK=<task>` and the plugin loaded:

| Hook | In a worker session | Elsewhere |
|---|---|---|
| SessionStart | restates the task's lifecycle, after a resume or a compaction too | with `workflow: build`, routes new work to `/sdlc:build` |
| PreToolUse (Bash) | denies `bd close`, `bd update --status closed`, `wt merge` and `git push`: `finish-task.sh` does those | nothing |
| Stop | blocks the first attempt to end while the task is open and the worker hasn't commented since it was dispatched | nothing |

## Worker permissions

Workers run with `--permission-mode auto`, which is Claude Code's classifier for unattended sessions. They never use `--dangerously-skip-permissions`. Allowing `finish-task.sh` explicitly is the only extra permission.

## Logs

- Worker logs: `.git/sdlc/logs/<task>-<session>.jsonl`, with `.err`, `.record`, `.wt` and `.remove` next to them. They survive worktree removal and reboots.
- Claude transcripts: `~/.claude/projects/<worktree path>/<session>.jsonl`, and subagents under `<session>/subagents/`.
