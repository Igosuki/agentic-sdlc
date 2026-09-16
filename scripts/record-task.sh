#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: record-task.sh <task-id>

Records a worker's attempt once its process has ended. Run by the wrapper that
run-task.sh and resume-task.sh start, or by hand if that wrapper died.

From the result lines of the worker log, it sets on the task:
  dispatch_state   merged (task closed), pr-opened (an epic-pr integration task opened its PR),
                   awaiting-review (a human review gate blocks it), failed (session ended
                   in error), or stopped
  dispatch_cost    the session's cost, over every run (a resume is a new run)
  dispatch_model, dispatch_agents
and creates a closed event bead dispatch.<state> targeting the task, with the
worker's final message as its description. For a merged task it then removes
the worktree, unless untracked files are left in it. A task awaiting review
keeps its worktree.

A log without a result means the worker didn't end normally: nothing is
recorded, and the task stays claimed with no outcome recorded, which shows as
crashed.

Exit codes: 0 recorded, 1 no result to record, 2 invalid arguments.
EOF
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
[[ $# -eq 1 && "$1" != -* ]] || { usage >&2; exit 2; }
id="$1"
dir=$(dirname "$(readlink -f "$0")")

task=$(bd show "$id" --json 2>/dev/null | jq '.[0]' 2>/dev/null) || { echo "error: no bead $id" >&2; exit 2; }
get() { jq -r "$1 // empty" <<<"$task"; }
session=$(get .metadata.dispatch_session)
branch=$(get .metadata.dispatch_branch)
agent=$(get .metadata.execution_agent_type)
[[ -n "$session" ]] || { echo "error: $id was never dispatched" >&2; exit 2; }

log="$(git rev-parse --path-format=absolute --git-common-dir)/sdlc/logs/$id-$session.jsonl"
# A worker killed mid-write leaves a truncated line, so every reader parses line by line.
results=$(jq -cR 'fromjson? | select(.type == "result")' "$log" 2>/dev/null) || results=""
[[ -n "$results" ]] || { echo "no result for $id in $log: the worker didn't end normally"; exit 1; }
last=$(tail -1 <<<"$results")

read -r cost turns seconds < <("$dir/tasks.py" log-totals "$log")
models=$(jq -rs 'map(.modelUsage // {} | keys) | add | unique | join(",")' <<<"$results")
agents=$( { [[ -z "$agent" ]] || echo "$agent"
  jq -rR 'fromjson? | select(.type == "assistant") | .message.content[]?
    | select(.type == "tool_use" and (.name == "Agent" or .name == "Task"))
    | .input.subagent_type // "general-purpose"' "$log" 2>/dev/null; } | sort -u | paste -sd, -)
summary=$(jq -r '.result // empty' <<<"$last")

if [[ -n "$(get .metadata.dispatch_pr)" ]]; then
  state=pr-opened
elif [[ "$(get .status)" == closed ]]; then
  state=merged
elif [[ "$(get .metadata.dispatch_state)" == awaiting-review ]]; then
  state=awaiting-review
elif [[ "$(jq -r .is_error <<<"$last")" == true ]]; then
  state=failed
else
  state=stopped
fi

meta=(--set-metadata "dispatch_state=$state" --set-metadata "dispatch_cost=$cost")
[[ -z "$models" ]] || meta+=(--set-metadata "dispatch_model=$models")
[[ -z "$agents" ]] || meta+=(--set-metadata "dispatch_agents=$agents")
bd update "$id" "${meta[@]}" >/dev/null

payload=$(jq -cn --arg session "$session" --arg model "$models" --arg agents "$agents" \
  --argjson cost "$cost" --argjson turns "$turns" --argjson seconds "$seconds" \
  --arg branch "$branch" --arg base "$(get .metadata.dispatch_base)" --arg host "$(get .metadata.dispatch_host)" \
  --arg subtype "$(jq -r '.subtype // empty' <<<"$last")" --arg log "$log" \
  '{session: $session, model: $model, agents: ($agents | split(",")), cost_usd: $cost, turns: $turns,
    duration_s: $seconds, branch: $branch, base: $base, host: $host, result: $subtype, log: $log}
   | with_entries(select(.value != "" and .value != []))')
event=$(bd create "$id $state" --type event --event-target "$id" --event-category "dispatch.$state" \
  --event-actor "${agents:-${models:-worker}}" --event-payload "$payload" \
  --description "${summary:-no final message}" --silent)
bd close "$event" >/dev/null

note=""
if [[ "$state" == merged || "$state" == pr-opened ]] && [[ -n "$branch" ]]; then
  if wt remove "$branch" </dev/null >/dev/null 2>"$log.remove"; then
    # A task branch rebased into an epic branch isn't an ancestor of it, so wt keeps the branch.
    ! git rev-parse --verify --quiet "refs/heads/$branch" >/dev/null || git branch -D "$branch" >/dev/null
  else
    note=" · worktree kept, see $log.remove"
  fi
fi
LC_NUMERIC=C printf '%s %s · $%.2f · %dm%02ds · %s · event %s%s\n' "$state" "$id" "$cost" \
  $((seconds / 60)) $((seconds % 60)) "${agents:-${models:-no model}}" "$event" "$note"
