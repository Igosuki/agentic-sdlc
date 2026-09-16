#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: close-prs.sh

Closes epic-pr integration tasks whose pull request was merged, and their epics.
Such a task keeps dispatch_state=pr-opened and a gh:pr gate that blocks it; once
bd gate check (or a person, with bd gate resolve) closes the gate, this closes
the task, then its epic when all the epic's tasks are closed. A pull request
closed without merging instead sets dispatch_state=stopped, with a comment, so
/sdlc:recover can pick it up. Run by watch.py.

Prints "closed <id>" for each task and epic it closes, and "stopped <id>" for
one whose pull request closed without merging.
Exit codes: 0 done.
EOF2
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
for task in $(bd list --status in_progress --limit 0 --metadata-field dispatch_state=pr-opened --json | jq -r '.[].id'); do
  bead=$(bd show "$task" --json | jq '.[0]')
  blocked=$(jq '[.dependencies[]? | select(.dependency_type == "blocks" and .status != "closed")] | length' <<<"$bead")
  pr=$(jq -r '.metadata.dispatch_pr' <<<"$bead")
  if [[ "$blocked" -gt 0 ]]; then
    # The gate only closes on a merge; a close without merging needs gh directly.
    state=$(gh pr view "$pr" --json state --jq .state 2>/dev/null) || continue
    if [[ "$state" == CLOSED ]]; then
      bd update "$task" --set-metadata dispatch_state=stopped >/dev/null
      bd comments add "$task" "pull request $pr closed without merging" >/dev/null
      echo "stopped $task"
    fi
    continue
  fi
  bd close "$task" --reason "pull request $pr merged" >/dev/null
  bd update "$task" --set-metadata dispatch_state=merged >/dev/null
  echo "closed $task"
  epic=$(jq -r '.parent // empty' <<<"$bead")
  [[ -n "$epic" ]] || continue
  open=$(bd list --parent "$epic" --all --limit 0 --json | jq '[.[] | select(.issue_type != "event" and .status != "closed")] | length')
  if [[ "$open" -eq 0 && "$(bd show "$epic" --json | jq -r '.[0].status')" != closed ]]; then
    bd close "$epic" --reason "pull request merged" >/dev/null
    echo "closed $epic"
  fi
done
