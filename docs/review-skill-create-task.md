I only have read-only tools in this session, so the review is below instead of in a file.

## Skill Review: create-task

### Summary
The SKILL.md body is about 350 words and `scripts/create-task.sh` is 103 lines. There's no `references/` or `examples/` folder. The SKILL.md is a reasonable length for a skill this narrow. The worst problems are in the script, which `split-plan` and `split-task` also use, so they affect all three skills. The script can put a task under an epic that has already been integrated, where it can never reach the target branch. It also creates the bead first and adds its dependencies in separate commands, leaving a window where the new task is unblocked.

### Description Analysis
**Current:** "Create one beads task that sdlc:dispatch can run, with acceptance criteria, scope, a verify command that exercises the behaviour, complexity and domain, and optionally its epic, the tasks it waits for, and an agent, model or effort hint. Use when the user wants to add a single task rather than split a plan."

**Issues:**
- Most of its ~310 characters list fields. There's only one trigger, and none of the phrases a user would actually type ("add a task", "create a bead for", "queue a fix", "follow-up task").
- It doesn't say this is how you add work while dispatch is running, even though the README promises that.
- It says "Use when…" instead of plugin-dev's "This skill should be used when…". All 11 skills in the repo use "Use when…", so keep it.

**Suggested:** "Create one beads task that sdlc:dispatch can run: acceptance, scope, a verify command that exercises the behaviour, complexity and domain, plus optionally its epic, what it waits for, and agent/model/effort hints. Use when the user wants to add a single task, fix or follow-up to the queue, including while dispatch runs: "add a task to…", "create a bead for…", "queue a fix for…". For a plan or large work use split-plan; to break down an existing bead use split-task."

### Content Quality
- **Word count:** ~350. That's under the 1,000-word guideline, but adding more would make it worse. The detailed rules are meant to come from elsewhere (see Major 2).
- **Writing style:** Imperative and plain.
- **Organization:** Three steps (gather, fill in, create) that match the workflow.

### Progressive Disclosure
- **SKILL.md:** ~350 words
- **references/:** none
- **examples/:** none (split-plan's example command covers this)
- **scripts/:** 1 (`create-task.sh`, documented with `--help`)

**Assessment:** This fits the skill's size. The only thing loaded on demand is a pointer to section 2 of another skill, and that pointer causes problems (Major 2). No `references/` folder is needed.

### Specific Issues

#### Critical (1)
- **`create-task.sh:73-75`, `--parent` check:** The script only checks that the parent bead exists. In `epic-merge` or `epic-pr` mode, a task added under an epic whose integration has started can never reach the target branch:
  - **Integration finished, or PR opened:** `record-task.sh:91-94` has already deleted the epic branch. `run-task.sh` claims the new task (l.115), then fails at `wt switch --create <id> --base <epic>` (l.123). The task stays `in_progress` with `dispatch_state=running` and no worker, and `watch.sh` reports it as crashed.
  - **Integration running:** the task can merge into the epic branch after that branch has been merged and just before it's deleted, so its work never reaches the target.
  - **Integration task still open:** nothing breaks, because `run-task.sh:76` refuses to start it. But `next-tasks.sh` lists it as ready, and `dispatch-next.sh` prints "not started" on every round.

  **Fix (in the script, which covers all three skills):** walk up to the epic using the same loop as `run-task.sh:50-55`.
  - If the epic has a `dispatch_integration_task` that isn't `open`, exit 2 with "epic X is already integrating; create the task without --parent or under a new epic".
  - If that task is open, run `bd dep add <integration> <new-id>` after creating the bead.

#### Major (4)
- **`create-task.sh:95-99`, creation isn't atomic:** The bead is ready from the moment `bd create` returns until every `bd dep add` has run.
  - `next-tasks.sh` only requires `metadata.verify`, so a running dispatch can start the task before the tasks it should wait for.
  - If `bd dep add` fails, the script exits 1 and leaves a ready bead with no dependencies. If the model reruns the command, as it would after any failure, it creates a duplicate.

  **Fix:**
  - Pass the dependencies to `bd create` (beads documents `--deps`). Check once with `bd show` that the edge means "new task waits for X", and keep the existence check, since the l.72 comment may apply there too.
  - In SKILL.md step 3, add: exit 2 means fix the listed arguments and rerun; exit 1 with a "created <id>" message means don't rerun.
- **SKILL.md:27, pointer to split-plan section 2:** That section conflicts with this skill.
  - It says to decompose large tasks into subtasks, while line 30 here says to create them anyway.
  - It brings in rules about graph shape, granularity and plan mode that don't apply to one task.
  - It has Sonnet Read a file after step 1 said not to read files yourself.
  - It breaks silently if split-plan renumbers its sections.

  **Fix:** drop the pointer and inline the ~80 words that apply to a single task:
  - what goes in Description, Acceptance and Verify
  - no inline scripts
  - verify may only rely on files that exist once this task and the tasks it waits for are done
  - the size thresholds
  - copy facts from prior art outside the repo into the description

  The Verify and Scope bullets already restated here become part of that block.
- **SKILL.md:30, large tasks:** The skill creates the task and suggests `/sdlc:split-task`. But the bead already has a verify command, and `next-tasks.sh` only skips beads with children. A running dispatch can therefore start it as one big task before anyone splits it. **Fix:** for large requests, create nothing and hand off to `/sdlc:split-plan "<request>"`.
- **SKILL.md:23, finding dependencies:** "The same search finds the tasks it must wait for" doesn't work. `bd search` matches text. It doesn't find open tasks that build an interface this task uses, or running tasks that change the same paths. Missed ones lead to verify commands that fail on missing code, or to rebase conflicts that `finish-task.sh` sends back to a worker. **Fix:**
  - Have the reading agent report which open or in-progress tasks produce what this task uses.
  - Compare the new `--scope` with the `metadata.scope` of open and in-progress tasks, and add `--after` for any overlap.

#### Minor (3)
- **SKILL.md has no beads-initialized check:** If beads isn't set up, `bd search` fails, and `create-task.sh:74` reports every `--parent`/`--after` as "no bead X", because it treats any `bd show` failure as a missing bead. Add split-plan's `` !`bd where …` `` line and stop, or initialize, when beads isn't set up.
- **SKILL.md:36-41, `--priority` missing:** The template leaves out `--priority`, which the script accepts, so "urgent fix" has no way through. Add `[--priority 0-4]`.
- **`allowed-tools` doesn't cover the Read of `${CLAUDE_SKILL_DIR}/../split-plan/SKILL.md`:** In an installed plugin that path is outside the project, so it may prompt, or be denied in a headless session. This goes away if Major 2 is fixed.

### Positive Aspects
- The script collects all validation errors before exiting and documents its exit codes in `--help`, so one rerun can fix everything.
- It checks that referenced beads exist before creating anything, and a one-line comment explains why (`bd dep add` accepts unknown ids).
- Metadata is built with `jq --arg`, so quotes in descriptions or verify commands can't break it. Empty keys are dropped, which matters: `run-task.sh`'s `get … // empty` would pass `""` through as `--model ""`.
- One script serves all three planning skills and matches the field table in `docs/beads.md`.
- The SKILL.md runs the script without loading it, pre-approves it, sends file reading to a haiku agent, checks for duplicates before creating, and writes "Assumptions" into the description when it can't ask the user.

### Overall Rating
**Needs Improvement.** The SKILL.md structure is fine. The Critical issue and the first Major are script bugs that also affect split-plan and split-task.

### Priority Recommendations
1. In `create-task.sh`, reject `--parent` under an epic whose integration task isn't open. When it is open, make the integration task wait for the new task.
2. Create dependencies in the same `bd create` call, and tell the skill not to rerun after exit 1.
3. Replace the split-plan section 2 pointer with the single-task rules, and hand large requests to split-plan instead of creating them.
