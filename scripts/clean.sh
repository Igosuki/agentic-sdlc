#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: clean.sh [--apply]

Lists leftovers, one line per item with its reason:
  worktree <id>  a closed task's worktree (and branch) were never removed
  worktree <id>  an open task with no dispatch_branch still has a worktree (reset)
  branch <id>    a closed task's branch is left with no worktree
  queue <branch> held by a task whose worker isn't running

With --apply, removes each: wt remove -D for a worktree, git branch -D for a
branch left without one, merge-queue.sh release for a queue.

Never touches the main checkout, the worktree of a claimed task (in_progress),
or a task whose dispatch_state is stopped, failed or awaiting-review.

Exit codes: 0 done (listed or applied), 2 invalid arguments.
EOF
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
apply=false
case "${1:-}" in
  "") [[ $# -eq 0 ]] || { usage >&2; exit 2; } ;;
  --apply) [[ $# -eq 1 ]] || { usage >&2; exit 2; }; apply=true ;;
  *) usage >&2; exit 2 ;;
esac

dir=$(dirname "$(readlink -f "$0")")
all_tasks=$(bd list --all --limit 0 --json)

# A closed task's worktree/branch is a leftover; an open one is only a leftover once
# it has been reset (no dispatch_branch) or its dispatch_state was cleared to nothing.
leftover_reason() {
  local status="$1" dispatch_branch="$2" dispatch_state="$3"
  case "$dispatch_state" in
    stopped | failed | awaiting-review) return ;;
  esac
  if [[ "$status" == closed ]]; then
    echo closed
  elif [[ "$status" == open && -z "$dispatch_branch" ]]; then
    echo reset
  fi
}

wt_items=$(wt list --format json </dev/null 2>/dev/null | jq -c '.items[] | select(.worktree.main != true)')
worktree_branches=""

while IFS= read -r item; do
  [[ -n "$item" ]] || continue
  branch=$(jq -r '.branch' <<<"$item")
  worktree_branches+="$branch"$'\n'
  bead=$(jq -c --arg b "$branch" '.[] | select(.id == $b)' <<<"$all_tasks")
  [[ -n "$bead" ]] || continue
  reason=$(leftover_reason "$(jq -r '.status' <<<"$bead")" "$(jq -r '.metadata.dispatch_branch // empty' <<<"$bead")" \
    "$(jq -r '.metadata.dispatch_state // empty' <<<"$bead")")
  [[ -n "$reason" ]] || continue
  if [[ "$reason" == closed ]]; then
    echo "worktree $branch  closed task, worktree and branch left behind"
  else
    echo "worktree $branch  open task with no dispatch_branch, worktree left behind (reset)"
  fi
  [[ "$apply" == false ]] || wt remove -D "$branch" </dev/null >/dev/null 2>&1 \
    || echo "error: could not remove the worktree for $branch" >&2
done <<<"$wt_items"

# A closed task's branch with no worktree: record-task.sh can leave one behind when the
# branch wasn't an ancestor of base (rebase changed its history) and its own git branch -D
# also failed, or the worktree was already removed by hand.
while IFS= read -r branch; do
  [[ -n "$branch" ]] || continue
  grep -qxF "$branch" <<<"$worktree_branches" && continue
  bead=$(jq -c --arg b "$branch" '.[] | select(.id == $b)' <<<"$all_tasks")
  [[ -n "$bead" ]] || continue
  [[ "$(jq -r '.status' <<<"$bead")" == closed ]] || continue
  echo "branch $branch  closed task, branch left behind with no worktree"
  [[ "$apply" == false ]] || git branch -D "$branch" >/dev/null 2>&1 \
    || echo "error: could not delete branch $branch" >&2
done < <(git for-each-ref --format='%(refname:short)' refs/heads/)

# A merge queue bead is held (in_progress, an assignee) while a task rebases, verifies and
# merges through finish-task.sh; a worker that dies mid-merge leaves it held.
while IFS=$'\t' read -r key lock_id; do
  [[ -n "$key" ]] || continue
  branch=${key#dispatch.queue.}
  qbead=$(bd show "$lock_id" --json 2>/dev/null | jq -c '.[0]') || continue
  [[ -n "$qbead" && "$qbead" != null ]] || continue
  [[ "$(jq -r '.status' <<<"$qbead")" == in_progress ]] || continue
  holder=$(jq -r '.assignee // empty' <<<"$qbead")
  [[ -n "$holder" ]] || continue
  running=$("$dir/tasks.py" worker "$holder" <<<"$all_tasks" 2>/dev/null) || running=false
  [[ "$running" == true ]] && continue
  echo "queue $branch  held by $holder, no running process"
  [[ "$apply" == false ]] || "$dir/merge-queue.sh" release "$branch" "$holder" >/dev/null
done < <(bd kv list --json 2>/dev/null | jq -r 'to_entries[] | select(.key | startswith("dispatch.queue.")) | "\(.key)\t\(.value)"')
