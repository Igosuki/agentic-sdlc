#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: verify.sh [--no-pre-merge] <task-id|parent-id|epic-id>

Runs the checks that finishing this task, parent task or epic runs:
  task    its own metadata.verify, in its worktree
  parent  every non-closed descendant task's metadata.verify (any depth), each
          in its own worktree
  epic    every closed descendant task's metadata.verify (any depth), on the
          epic branch (epic-merge, epic-pr) or the target (direct), then the
          project's pre-merge checks (wt hook pre-merge)

`finish-task.sh` calls this for its own verify step, so both share one definition
of what verifying a task, parent or epic means. It passes --no-pre-merge, which
skips an epic's pre-merge checks, when it is about to run them itself right after
(an integration task's own merge or pull request).

A parent's or epic's checks stop at the first failure, same as finish-task.sh's did.
Each verify command gets 600s.

Exit codes: 0 passed, 1 a check failed, 2 invalid arguments or nothing to check.
EOF
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
no_pre_merge=false
if [[ "${1:-}" == --no-pre-merge ]]; then no_pre_merge=true; shift; fi
[[ $# -eq 1 && "$1" != -* ]] || { usage >&2; exit 2; }
id="$1"

show() { bd show "$1" --json 2>/dev/null | jq '.[0]' 2>/dev/null; }
get() { jq -r "$2 // empty" <<<"$1"; }
config() { local v; v=$(bd config get "custom.dispatch.$1" 2>/dev/null) || v=""; [[ "$v" == *"(not set)" ]] && v=""; echo "$v"; }
worktree_of() { wt list --format json </dev/null 2>/dev/null | jq -r --arg b "$1" '.items[] | select(.branch == $b) | .worktree.path // empty'; }
children_of() { bd list --parent "$1" --all --limit 0 --json | jq -c '[.[] | select(.issue_type != "event")]'; }

descendants_of() {
  local queue=("$1") head kids n i
  while [[ ${#queue[@]} -gt 0 ]]; do
    head="${queue[0]}"; queue=("${queue[@]:1}")
    kids=$(children_of "$head")
    n=$(jq length <<<"$kids")
    for ((i = 0; i < n; i++)); do
      jq -c ".[$i]" <<<"$kids"
      queue+=("$(jq -r ".[$i].id" <<<"$kids")")
    done
  done
}

run_check() {
  local check_id=$1 check=$2 wt_path=$3
  echo "verify $check_id: $check"
  local out
  if ! out=$(cd "$wt_path" && timeout 600 bash -c "$check" 2>&1); then
    echo "$out"
    echo "verify $check_id failed"
    exit 1
  fi
}

bead=$(show "$id") || { echo "error: no bead $id" >&2; exit 2; }

if [[ "$(get "$bead" .issue_type)" == epic ]]; then
  target=$(config target); target=${target:-main}
  mode=$(get "$bead" .metadata.dispatch_integration)
  [[ -n "$mode" ]] || mode=$(config integration)
  mode=${mode:-direct}
  if [[ "$mode" == direct ]]; then
    branch=$target
  else
    branch=$(get "$bead" .metadata.dispatch_branch); branch=${branch:-$id}
  fi
  wt_path=$(worktree_of "$branch")
  [[ -n "$wt_path" ]] || { echo "error: no worktree for branch $branch" >&2; exit 2; }

  descendants=$(descendants_of "$id" | jq -cs '.')
  n=$(jq length <<<"$descendants")
  for ((i = 0; i < n; i++)); do
    descendant=$(jq -c ".[$i]" <<<"$descendants")
    verify=$(get "$descendant" .metadata.verify)
    # Only a closed descendant's code has landed on this branch; an open one's hasn't merged yet.
    [[ -n "$verify" && "$(get "$descendant" .status)" == closed ]] || continue
    run_check "$(get "$descendant" .id)" "$verify" "$wt_path"
  done

  if [[ "$no_pre_merge" == false ]]; then
    echo "pre-merge checks: wt hook pre-merge"
    if ! out=$(wt hook pre-merge -C "$wt_path" 2>&1); then
      echo "$out"
      echo "pre-merge checks failed"
      exit 1
    fi
  fi
  echo "$id passed"
  exit 0
fi

descendants=$(descendants_of "$id" | jq -cs '.')
if [[ "$(jq length <<<"$descendants")" -gt 0 ]]; then
  n=$(jq length <<<"$descendants")
  for ((i = 0; i < n; i++)); do
    descendant=$(jq -c ".[$i]" <<<"$descendants")
    descendant_id=$(get "$descendant" .id)
    verify=$(get "$descendant" .metadata.verify)
    [[ -n "$verify" && "$(get "$descendant" .status)" != closed ]] || continue
    branch=$(get "$descendant" .metadata.dispatch_branch); branch=${branch:-$descendant_id}
    wt_path=$(worktree_of "$branch")
    [[ -n "$wt_path" ]] || { echo "error: no worktree for $descendant_id (branch $branch)" >&2; exit 2; }
    run_check "$descendant_id" "$verify" "$wt_path"
  done
  echo "$id passed"
  exit 0
fi

verify=$(get "$bead" .metadata.verify)
[[ -n "$verify" ]] || { echo "error: $id has no metadata.verify" >&2; exit 2; }
branch=$(get "$bead" .metadata.dispatch_branch); branch=${branch:-$id}
wt_path=$(worktree_of "$branch")
[[ -n "$wt_path" ]] || { echo "error: no worktree for branch $branch" >&2; exit 2; }
run_check "$id" "$verify" "$wt_path"
echo "$id passed"
