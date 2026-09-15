# Plan: fixes from the plugin validator and skill reviews

Sources: the 12 `docs/review-*.md` files, about 130 findings. References such as `dispatch C2` or `validator #3` point to a finding in `docs/review-<name>.md`.

The reviews predate commit `3e01b89` (project checks and review gates), so their line numbers are stale. This plan was checked against `85d1aa4`. Every issue in the Critical section is still present there.

Triage rule (build-minimal): fix what breaks a real run. Drop hypothetical edge cases and cosmetic changes, and list them at the end with the reason.

## Critical

These were confirmed by running beads in a scratch repo, by reading the Claude Code docs, or by reading the code at HEAD.

| # | Issue | Evidence | Task |
|---|---|---|---|
| C1 | A task with children is never dispatched and never closed. Everything waiting on it blocks, and so does its epic and the epic's integration. | bd 1.2.2: closing the last child leaves the parent open, and `bd ready` lists it. `bd epic close-eligible` closes only epics. | T1, T4 |
| C2 | The scripts disagree on a task's epic. `watch.sh`, `workers.sh` and `stats.sh` use the direct parent; `next-tasks.sh` and `run-task.sh` walk up. Subtasks are dispatched but never followed, so the watch goes idle while they run, and stats credits them to the wrong epic. | Code | T1, T2, T5 |
| C3 | `next-tasks.sh` and `stats.sh` pass the whole bead database to jq as a command-line argument. Linux caps one argument at 128 KiB, so `/sdlc:status`, `/sdlc:stats` and dispatch break as history grows (this repo is at 28 KiB). | `--argjson all "$all"` | T2 |
| C4 | Stats counts a resumed worker session twice: each attempt writes an event carrying the session's running total. | Code | T2 |
| C5 | `create-task.sh` creates the bead, then adds dependencies with separate `bd dep add` calls. A running dispatch can start the task before them, and a failed call leaves a ready task with no dependencies. `bd create --deps` does both in one call. | bd 1.2.2 | T13 |
| C6 | A `!` command in SKILL.md that isn't pre-approved aborts the skill; so does a non-zero exit. Affected: `design` and `build` (no `allowed-tools` for `settings.sh`); `init` (settings.sh not listed); `dispatch` (its call to `stats.sh`); `status` and `stats` (abort in a project without beads). | code.claude.com/docs/en/skills | T2, T7, T8, T10, T14, T15 |
| C7 | `logs`' `!` line pipes into `tail -80`. Each part of a pipe must match a rule, and `tail` doesn't, so `/sdlc:logs` aborts. | code.claude.com/docs/en/permissions | T2 |

Other findings the reviewers rated critical come right after, in the task order below: dispatch C1 (flags), dispatch C2 and C3 (the supervisor stops early or waits forever), init's `.gitignore` corruption and overwritten settings, build creating the task graph twice, and split-plan's quoting.

## Decisions

1. **Epic closure means the code is on the target branch** (main or a release branch).
   - A parent task closes when its last child closes, since its code is then merged into the epic branch or the target.
   - An epic closes only when its code reaches the target: in direct mode when its last task merges; in epic-merge mode when the integration task merges; in epic-pr mode when the PR merges.
   - No epic under an epic: the inner one would close on merging into the outer epic's branch.
   - No task is added under an epic that is closed or integrating.
2. **No state value for a running worker.** A task's worker is running when all three hold:
   - the task is claimed (`in_progress` with a `dispatch_session`);
   - a process exists for it: `run-task.sh <id>` still starting it, or the worker session;
   - no attempt outcome is recorded.

   The `running` value goes, and there is no `starting` value. `dispatch_state` keeps only what can't be seen once the process is gone: how the last attempt ended (`stopped`, `failed`, `awaiting-review`, `pr-opened`, `merged`). A claimed task with no process and no outcome has crashed.

   Until T3 lands, some tasks still carry `running`, so checks treat "no outcome" as `dispatch_state` being empty or `running`.
3. **References:** `skills/split-plan/references/task-rules.md`, read by split-plan, split-task and create-task.
4. **`--domain` is dropped.** The worker infers the kind of work from the task.
5. **Workers on other machines:** deferred until beads is shared between machines.
6. **Bash + jq for commands, Python for logic.** This is the split Anthropic's own plugins use: `ralph-loop` and `plugin-dev` hooks in bash + jq, `hookify`, `security-guidance`, `claude-security` and `skill-creator` in Python. See the next section.

## Scripts: where Python replaces bash

**The rule, written into `docs/development.md`:**
- **Bash + jq** for a script that runs commands and reads a few fields from JSON.
- **Python 3.9+, standard library only,** for a script that walks the task graph, sorts, totals, keeps state across rounds or renders logs.
- Bead data is never passed as a command-line argument.

**Shared code: new `skills/dispatch/scripts/tasks.py`.** It reads the tasks from beads once and answers what the scripts ask:
- a task's epic, and whether a bead is under an epic at any depth
- the parent tasks to close after a task closes
- the dispatch order
- whether a task's worker is running (decision 2)
- the totals of an attempt's log

It has a small CLI (`epic <id>`, `parents-to-close <id>`, `worker <id>`, `log-totals <log>`) for the bash scripts. `stats`, `logs` and `create-task` reach it at `../dispatch/scripts`, the way `status` and `logs` already call dispatch's scripts.

**Ported to Python (about 400 lines of bash):** `next-tasks`, `stats`, `logs`, `workers` and `watch`.
- Each keeps its name with `.py`, and its options, output lines and exit codes.
- Each port includes the fixes for that script.
- `stats.py` moves next to the others in `skills/dispatch/scripts/`.

**Stay bash + jq:** `run-task`, `resume-task`, `resume-reviewed`, `record-task`, `finish-task`, `merge-queue`, `close-prs`, `dispatch-next`, `settings`, `init`, `checks`, `create-task`, `check`, and the three hooks. They call `tasks.py` for graph questions, instead of keeping their own copy.

**Requirements:** `check.sh` and the README add `python3` next to `jq`.

## Tasks

No two tasks edit the same file, so tasks whose dependencies are done can run in parallel. Each skill's task also rewrites that skill's description, using the reviewer's suggested wording with its trigger phrases and its "not for…" exclusions.

### T1. tasks.py and its tests
- **Why:** C1 and C2 at their source, plus decision 2.
- **Change:**
  - **New `tasks.py`** with the functions and CLI listed above. It reads `bd` output through a pipe.
    - Epic: walk up the parents to the nearest epic.
    - Parents to close: walk up and return each parent task (not an epic) whose children are all closed.
    - Dispatch order: today's `next-tasks.sh` rules, using that epic walk.
    - Worker running: follows decision 2. The process check matches `run-task.sh <id>` or the session's `--session-id` / `--resume`, and ignores `--fork-session` (a user inspecting the conversation, dispatch minor 2).
    - Log totals: the same totals `record-task.sh` computes today, reading line by line and skipping broken lines.
  - **New `tests/test_tasks.py`** (`unittest`, real `bd` in a temp git repo, no stubs). It covers a nested task (its epic, and closing parents), dispatch order skipping parents, more than 128 KiB of beads, and log totals for a resumed session.
  - **`docs/development.md`:** the rule above, replacing "Python only once the logic gets complex".
- **Files:** new `skills/dispatch/scripts/tasks.py`, new `tests/test_tasks.py`, `docs/development.md`
- **Check:** `python3 -m unittest tests/test_tasks.py` passes.

### T2. next-tasks, stats and logs in Python (waits for T1)
- **Why:**
  - C2–C4, C6 (stats) and C7
  - stats Major 3
  - logs Major 1 and its minors on multi-line entries, running-total cost and `--raw` help
- **Change:**
  - **`next-tasks.py`:** the `tasks.py` dispatch order, with today's output.
  - **`stats.py`** (in `skills/dispatch/scripts/`):
    - Credits each task to its real epic.
    - Keeps the latest event per session.
    - Includes review cost as today.
    - Accepts the epic as a plain argument or as `--epic`.
  - **`logs.py`:**
    - `--follow` is refused when stdout isn't a terminal.
    - New `--last N`: says how many lines were left out and repeats the header of the session the first kept line belongs to.
    - Prints `$log.wt` when no `.jsonl` exists.
    - Tool inputs and text become one line each.
    - Cost is labelled as a running total.
  - **Skill files:**
    - `stats/SKILL.md` and `logs/SKILL.md` point to the new scripts, with `2>&1 || true`.
    - The logs `!` line becomes `logs.py --last 80 $ARGUMENTS 2>&1 || true`, with no pipe.
  - **`dispatch-next.sh`:** calls `next-tasks.py`.
  - Delete `next-tasks.sh`, `skills/stats/scripts/stats.sh` and `logs.sh`. Update the mentions in `docs/harnesses.md`.
- **Files:** new `next-tasks.py`, `stats.py`, `logs.py`; `dispatch-next.sh`, `skills/stats/SKILL.md`, `skills/logs/SKILL.md`, `docs/harnesses.md`
- **Check:** output matches the old scripts on this repo's beads, and `/sdlc:logs <id>` runs without a permission prompt.

### T3. No running state; a failed start leaves no claim (waits for T1)
- **Why:** decision 2, dispatch C2 and M3, validator #3.
- **Change:**
  - **`run-task.sh`:**
    - Claim without `dispatch_state`.
    - On any failure after the claim, undo it (status open, remove the `dispatch_*` metadata) and print the reason, including the `$log.wt` error.
    - Take the epic from `tasks.py epic`.
  - **`resume-task.sh`:**
    - Use `tasks.py worker`.
    - Release the merge queue (`merge-queue.sh release <dispatch_base> <task>`) before resuming.
  - **`resume-reviewed.sh`:** when resuming, remove `dispatch_state` instead of setting `running`.
  - **`record-task.sh`:** takes the log totals from `tasks.py log-totals`, and its help text is updated.
  - **`docs/beads.md`:** the state table drops `running` and defines running and crashed as in decision 2.
- **Files:** `run-task.sh`, `resume-task.sh`, `resume-reviewed.sh`, `record-task.sh`, `docs/beads.md`
- **Check (sandbox):**
  - Make `wt switch` fail: the task goes back to open, and the reason is shown.
  - Watch while a slow worktrunk post-create hook runs: no `crashed` event.
  - Kill a worker during verify, then resume it: the merge goes through.

### T4. finish-task closes parents; epics close only on the target; merge queue recovers (waits for T1)
- **Why:** C1, decision 1, dispatch M5, dispatch minor 4.
- **Change:**
  - **`finish-task.sh`:**
    - After closing the task, close the parents that `tasks.py parents-to-close` returns.
    - Close the epic only under the rules of decision 1.
    - The "has a dispatched worker" check follows decision 2: claimed, with no outcome recorded.
    - Capture the push error from the first push, instead of pushing a second time.
  - **`merge-queue.sh acquire`:** a queue already held by the same holder counts as acquired.
  - **`close-prs.sh`:** find out whether a `gh:pr` gate also resolves when a PR is closed without merging. If it does, check the PR state before closing the task and epic as merged.
- **Files:** `finish-task.sh`, `merge-queue.sh`, `close-prs.sh`
- **Check (sandbox):** epic E with task P split into P.1 and P.2, and task X `--after` P. In direct mode and in epic-merge mode, P closes when P.2 merges, X starts, and E closes only once its code is on the target.

### T5. workers and watch in Python (waits for T2 and T3)
- **Why:** C2, dispatch M2, status minor 5.
- **Change:**
  - **`workers.py`:** states from the `tasks.py` worker check, and the same evidence as today for crashed, stopped, failed and awaiting-review tasks. A failed `bd comments` call doesn't end the listing.
  - **`watch.py`:**
    - Same events and each-round calls (`bd gate check`, `close-prs.sh`, `resume-reviewed.sh`).
    - Epic filter at any depth.
    - Prints `ended <task> <state>` for a task already ended the first time a later round sees it.
  - Delete `workers.sh` and `watch.sh`.
- **Files:** new `workers.py`, `watch.py`
- **Check (sandbox):**
  - A worker whose model is invalid exits within seconds: `ended … failed` is printed.
  - Watching with `--epic` while a subtask runs: it stays alive until the subtask ends.

### T6. Worker hooks
- **Why:** decision 2, validator #5.
- **Change:**
  - **`worker-stop.sh`:** block stopping while the task is claimed by this session and no outcome is recorded.
  - **`worker-guard.sh`:** also deny `git <options> push` and `gh pr merge`.
- **Files:** `hooks/worker-stop.sh`, `hooks/worker-guard.sh`

### T7. Dispatch skill text (waits for T5)
- **Why:** C6 (stats call), dispatch C1, C3, M3 (recovery), M4 and M7, dispatch minors 7 and 8, validator #7.
- **Change to `dispatch/SKILL.md`:**
  - Script paths updated. The flags are listed per script: `--epic` for workers, next-tasks, dispatch-next, watch and stats; `--parallel` for dispatch-next only.
  - "Crashed" follows decision 2.
  - Step 1: don't ask for confirmation again when `sdlc:build` invoked the skill after plan approval.
  - "Can't" recovery: release the merge queue, run `wt remove -D <branch>` (so the next `wt switch --create` works), then reopen.
  - Step 3: report each `not started` reason. If nothing started and no worker is running, stop and report instead of watching.
  - Step 4:
    - After `ended … stopped|failed`, or after a crash decision, run `dispatch-next.sh`. The exception is a cause that would stop any new worker too (usage limit, authentication, full disk): then stop and report.
    - Skip crashes already decided in step 2.
  - Step 5: run `workers.py` again before reporting, and list tasks waiting on a PR with "run `/sdlc:dispatch` after it merges".
- **Files:** `skills/dispatch/SKILL.md`

### T8. status (waits for T5)
- **Why:** C6 (status), status Majors 1–3, minors 1 and 3.
- **Change to `status/SKILL.md`:**
  - Script paths updated, with `2>&1 || true` on each `!` line.
  - `allowed-tools` lists only `workers.py`, `next-tasks.py` and `settings.sh`.
  - Code blocks, then one next step per task:
    - crashed → `/sdlc:dispatch`
    - stopped or failed → its last comment, `/sdlc:logs <task>`, then clarify the task, `/sdlc:split-task` or fix it by hand
    - awaiting-review → the review commands
  - The header becomes "Dispatch queue".
- **Files:** `skills/status/SKILL.md`

### T9. settings.sh computes only the key it's asked for
- **Why:** validator #6 and #8, design minors (bash 3.2, extra `bd` calls).
- **Change:** no `bd config get` for keys that come from the local file, and no `declare -A`. The help text lists `epic-pr`.
- **Files:** `skills/dispatch/scripts/settings.sh`

### T10. init
- **Why:** C6 (init), init Criticals 1 and 2, Majors 3–6, minors 1–4, validator #9.
- **Change:**
  - **`SKILL.md`:**
    - Headless: pass only the options given in `$ARGUMENTS`.
    - Interactive: ask only about settings that aren't saved yet. When asking about a saved one, put its value first as the recommended option.
    - "No" to build routing: omit `--workflow` on a first run, and pass `--workflow none` to remove a saved value.
    - Show the raw saved values and the current branch.
    - Decide whether to commit from `git status --porcelain -- .gitignore .beads`, and commit only those paths.
    - `allowed-tools` names exactly those commands plus `settings.sh`. `argument-hint` adds `--design-dir`.
  - **`init.sh`:**
    - Add a newline before appending to a `.gitignore` that doesn't end with one.
    - Find the root through `--git-common-dir`.
    - `set_key` exits 1 when it didn't write the key.
    - Exit 2 with a message on a detached HEAD or in a repo with no commits.
    - If `bd` is missing, say "run /sdlc:setup".
- **Files:** `skills/init/SKILL.md`, `skills/init/scripts/init.sh`
- **Check (sandbox):**
  - A `.gitignore` without a final newline keeps its last entry.
  - Re-running headless on an `epic-pr` repo from a feature branch changes nothing.
  - Running from a `wt` worktree writes to the main checkout.

### T11. split-plan and the task rules reference
- **Why:** split-plan Majors 1–6, its minors, and decisions 1, 3 and 4.
- **Change:**
  - **New `references/task-rules.md`**, moved out of SKILL.md section 2: sizing, scope, shared interfaces, task format, review level and verify rules. It adds:
    - Graph shape (decision 1): no epic under an epic. A large task may be a parent. Never add `--after` between a parent and its own children. Tasks that depend on each other go in the same epic.
    - Verify: runs from the repository root and must finish within 10 minutes. In epic modes it runs again on the finished epic branch, so it must still pass after later tasks land.
    - Scope: shared manifests and lockfiles don't count as overlap.
  - **`SKILL.md`:**
    - A **Mode** block after the `bd where` line:
      - In plan mode: decompose into the plan file, using labels (T1, T2…) for `--parent` and `--after`, and write nothing to beads.
      - When an approved plan in this conversation already holds a graph: create it without asking again.
      - Otherwise: steps 1–3.
    - The create template and example use single quotes (an apostrophe is written `'\''`) and drop `--domain`.
    - Step 1: run `bd search` and `bd list --type epic` directly. Stop if an existing epic already covers the plan, and add `--after` for open tasks the new ones need.
    - Sources not committed on the target branch (uncommitted docs, plan-mode plans): copy their facts into descriptions. Step 3 lists any `--design` document that needs a commit before dispatch.
    - When beads isn't initialized, send the user to `/sdlc:init`.
    - Step 3: use AskUserQuestion, with a headless fallback. Validate again after changes, and show the dependencies.
- **Files:** `skills/split-plan/SKILL.md`, new `skills/split-plan/references/task-rules.md`

### T12. split-task (waits for T11)
- **Why:** split-task Majors 1 and 2 and its minors.
- **Change:**
  - **Stopped or failed task:** read its last comment, and have the reader summarize the commits in its worktree. After the split, offer the reset: `wt remove -D <branch>`, then reopen with the `dispatch_*` metadata removed. Ask first with AskUserQuestion; in a headless session, only report it. Add `Bash(wt remove *)` to `allowed-tools`.
  - Put every acceptance check of the parent into some child's acceptance, and report any check that didn't land.
  - Read `task-rules.md` directly, not through the reader.
  - Find "the nearest epic above it, or the bead itself".
  - Check "children that aren't closed".
  - Check sibling scopes with `bd list --parent <p> --json`.
  - Find out whether `bd swarm validate` accepts a bead that isn't an epic.
- **Files:** `skills/split-task/SKILL.md`

### T13. create-task (waits for T1 and T11)
- **Why:** C5, create-task Critical, Majors 2–4, minors 1 and 2, decision 4.
- **Change:**
  - **`create-task.sh`:**
    - Pass dependencies to `bd create --deps`, and keep the existence check.
    - Drop `--domain`.
    - With `--parent`, find the epic with `tasks.py epic`. If the epic is closed or its `dispatch_integration_task` isn't open, exit 2. If that task is open, run `bd dep add <integration> <new-id>`.
  - **`SKILL.md`:**
    - Large requests: create nothing, and hand off to `/sdlc:split-plan "<request>"`.
    - Exit 2 means fix the arguments and rerun. Exit 1 after "created <id>" means don't rerun.
    - Compare `--scope` with the `metadata.scope` of open and in-progress tasks, and add `--after` for any overlap.
    - Add a `bd where` check and `[--priority 0-4]`.
    - Point to `task-rules.md`.
- **Files:** `skills/create-task/SKILL.md`, `skills/create-task/scripts/create-task.sh`

### T14. build
- **Why:** C6 (build), build C1, C2, M1–M3, m1 and m2.
- **Contracts:** dispatch skips its confirmation when build invokes it (T7). split-plan's Mode block handles the second call after approval (T11).
- **Change to `SKILL.md`:**
  - Without plan mode: design writes the document and split-plan creates the tasks during step 1. Skip 1.4, 2.1 and 2.2.
  - Exactly one top-level epic. Pass its id to dispatch.
  - In plan mode, split-plan splits the design from the plan file and sets `--design <path the document will be written to>`.
  - Inject `git branch --show-current` and compare it with the target in step 1. A branch switch goes into the plan. If the switch can't happen, stop before creating anything. Dispatch only after the commit succeeds.
  - The plan shows the integration mode, target branch, parallel limit and the default review level.
  - The reason for the commit is the design document (tasks live in Dolt).
  - `!` settings line gets `2>&1 || true`. `allowed-tools`: `settings.sh`, `git branch --show-current`, and `git add`/`git commit` for the document.
- **Files:** `skills/build/SKILL.md`

### T15. design
- **Why:** C6 (design), design Major 1, the reader part of Major 2.
- **Change to `SKILL.md`:**
  - `allowed-tools: Bash(${CLAUDE_SKILL_DIR}/../dispatch/scripts/settings.sh *)`. The `design_dir` call gets `2>/dev/null || true` and prints `(not set)` when empty.
  - Headless: use only the sources the request names or links, and list the others under Open questions.
  - `bd` commands run directly; delegate only the reading of large results.
- **Files:** `skills/design/SKILL.md`

### T16. setup
- **Why:** decision 6, setup Majors 1–3, minors on rtk detection, OS note, usage text and headless test.
- **Change:**
  - **`SKILL.md`:**
    - The required tools add `python3`, including the Debian and Ubuntu package.
    - Name `${CLAUDE_SKILL_DIR}/scripts/check.sh` in the re-check step.
    - Commands needing `sudo` or a password: give the command, and ask the user to run it with `! <command>`.
    - Companions: give the rtk URL (not reachingforthejack/rtk), and one line on the role of each agent.
    - Say first when the OS isn't Linux.
    - Headless means AskUserQuestion isn't available.
  - **`check.sh`:**
    - Requires `python3` 3.9 or later.
    - Detects rtk with `rtk gain`.
    - The usage text matches the actual output.
- **Files:** `skills/setup/SKILL.md`, `skills/setup/scripts/check.sh`

### T17. Docs (waits for T3 and T15)
- **Why:** validator #4, design minor (docs contradiction), decision 2 in the workflow doc, decisions 4 and 6.
- **Change:**
  - **`README.md`:** requirements add `python3`.
  - **`docs/configuration.md`:**
    - "Worker permissions": anyone who can write to beads can run commands on the machine that dispatches. Worker prompts come from bead text, workers run in auto mode, and `verify` runs through `bash -c`.
    - The worker guard is a guardrail, not a security boundary.
    - The `design_dir` order follows the skill.
  - **`docs/workflow.md`:**
    - The crashed definition follows decision 2.
    - The `design_dir` order follows the skill.
    - The domain field goes.
    - The ported scripts end in `.py`.
- **Files:** `README.md`, `docs/configuration.md`, `docs/workflow.md`

### T18. Wild tests (extends sdlc-714.5; waits for all)
- **Why:** dispatch minor 9, and validator #2's point that `tests/wild/run.sh` hides permission gaps.
- **Change:**
  - **`tests/wild/dispatch.sh`:**
    - Runs the supervisor once as a follow loop with `--epic` and `--parallel 2`.
    - Adds a split task that another task waits on (epic-merge).
  - Run design, split-plan, status, stats and logs once without `--dangerously-skip-permissions`.
- **Files:** `tests/wild/dispatch.sh`, `tests/wild/run.sh`

## Order

| Task | Waits for |
|---|---|
| T1, T6, T9, T10, T11, T14, T15, T16 | nothing |
| T2, T3, T4 | T1 |
| T5 | T2, T3 |
| T7, T8 | T5 |
| T12 | T11 |
| T13 | T1, T11 |
| T17 | T3, T15 |
| T18 | all |

The critical issues are closed by T1–T5, T7, T8, T10 and T13–T15. After implementation: one `reviewer` pass per task, then T18.

## Deferred

- **Workers on another machine** (dispatch M1, status minor 4): wait until beads is shared between machines.

## Dropped

| Finding | Reason |
|---|---|
| design minor: `effort: high` unconfirmed | Supported field |
| build m3: nested skill model | `model:` applies when a skill is invoked by another skill |
| logs Major 3: resume hint | `claude --resume` finds sessions from any directory (Claude Code ≥ 2.1.223) |
| stats minor: `stats.sh ` with a trailing space | `Bash(x *)` matches the bare command |
| stats Major 2, race with `record-task.sh` | The wrapper keeps the worker's arguments in its command line until recording ends; the resumed-session double count is C4 |
| init minor 5: `.worktrees/` entry | Your worktrunk config puts worktrees there |
| dispatch minor 3: a result written after a wake-up | Needs a kill in the seconds after a wake-up; recovery is a manual resume |
| dispatch minor 5: epic branch deleted while the PR is open | The branch is on origin; the PR is unaffected |
| validator #10: version in both manifests | No drift yet |
| stats minors: sort order, "worker time" label, stale state note, no-argument size, unknown id | Cosmetic |
| init minor 6: one output line per step | Cosmetic |
| setup minors: `~/.claude/agents` double count, "version unknown", the `missing claude` clause | Cosmetic |
| status minor 2: `model: haiku` | Short, user-run view |
