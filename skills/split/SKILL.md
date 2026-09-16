---
name: split
description: Split work into a beads task graph — new epics, tasks, subtasks and dependencies, shaped by the agent, or children of an existing bead — each with acceptance criteria, scope and a verify command. The input can be markdown docs (for example from sdlc:design), a plan made in plan mode earlier in the conversation, a plain prompt, or an existing bead id (task or epic) that is too large or was created by hand without a breakdown. Use whenever work needs to become, or be broken further into, beads tasks.
argument-hint: "[doc paths... | bead-id] [prompt or instructions]"
model: opus
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/create-task.sh *), Bash(bd *), Bash(wt remove *), Read(/${CLAUDE_SKILL_DIR}/references/**)
---

# Split

Arguments: $ARGUMENTS

Beads in this repository: !`bd where >/dev/null 2>&1 && echo "initialized" || echo "not initialized"`

## Mode

- **Plan mode is active:** decompose into the plan file, using labels (T1, T2…) for `--parent` and `--after` in place of ids. Write nothing to beads: no `bd init`, no `create-task.sh`, no step 3.
- **An approved plan in this conversation already holds a task graph:** create it, mapping labels to the ids `create-task.sh` prints, without asking again.
- **The arguments name an existing bead id:** follow "Split an existing bead" below in place of step 1.
- **Otherwise:** steps 1–3.

## Reading

Don't read files, documents or external sources yourself. Delegate every read to a subagent, then think over what it returns.
- Pick a reading agent from the available agent types: prefer one made for reading or summarizing large content (for example `bulk-reader`); otherwise use `Explore` with `model: haiku`.
- Tell it exactly what to return: paths, contracts and data shapes verbatim, build and test commands, and anything that conflicts with the request.
- Run independent reads in parallel.

The one exception is `references/task-rules.md` (used in Decompose below): read it yourself. A reader's summary would reword its rules.

Bead commands (`bd show`, `bd list`, `bd children`, `bd comments`) return little and can run directly.

## 1. Find what to split

Use the first of these that applies:
1. **Markdown docs named in the arguments.** These can be designs, specs or any `.md` file. Have them read in full, along with the prior art they list for the parts the tasks will touch.
2. **A plan produced in plan mode** earlier in this conversation.
3. **The arguments as a plain prompt.**

If there are no arguments and no plan in the conversation, ask what to split.

Have the reader collect what you need from the repository to name real paths and real verify commands: manifests, build and test setup, directory layout. If the repository has no tooling yet, the first task sets it up, and its verify command proves that it works.

Splitting doesn't implement anything: don't write code, build prototypes or run verify commands to check them.

If beads is not initialized, send the user to `/sdlc:init` and stop.

`bd search <terms>` and `bd list --type epic` find an epic that already covers the plan (stop and say so) and open tasks the new ones must wait for (`--after <existing-id>`).

## Split an existing bead

Used when the arguments name an existing bead id, instead of step 1 above.

- **The bead:** run `bd show <id>`. Note its title, description, acceptance, metadata, parent and existing children. If it already has children that aren't closed, stop and say so. If the bead itself is closed, stop.
- **Stopped or failed task:** if `metadata.dispatch_state` is `stopped` or `failed`, the task was dispatched and its worker gave up without finishing.
  - Read its last comment yourself: `bd comments <id>`.
  - Have the reader summarize the commits in its worktree: find the path with `wt list --format json`, matching `.branch` to `metadata.dispatch_branch`, then summarize `git log <metadata.dispatch_base>..<metadata.dispatch_branch>` run in that worktree.
  - Use both to understand why it stopped and what's already done before you decompose the rest.
- **The document that covers it,** looked up in this order:
  1. the bead's spec or `metadata.design`
  2. the parent epic's spec or design
  3. a design document matching its title, in `docs/design/` by default or wherever the repository keeps designs
- **Its siblings:** `bd children <parent-id> --json`, for their `metadata.scope`, so you don't duplicate their work or give a child a path a sibling already owns.
- **The code and docs** the bead touches.

If the bead is only a title, nothing covers it, or it conflicts with an existing design: split it anyway.
- Make reasonable assumptions, and write them under "Assumptions" in the descriptions of the tasks they affect.
- Name any conflict in those descriptions, for example: contradicts a non-goal of `docs/design/x.md`.
- In the report, mention that `/sdlc:design` could settle it.

Create each child with `--parent <bead-id>`, following Decompose below. Place every acceptance check of the parent bead into some child's `--acceptance`. Note in Show and confirm any check that doesn't land anywhere.

## 2. Decompose

Break the plan into a beads task graph. You decide its shape: one epic, several epics, tasks nested under larger tasks — or, when splitting an existing bead, its children. Choose whatever fits.

Follow `references/task-rules.md` for sizing, granularity, review level, shared interfaces, scope and task format. Read it if it isn't already in your context.

Create each bead in dependency order, running the script with the path exactly as written. Use single quotes, and write an apostrophe as `'\''`:

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/create-task.sh --title '<title>' --description '<details>' \
  --acceptance '<checks>' --scope '<path/,other/path>' --verify '<command>' \
  --complexity small|medium|large \
  [--type epic] [--parent <id>] [--after <id>]... [--design <doc>] \
  [--agent <agent>] [--model <model>] [--effort <level>] [--review none|agent|human]
```

Set `--agent`, `--model` or `--effort` only when a task clearly needs a particular installed agent, model or effort. Otherwise the worker and the user's configuration decide.

Use `bd` directly for anything the script doesn't cover. Review the boundaries, and decompose further where needed.

A source that isn't committed on the target branch — a document named in the arguments that hasn't been committed, or a plan-mode plan — is invisible to workers, who branch from committed code. Copy the facts each task needs into its description, the same way you copy facts from prior art that lives outside the repository.

Example:
```bash
${CLAUDE_PLUGIN_ROOT}/scripts/create-task.sh --parent sdlc-a1b \
  --title 'Implement user authentication' \
  --description 'JWT auth: POST /auth/login, token validation middleware, refresh token rotation. Uses the users table from the schema task.' \
  --acceptance 'Valid credentials return a token; invalid ones return 401; expired tokens are rejected' \
  --scope 'src/auth/,tests/auth/' --verify 'pytest tests/auth -v' \
  --complexity medium --after sdlc-a1b.1 --review agent
```

## 3. Show and confirm

Find the epic or epics to validate:
- **New task graph:** each epic you created.
- **Existing bead:** the bead itself if its `issue_type` is `epic`, otherwise the nearest epic above it — walk up through `.parent` with `bd show` until you reach a bead whose `issue_type` is `epic`, or run out of parents.

`bd swarm validate` only accepts an epic (it exits 1 with "is not an epic or molecule" on anything else). Run `bd swarm validate <epic-id>` for each epic found and fix what it reports, with `bd` or the script; skip validation if an existing bead has no epic above it.

Show the graph you created: `bd list --parent <id> --pretty` for each top-level bead, plus the dependencies from `create-task.sh`'s `created <id> ... after <ids>` lines.

If any `--design` document, or another source you copied facts from, isn't committed on the target branch, say it needs a commit before `/sdlc:dispatch`.

If the bead you split was stopped or failed, offer the reset once the tree above is shown: `wt remove -D <branch>`, then reopen it with every `dispatch_*` metadata key removed:

```bash
bd show <id> --json | jq -r '.[0].metadata | keys[] | select(startswith("dispatch_"))'
bd update <id> --status open --unset-metadata <key> [--unset-metadata <key>]...
```

Ask first with AskUserQuestion. In a headless session, don't reset anything — just report that the reset is available.

- **If you can ask the user:** use AskUserQuestion. Wait for approval, apply any requested changes with `create-task.sh` or `bd`, and run `bd swarm validate` again.
- **If you can't ask** (headless session): report the tree, plus any part of the plan that no task covers, and why.
