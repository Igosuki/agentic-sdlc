---
name: dispatch
description: Supervise the implementation of beads tasks. Confirms what's about to happen, then starts a supervisor that dispatches ready tasks in work order, within the parallel limit, to worker sessions that each implement, merge and close one task in its own worktree, and follows them until nothing is left. Takes an epic, or all dispatchable work when given none. Use when tasks from sdlc:split are ready to implement, or after a restart to pick up dispatched work.
argument-hint: "[epic-id] [--parallel N]"
model: sonnet
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/workers.py *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/next-tasks.py *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/merge-queue.sh *), Bash(bd *), Bash(wt remove *), Agent
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

When the arguments name an epic, it's the one the supervisor works on; otherwise all dispatchable work. When they give a parallel limit, it's the one the supervisor passes on to `dispatch-next.sh`.

## 1. Confirm

The workers and dispatch queue above are what's about to happen. Confirm with AskUserQuestion: the tasks that will start, the parallel limit, the integration mode and the target branch (from the settings above). Skip this if `sdlc:build` invoked this command after its own plan already covered dispatching — it doesn't need a second approval. If AskUserQuestion isn't available (headless session), go ahead without asking. Never ask in plain text and stop.

## 2. Start the supervisor

Start `sdlc:supervisor` with the Agent tool (`subagent_type: sdlc:supervisor`), in the background, so this session stays usable while it runs. Its prompt is the epic id, if the arguments name one, and the parallel limit, if they give one.

## 3. Relay and decide

The supervisor reports back once it has nothing left to watch: epics and tasks closed, stopped, failed or crashed tasks with their reasons and next steps, tasks waiting on a pull request, `Can't` tasks it left claimed because their transcript or worktree is gone, and the cost. Relay this to the user as it comes in.

For each `Can't` task, ask the user with AskUserQuestion whether to reopen it. If they agree, run all three steps the supervisor named, in order: `${CLAUDE_PLUGIN_ROOT}/scripts/merge-queue.sh release <dispatch_base> <task>`, so the dead session stops holding that branch's queue and the next task can merge; `wt remove -D <dispatch_branch>` so the branch can be reused; then `bd update <task> --status open --unset-metadata dispatch_session --unset-metadata dispatch_host --unset-metadata dispatch_base --unset-metadata dispatch_branch --unset-metadata dispatch_started`. For anything else the supervisor flagged that needs a person, ask the same way, and do what they decide.

Once you've acted on a decision, start `sdlc:supervisor` again (Agent tool, in the background, same epic and parallel limit) so dispatching continues — a freshly reopened task, or anything else that changed, only gets picked up by a new look at beads.
