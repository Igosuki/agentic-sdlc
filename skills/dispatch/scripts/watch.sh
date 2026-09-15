#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: watch.sh [--epic EPIC] [--interval SECONDS] [--once]

Watches beads and the worker processes, and prints one line per change, for
the Monitor tool:
  ready <task>                a task can be dispatched (next-tasks.sh)
  ended <task> <state>        a worker ended: merged, stopped or failed
  crashed <task>              dispatch_state=running but no process runs its session
  closed <epic>               an epic was closed
  idle                        no worker runs and no task is ready; the watch ends

The first round reports every ready and crashed task. Each round also runs
bd gate check, so gates that can resolve on their own do.

Options:
  --epic EPIC          only that epic's tasks
  --interval SECONDS   time between rounds, default 10
  --once               one round, then exit

Exit codes: 0 ended (idle or --once), 2 invalid arguments.
EOF2
}

epic="" interval=10 once=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --once) once=true ;;
    --epic|--interval)
      [[ $# -ge 2 ]] || { echo "error: $1 needs a value" >&2; usage >&2; exit 2; }
      [[ "$1" == --epic ]] && epic="$2" || interval="$2"
      shift ;;
    *) echo "error: unknown argument $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
[[ "$interval" =~ ^[1-9][0-9]*$ ]] || { echo "error: --interval must be a positive number" >&2; exit 2; }
dir=$(dirname "$(readlink -f "$0")")
filter=()
[[ -z "$epic" ]] || filter=(--epic "$epic")

declare -A seen_ready=() seen_state=() seen_crash=() seen_closed=()
first=true
while :; do
  bd gate check >/dev/null 2>&1 || true
  ready=$("$dir/next-tasks.sh" --ids "${filter[@]}")
  for task in $ready; do
    [[ -n "${seen_ready[$task]:-}" ]] || echo "ready $task"
  done
  seen_ready=()
  for task in $ready; do seen_ready[$task]=1; done

  alive=0
  while IFS=$'\t' read -r task status state session parent issue_type; do
    [[ -n "$task" ]] || continue
    if [[ "$issue_type" == epic ]]; then
      [[ "$status" != closed || -n "${seen_closed[$task]:-}" || $first == true ]] || echo "closed $task"
      [[ "$status" != closed ]] || seen_closed[$task]=1
      continue
    fi
    previous=${seen_state[$task]:-}
    seen_state[$task]=$state
    if [[ "$state" == running ]]; then
      if pgrep -f -- "--(session-id|resume) $session" >/dev/null; then
        alive=$((alive + 1))
        unset "seen_crash[$task]"
      elif [[ -z "${seen_crash[$task]:-}" ]]; then
        echo "crashed $task"
        seen_crash[$task]=1
      fi
    elif [[ "$previous" == running ]]; then
      echo "ended $task $state"
    fi
  done < <(bd list --all --limit 0 --json | jq -r --arg e "$epic" '
    .[] | select((.metadata.dispatch_session // "") != "" or .issue_type == "epic")
    | select($e == "" or .parent == $e or .id == $e)
    | [.id, .status, (.metadata.dispatch_state // "-"), (.metadata.dispatch_session // "-"), (.parent // "-"), .issue_type] | @tsv')

  first=false
  if $once; then exit 0; fi
  if [[ $alive -eq 0 && -z "$ready" ]]; then
    echo "idle"
    exit 0
  fi
  sleep "$interval"
done
