#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: reset-task.sh <task-id>

Undoes a dispatch: releases the branch's merge queue, removes the task's
worktree and branch with wt remove -D (if one exists), clears the branch's
worktrunk state marker, and reopens the task with every dispatch_* metadata
key unset. A later dispatch picks the task up like new. dispatch, split and
/sdlc:recover all call this instead of writing the same steps themselves.

Exit codes: 0 reset, 2 invalid arguments or no such bead.
EOF
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
[[ $# -eq 1 && "$1" != -* ]] || { usage >&2; exit 2; }
id="$1"
dir=$(dirname "$(readlink -f "$0")")

task=$(bd show "$id" --json 2>/dev/null | jq '.[0]' 2>/dev/null) || { echo "error: no bead $id" >&2; exit 2; }
base=$(jq -r '.metadata.dispatch_base // empty' <<<"$task")
branch=$(jq -r '.metadata.dispatch_branch // empty' <<<"$task")

[[ -z "$base" ]] || "$dir/merge-queue.sh" release "$base" "$id" >/dev/null

if [[ -n "$branch" ]] && wt list --format json </dev/null 2>/dev/null |
  jq -e --arg b "$branch" '.items[] | select(.branch == $b)' >/dev/null; then
  wt remove -D "$branch" </dev/null >/dev/null
fi
[[ -z "$branch" ]] || "$dir/mark-branch.sh" "$branch" clear

unset_args=()
while IFS= read -r key; do
  unset_args+=(--unset-metadata "$key")
done < <(jq -r '.metadata // {} | keys[] | select(startswith("dispatch_"))' <<<"$task")

bd update "$id" --status open "${unset_args[@]}" >/dev/null
echo "reset $id"
