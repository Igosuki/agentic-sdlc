---
name: stop
description: Stop running workers — a task's own, every worker under an epic, or every running worker when given neither. Ends the process, releases the merge queue, and leaves the task stopped with a comment. Use when work needs to pause.
argument-hint: "[task-id|epic-id]"
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/workers.py *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/stop-task.sh *), Bash(bd show *)
---

# Stop

Arguments: $ARGUMENTS

Workers:
!`${CLAUDE_PLUGIN_ROOT}/scripts/workers.py 2>&1 || true`

## 1. Find what will stop

- **No arguments:** every worker listed above as `running`.
- **A task id:** that task's own line above, if it says `running`.
- **An epic id:** run `bd show <id> --json`. If `issue_type` is `epic`, run `${CLAUDE_PLUGIN_ROOT}/scripts/workers.py --epic <id>` and take its `running` lines.

If nothing found is running, say so and stop; there's nothing to do.

## 2. Confirm

List the tasks that will stop. Confirm with AskUserQuestion. If AskUserQuestion isn't available (headless session), stop here without running anything: report which workers would have stopped.

## 3. Stop them

Run `${CLAUDE_PLUGIN_ROOT}/scripts/stop-task.sh <id>` — once for the id given, or once per running task found in step 1 when none was given. Report what each run printed.

To pick a stopped task back up later, use `/sdlc:recover <task>`.
