#!/usr/bin/env bash
# In a worker session, blocks the first attempt to stop while the task is claimed by this session
# (in_progress, dispatch_session matching, no outcome recorded) and the worker hasn't commented since
# it was dispatched. A second attempt (stop_hook_active) is let through.
set -euo pipefail
[[ -n "${DISPATCH_TASK:-}" ]] || { cat >/dev/null; exit 0; }
input=$(cat)
[[ "$(jq -r '.stop_hook_active // false' <<<"$input")" != true ]] || exit 0
this_session=$(jq -r '.session_id // empty' <<<"$input")

task=$(bd show "$DISPATCH_TASK" --json 2>/dev/null | jq '.[0]' 2>/dev/null) || exit 0
status=$(jq -r .status <<<"$task")
claimed_session=$(jq -r '.metadata.dispatch_session // empty' <<<"$task")
state=$(jq -r '.metadata.dispatch_state // empty' <<<"$task")
[[ -n "$claimed_session" && "$status" == in_progress && "$claimed_session" == "$this_session" \
  && ( "$state" == "" || "$state" == running ) ]] || exit 0
started=$(jq -r '.metadata.dispatch_started // empty' <<<"$task")
comments=$(bd comments "$DISPATCH_TASK" --json 2>/dev/null | jq --arg s "$started" '[.[]? | select(.created_at >= $s)] | length' 2>/dev/null) || comments=0
[[ "$comments" -eq 0 ]] || exit 0

finish="${CLAUDE_PLUGIN_ROOT}/scripts/finish-task.sh $DISPATCH_TASK"
jq -cn --arg r "Task $DISPATCH_TASK isn't closed. Commit your work and run $finish. If you can't finish, record what's missing with: bd comments add $DISPATCH_TASK \"<what's missing>\"." \
  '{decision: "block", reason: $r}'
