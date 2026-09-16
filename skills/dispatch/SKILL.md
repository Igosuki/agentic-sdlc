---
name: dispatch
description: Supervise the implementation of beads tasks. Confirms what's about to happen, then starts a supervisor that dispatches ready tasks in work order, within the parallel limit, to worker sessions that each implement, merge and close one task in its own worktree, and reports the moment a person is needed. Takes any mix of task, parent task and epic ids, or all dispatchable work when given none. Use when tasks from sdlc:split are ready to implement, or after a restart to pick up dispatched work.
argument-hint: "[id...] [--parallel N]"
model: sonnet
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/workers.py *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/next-tasks.py *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/reset-task.sh *), Bash(bd *), Agent
---

# Dispatch

Arguments: $ARGUMENTS

Settings:
!`${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh`

Workers:
!`${CLAUDE_PLUGIN_ROOT}/scripts/workers.py 2>&1 || true`

Dispatch queue:
!`${CLAUDE_PLUGIN_ROOT}/scripts/next-tasks.py 2>&1 || true`

Each task is carried by a worker: a Claude session in the task's own worktree that implements the task, merges it and closes it. The `sdlc:supervisor` agent starts and follows workers; you don't implement, merge or follow workers yourself.

The arguments are any mix of task, parent task and epic ids, in any order, or none for all dispatchable work. Each named id becomes a `--under <id>` for the supervisor: its scope is those beads and their descendants. When the arguments give a parallel limit, it's the one the supervisor passes on to `dispatch-next.sh`.

## 1. Check what's named

For each named id, `bd show <id> --json` and look at its `dependencies` where `dependency_type` is `blocks` and `status` isn't `closed`. If there are any, the bead isn't ready: tell the user what it's waiting for (their ids and titles), and offer with AskUserQuestion to add those blockers to the dispatch too. If they agree, add the blockers' ids to the set of ids being dispatched.

## 2. Confirm

The workers and dispatch queue above are what's about to happen. Confirm with AskUserQuestion: the tasks that will start, the parallel limit, the integration mode and the target branch (from the settings above). In epic-merge and epic-pr modes, say that the first task dispatched creates the epic branch and an integration task that waits for the rest of the epic. Skip this if `sdlc:build` invoked this command after its own plan already covered dispatching — it doesn't need a second approval. If AskUserQuestion isn't available (headless session), go ahead without asking. Never ask in plain text and stop.

## 3. Start the supervisor

Start `sdlc:supervisor` with the Agent tool (`subagent_type: sdlc:supervisor`), in the background, so this session stays usable while it runs. Its prompt is the ids from the arguments (and any added in step 1), if there are any, and the parallel limit, if the arguments give one.

## 4. Relay and decide

The supervisor ends its run and reports as soon as one task newly needs a person: awaiting review, stopped, failed, or a `Can't` task it left claimed because its transcript or worktree is gone. It also reports the full summary once nothing is left to watch: epics and tasks closed, tasks still waiting on a person, tasks waiting on a pull request, and the cost.

Keep a list, for this session, of task ids you've already reported as needing a person. The moment a report comes in, start `sdlc:supervisor` again (Agent tool, in the background, same ids and parallel limit, plus `already reported: <ids>` from that list if it isn't empty) so dispatching keeps going while you deal with the report, without the same task ending its run again before anyone has acted. Then act on what it sent:
- **Awaiting review:** suggest `/sdlc:review <task>`. Add the task to the already-reported list.
- **Stopped or failed:** suggest `/sdlc:recover <task>`. Add the task to the already-reported list.
- **Can't:** ask the user with AskUserQuestion whether to reopen it. If they agree, run `${CLAUDE_PLUGIN_ROOT}/scripts/reset-task.sh <task>` — it releases the merge queue, removes the worktree and reopens the task with its `dispatch_*` metadata unset — and drop it from the already-reported list, since reopened it isn't waiting on a person any more. A freshly reopened task only gets picked up by a new look at beads, which the supervisor you just restarted will take. If they decline, add it to the already-reported list so it isn't reported again this session.
- **The full summary:** relay it to the user, including anything it still lists as waiting on a person. Drop from the already-reported list any task the summary no longer lists that way — it's been reviewed, recovered or otherwise resolved outside this session.
