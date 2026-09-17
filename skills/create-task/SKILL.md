---
name: create-task
description: Create one beads task that sdlc:dispatch can run, with acceptance criteria, scope, a verify command that exercises the behaviour and complexity, and optionally its epic, the tasks it waits for, and an agent, model or effort hint. Use when the user wants to add a single task rather than split a plan.
argument-hint: "<what the task should do> [--parent <epic>] [--after <id>]"
model: sonnet
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/create-task.sh *), Bash(bd *), Read(/${CLAUDE_PLUGIN_ROOT}/skills/split/references/**)
---

# Create task

Request: $ARGUMENTS

## 1. Gather context

Gather information with the skills, agents and MCP tools this session has. Users install the ones that fit their projects, such as code search, code graphs, documentation lookups or bulk readers. Find them in your context, and through tool search for deferred tools. Use what fits each source; where nothing does, read and search the repository yourself. Collect:
- the files and interfaces the task touches
- how the project is built and tested, so the verify command is real
- the design document that covers the task, if there is one

Bead commands return little and can run directly:
- `bd search <terms>` finds a task that already covers the request. If one does, say so and stop.
- `bd list --type epic` finds the epic the task belongs to, when the arguments don't name one.
- `bd list --status open,in_progress --limit 0 --json` finds the tasks it must wait for: compare its `--scope` against each task's `metadata.scope`, and add `--after <id>` for any overlap, plus any task whose work this one depends on.

## 2. Fill in the task

Follow `${CLAUDE_PLUGIN_ROOT}/skills/split/references/task-rules.md` for sizing, scope, review level and task format. Read it if it isn't already in your context.
- **Verify:** one short command that exits 0 when the acceptance is met. It must exercise the behaviour, so a syntax check alone doesn't count.
- **Scope:** the path prefixes the task changes.
- **Review:** choose `--review` with the same rules as `task-rules.md`: `agent` by default; `human` only when an agent's approval isn't enough (legal or compliance text, a destructive data migration, or a request that asks for a person's sign-off); `none` for small documentation, configuration or test-only tasks.
- **Large requests:** if `task-rules.md`'s size thresholds make this large, create nothing here. Hand off to `/sdlc:split "<request>"` instead.

Ask with AskUserQuestion only what you can't infer, such as which epic the task belongs to. If AskUserQuestion isn't available (headless session), choose the most reasonable option and write it under "Assumptions" in the description.

## 3. Create

Run the script with the path exactly as written. Use single quotes, and write an apostrophe as `'\''`:

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/create-task.sh --title '<title>' --description '<details>' \
  --acceptance '<checks>' --scope '<path/,other/path>' --verify '<command>' \
  --complexity small|medium|large \
  [--parent <epic>] [--after <id>]... [--design <doc>] [--priority 0-4] \
  [--agent <agent>] [--model <model>] [--effort <level>] [--review none|agent|human]
```

Exit 2 lists every problem with the arguments: fix them and rerun. Exit 1 after a message containing `created <id>` means the bead exists already — don't rerun the command; fix what it reports by hand with `bd`.

Show `bd show <id>`. Then say whether the task is ready for `/sdlc:dispatch` or what it waits for.
