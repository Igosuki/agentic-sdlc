# Task rules

Read by split and create-task.

## Graph shape

- No epic under an epic: the inner one would close on merging into the outer epic's branch, not the target.
- A large task may be a parent: create small or medium children under it with `--parent`.
- Never add `--after` between a parent and its own children.
- Tasks that depend on each other go in the same epic. A task branches from its own epic's branch and closes by merging there, so a task that waits on one in another epic isn't waiting on done work until that epic's code reaches the target.

## Task sizing

Estimate each task's complexity:
- **small:** under 50 lines, 1–2 files
- **medium:** under 200 lines, some design decisions
- **large:** over 200 lines, or architectural. Decompose it into subtasks, per Graph shape above.

## Task granularity

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

## Review

Set `--review` on each task:
- `agent`: medium and large tasks, and any task touching authentication, security, payments, data migrations or public APIs
- `human`: a person must sign off — security-sensitive changes, destructive migrations, legal or compliance text
- `none`: small documentation, configuration or test-only tasks

## Shared interfaces

If a task defines interfaces that other tasks consume (types, schemas, API contracts, file formats), make it a separate task and make the consumers wait for it with `--after`. Otherwise they build against nothing.

## Scope

`--scope` lists the path prefixes a task may change. Two tasks that don't wait for each other must not share a path: either add `--after` or merge the tasks. Shared manifests and lockfiles (for example `package.json`, a lockfile, a route index) don't count as overlap.

## Task format

The fields are split like this:
- **Description:** what to do, the interfaces the task depends on from other tasks, and the design sections or prior-art files that matter. Implementation guidance belongs here.
- **Acceptance:** observable checks.
- **Verify:** one short command that exits 0 when the acceptance is met, usually the test the task itself adds, for example `node --test test/auth.test.js` or `pytest tests/auth -v`. No inline scripts.
  - It must exercise the behaviour the acceptance describes. A syntax check or a lint alone doesn't count.
  - It may only rely on files that exist once this task and the tasks it waits for are done.
  - Runs from the repository root and must finish within 10 minutes.
  - In epic modes it runs again on the finished epic branch, so it must still pass after later tasks land.

Prior art that lives outside the repository (Notion, Drive, wikis) may not be reachable by the agent that implements the task. Copy the facts the task needs into its description, along with the link.
