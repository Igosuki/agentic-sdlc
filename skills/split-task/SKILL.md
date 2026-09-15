---
name: split-task
description: Split an existing bead (task or epic) into child tasks with acceptance criteria, scope, verify command and dependencies. Use when a bead is too large, or was created by hand without a breakdown.
argument-hint: "<bead-id> [instructions]"
model: opus
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/../create-task/scripts/create-task.sh *), Bash(bd *), Bash(wt remove *)
---

# Split task

Arguments: $ARGUMENTS

## Reading

Don't read files, documents or external sources yourself. Delegate every read to a subagent, then think over what it returns.
- Pick a reading agent from the available agent types: prefer one made for reading or summarizing large content (for example `bulk-reader`); otherwise use `Explore` with `model: haiku`.
- Tell it exactly what to return: paths, contracts and data shapes verbatim, build and test commands, and anything that conflicts with the request.
- Run independent reads in parallel.

The one exception is `references/task-rules.md` (used in step 2): read it yourself. A reader's summary would reword its rules.

Bead commands (`bd show`, `bd list`, `bd comments`) return little and can run directly.

## 1. Read the bead and its context

- **The bead:** run `bd show <id>`. Note its title, description, acceptance, metadata, parent and existing children. If it already has children that aren't closed, stop and say so. If the bead itself is closed, stop.
- **Stopped or failed task:** if `metadata.dispatch_state` is `stopped` or `failed`, the task was dispatched and its worker gave up without finishing.
  - Read its last comment yourself: `bd comments <id>`.
  - Have the reader summarize the commits in its worktree: find the path with `wt list --format json`, matching `.branch` to `metadata.dispatch_branch`, then summarize `git log <metadata.dispatch_base>..<metadata.dispatch_branch>` run in that worktree.
  - Use both to understand why it stopped and what's already done before you decompose the rest.
- **The document that covers it,** looked up in this order:
  1. the bead's spec or `metadata.design`
  2. the parent epic's spec or design
  3. a design document matching its title, in `docs/design/` by default or wherever the repository keeps designs
- **Its siblings:** `bd list --parent <parent-id> --json`, for their `metadata.scope`, so you don't duplicate their work or give a child a path a sibling already owns.
- **The code and docs** the bead touches.

If the bead is only a title, nothing covers it, or it conflicts with an existing design: split it anyway.
- Make reasonable assumptions, and write them under "Assumptions" in the descriptions of the tasks they affect.
- Name any conflict in those descriptions, for example: contradicts a non-goal of `docs/design/x.md`.
- In the report, mention that `/sdlc:design` could settle it.

## 2. Decompose

Follow `${CLAUDE_SKILL_DIR}/../split-plan/references/task-rules.md` for sizing, granularity, shared interfaces, scope, review level and task format. Read it yourself, directly, if it isn't already in your context.

Create each child, in dependency order:

```bash
${CLAUDE_SKILL_DIR}/../create-task/scripts/create-task.sh --parent <bead-id> \
  --title '<title>' --description '<details>' --acceptance '<checks>' \
  --scope '<path/,other/path>' --verify '<command>' \
  --complexity small|medium|large \
  [--after <id>]... [--design <doc>] [--review none|agent|human]
```

Place every acceptance check of the parent bead into some child's `--acceptance`. Note in step 3 any check that doesn't land anywhere.

Use `bd` directly for fixes the script doesn't cover.

## 3. Show and confirm

Find the epic to validate: the bead itself if its `issue_type` is `epic`, otherwise the nearest epic above it — walk up through `.parent` with `bd show` until you reach a bead whose `issue_type` is `epic`, or run out of parents. `bd swarm validate` only accepts an epic (it exits 1 with "is not an epic or molecule" on anything else); if you found one, run `bd swarm validate <epic-id>` and fix what it reports; otherwise skip validation.

Show `bd list --parent <bead-id> --pretty`. Report any acceptance check of the parent that didn't land in a child.

If the bead was stopped or failed (step 1), offer the reset: `wt remove -D <branch>`, then reopen it with every `dispatch_*` metadata key removed:

```bash
bd show <id> --json | jq -r '.[0].metadata | keys[] | select(startswith("dispatch_"))'
bd update <id> --status open --unset-metadata <key> [--unset-metadata <key>]...
```

Ask first with AskUserQuestion. In a headless session, don't reset anything — just report that the reset is available.

- **If you can ask the user:** wait for approval and apply any changes they request.
- **If you can't ask:** report the tree and the assumptions you made.
