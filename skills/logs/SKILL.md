---
name: logs
description: Show what the workers of a dispatched task did, for each attempt: messages, tool calls, results and cost, from the worker logs. Read-only.
argument-hint: "<task-id>"
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/../dispatch/scripts/logs.sh *)
---

# Logs

!`${CLAUDE_SKILL_DIR}/../dispatch/scripts/logs.sh $ARGUMENTS 2>&1 | tail -80`

Show the output above to the user as it is. It keeps only the last 80 lines. Then add one line: the whole history is available with `${CLAUDE_SKILL_DIR}/../dispatch/scripts/logs.sh <task-id>` in a terminal (`--follow` for a running worker), and a worker's full conversation with `claude --resume <session> --fork-session`. Don't run anything else.
