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

In every script call below, pass `--epic <id>` when the arguments name an epic, and `--parallel <N>` when they give one.

## 1. Look

- `${CLAUDE_SKILL_DIR}/scripts/workers.sh`: dispatched tasks that aren't closed, with their state (running, crashed, stopped or failed).
- `${CLAUDE_SKILL_DIR}/scripts/next-tasks.sh`: ready tasks in work order.

Confirm with AskUserQuestion what is about to happen: the tasks that will start, the parallel limit, the integration mode and the target branch. If AskUserQuestion isn't available (headless session), go ahead. Never ask in plain text and stop.

## 2. Handle crashed and stopped workers

**Crashed** (`dispatch_state=running`, no process): decide from the evidence `workers.sh` prints. For more, such as the full log, have a reading agent answer a precise question.
- **The log has a result:** the worker ended, but its attempt wasn't recorded. Run `${CLAUDE_SKILL_DIR}/scripts/record-task.sh <task>`.
- **Resume:** the transcript and worktree exist, and the cause is gone: a shutdown, a killed process, a transient error. A stop with no error is a reason to resume, even if it happened before. Run `${CLAUDE_SKILL_DIR}/scripts/resume-task.sh <task> --prompt "<what stopped it, and continue task <task>>"`.
- **Not yet:** the same cause would stop it again, such as a usage limit, an authentication failure or a full disk. Report the cause and what would fix it.
- **Not again:** earlier resumes ended with the same error. Report instead of looping.
- **Can't:** the transcript or the worktree is gone. Propose to reopen the task: `wt remove <branch>` if the worktree exists, then `bd update <task> --status open --unset-metadata dispatch_state --unset-metadata dispatch_session`. Do it only after the user agrees through AskUserQuestion.

**Stopped or failed:** the worker ended without closing its task. Its comment says why. Report it with a next step: clarify the task, `/sdlc:split-task <task>`, or fix it by hand in its worktree. Don't dispatch it again yourself.

## 3. Dispatch

Run `${CLAUDE_SKILL_DIR}/scripts/dispatch-next.sh`. It starts the next ready tasks in work order, up to the parallel limit, and prints what it started.

## 4. Follow

Watch with the Monitor tool, `persistent: true`, command `${CLAUDE_SKILL_DIR}/scripts/watch.sh`. A headless session keeps running while the watch lasts. Each line is an event:
- `ready <task>`, `ended <task> merged` or `ended <task> pr-opened`: run `dispatch-next.sh`. Say one short line at most. For `pr-opened`, give the pull request's URL (`dispatch_pr` on the task).
- `ended <task> stopped` or `ended <task> failed`: handle it as in step 2, and tell the user.
- `crashed <task>`: handle it as in step 2.
- `closed <epic>`: tell the user.
- `idle`: the watch ends. Report.

## 5. Report

- The epics and tasks closed, and what is still open or waiting.
- Each stopped, failed or crashed task, with its reason and next step.
- The cost, from `${CLAUDE_PLUGIN_ROOT}/skills/stats/scripts/stats.sh`.
