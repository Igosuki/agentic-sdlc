---
name: split-plan
description: Split a plan into a beads task graph (one or several epics, tasks, subtasks and dependencies, shaped by the agent), each task with acceptance criteria, scope and verify command. The plan can be markdown docs (for example from sdlc:design), a plan made in plan mode earlier in the conversation, or a plain prompt. Use when work needs to become beads tasks.
argument-hint: "[doc paths...] [prompt or instructions]"
model: opus
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/../create-task/scripts/create-task.sh *), Bash(bd *)
---

# Split plan

Arguments: $ARGUMENTS

Beads in this repository: !`bd where >/dev/null 2>&1 && echo "initialized" || echo "not initialized"`

## Mode

- **Plan mode is active:** decompose into the plan file, using labels (T1, T2…) for `--parent` and `--after` in place of ids. Write nothing to beads: no `bd init`, no `create-task.sh`, no step 3.
- **An approved plan in this conversation already holds a task graph:** create it, mapping labels to the ids `create-task.sh` prints, without asking again.
- **Otherwise:** steps 1–3.

## Reading

Don't read files, documents or external sources yourself. Delegate every read to a subagent, then think over what it returns.
- Pick a reading agent from the available agent types: prefer one made for reading or summarizing large content (for example `bulk-reader`); otherwise use `Explore` with `model: haiku`.
- Tell it exactly what to return: paths, contracts and data shapes verbatim, build and test commands, and anything that conflicts with the request.
- Run independent reads in parallel.

## 1. Find what to split

Use the first of these that applies:
1. **Markdown docs named in the arguments.** These can be designs, specs or any `.md` file. Have them read in full, along with the prior art they list for the parts the tasks will touch.
2. **A plan produced in plan mode** earlier in this conversation.
3. **The arguments as a plain prompt.**

If there are no arguments and no plan in the conversation, ask what to split.

Have the reader collect what you need from the repository to name real paths and real verify commands: manifests, build and test setup, directory layout. If the repository has no tooling yet, the first task sets it up, and its verify command proves that it works.

Splitting doesn't implement anything: don't write code, build prototypes or run verify commands to check them.

If beads is not initialized, send the user to `/sdlc:init` and stop.

Bead commands return little and can run directly: `bd search <terms>` and `bd list --type epic` find an epic that already covers the plan (stop and say so) and open tasks the new ones must wait for (`--after <existing-id>`).

## 2. Decompose

Break the plan into a beads task graph. You decide its shape: one epic, several epics, tasks nested under larger tasks. Choose whatever fits the plan.

Follow `references/task-rules.md` for sizing, granularity, review level, shared interfaces, scope and task format. Read it if it isn't already in your context.

Create each bead in dependency order. Use single quotes, and write an apostrophe as `'\''`:

```bash
${CLAUDE_SKILL_DIR}/../create-task/scripts/create-task.sh --title '<title>' --description '<details>' \
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
${CLAUDE_SKILL_DIR}/../create-task/scripts/create-task.sh --parent sdlc-a1b \
  --title 'Implement user authentication' \
  --description 'JWT auth: POST /auth/login, token validation middleware, refresh token rotation. Uses the users table from the schema task.' \
  --acceptance 'Valid credentials return a token; invalid ones return 401; expired tokens are rejected' \
  --scope 'src/auth/,tests/auth/' --verify 'pytest tests/auth -v' \
  --complexity medium --after sdlc-a1b.1 --review agent
```

## 3. Show and confirm

For each epic you created, run `bd swarm validate <epic>`. It reports dependency cycles, tasks nothing leads to, and parts of the graph that aren't connected. Fix what it reports, with `bd` or the script, before going on.

Show the graph you created: `bd list --parent <id> --pretty` for each top-level bead, plus the dependencies from `create-task.sh`'s `created <id> ... after <ids>` lines.

If any `--design` document, or another source you copied facts from, isn't committed on the target branch, say it needs a commit before `/sdlc:dispatch`.

- **If you can ask the user:** use AskUserQuestion. Wait for approval, apply any requested changes with `create-task.sh` or `bd`, and run `bd swarm validate` again.
- **If you can't ask** (headless session): report the tree, plus any part of the plan that no task covers, and why.
