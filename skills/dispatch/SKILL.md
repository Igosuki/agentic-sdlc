---
name: dispatch
description: Supervise the implementation of beads tasks. Confirms what's about to happen, then starts a supervisor script that dispatches ready tasks in work order, within the parallel limit, to worker sessions that each implement, merge and close one task in its own worktree; this session is woken only when a person is needed or new work appears. Takes any mix of task, parent task and epic ids, or all dispatchable work when given none. Use when tasks from sdlc:split are ready to implement, or after a restart to pick up dispatched work.
argument-hint: "[id...] [--parallel N]"
model: sonnet
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/workers.py *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/next-tasks.py *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/supervise.py *), Bash(bd *)
---

# Dispatch

Arguments: $ARGUMENTS

Settings:
!`${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh`

Supervisor:
!`${CLAUDE_PLUGIN_ROOT}/scripts/supervise.py --running 2>&1 || true`

Workers:
!`${CLAUDE_PLUGIN_ROOT}/scripts/workers.py 2>&1 || true`

Dispatch queue:
!`${CLAUDE_PLUGIN_ROOT}/scripts/next-tasks.py 2>&1 || true`

Each task is carried by a worker: a Claude session in the task's own worktree that implements the task, merges it and closes it. The supervisor is the script `${CLAUDE_PLUGIN_ROOT}/scripts/supervise.py`, run by this session in the background; you don't implement, merge or follow workers yourself.

The arguments are any mix of task, parent task and epic ids, in any order, or none for all dispatchable work. Each named id becomes a `--under <id>` for the supervisor: its scope is those beads and their descendants. When the arguments give a parallel limit, it's the one this session passes to `supervise.py` as `--parallel`.

## 1. Check what's named

For each named id, `bd show <id> --json` and look at its `dependencies` where `dependency_type` is `blocks` and `status` isn't `closed`. If there are any, the bead isn't ready: tell the user what it's waiting for (their ids and titles), and offer with AskUserQuestion to add those blockers to the dispatch too. If they agree, add the blockers' ids to the set of ids being dispatched.

## 2. Confirm

The workers and dispatch queue above are what's about to happen. Confirm with AskUserQuestion: the tasks that will start, the parallel limit, the integration mode and the target branch (from the settings above). In epic-merge and epic-pr modes, say that the first task dispatched creates the epic branch and an integration task that waits for the rest of the epic. If the Supervisor line above shows one running, say that dispatching replaces it — it may belong to another session. Skip this if `sdlc:build` invoked this command after its own plan already covered dispatching — it doesn't need a second approval. If AskUserQuestion isn't available (headless session), go ahead without asking. Never ask in plain text and stop.

## 3. Start the supervisor

Run `${CLAUDE_PLUGIN_ROOT}/scripts/supervise.py`, with `--under <id>` for each id from the arguments and step 1, and `--parallel N` if the arguments gave one, using the Bash tool with `run_in_background: true`, so this session stays free while it runs. Say nothing more than that it's running.

## 4. Act on what it exits with

`supervise.py` runs until a person is needed or new work appears, then prints lines and exits. When that background command finishes, read its output.

**Lines other than `taken over`:** start `supervise.py` again first, exactly as in step 3, so dispatching goes on while you deal with what follows. Then go through each line:
- `blocked <task> awaiting-review: <gate>` — suggest `/sdlc:review <task>`.
- `blocked <task> stopped: <comment>` or `blocked <task> failed: <comment>` — give the comment, suggest `/sdlc:recover <task>`.
- `blocked <task> pr-opened: <url>` — give the URL, for a person to review and merge.
- `blocked <task> not started: <reason>` — relay the reason.
- `new-work <id> <id>...` — ask with AskUserQuestion whether to dispatch those too. If they agree, start `supervise.py` once more with those ids added as `--under` — the newer run takes over the one you just started, and that one's `taken over` exit needs no reply. If AskUserQuestion isn't available (headless session), just relay the ids.

**Output with `taken over`:** don't start it again — unless you started the newer run yourself, for `new-work`. Say once that another session now supervises, and relay any other lines in that output as above.

**A non-zero exit with no lines:** relay stderr. Don't start it again.
