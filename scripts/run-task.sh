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
  epic-pr     like epic-merge, but the integration task pushes the epic branch and
              opens a pull request; the epic closes once the PR is merged (a gh:pr gate)

The worker runs as the sdlc:worker agent (sdlc:integrator for an integration task),
which owns the task's lifecycle: implement, commit, review, finish-task.sh. Worker
options come from the task's metadata: execution_suggested_model (--model, no
default: the agent's frontmatter decides), execution_reasoning_effort (--effort).
execution_agent_type, when set, doesn't pick the CLI agent; it names the agent
(Agent tool) the worker hands implementation to, and is mentioned in its prompt.

Sets on the task: dispatch_session, dispatch_host, dispatch_base, dispatch_branch,
dispatch_started. The worker runs with DISPATCH_TASK=<task> and this plugin loaded, so
its hooks keep it on the task's lifecycle. The worker log is .git/sdlc/logs/<task>-<session>.jsonl.
On any failure after the claim, the task goes back to open, that metadata is removed, and
the reason is printed, including the worktree creation error when that's the cause.
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

epic=$(bd list --all --limit 0 --json | "$dir/tasks.py" epic "$id")
epic_bead=""
[[ -z "$epic" ]] || epic_bead=$(show "$epic")

target=$(config target)
target=${target:-main}
mode=$(config integration)
[[ -z "$epic" ]] || mode=$(get "$epic_bead" ".metadata.dispatch_integration // \"$mode\"")
mode=${mode:-direct}
[[ -n "$epic" ]] || mode=direct

errors=()
case "$mode" in
  direct|epic-merge|epic-pr) ;;
  *) errors+=("unknown integration mode $mode (direct, epic-merge, epic-pr)") ;;
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
  if [[ "$mode" == epic-pr ]]; then
    git remote get-url origin >/dev/null 2>&1 || errors+=("epic-pr mode needs a git remote named origin")
    command -v gh >/dev/null || errors+=("epic-pr mode needs the gh CLI")
  fi
fi
if [[ ${#errors[@]} -gt 0 ]]; then
  printf 'error: %s\n' "${errors[@]}" >&2
  exit 2
fi

if [[ "$mode" == epic-* && -z "$(get "$epic_bead" .metadata.dispatch_branch)" ]]; then
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
elif [[ "$mode" == epic-* ]]; then
  base=$epic branch=$id
else
  base=$target branch=$id
fi
"$dir/merge-queue.sh" ensure "$base" >/dev/null

session=$(uuidgen)
logs="$(git rev-parse --path-format=absolute --git-common-dir)/sdlc/logs"
mkdir -p "$logs"
log="$logs/$id-$session.jsonl"
bd update "$id" --claim --set-metadata "dispatch_session=$session" \
  --set-metadata "dispatch_host=$(uname -n)" --set-metadata "dispatch_base=$base" \
  --set-metadata "dispatch_branch=$branch" --set-metadata "dispatch_started=$(date -u +%FT%TZ)" >/dev/null \
  || { echo "error: could not claim $id" >&2; exit 1; }

# Claimed but not yet started: undo the claim on any failure from here on, so a
# supervisor sees the task as open again instead of a false crash.
started=false
rollback() {
  [[ "$started" == true ]] || bd update "$id" --status open --unset-metadata dispatch_session \
    --unset-metadata dispatch_host --unset-metadata dispatch_base --unset-metadata dispatch_branch \
    --unset-metadata dispatch_started >/dev/null
}
trap rollback EXIT
fail() { printf 'error: %s\n' "$1" >&2; exit 1; }

if [[ "$role" == integration ]]; then
  switch=(wt switch "$branch" --no-cd --format json)
else
  switch=(wt switch --create "$branch" --base "$base" --no-cd --format json)
fi
"${switch[@]}" </dev/null >/dev/null 2>"$log.wt" \
  || fail "could not create the worktree for $branch: $(cat "$log.wt" 2>/dev/null)"
wt_path=$(wt list --format json </dev/null 2>/dev/null | jq -r --arg b "$branch" '.items[] | select(.branch == $b) | .worktree.path // empty')
[[ -n "$wt_path" && -d "$wt_path" ]] || fail "no worktree for branch $branch"

if [[ "$role" == integration ]]; then
  prompt="Epic $epic: $(get "$epic_bead" .title)
Target: $target
Branch: $branch"
else
  prompt="Task $id: $(get "$task" .title)

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
Base: $base
Branch: $branch"
  agent=$(get "$task" .metadata.execution_agent_type)
  [[ -z "$agent" ]] || prompt+="
Hand the implementation to the $agent agent (Agent tool, subagent_type: $agent)."
fi

"$dir/start-worker.sh" "$id" --prompt "$prompt" || fail "could not start the worker"
started=true
