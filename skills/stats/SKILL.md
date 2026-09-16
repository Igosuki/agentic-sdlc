---
name: stats
description: Show the cost, duration, models and agents of dispatched work, per task and per epic, from the attempts recorded in beads. Read-only.
argument-hint: "[epic-id]"
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/stats.py *)
---

# Stats

!`${CLAUDE_PLUGIN_ROOT}/scripts/stats.py $ARGUMENTS 2>&1 || true`

Show the report above to the user as it is. Don't run anything else.
