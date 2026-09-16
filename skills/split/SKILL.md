---
name: split
description: Split work into a beads task graph, with acceptance criteria, scope and a verify command on each task. Takes design docs, a design or plan stated earlier in the conversation (for example by sdlc:design or plan mode), a plain prompt, or an existing bead (task or epic) that is too large or was created without a breakdown. Use whenever work needs to become, or be broken further into, beads tasks.
argument-hint: "[doc paths... | bead-id] [prompt or instructions]"
model: opus
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/create-task.sh *), Bash(bd *), Bash(wt remove *), Read(/${CLAUDE_SKILL_DIR}/references/**)
---

# Split

Arguments: $ARGUMENTS

Split creates beads. If plan mode is active, stop and say that split needs plan mode off.

## Reading

Don't read files, documents or external sources yourself. Give each read to the `sdlc:reader` agent (Agent tool, `subagent_type: sdlc:reader`). Tell it exactly what to return — paths, contracts and data shapes verbatim, build and test commands, and anything that conflicts with the request — and run independent reads in parallel. Then think over what it returns.

The one exception is `references/task-rules.md` (used in step 3): read it yourself. A reader's summary would reword its rules.

Bead commands (`bd show`, `bd list`, `bd search`, `bd comments`) return little and can run directly.

## 1. What to split

Splitting doesn't implement anything: don't write code, build prototypes or run verify commands to check them.

Split the first of these that applies. The rest of the arguments are instructions for the split.
1. **A bead id.** Run `bd show <id> --json`. If the bead is closed, or has children that aren't closed, stop and say so.
2. **Markdown docs:** designs, specs or any `.md` file.
3. **A design or plan earlier in this conversation**, from `sdlc:design` or plan mode.
4. **The arguments as a plain prompt.**

If none applies, ask what to split.

## 2. Gather

Whatever the source, have the reader collect:
- **Tooling:** manifests, build and test setup, directory layout, so tasks name real paths and real verify commands. If the repository has no tooling yet, the first task sets it up, and its verify command proves that it works.
- **The code and docs** the work touches.

Then, by source:
- **Docs:** read them in full, along with the prior art they list for the parts the tasks will touch.
- **A bead:** the document that covers it, looked up in this order: the bead's `metadata.design` or spec; its parent's; a design document matching its title, in `docs/design/` or wherever the repository keeps designs.
- **A bead that was stopped or failed** (`metadata.dispatch_state` is `stopped` or `failed`): its worker gave up. Read its last comment with `bd comments <id>`. Have the reader summarize `git log <metadata.dispatch_base>..<metadata.dispatch_branch>`, run in the worktree whose `.branch` in `wt list --format json` is `metadata.dispatch_branch`.

Existing work:
- **Already covered:** unless the source is a bead, `bd search <terms>` and `bd list --type epic` find an epic or task that already covers this work. If one does, stop and say so.
- **Open tasks:** `bd list --status open,in_progress --limit 0 --json`. The new tasks wait for the ones whose work they depend on or whose `metadata.scope` overlaps theirs. When splitting a bead, leave the bead itself out: its children already wait for whatever it waits for.

## 3. Decompose

Follow `references/task-rules.md` for graph shape, sizing, granularity, review level, shared interfaces, scope and task format. Read it if it isn't already in your context.

**Shape:**
- **New work:** you decide: one epic, several epics, tasks nested under larger tasks.
- **A bead:** children only, each with `--parent <bead-id>` or under another child, never `--type epic`. Each child carries the bead's `metadata.design` as `--design`, a `--review` at least as strict as the bead's `metadata.review` (none, then agent, then human), and the bead's agent, model and effort hints unless a child clearly needs others. Every acceptance check of the bead lands in some child's `--acceptance`.

**Coverage:** every requirement of the source lands in some task. Keep a note of anything that doesn't, and why, for step 4.

**Thin or conflicting source:** a bare title, a short prompt, a bead nothing covers, or a source that conflicts with an existing design. Split it anyway:
- Make reasonable assumptions, and write them under "Assumptions" in the descriptions of the tasks they affect.
- Name any conflict in those descriptions, for example: contradicts a non-goal of `docs/design/x.md`.

**Stopped or failed bead:** resetting it deletes its branch, so the children redo that work. Write what was tried and why it stopped into the descriptions of the children it concerns.

**Uncommitted sources:** a document that isn't committed on the target branch, or a design or plan stated in this conversation, is invisible to workers, who branch from committed code. Copy the facts each task needs into its description, the same way you copy facts from prior art that lives outside the repository.

Create each bead in dependency order, running the script with the path exactly as written. Use single quotes, and write an apostrophe as `'\''`:

```bash
${CLAUDE_PLUGIN_ROOT}/scripts/create-task.sh --title '<title>' --description '<details>' \
  --acceptance '<checks>' --scope '<path/,other/path>' --verify '<command>' \
  --complexity small|medium|large \
  [--type epic] [--parent <id>] [--after <id>]... [--design <doc>] \
  [--agent <agent>] [--model <model>] [--effort <level>] [--review none|agent|human]
```

Set `--agent`, `--model` or `--effort` only when a task clearly needs a particular installed agent, model or effort. Otherwise the worker and the user's configuration decide.

Set `--design` only when a committed document on the target branch covers the task. A design or plan stated only in this conversation isn't a `--design` document: copy its facts into the description instead (see Uncommitted sources above).

Use `bd` directly for anything the script doesn't cover. Review the boundaries, and decompose further where needed.

Example:
```bash
${CLAUDE_PLUGIN_ROOT}/scripts/create-task.sh --parent sdlc-a1b \
  --title 'Implement user authentication' \
  --description 'JWT auth: POST /auth/login, token validation middleware, refresh token rotation. Uses the users table from the schema task.' \
  --acceptance 'Valid credentials return a token; invalid ones return 401; expired tokens are rejected' \
  --scope 'src/auth/,tests/auth/' --verify 'pytest tests/auth -v' \
  --complexity medium --after sdlc-a1b.1 --review agent
```

## 4. Validate and confirm

`bd swarm validate <epic-id>` reports dependency cycles, tasks nothing leads to, and parts of the graph that aren't connected. It only accepts an epic: on anything else it exits 1 with "is not an epic or molecule". Validate:
- **New work:** each epic you created.
- **A bead:** the bead if its `issue_type` is `epic`, otherwise the nearest epic above it. Walk up `.parent` with `bd show` until a bead's `issue_type` is `epic`, or parents run out.

Fix what it reports about beads you created, with the script or `bd`. Report anything else it finds without changing it. If there's no epic to validate, say validation was skipped.

Show the graph: `bd list --parent <id> --pretty` for each top-level bead you created, or for the bead you split, plus the dependencies from `create-task.sh`'s `created <id> ... after <ids>` lines. Then report:
- any requirement or acceptance check that no task covers, and why
- the assumptions and conflicts you wrote down, and that `/sdlc:design` could settle them
- any source you copied facts from instead of setting `--design`, because it isn't committed on the target branch: it needs a commit before `/sdlc:dispatch`

**If you can ask the user:** ask for approval with AskUserQuestion. Apply any requested changes with `create-task.sh` or `bd`, and validate again. Once the graph is approved, if the bead you split was stopped or failed, ask whether to reset it:
1. `wt remove -D <metadata.dispatch_branch>`
2. `bd update <id> --status open`, with `--unset-metadata <key>` for each `dispatch_*` key in its metadata

**If you can't ask** (headless session): report only. Don't reset anything; say the reset is available.
