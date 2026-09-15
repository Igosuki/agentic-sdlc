#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: finish-task.sh <task-id>

Run by a task's worker once its work is committed. While holding the merge
queue of the task's base branch:
  1. checks that the branch has commits and no tracked file has uncommitted changes
  2. rebases the branch onto the base
  3. runs the verify command (for an integration task, the verify command of
     every task in the epic)
  4. fast-forwards the base to the branch
Then closes the task, and closes the epic when it is done: after its last task
in direct mode, after its integration task in epic-merge mode.

On a problem it prints what to fix and exits 1: fix it, commit, run it again.
The worktree is removed later, by record-task.sh, once the worker has ended.

Exit codes: 0 merged and closed, 1 something to fix, 2 invalid arguments or no dispatched worker.
EOF
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
[[ $# -eq 1 && "$1" != -* ]] || { usage >&2; exit 2; }
id="$1"
dir=$(dirname "$(readlink -f "$0")")

show() { bd show "$1" --json 2>/dev/null | jq '.[0]' 2>/dev/null; }
get() { jq -r "$2 // empty" <<<"$1"; }
problem() { echo "not merged: $1"; exit 1; }

task=$(show "$id") || { echo "error: no bead $id" >&2; exit 2; }
base=$(get "$task" .metadata.dispatch_base)
branch=$(get "$task" .metadata.dispatch_branch)
role=$(get "$task" .metadata.dispatch_role)
if [[ "$(get "$task" .status)" != in_progress || "$(get "$task" .metadata.dispatch_state)" != running || -z "$base" || -z "$branch" ]]; then
  echo "error: $id has no dispatched worker (status $(get "$task" .status), dispatch_state: $(get "$task" .metadata.dispatch_state))" >&2
  exit 2
fi
wt_path=$(wt list --format json </dev/null 2>/dev/null | jq -r --arg b "$branch" '.items[] | select(.branch == $b) | .worktree.path // empty')
[[ -n "$wt_path" ]] || { echo "error: no worktree for branch $branch" >&2; exit 2; }

epic="" parent=$(get "$task" .parent)
while [[ -n "$parent" ]]; do
  bead=$(show "$parent") || break
  if [[ "$(get "$bead" .issue_type)" == epic ]]; then epic="$parent"; break; fi
  parent=$(get "$bead" .parent)
done

if [[ "$role" == integration ]]; then
  verifies=$(bd list --parent "$epic" --all --limit 0 --json |
    jq -c --arg id "$id" '[.[] | select(.id != $id and (.metadata.verify // "") != "") | {id, verify: .metadata.verify}]')
else
  verifies=$(jq -cn --arg id "$id" --arg v "$(get "$task" .metadata.verify)" '[{id: $id, verify: $v}]')
fi

[[ "$(git -C "$wt_path" rev-list --count "$base..$branch")" -gt 0 ]] || problem "nothing committed on $branch since $base"
dirty=$(git -C "$wt_path" status --porcelain --untracked-files=no | cut -c4- | paste -sd' ' -)
[[ -z "$dirty" ]] || problem "uncommitted changes to tracked files: $dirty. Commit or discard them."

"$dir/merge-queue.sh" acquire "$base" "$id"
trap '"$dir/merge-queue.sh" release "$base" "$id" >/dev/null 2>&1 || true' EXIT

if ! git -C "$wt_path" rebase "$base" >/dev/null 2>&1; then
  conflicts=$(git -C "$wt_path" diff --name-only --diff-filter=U | paste -sd' ' -)
  git -C "$wt_path" rebase --abort >/dev/null 2>&1 || true
  problem "rebasing $branch onto $base conflicts in: $conflicts. Run git rebase $base, resolve the conflicts, then run this again."
fi

for ((i = 0; i < $(jq length <<<"$verifies"); i++)); do
  check_id=$(jq -r ".[$i].id" <<<"$verifies")
  check=$(jq -r ".[$i].verify" <<<"$verifies")
  out=$(cd "$wt_path" && timeout 600 bash -c "$check" 2>&1) \
    || problem "verify for $check_id failed after rebasing onto $base: $(tail -5 <<<"$out")"
done

merge_log=$(mktemp)
wt merge "$base" -C "$wt_path" --no-squash --no-rebase --stage none --no-remove --format json </dev/null >/dev/null 2>"$merge_log" \
  || problem "merge into $base failed: $(tail -5 "$merge_log")"
rm -f "$merge_log"

bd close "$id" --reason "merged into $base" >/dev/null
bd update "$id" --set-metadata dispatch_state=merged >/dev/null
echo "merged $id into $base and closed it"

if [[ -n "$epic" && "$(show "$epic" | jq -r .status)" != closed ]]; then
  integration=$(show "$epic" | jq -r '.metadata.dispatch_integration_task // empty')
  open=$(bd list --parent "$epic" --all --limit 0 --json | jq '[.[] | select(.issue_type != "event" and .status != "closed")] | length')
  if [[ "$role" == integration || ( -z "$integration" && "$open" -eq 0 ) ]]; then
    bd close "$epic" --reason "all tasks merged into $base" >/dev/null
    echo "closed epic $epic"
  fi
fi
