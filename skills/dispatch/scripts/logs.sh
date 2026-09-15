#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: logs.sh <task-id> [--follow] [--raw]

Shows what a task's workers did, from their logs in .git/sdlc/logs: every
attempt, oldest first, as readable lines. Messages, tool calls, tool results
(shortened), and each run's cost.

Options:
  --follow   after the history, keep printing what the current worker writes
  --raw      print the log files of each attempt instead

To open a worker's whole conversation in Claude Code, without changing it:
  claude --resume <session> --fork-session

Exit codes: 0 shown, 1 no log, 2 invalid arguments.
EOF2
}

id="" follow=false raw=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --follow) follow=true ;;
    --raw) raw=true ;;
    -*) echo "error: unknown option $1" >&2; usage >&2; exit 2 ;;
    *)
      [[ -z "$id" ]] || { echo "error: one task at a time" >&2; usage >&2; exit 2; }
      id="$1" ;;
  esac
  shift
done
[[ -n "$id" ]] || { usage >&2; exit 2; }

task=$(bd show "$id" --json 2>/dev/null | jq '.[0]' 2>/dev/null) || { echo "error: no bead $id" >&2; exit 2; }
current=$(jq -r '.metadata.dispatch_session // empty' <<<"$task")
logs="$(git rev-parse --path-format=absolute --git-common-dir)/sdlc/logs"
sessions=$( { bd list --type event --all --limit 0 --json |
    jq -r --arg id "$id" '[.[] | select(.target == $id)] | sort_by(.created_at) | .[] | .payload | try fromjson catch {} | .session // empty'
  [[ -z "$current" ]] || echo "$current"; } | awk '!seen[$0]++')
[[ -n "$sessions" ]] || { echo "$id was never dispatched"; exit 1; }

render='fromjson? | (
  if .type == "dispatch_run" then "── run started \(.started)"
  elif .type == "assistant" then
    (if .parent_tool_use_id then "    " else "" end) as $in
    | .message.content[]?
    | if .type == "text" then "\($in)● \(.text)"
      elif .type == "tool_use" then "\($in)→ \(.name) \((.input.command // .input.file_path // .input.pattern // .input.skill // .input.description // "") | tostring | .[0:300])"
      else empty end
  elif .type == "user" then
    (if .parent_tool_use_id then "    " else "" end) as $in
    | .message.content[]? | select(.type == "tool_result")
    | "\($in)  \(if .is_error then "✗" else "←" end) \((.content | if type == "array" then map(.text? // "") | join(" ") else tostring end) | gsub("\\s+"; " ") | .[0:200])"
  elif .type == "result" then "── result \(.subtype) · $\(.total_cost_usd) · \(.num_turns) turns"
  else empty end)'

for session in $sessions; do
  log="$logs/$id-$session.jsonl"
  if $raw; then
    ls "$log"* 2>/dev/null || echo "missing: $log"
    continue
  fi
  echo "═══ $id · session $session"
  if [[ -f "$log" ]]; then
    jq -rR "$render" "$log" 2>/dev/null || echo "(unreadable log $log)"
    [[ ! -s "$log.err" ]] || { echo "── stderr"; cat "$log.err"; }
    [[ ! -s "$log.record" ]] || { echo "── recorded"; cat "$log.record"; }
  else
    echo "(no log at $log)"
  fi
done

if $follow && ! $raw && [[ -n "$current" ]]; then
  echo "═══ following $id · session $current (Ctrl-C to stop)"
  tail -n 0 -F "$logs/$id-$current.jsonl" | jq -rR --unbuffered "$render"
fi
