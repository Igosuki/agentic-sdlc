---
name: stats
description: Show the cost, duration, models and agents of dispatched work, per task and per epic, from the attempts recorded in beads. Read-only.
argument-hint: "[epic-id]"
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/../dispatch/scripts/stats.py *)
---

# Stats

!`${CLAUDE_SKILL_DIR}/../dispatch/scripts/stats.py $ARGUMENTS 2>&1 || true`

Show the report above to the user as it is. Don't run anything else.
