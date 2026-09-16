#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: start-worker.sh <task-id> [--resume] [--prompt TEXT]

Starts a task's worker session, detached, in the task's worktree, and
returns. Called by run-task.sh right after it claims a task and creates its
worktree, and by resume-task.sh after its own checks. Finds the worktree from
metadata.dispatch_branch, builds the claude -p command from the task's
metadata, and runs it under setsid so it outlives whoever started it. Writes
a dispatch_run line to the log first, then, once the worker ends, runs
record-task.sh to record the attempt.

Agent: sdlc:integrator when metadata.dispatch_role is integration, else
sdlc:worker. That agent's frontmatter picks the model unless overridden.
Worker options come from the task's metadata: execution_suggested_model
(--model, no default), execution_reasoning_effort (--effort).

Options:
  --resume        resume metadata.dispatch_session (claude -p --resume)
                   instead of starting it fresh (claude -p --session-id)
  --prompt TEXT   message to send to the session; required

Prints: "started <task> <worktree> <log>", or "resumed <task> <worktree>
<log>" with --resume.
Exit codes: 0 started, 2 invalid arguments or task not startable.
EOF
}

id="" resume=false prompt=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --resume) resume=true ;;
    --prompt)
      [[ $# -ge 2 ]] || { echo "error: --prompt needs a value" >&2; usage >&2; exit 2; }
      prompt="$2"; shift ;;
    -*) echo "error: unknown option $1" >&2; usage >&2; exit 2 ;;
    *)
      [[ -z "$id" ]] || { echo "error: one task at a time" >&2; usage >&2; exit 2; }
      id="$1" ;;
  esac
  shift
done
errors=()
[[ -n "$id" ]] || errors+=("a task id is required")
[[ -n "$prompt" ]] || errors+=("--prompt is required")
if [[ ${#errors[@]} -gt 0 ]]; then
  printf 'error: %s\n' "${errors[@]}" >&2
  usage >&2
  exit 2
fi
dir=$(dirname "$(readlink -f "$0")")

task=$(bd show "$id" --json 2>/dev/null | jq '.[0]' 2>/dev/null) || { echo "error: no bead $id" >&2; exit 2; }
get() { jq -r "$1 // empty" <<<"$task"; }
session=$(get .metadata.dispatch_session)
branch=$(get .metadata.dispatch_branch)
role=$(get .metadata.dispatch_role)
[[ -n "$session" && -n "$branch" ]] || { echo "error: $id has no dispatch_session or dispatch_branch set" >&2; exit 2; }

wt_path=$(wt list --format json </dev/null 2>/dev/null | jq -r --arg b "$branch" '.items[] | select(.branch == $b) | .worktree.path // empty')
[[ -n "$wt_path" && -d "$wt_path" ]] || { echo "error: no worktree for branch $branch" >&2; exit 2; }

logs="$(git rev-parse --path-format=absolute --git-common-dir)/sdlc/logs"
mkdir -p "$logs"
log="$logs/$id-$session.jsonl"

plugin_root=$(cd "$dir/.." && pwd)
finish="$dir/finish-task.sh"
worker=(env "DISPATCH_TASK=$id" claude -p --permission-mode auto --output-format stream-json --verbose --forward-subagent-text
  --allowedTools "Bash($finish *)")
if [[ "$resume" == true ]]; then worker+=(--resume "$session"); else worker+=(--session-id "$session"); fi
# The worker runs as a plugin agent, so it needs the plugin loaded; its hooks come with it.
[[ -f "$plugin_root/.claude-plugin/plugin.json" ]] || { echo "error: no plugin manifest in $plugin_root, so the worker would run without its agent and hooks" >&2; exit 2; }
worker+=(--plugin-dir "$plugin_root")
if [[ "$role" == integration ]]; then worker+=(--agent sdlc:integrator); else worker+=(--agent sdlc:worker); fi
model=$(get .metadata.execution_suggested_model)
[[ -z "$model" ]] || worker+=(--model "$model")
effort=$(get .metadata.execution_reasoning_effort)
[[ -z "$effort" ]] || worker+=(--effort "$effort")

# setsid: the worker must outlive whoever started it.
setsid -f bash -c '
  wt_path=$1 root=$2 log=$3 record=$4 id=$5
  shift 5
  printf "\n{\"type\":\"dispatch_run\",\"started\":\"%s\"}\n" "$(date -Is)" >>"$log"
  (cd "$wt_path" && "$@") </dev/null >>"$log" 2>>"$log.err"
  cd "$root" && "$record" "$id" >>"$log.record" 2>&1
' start-worker "$wt_path" "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")" "$log" "$dir/record-task.sh" "$id" \
  "${worker[@]}" "$prompt" </dev/null >/dev/null 2>&1

if [[ "$resume" == true ]]; then echo "resumed $id $wt_path $log"; else echo "started $id $wt_path $log"; fi
