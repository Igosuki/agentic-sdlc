---
name: dispatch
description: Supervise the implementation of beads tasks. Dispatches ready tasks in work order, within the parallel limit, to worker sessions that each implement, merge and close one task in its own worktree; follows them as they end; resumes crashed workers and reports stopped ones. Takes an epic, or all dispatchable work when given none. Use when tasks from sdlc:split-plan or sdlc:split-task are ready to implement, or after a restart to pick up dispatched work.
argument-hint: "[epic-id] [--parallel N]"
model: sonnet
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/*), Bash(bd *), Bash(wt remove *)
---

# Dispatch

Arguments: $ARGUMENTS

Settings:
!`${CLAUDE_SKILL_DIR}/scripts/settings.sh`

You are the supervisor. Each task is carried by a worker: a Claude session in the task's own worktree that implements the task, merges it and closes it. You don't implement or merge anything. You start workers, follow them, and handle what they can't.

When the arguments name an epic, pass `--epic <id>` to `workers.py`, `next-tasks.py`, `dispatch-next.sh`, `watch.py` and `stats.py`. When they give a parallel limit, pass `--parallel <N>` to `dispatch-next.sh` only.

Run the scripts by the paths written here, without a `python3` or `bash` prefix: they're executable, and a prefixed command doesn't match this skill's permissions. Run them; don't read their source.

## 1. Look

- `${CLAUDE_SKILL_DIR}/scripts/workers.py`: dispatched tasks that aren't closed, with their state (running, crashed, stopped, failed or awaiting-review).
- `${CLAUDE_SKILL_DIR}/scripts/next-tasks.py`: ready tasks in work order.

Confirm with AskUserQuestion what is about to happen: the tasks that will start, the parallel limit, the integration mode and the target branch. Skip this if `sdlc:build` invoked this skill after its own plan already covered dispatching — it doesn't need a second approval. If AskUserQuestion isn't available (headless session), go ahead. Never ask in plain text and stop.

## 2. Handle crashed and stopped workers

**Crashed** (the task is claimed — `in_progress` with `dispatch_session` set — no outcome is recorded, and no process runs its session): decide from the evidence `workers.py` prints: its last events usually say enough. Don't read worker logs yourself, since they are long and full of encoded thinking blocks. If you need more, run `${CLAUDE_SKILL_DIR}/scripts/logs.py <task>`, or have a reading agent answer a precise question.
- **The log has a result:** the worker ended, but its attempt wasn't recorded. Run `${CLAUDE_SKILL_DIR}/scripts/record-task.sh <task>`.
- **Resume:** the transcript and worktree exist, and the cause is gone: a shutdown, a killed process, a transient error. A stop with no error is a reason to resume, even if it happened before. Run `${CLAUDE_SKILL_DIR}/scripts/resume-task.sh <task> --prompt "<what stopped it, and continue task <task>>"`.
- **Not yet:** the same cause would stop it again, such as a usage limit, an authentication failure or a full disk. Report the cause and what would fix it.
- **Not again:** earlier resumes ended with the same error. Report instead of looping.
- **Can't:** the transcript or the worktree is gone. Release the merge queue (`${CLAUDE_SKILL_DIR}/scripts/merge-queue.sh release <dispatch_base> <task>`), then `wt remove -D <dispatch_branch>` so the next `wt switch --create` can reuse the branch, then propose to reopen the task: `bd update <task> --status open --unset-metadata dispatch_session --unset-metadata dispatch_host --unset-metadata dispatch_base --unset-metadata dispatch_branch --unset-metadata dispatch_started`. Do it only after the user agrees through AskUserQuestion.

Keep track of every task you decide on here: step 4 skips a `crashed` event for a task already decided in this step.

**Stopped or failed:** the worker ended without closing its task. Its comment says why. Report it with a next step: clarify the task, `/sdlc:split-task <task>`, or fix it by hand in its worktree. Don't dispatch it again yourself.

## 3. Dispatch

Run `${CLAUDE_SKILL_DIR}/scripts/dispatch-next.sh`. It starts the next ready tasks in work order, up to the parallel limit, and prints what it started, a `not started <task>: <reason>` line for each task it couldn't start, and a final `<n> of <parallel> workers running` line.

Report each `not started` reason. If nothing started and that final line shows 0 workers running, stop here and report instead of going on to step 4 — there is nothing left to watch.

## 4. Follow

Watch with the Monitor tool, with `persistent: true` so the watch doesn't time out while workers run, and command `${CLAUDE_SKILL_DIR}/scripts/watch.py`, plus `--epic <id>` when there is one. The watch takes no `--parallel`. A headless session keeps running while the watch lasts. Each line is an event:
- `ready <task>`, `ended <task> merged` or `ended <task> pr-opened`: run `dispatch-next.sh`. Say one short line at most. For `pr-opened`, give the pull request's URL (`dispatch_pr` on the task).
- `ended <task> stopped` or `ended <task> failed`: handle it as in step 2, tell the user, then run `dispatch-next.sh` to refill the slot it freed — unless the cause would stop any new worker too (a usage limit, an authentication failure, a full disk), in which case stop the watch and report instead.
- `ended <task> awaiting-review`: tell the user which task waits for their review, and the commands from `workers.py` (review the diff, request changes, or `bd gate resolve`). It resumes on its own once they resolve the gate.
- `crashed <task>`: skip it if step 2 already decided it this run. Otherwise handle it as in step 2, then run `dispatch-next.sh` under the same exception as above.
- `closed <epic>`: tell the user.
- `idle`: the watch ends. Go to step 5.

## 5. Report

Run `${CLAUDE_SKILL_DIR}/scripts/workers.py` again first, so the report reflects anything that changed since the last event.

- The epics and tasks closed, and what is still open or waiting.
- Each stopped, failed or crashed task, with its reason and next step.
- Each task waiting on a pull request: "run `/sdlc:dispatch` after it merges".
- The cost, from `${CLAUDE_SKILL_DIR}/scripts/stats.py`.
