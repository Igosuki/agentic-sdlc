---
name: status
description: Show dispatched work at a glance, read-only. Lists running, crashed, stopped and failed workers, tasks waiting on a pull request, the dispatch queue in work order, and the sdlc settings.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/workers.py *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/next-tasks.py *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh *)
---

# Status

## Workers

!`${CLAUDE_PLUGIN_ROOT}/scripts/workers.py 2>&1 || true`

## Dispatch queue

!`${CLAUDE_PLUGIN_ROOT}/scripts/next-tasks.py 2>&1 || true`

## Settings

!`${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh 2>&1 || true`

Show the three sections above to the user unchanged, in code blocks. Then add one line per task that needs attention:
- crashed: `/sdlc:dispatch` resumes it or says why it can't.
- stopped or failed: its last comment says why. `/sdlc:logs <task>` shows what the worker did. Next step: clarify the task, `/sdlc:split <task>`, or fix it by hand in its worktree.
- awaiting-review: use the review commands shown above (review the diff, request changes, or `bd gate resolve`).

Don't run anything else.
