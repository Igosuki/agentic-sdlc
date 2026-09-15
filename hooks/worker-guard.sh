#!/usr/bin/env bash
# In a worker session, denies the Bash commands that would close or merge work outside finish-task.sh.
set -euo pipefail
[[ -n "${DISPATCH_TASK:-}" ]] || { cat >/dev/null; exit 0; }
cmd=$(jq -r '.tool_input.command // empty')

deny() {
  jq -cn --arg r "$1" '{hookSpecificOutput: {hookEventName: "PreToolUse", permissionDecision: "deny", permissionDecisionReason: $r}}'
  exit 0
}
start='(^|[;&|(`[:space:]])'
finish="${CLAUDE_PLUGIN_ROOT}/skills/dispatch/scripts/finish-task.sh $DISPATCH_TASK"

[[ ! "$cmd" =~ ${start}bd[[:space:]]+(close|done)([[:space:]]|$) ]] \
  || deny "Workers don't close issues with bd. Run $finish: it merges and closes the task, and the epic when it is done."
[[ ! "$cmd" =~ ${start}bd[[:space:]]+update[[:space:]].*--status[=[:space:]]+closed ]] \
  || deny "Workers don't close issues with bd. Run $finish: it merges and closes the task."
[[ ! "$cmd" =~ ${start}wt[[:space:]]+merge([[:space:]]|$) ]] \
  || deny "Workers don't merge with wt. Run $finish: it rebases, verifies and merges through the merge queue."
[[ ! "$cmd" =~ ${start}git[[:space:]]+push([[:space:]]|$) ]] \
  || deny "Workers don't push. Run $finish: it merges, or pushes and opens the PR in epic-pr mode."
[[ ! "$cmd" =~ ${start}bd[[:space:]]+gate[[:space:]]+(resolve|close)([[:space:]]|$) ]] \
  || deny "Workers don't resolve review gates. A person runs bd gate resolve after reviewing."
[[ ! "$cmd" =~ (--set-metadata|--unset-metadata)(=|[[:space:]]+)[\"\']?(review|dispatch_review[a-zA-Z_]*)([=[:space:]\"\']|$) ]] \
  || deny "Workers don't set the review verdict. $finish manages review and dispatch_review* metadata."
exit 0
