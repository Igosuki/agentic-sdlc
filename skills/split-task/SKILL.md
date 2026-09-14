---
name: split-task
description: Split an existing bead (task or epic) into child tasks with acceptance criteria, scope, verify command and dependencies. Use when a bead is too large, or was created by hand without a breakdown.
argument-hint: "<bead-id> [instructions]"
model: opus
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/skills/split-plan/scripts/create-task.sh *), Bash(bd *)
---

# Split task

Arguments: $ARGUMENTS

## Reading

Don't read files, documents or external sources yourself. Delegate every read to a subagent, then think over what it returns.
- Pick a reading agent from the available agent types: prefer one made for reading or summarizing large content (for example `bulk-reader`); otherwise use `Explore` with `model: haiku`.
- Tell it exactly what to return: paths, contracts and data shapes verbatim, build and test commands, and anything that conflicts with the request.
- Run independent reads in parallel.

Bead commands (`bd show`, `bd children`) return little and can run directly.

## 1. Read the bead and its context

- **The bead:** run `bd show <id>`. Note its title, description, acceptance, metadata, parent and existing children. If it already has open children, stop and say so.
- **The document that covers it,** looked up in this order:
  1. the bead's spec or `metadata.design`
  2. the parent epic's spec or design
  3. a design document matching its title, in `docs/design/` by default or wherever the repository keeps designs
- **Its siblings:** `bd children <parent-id>`, so you don't duplicate their work.
- **The code and docs** the bead touches.

If the bead is only a title, nothing covers it, or it conflicts with an existing design: split it anyway.
- Make reasonable assumptions, and write them under "Assumptions" in the descriptions of the tasks they affect.
- Name any conflict in those descriptions, for example: contradicts a non-goal of `docs/design/x.md`.
- In the report, mention that `/sdlc:design` could settle it.

## 2. Decompose

Apply the sizing, granularity, shared-interface, scope and task-format rules from the split-plan skill: `${CLAUDE_PLUGIN_ROOT}/skills/split-plan/SKILL.md`, section 2. Read that section if it isn't already in your context.

Create each child, in dependency order:

```bash
${CLAUDE_PLUGIN_ROOT}/skills/split-plan/scripts/create-task.sh --parent <bead-id> \
  --title "<title>" --description "<details>" --acceptance "<checks>" \
  --scope "<path/,other/path>" --verify "<command>" \
  --complexity small|medium|large --domain <domain> \
  [--after <id>]... [--design <doc>]
```

Use `bd` directly for fixes the script doesn't cover.

## 3. Show and confirm

Show `bd list --parent <bead-id> --pretty`.

- **If you can ask the user:** wait for approval and apply any changes they request.
- **If you can't ask:** report the tree and the assumptions you made.
