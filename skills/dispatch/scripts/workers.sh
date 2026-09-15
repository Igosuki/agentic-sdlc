#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: workers.sh [--epic EPIC] [--alive-count]

Lists dispatched tasks that aren't closed, with where their worker runs:
  running   the worker's process is alive
  crashed   dispatch_state=running but no process runs its session; followed by
            the evidence to decide on resuming: worktree, commits, uncommitted
            files, transcript, log runs and result, last events, stderr
  stopped / failed   the worker ended without closing the task; followed by
            the task's last comment

Options:
  --epic EPIC     only tasks whose parent is EPIC
  --alive-count   print only the number of live workers on this machine

Exit codes: 0 listed, 2 invalid arguments.
EOF2
}

epic="" count=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --alive-count) count=true ;;
    --epic)
      [[ $# -ge 2 ]] || { echo "error: --epic needs a value" >&2; usage >&2; exit 2; }
      epic="$2"; shift ;;
    *) echo "error: unknown argument $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

logs="$(git rev-parse --path-format=absolute --git-common-dir)/sdlc/logs"
alive() { pgrep -f -- "--(session-id|resume) $1" >/dev/null; }
tasks=$(bd list --status in_progress --has-metadata-key dispatch_session --limit 0 --json |
  jq -c --arg e "$epic" '.[] | select($e == "" or .parent == $e)')

if $count; then
  n=0
  while IFS= read -r task; do
    [[ -n "$task" ]] || continue
    alive "$(jq -r .metadata.dispatch_session <<<"$task")" && n=$((n + 1))
  done <<<"$tasks"
  echo "$n"
  exit 0
fi

[[ -n "$tasks" ]] || { echo "no dispatched task in progress"; exit 0; }
worktrees=$(wt list --format json </dev/null 2>/dev/null || echo '{"items": []}')
now=$(date +%s)
ago() { local s=$((now - $1)); if ((s < 120)); then echo "${s}s"; elif ((s < 7200)); then echo "$((s / 60))m"; else echo "$((s / 3600))h"; fi; }

while IFS= read -r task; do
  get() { jq -r "$1 // empty" <<<"$task"; }
  id=$(get .id) session=$(get .metadata.dispatch_session) state=$(get .metadata.dispatch_state)
  branch=$(get .metadata.dispatch_branch) base=$(get .metadata.dispatch_base)
  log="$logs/$id-$session.jsonl"
  wt_path=$(jq -r --arg b "$branch" '.items[] | select(.branch == $b) | .worktree.path // empty' <<<"$worktrees")
  started=$( [[ -f "$log.wt" ]] && ago "$(stat -c %Y "$log.wt")" || echo "?")
  output=$( [[ -f "$log" ]] && ago "$(stat -c %Y "$log")" || echo "never")

  if [[ "$state" == running ]] && alive "$session"; then
    echo "$id  running  on $(get .metadata.dispatch_host)  started $started ago  last output $output ago  \"$(get .title)\""
  elif [[ "$state" == running ]]; then
    echo "$id  crashed  on $(get .metadata.dispatch_host)  started $started ago  last output $output ago  \"$(get .title)\""
    echo "  session: $session"
    echo "  transcript: $(find ~/.claude/projects -name "$session.jsonl" -print -quit 2>/dev/null | grep . || echo missing)"
    if [[ -n "$wt_path" && -d "$wt_path" ]]; then
      echo "  worktree: $wt_path"
      echo "  commits since $base: $(git -C "$wt_path" rev-list --count "$base..HEAD" 2>/dev/null || echo unknown)"
      echo "  uncommitted: $(git -C "$wt_path" status --porcelain | cut -c4- | paste -sd' ' - | grep . || echo none)"
    else
      echo "  worktree: missing"
    fi
    if [[ -f "$log" ]]; then
      echo "  log: $log"
      echo "  worker runs: $(jq -c 'select(.type == "dispatch_run")' "$log" 2>/dev/null | wc -l)"
      result=$(jq -r 'select(.type == "result") | "\(.subtype) (error: \(.is_error))"' "$log" 2>/dev/null | tail -1)
      echo "  result: ${result:-none}"
      echo "  last events:"
      jq -r 'select(.type == "assistant" or .type == "user") | .message.content[]?
        | if .type == "tool_use" then "tool call \(.name): \((.input.command // .input.file_path // .input.description // "") | tostring)"
          elif .type == "text" then "text: \(.text)"
          elif .type == "tool_result" then "tool result\(if .is_error then " (error)" else "" end): \(.content | if type == "array" then map(.text? // "") | join(" ") else tostring end)"
          else empty end
        | gsub("\\s+"; " ") | .[0:160]' "$log" 2>/dev/null | tail -6 | sed 's/^/    /'
    else
      echo "  log: missing"
    fi
    [[ ! -s "$log.err" ]] || { echo "  stderr:"; tail -5 "$log.err" | sed 's/^/    /'; }
    echo "  machine booted: $(uptime -s 2>/dev/null || echo unknown)"
  else
    comment=$(bd comments "$id" --json 2>/dev/null | jq -r 'last | .text // empty' 2>/dev/null | tr '\n' ' ' | cut -c1-300)
    echo "$id  $state  on $(get .metadata.dispatch_host)  worktree ${wt_path:-missing}  \"$(get .title)\""
    if [[ "$state" == pr-opened ]]; then
      echo "  pull request: $(get .metadata.dispatch_pr), waiting for its merge"
    else
      echo "  last comment: ${comment:-none}"
    fi
  fi
done <<<"$tasks"
