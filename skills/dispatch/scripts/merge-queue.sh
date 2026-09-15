#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: merge-queue.sh ensure <branch>
       merge-queue.sh acquire <branch> <holder> [--timeout SECONDS]
       merge-queue.sh release <branch> <holder>

One merge queue per branch, so merges into that branch happen one at a time,
on every machine sharing the beads database. The queue is an ephemeral bead
(hidden from bd ready and bd list) whose id is kept in bd kv as
dispatch.queue.<branch>. Holding it means having claimed that bead.

  ensure    create the queue if it doesn't exist; prints its bead id
  acquire   wait until <holder> holds the queue (default timeout 1800s)
  release   free the queue if <holder> holds it

Exit codes: 0 done, 1 timed out or bd failed, 2 invalid arguments or no queue.
EOF
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
cmd="${1:-}" branch="${2:-}" holder="${3:-}" timeout=1800
case "$cmd" in
  ensure) [[ $# -eq 2 ]] || { usage >&2; exit 2; } ;;
  acquire)
    [[ $# -eq 3 || ($# -eq 5 && "$4" == --timeout) ]] || { usage >&2; exit 2; }
    [[ $# -eq 3 ]] || timeout="$5"
    [[ "$timeout" =~ ^[0-9]+$ ]] || { echo "error: --timeout must be a number of seconds" >&2; exit 2; } ;;
  release) [[ $# -eq 3 ]] || { usage >&2; exit 2; } ;;
  *) usage >&2; exit 2 ;;
esac

key="dispatch.queue.$branch"
lock=$(bd kv get "$key" 2>/dev/null) || lock=""
[[ -z "$lock" ]] || bd show "$lock" --json >/dev/null 2>&1 || lock=""

case "$cmd" in
  ensure)
    if [[ -z "$lock" ]]; then
      lock=$(bd create "merge queue $branch" --type chore --ephemeral \
        --description "Held while a task merges into $branch. Managed by merge-queue.sh." --silent)
      bd kv set "$key" "$lock" >/dev/null
    fi
    echo "$lock"
    ;;
  acquire)
    [[ -n "$lock" ]] || { echo "error: no merge queue for $branch (run: merge-queue.sh ensure $branch)" >&2; exit 2; }
    deadline=$(( $(date +%s) + timeout ))
    waiting=""
    until bd update "$lock" --claim --actor "$holder" >/dev/null 2>&1; do
      if [[ -z "$waiting" ]]; then
        echo "waiting for the $branch merge queue, held by $(bd show "$lock" --json | jq -r '.[0].assignee // "unknown"')"
        waiting=1
      fi
      (( $(date +%s) < deadline )) || { echo "error: timed out waiting for the $branch merge queue" >&2; exit 1; }
      sleep 5
    done
    ;;
  release)
    [[ -n "$lock" ]] || exit 0
    [[ "$(bd show "$lock" --json | jq -r '.[0].assignee // empty')" == "$holder" ]] || exit 0
    bd update "$lock" --status open --assignee "" >/dev/null
    ;;
esac
