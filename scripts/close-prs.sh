#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: close-prs.sh <task-id>

Closes an epic-pr integration task once its pull request is merged, then its
epic once all the epic's tasks are closed. The task must be in_progress with
dispatch_state=pr-opened and a dispatch_pr, blocked by a gh:pr gate; once
bd gate check (or a person, with bd gate resolve) closes the gate, this closes
the task, then the epic. A pull request closed without merging instead sets
dispatch_state=stopped, with a comment, so /sdlc:recover can pick it up. Run
by supervise.py.

Prints "closed <id>" for the task and, when it leaves its epic fully closed,
the epic too; "stopped <id>" for one whose pull request closed without
merging. Prints nothing when its gate is still open and the pull request
hasn't closed.
Exit codes: 0 done (including nothing to do), 2 invalid arguments or the task
isn't a pull-request task.
EOF2
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
[[ $# -eq 1 && "$1" != -* ]] || { usage >&2; exit 2; }
id="$1"

bead=$(bd show "$id" --json 2>/dev/null | jq '.[0]') || { echo "error: no bead $id" >&2; exit 2; }
get() { jq -r "$1 // empty" <<<"$bead"; }
dispatch_state=$(get .metadata.dispatch_state)
pr=$(get .metadata.dispatch_pr)
if [[ "$(get .status)" != in_progress || "$dispatch_state" != pr-opened || -z "$pr" ]]; then
  echo "error: $id is not a pull-request task (status $(get .status), dispatch_state: $dispatch_state)" >&2
  exit 2
fi

blocked=$(jq '[.dependencies[]? | select(.dependency_type == "blocks" and .status != "closed")] | length' <<<"$bead")
if [[ "$blocked" -gt 0 ]]; then
  # The gate only closes on a merge; a close without merging needs gh directly.
  pr_state=$(gh pr view "$pr" --json state --jq .state 2>/dev/null) || exit 0
  if [[ "$pr_state" == CLOSED ]]; then
    bd update "$id" --set-metadata dispatch_state=stopped >/dev/null
    bd comments add "$id" "pull request $pr closed without merging" >/dev/null
    echo "stopped $id"
  fi
  exit 0
fi

bd close "$id" --reason "pull request $pr merged" >/dev/null
bd update "$id" --set-metadata dispatch_state=merged >/dev/null
echo "closed $id"

epic=$(get .parent)
[[ -n "$epic" ]] || exit 0
open=$(bd list --parent "$epic" --all --limit 0 --json | jq '[.[] | select(.issue_type != "event" and .status != "closed")] | length')
if [[ "$open" -eq 0 && "$(bd show "$epic" --json | jq -r '.[0].status')" != closed ]]; then
  bd close "$epic" --reason "pull request merged" >/dev/null
  echo "closed $epic"
fi
