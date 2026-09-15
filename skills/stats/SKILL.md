---
name: stats
description: Show the cost, duration, models and agents of dispatched work, per task and per epic, from the attempts recorded in beads. Read-only.
argument-hint: "[epic-id]"
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/stats.sh *)
---

# Stats

!`${CLAUDE_SKILL_DIR}/scripts/stats.sh $ARGUMENTS`

Show the report above to the user as it is. Don't run anything else.
