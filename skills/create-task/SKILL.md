---
name: create-task
description: Create one beads task that sdlc:dispatch can run, with acceptance criteria, scope, a verify command that exercises the behaviour, complexity and domain, and optionally its epic, the tasks it waits for, and an agent, model or effort hint. Use when the user wants to add a single task rather than split a plan.
argument-hint: "<what the task should do> [--parent <epic>] [--after <id>]"
model: sonnet
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/create-task.sh *), Bash(bd *)
---

# Create task

Request: $ARGUMENTS

## 1. Gather context

Have a reading agent collect what the task needs, rather than reading files yourself: prefer one made for reading (for example `bulk-reader`), otherwise `Explore` with `model: haiku`. Ask it for:
- the files and interfaces the task touches
- how the project is built and tested, so the verify command is real
- the design document that covers the task, if there is one

Bead commands return little and can run directly:
- `bd search <terms>` finds a task that already covers the request. If one does, say so and stop.
- `bd list --type epic` finds the epic the task belongs to, when the arguments don't name one.
- The same search finds the tasks it must wait for.

## 2. Fill in the task

Follow the task format and verify rules of the split-plan skill, `${CLAUDE_SKILL_DIR}/../split-plan/SKILL.md`, section 2. Read that section if it isn't already in your context.
- **Verify:** one short command that exits 0 when the acceptance is met. It must exercise the behaviour, so a syntax check alone doesn't count.
- **Scope:** the path prefixes the task changes.
- **Large tasks:** if the task is large, create it anyway, then suggest `/sdlc:split-task <id>`.

Ask with AskUserQuestion only what you can't infer, such as which epic the task belongs to. If AskUserQuestion isn't available (headless session), choose the most reasonable option and write it under "Assumptions" in the description.

## 3. Create

```bash
${CLAUDE_SKILL_DIR}/scripts/create-task.sh --title "<title>" --description "<details>" \
  --acceptance "<checks>" --scope "<path/,other/path>" --verify "<command>" \
  --complexity small|medium|large --domain <domain> \
  [--parent <epic>] [--after <id>]... [--design <doc>] [--agent <agent>] [--model <model>] [--effort <level>]
```

Show `bd show <id>`. Then say whether the task is ready for `/sdlc:dispatch` or what it waits for.
