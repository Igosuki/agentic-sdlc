## Skill Review: split-task

### Summary
The SKILL.md is short (about 400 words) and does most of its job by pointing to split-plan's section 2. `skills/split-task/` has no `scripts/` folder. The only script it runs is `skills/create-task/scripts/create-task.sh`, so I reviewed that one. It works fine for this skill.

The biggest problem isn't in the SKILL.md. Splitting a **task** (not an epic) leaves behind a parent task that nothing in dispatch ever closes, so the work after it never finishes. There's one other problem in the skill itself: dispatch sends stopped tasks here, but the skill has no steps for them.

I only had read tools, so a few `bd` behaviours are marked "confirm" below.

### Description Analysis
**Current:** "Split an existing bead (task or epic) into child tasks with acceptance criteria, scope, verify command and dependencies. Use when a bead is too large, or was created by hand without a breakdown." (~195 chars)

**Issues:**
- It leaves out the case dispatch sends here: a worker stopped or failed on a task (`dispatch/SKILL.md:36`).
- Missing wording users would type: "break down", "decompose", "subtasks".

**Recommendations:**
- Keep "Use when…". Every sibling skill words it that way, so switching this one to "This skill should be used when…" would just be churn.
- Suggested: "Split an existing bead (task or epic) into child tasks with acceptance criteria, scope, verify command and dependencies. Use when a bead is too large, was created by hand without a breakdown, or its dispatched worker stopped; or when asked to break down or decompose a bead."

### Content Quality
- **Word count:** about 400. That's below the usual 1,000 words, but it's the right size because the rules live in split-plan. Don't pad it.
- **Writing style:** imperative and plain, same as split-plan and create-task.
- **Organization:** read, decompose, then show. It mirrors split-plan and is easy to follow.

### Progressive Disclosure
- SKILL.md: about 400 words
- references/: none. Split-plan's section 2 plays that role.
- examples/: none. It uses split-plan's example.
- scripts/: none of its own. It calls `create-task.sh`.

Pointing to split-plan's section 2 keeps the sizing, scope and verify rules in one place.

### Specific Issues

#### Critical (1)
- **`dispatch/scripts/finish-task.sh`: a split task is never closed.**
  - **Cause:** once split-task gives a task children, dispatch skips it (`next-tasks.sh:52`), which is correct. But `finish-task.sh` only closes the task that just merged (line 110). It then goes straight up to the epic (lines 48–53), which closes only when all of its *direct* children are closed (line 116). The split task is one of those direct children, and nothing ever closes it.
  - **What breaks:**
    - The epic never closes.
    - Tasks that had `--after <split-task>` stay blocked for good.
    - In epic-merge or epic-pr mode, the integration task never starts, because it waits on every direct child (`run-task.sh:94–95`).
  - **Who hits it:** both routes the plugin recommends, create-task's "large, suggest split-task" and dispatch's "stopped, split-task". split-plan's nested large tasks hit it too.
  - **Fix:** in `finish-task.sh`, after closing a task, go up through its parents. Close each non-epic parent whose children are all closed, then do the epic check.
  - **Test:** in the sandbox, split a *task* that another task waits on, then dispatch. The current wild test only splits a new epic with nothing waiting on it, so it can't catch this.
  - Confirm that bd 1.2.2 doesn't close parents on its own.

#### Major (2)
- **`SKILL.md` step 1: no steps for a stopped or failed task.**
  - **What's missing:** dispatch sends these here, but the skill never reads the worker's last comment (`bd comments <id>`, as `workers.sh:97` does). That comment explains why the task was too big.
  - **What's left behind:**
    - The task stays `in_progress` with `dispatch_state=stopped` and a `dispatch_session`, so `workers.sh:39` lists it as stopped on every dispatch run.
    - Its worktree holds partial commits that the child tasks won't build on.
  - **Fix:**
    - In step 1, if the task has a `dispatch_state`, read its last comment and have a reader summarize the commits in its worktree.
    - In step 3, offer dispatch's existing reset: `wt remove <branch>`, then `bd update <id> --status open --unset-metadata dispatch_state --unset-metadata dispatch_session`. Ask first with AskUserQuestion. In a headless session, just report it.
    - Add `Bash(wt remove *)` to allowed-tools.
    - If the task is closed, stop.
- **`SKILL.md` step 3: nothing checks that the children cover the parent's acceptance.**
  - After the split, the parent's own checks are never run as a task. Its verify only runs during integration in the epic modes (`finish-task.sh:57`), and never in direct mode.
  - split-plan's report lists anything the tasks don't cover (line 116). split-task dropped that step.
  - **Fix:** in step 2, place every acceptance check of the parent task into some child's acceptance. In step 3, report any check that didn't land anywhere.

#### Minor (4)
- **Line 55, no epic:** "the epic the bead belongs to" doesn't exist for a task create-task made without `--parent`. And if the direct parent is a task, the skill has to keep going up to find the epic. Say "the nearest epic above it, or the bead itself if there is none". Confirm `bd swarm validate` accepts a non-epic.
- **Line 15 vs line 39, conflicting read rules:** the skill says to delegate every read, then says to read split-plan's section 2 yourself. Call this out as the one file to read directly, because a haiku summary would reword the rules.
- **Line 24, "open children":** an epic whose children are `in_progress` or `blocked` passes this check, and the skill then adds duplicate children. Use "children that aren't closed".
- **Line 29, sibling scopes:** `bd children` shows only titles. To apply split-plan's "no shared paths" rule against siblings, it needs their `metadata.scope` (`bd list --parent <parent> --json`).

#### create-task.sh (as split-task uses it)
Nothing to fix:
- It checks that the parent and `--after` ids exist, with a comment explaining why (`bd dep add` silently accepts unknown ids).
- It lists every argument problem at once and documents its exit codes.
- If `bd dep add` fails after the bead is created, the error names the new id, so the fix with `bd` is clear.

### Positive Aspects
- It doesn't copy split-plan's rules, so they're kept in one place.
- It gives a clear order for finding the design doc: the bead, then its parent epic, then `docs/design/`.
- It still splits thin or conflicting beads, writes the guesses under "Assumptions" and suggests `/sdlc:design`, so it works headless.
- The frontmatter follows the project's model rules: Opus, reads delegated, `bd` run directly.
- Stopping when children already exist prevents splitting split-plan's output a second time.

### Overall Rating
**Needs Improvement.** The critical issue is fixed in `finish-task.sh`, not the SKILL.md, but until it is, the skill's main use (splitting a task inside an epic) blocks the rest of that epic.

### Priority Recommendations
1. Close parent tasks once all their children are closed in `finish-task.sh`, and add a sandbox run that splits a task another task waits on.
2. Add steps for a stopped or failed task: read the worker's comment, then reset the task and its worktree.
3. Place each of the parent's acceptance checks into a child, and report any that don't land.
