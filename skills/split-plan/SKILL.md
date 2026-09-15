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

If beads is not initialized, run `bd init --non-interactive --skip-agents --skip-hooks` and say so.

## 2. Decompose

Break the plan into a beads task graph. You decide its shape: one epic, several epics, tasks nested under larger tasks. Choose whatever fits the plan.

Create each bead in dependency order:

```bash
${CLAUDE_SKILL_DIR}/../create-task/scripts/create-task.sh --title "<title>" --description "<details>" \
  --acceptance "<checks>" --scope "<path/,other/path>" --verify "<command>" \
  --complexity small|medium|large --domain <domain> \
  [--type epic] [--parent <id>] [--after <id>]... [--design <doc>] \
  [--agent <agent>] [--model <model>] [--effort <level>]
```

Set `--agent`, `--model` or `--effort` only when a task clearly needs a particular installed agent, model or effort. Otherwise the worker and the user's configuration decide.

Use `bd` directly for anything the script doesn't cover. Review the boundaries, and decompose further where needed.

### Task sizing

Estimate each task's complexity:
- **small:** under 50 lines, 1–2 files
- **medium:** under 200 lines, some design decisions
- **large:** over 200 lines, or architectural. Decompose it into subtasks.

A large task becomes a parent with small or medium children: create the children with `--parent <large-task-id>`.

### Task granularity

Create subtasks when:
- clear interface boundaries exist (for example "define schema" and "implement parser")
- parts could genuinely be worked on in parallel
- different expertise or concerns are involved (for example backend and frontend)
- separate verification steps are required
- >2 people/agents could meaningfully work on different parts simultaneously

Keep work together when:
- it is tightly coupled, so changing one part requires changing another
- it shares state or context (parsing and validating the same structure)
- it has a single verification point

### Shared interfaces

If a task defines interfaces that other tasks consume (types, schemas, API contracts, file formats), make it a separate task and make the consumers wait for it with `--after`. Otherwise they build against nothing.

### Scope

`--scope` lists the path prefixes a task may change. Two tasks that don't wait for each other must not share a path: either add `--after` or merge the tasks.

### Task format

The fields are split like this:
- **Description:** what to do, the interfaces the task depends on from other tasks, and the design sections or prior-art files that matter. Implementation guidance belongs here.
- **Acceptance:** observable checks.
- **Verify:** one short command that exits 0 when the acceptance is met, usually the test the task itself adds, for example `node --test test/auth.test.js` or `pytest tests/auth -v`. No inline scripts.
  - It must exercise the behaviour the acceptance describes. A syntax check or a lint alone doesn't count.
  - It may only rely on files that exist once this task and the tasks it waits for are done.

Prior art that lives outside the repository (Notion, Drive, wikis) may not be reachable by the agent that implements the task. Copy the facts the task needs into its description, along with the link.

Example:
```bash
${CLAUDE_SKILL_DIR}/../create-task/scripts/create-task.sh --parent sdlc-a1b \
  --title "Implement user authentication" \
  --description "JWT auth: POST /auth/login, token validation middleware, refresh token rotation. Uses the users table from the schema task." \
  --acceptance "Valid credentials return a token; invalid ones return 401; expired tokens are rejected" \
  --scope "src/auth/,tests/auth/" --verify "pytest tests/auth -v" \
  --complexity medium --domain backend --after sdlc-a1b.1
```

**In plan mode**, don't create anything: plan mode is read-only. Write the task graph into the plan file instead, with every field the script takes and the dependencies, so the user approves it with the plan. Once plan mode has ended and the plan is approved, create exactly that graph, and don't ask for approval again.

## 3. Show and confirm

For each epic you created, run `bd swarm validate <epic>`. It reports dependency cycles, tasks nothing leads to, and parts of the graph that aren't connected. Fix what it reports, with `bd` or the script, before going on.

Show the graph you created: `bd list --parent <id> --pretty` for each top-level bead.

- **If you can ask the user:** wait for approval. Apply any requested changes with `create-task.sh` or `bd`.
- **If you can't ask:** report the tree, plus any part of the plan that no task covers, and why.
