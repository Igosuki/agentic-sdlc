#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: dispatch-next.sh [--epic EPIC] [--parallel N]

Starts the next ready tasks in work order (next-tasks.py) with run-task.sh,
until this machine runs N workers (default: settings.sh parallel).

Prints run-task.sh's lines, "not started <task>: <reason>" for a task that
couldn't start, and a final line with the number of workers running.
Exit codes: 0 done (possibly nothing started), 2 invalid arguments.
EOF2
}

epic="" parallel=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --epic|--parallel)
      [[ $# -ge 2 ]] || { echo "error: $1 needs a value" >&2; usage >&2; exit 2; }
      [[ "$1" == --epic ]] && epic="$2" || parallel="$2"
      shift ;;
    *) echo "error: unknown argument $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done
dir=$(dirname "$(readlink -f "$0")")
parallel=${parallel:-$("$dir/settings.sh" parallel)}
[[ "$parallel" =~ ^[1-9][0-9]*$ ]] || { echo "error: parallel must be a positive number, got $parallel" >&2; exit 2; }

running=$("$dir/workers.py" --alive-count)
filter=()
[[ -z "$epic" ]] || filter=(--epic "$epic")
for task in $("$dir/next-tasks.py" --ids "${filter[@]}"); do
  (( running < parallel )) || break
  if out=$("$dir/run-task.sh" "$task" 2>&1); then
    echo "$out"
    running=$((running + 1))
  else
    echo "not started $task: $(tail -1 <<<"$out")"
  fi
done
echo "$running of $parallel workers running"
