#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: stop-task.sh <task-id|epic-id>

Ends running workers. Given a task, stops its own worker, if one is running.
Given an epic, stops every running worker under it, at any depth (tasks.py
epic, the same lookup workers.py uses for --under).

For each worker stopped:
  1. sets dispatch_state=stopped, before signalling the process, so a task
     that shows as crashed mid-stop still reads as stopped instead
  2. sends the process TERM, then KILL if it's still running after a short wait
  3. releases the branch's merge queue (merge-queue.sh release)
  4. waits for start-worker.sh's own record-task.sh call (it runs once the
     process ends) to finish, then sets dispatch_state=stopped again, so
     whichever of the two writes last, the task still ends up stopped
  5. adds a comment saying a person stopped it

A task, or an epic, with no running worker is reported, unchanged.

Exit codes: 0 done (something was stopped, or nothing needed to be),
  2 invalid arguments or no such bead.
EOF
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
[[ $# -eq 1 && "$1" != -* ]] || { usage >&2; exit 2; }
id="$1"
dir=$(dirname "$(readlink -f "$0")")

task=$(bd show "$id" --json 2>/dev/null | jq '.[0]' 2>/dev/null) || { echo "error: no bead $id" >&2; exit 2; }
issue_type=$(jq -r '.issue_type // empty' <<<"$task")

all=$(bd list --all --limit 0 --json)

esc() { sed 's/[.[\*^$]/\\&/g' <<<"$1"; }

pids_matching() {
  local t_esc s_esc pattern
  t_esc=$(esc "$1")
  s_esc=$(esc "$2")
  pattern="(run-task\.sh ${t_esc}\b|--(session-id|resume) ${s_esc}\b)"
  pgrep -af "$pattern" 2>/dev/null | grep -v -- '--fork-session' | awk '{print $1}' || true
}

wait_until_gone() {
  local task_id="$1" session="$2" timeout="$3"
  local deadline=$(( $(date +%s) + timeout ))
  while [[ -n "$(pids_matching "$task_id" "$session")" ]] && (( $(date +%s) < deadline )); do
    sleep 0.5
  done
}

stop_one() {
  local t="$1" t_json session base pids
  t_json=$(jq -c --arg id "$t" '.[] | select(.id == $id)' <<<"$all")
  session=$(jq -r '.metadata.dispatch_session // empty' <<<"$t_json")
  base=$(jq -r '.metadata.dispatch_base // empty' <<<"$t_json")

  bd update "$t" --set-metadata dispatch_state=stopped >/dev/null

  pids=$(pids_matching "$t" "$session")
  if [[ -n "$pids" ]]; then
    kill -TERM $pids 2>/dev/null || true
    wait_until_gone "$t" "$session" 5
    pids=$(pids_matching "$t" "$session")
    if [[ -n "$pids" ]]; then
      kill -KILL $pids 2>/dev/null || true
      wait_until_gone "$t" "$session" 2
    fi
  fi

  [[ -z "$base" ]] || "$dir/merge-queue.sh" release "$base" "$t" >/dev/null

  local deadline=$(( $(date +%s) + 10 ))
  while pgrep -f "record-task\.sh $(esc "$t")\b" >/dev/null 2>&1 && (( $(date +%s) < deadline )); do
    sleep 0.5
  done
  bd update "$t" --set-metadata dispatch_state=stopped >/dev/null
  bd comments add "$t" "Stopped by a person." >/dev/null
  echo "stopped $t"
}

if [[ "$issue_type" == epic ]]; then
  mapfile -t dispatched < <(jq -r '.[] | select(.status == "in_progress" and (.metadata.dispatch_session // "") != "") | .id' <<<"$all")
  targets=()
  for candidate in "${dispatched[@]}"; do
    epic_id=$("$dir/tasks.py" epic "$candidate" <<<"$all")
    [[ "$epic_id" == "$id" ]] || continue
    running=$("$dir/tasks.py" worker "$candidate" <<<"$all")
    [[ "$running" == true ]] || continue
    targets+=("$candidate")
  done
  if [[ ${#targets[@]} -eq 0 ]]; then
    echo "$id: no running worker under it"
    exit 0
  fi
  for t in "${targets[@]}"; do
    stop_one "$t"
  done
else
  running=$("$dir/tasks.py" worker "$id" <<<"$all")
  if [[ "$running" != true ]]; then
    echo "$id: no running worker"
    exit 0
  fi
  stop_one "$id"
fi
