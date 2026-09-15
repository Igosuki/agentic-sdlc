---
name: logs
description: Show what the workers of a dispatched task did, for each attempt: messages, tool calls, results and cost, from the worker logs. Read-only.
argument-hint: "<task-id>"
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/../dispatch/scripts/logs.py *)
---

# Logs

!`${CLAUDE_SKILL_DIR}/../dispatch/scripts/logs.py --last 80 $ARGUMENTS 2>&1 || true`

Show the output above to the user as it is. Then add one line: the whole history is available with `${CLAUDE_SKILL_DIR}/../dispatch/scripts/logs.py <task-id>` from the repository (`--follow` for a running worker, in a terminal), and a worker's full conversation with `claude --resume <session> --fork-session`. Don't run anything else.
