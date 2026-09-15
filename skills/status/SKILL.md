---
name: status
description: Show dispatched work at a glance, read-only. Lists where workers run, crashed or stopped tasks, the ready queue in work order, and the dispatch settings.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/skills/dispatch/scripts/*)
---

# Status

## Workers

!`${CLAUDE_PLUGIN_ROOT}/skills/dispatch/scripts/workers.sh`

## Ready queue

!`${CLAUDE_PLUGIN_ROOT}/skills/dispatch/scripts/next-tasks.sh`

## Settings

!`${CLAUDE_PLUGIN_ROOT}/skills/dispatch/scripts/settings.sh`

Show the three sections above to the user as they are. Then, if a task is crashed, stopped or failed, add one line naming it and suggesting `/sdlc:dispatch`. Don't run anything else.
