#!/usr/bin/env bash
# In a worker session, blocks the first attempt to stop while the task is still open and the worker
# hasn't commented since it was dispatched. A second attempt (stop_hook_active) is let through.
set -euo pipefail
[[ -n "${DISPATCH_TASK:-}" ]] || { cat >/dev/null; exit 0; }
[[ "$(jq -r '.stop_hook_active // false')" != true ]] || exit 0

task=$(bd show "$DISPATCH_TASK" --json 2>/dev/null | jq '.[0]' 2>/dev/null) || exit 0
[[ "$(jq -r .status <<<"$task")" != closed && "$(jq -r '.metadata.dispatch_state // empty' <<<"$task")" == running ]] || exit 0
started=$(jq -r '.metadata.dispatch_started // empty' <<<"$task")
comments=$(bd comments "$DISPATCH_TASK" --json 2>/dev/null | jq --arg s "$started" '[.[]? | select(.created_at >= $s)] | length' 2>/dev/null) || comments=0
[[ "$comments" -eq 0 ]] || exit 0

finish="${CLAUDE_PLUGIN_ROOT}/skills/dispatch/scripts/finish-task.sh $DISPATCH_TASK"
jq -cn --arg r "Task $DISPATCH_TASK isn't closed. Commit your work and run $finish. If you can't finish, record what's missing with: bd comments add $DISPATCH_TASK \"<what's missing>\"." \
  '{decision: "block", reason: $r}'
