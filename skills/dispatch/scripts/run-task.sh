#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: run-task.sh <task-id>

Dispatches an open task: claims it, creates its worktree, starts its worker
detached, and returns. The worker is a headless claude session that owns the
task until it is closed: it implements, commits, and runs finish-task.sh to
check, merge and close. When the worker process ends, record-task.sh records
the attempt.

Integration mode: the epic's metadata dispatch_integration, else
bd config custom.dispatch.integration, else direct. Target branch:
bd config custom.dispatch.target, else main.
  direct      the worktree starts from the target and merges into it
  epic-merge  the worktree starts from the epic branch <epic-id> and merges into it.
              An epic's first dispatch creates that branch and an integration
              task "Integrate <epic-id> into <target>", which waits for the
              epic's other tasks and merges the epic branch into the target.

Worker options come from the task's metadata: execution_agent_type (--agent),
execution_suggested_model (--model, default sonnet, ignored with an agent),
execution_reasoning_effort (--effort).

Sets on the task: dispatch_state=running, dispatch_session, dispatch_host,
dispatch_base, dispatch_branch. The worker log is .git/sdlc/logs/<task>-<session>.jsonl.
Prints: "started <task> <worktree> <log>".
Exit codes: 0 started, 1 could not start, 2 invalid arguments or task not dispatchable.
EOF
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
[[ $# -eq 1 && "$1" != -* ]] || { usage >&2; exit 2; }
id="$1"
dir=$(dirname "$(readlink -f "$0")")

show() { bd show "$1" --json 2>/dev/null | jq '.[0]' 2>/dev/null; }
get() { jq -r "$2 // empty" <<<"$1"; }
config() { local v; v=$(bd config get "custom.dispatch.$1" 2>/dev/null) || v=""; [[ "$v" == *"(not set)" ]] && v=""; echo "$v"; }
children() { bd list --parent "$1" --all --limit 0 --json | jq -c '[.[] | select(.issue_type != "event")]'; }

task=$(show "$id") || { echo "error: no bead $id" >&2; exit 2; }
role=$(get "$task" .metadata.dispatch_role)

epic="" epic_bead="" parent=$(get "$task" .parent)
while [[ -n "$parent" ]]; do
  bead=$(show "$parent") || break
  if [[ "$(get "$bead" .issue_type)" == epic ]]; then epic="$parent" epic_bead="$bead"; break; fi
  parent=$(get "$bead" .parent)
done

target=$(config target)
target=${target:-main}
mode=$(config integration)
[[ -z "$epic" ]] || mode=$(get "$epic_bead" ".metadata.dispatch_integration // \"$mode\"")
mode=${mode:-direct}
[[ -n "$epic" ]] || mode=direct

errors=()
case "$mode" in
  direct|epic-merge) ;;
  epic-pr) errors+=("integration mode epic-pr is not supported yet") ;;
  *) errors+=("unknown integration mode $mode (direct, epic-merge)") ;;
esac
[[ "$(get "$task" .issue_type)" != epic ]] || errors+=("$id is an epic: dispatch its tasks")
[[ "$(get "$task" .status)" == open ]] || errors+=("$id is $(get "$task" .status), expected open")
[[ "$role" == integration || -n "$(get "$task" .metadata.verify)" ]] || errors+=("$id has no metadata.verify")
blockers=$(jq -r '[.dependencies[]? | select(.dependency_type == "blocks" and .status != "closed") | .id] | join(" ")' <<<"$task")
[[ -z "$blockers" ]] || errors+=("$id waits for $blockers")
git rev-parse --verify --quiet "refs/heads/$target" >/dev/null || errors+=("no branch $target")
if [[ "$role" == integration ]]; then
  pending=$(children "$epic" | jq -r --arg id "$id" '[.[] | select(.id != $id and .status != "closed") | .id] | join(" ")')
  [[ -z "$pending" ]] || errors+=("$id integrates $epic, whose other tasks aren't closed: $pending")
fi
if [[ ${#errors[@]} -gt 0 ]]; then
  printf 'error: %s\n' "${errors[@]}" >&2
  exit 2
fi

if [[ "$mode" == epic-merge && -z "$(get "$epic_bead" .metadata.dispatch_branch)" ]]; then
  git rev-parse --verify --quiet "refs/heads/$epic" >/dev/null || git branch "$epic" "$target"
  "$dir/merge-queue.sh" ensure "$epic" >/dev/null
  integration=$(bd create "Integrate $epic into $target" --parent "$epic" --type task \
    --description "Merge branch $epic, where the tasks of epic $epic landed, into $target." \
    --metadata '{"dispatch_role": "integration"}' --silent)
  for child in $(children "$epic" | jq -r --arg i "$integration" '.[] | select(.id != $i and .status != "closed") | .id'); do
    bd dep add "$integration" "$child" >/dev/null
  done
  bd update "$epic" --set-metadata "dispatch_branch=$epic" --set-metadata "dispatch_integration=$mode" \
    --set-metadata "dispatch_integration_task=$integration" >/dev/null
  echo "epic $epic: created branch $epic and integration task $integration"
fi

if [[ "$role" == integration ]]; then
  base=$target branch=$epic
elif [[ "$mode" == epic-merge ]]; then
  base=$epic branch=$id
else
  base=$target branch=$id
fi
"$dir/merge-queue.sh" ensure "$base" >/dev/null

session=$(uuidgen)
logs="$(git rev-parse --path-format=absolute --git-common-dir)/sdlc/logs"
mkdir -p "$logs"
log="$logs/$id-$session.jsonl"
bd update "$id" --claim --set-metadata dispatch_state=running --set-metadata "dispatch_session=$session" \
  --set-metadata "dispatch_host=$(uname -n)" --set-metadata "dispatch_base=$base" \
  --set-metadata "dispatch_branch=$branch" >/dev/null \
  || { echo "error: could not claim $id" >&2; exit 1; }

if [[ "$role" == integration ]]; then
  switch=(wt switch "$branch" --no-cd --format json)
else
  switch=(wt switch --create "$branch" --base "$base" --no-cd --format json)
fi
"${switch[@]}" </dev/null >/dev/null 2>"$log.wt" \
  || { echo "error: could not create the worktree for $branch, see $log.wt" >&2; exit 1; }
wt_path=$(wt list --format json </dev/null 2>/dev/null | jq -r --arg b "$branch" '.items[] | select(.branch == $b) | .worktree.path // empty')
[[ -n "$wt_path" && -d "$wt_path" ]] || { echo "error: no worktree for branch $branch" >&2; exit 1; }

finish="$dir/finish-task.sh"
if [[ "$role" == integration ]]; then
  prompt="Merge epic $epic ($(get "$epic_bead" .title)) into $target.

Every other task of the epic is closed and merged into branch $epic, which is checked out in this worktree (bd children $epic lists them). Merging may require editing the code: $target may have moved, or the tasks may not work together.

You own this merge until it is closed:
1. Run: $finish $id
   It rebases $epic onto $target, runs the verify command of every task in the epic, merges into $target, and closes this task and the epic.
2. If it reports a problem (a conflict, a failing verify), fix the code, commit, and run it again.
3. If you can't finish, record what's missing with: bd comments add $id \"<what's missing>\", then stop.
Don't merge or close anything by other means."
else
  prompt="Implement task $id: $(get "$task" .title)

$(get "$task" .description)

Acceptance:
$(get "$task" .acceptance_criteria)

Verify command, which must exit 0 from the worktree root:
$(get "$task" .metadata.verify)
"
  [[ -z "$(get "$task" .metadata.scope)" ]] || prompt+="
Scope: $(get "$task" .metadata.scope)"
  [[ -z "$(get "$task" .metadata.design)" ]] || prompt+="
Design: $(get "$task" .metadata.design)"
  [[ -z "$epic" ]] || prompt+="
Epic: $epic (bd show $epic; bd children $epic lists the sibling tasks)"
  prompt+="

The task is already split: implement it here, don't decompose or dispatch it further.
This is your own git worktree, on branch $branch, created from $base. You own this task until it is closed:
1. Implement it and commit. Only committed work is merged.
2. Run: $finish $id
   It rebases onto $base, runs the verify command, merges into $base and closes the task. If it reports a problem (a failing verify, a conflict with a sibling's change on $base), fix it, commit, and run it again. git log $base and bd show <task> explain what sibling tasks changed.
3. If you can't finish, record what's missing with: bd comments add $id \"<what's missing>\", then stop.
Don't merge or close the task by other means."
fi

worker=(claude -p --session-id "$session" --permission-mode auto --output-format stream-json --verbose
  --allowedTools "Bash($finish *)")
agent=$(get "$task" .metadata.execution_agent_type)
model=$(get "$task" .metadata.execution_suggested_model)
effort=$(get "$task" .metadata.execution_reasoning_effort)
if [[ -n "$agent" ]]; then worker+=(--agent "$agent"); else worker+=(--model "${model:-sonnet}"); fi
[[ -z "$effort" ]] || worker+=(--effort "$effort")

# setsid: the worker must outlive whoever dispatched it.
setsid -f bash -c '
  wt_path=$1 root=$2 log=$3 record=$4 id=$5
  shift 5
  printf "{\"type\":\"dispatch_run\",\"started\":\"%s\"}\n" "$(date -Is)" >>"$log"
  (cd "$wt_path" && "$@") </dev/null >>"$log" 2>>"$log.err"
  cd "$root" && "$record" "$id" >>"$log.record" 2>&1
' run-task "$wt_path" "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")" "$log" "$dir/record-task.sh" "$id" \
  "${worker[@]}" "$prompt" </dev/null >/dev/null 2>&1
echo "started $id $wt_path $log"
