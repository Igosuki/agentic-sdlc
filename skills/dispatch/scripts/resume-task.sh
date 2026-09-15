#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: resume-task.sh <task-id> [--prompt TEXT]

Resumes the Claude session of a task whose worker crashed, detached, in the
task's worktree, and returns. When the worker ends, record-task.sh records the
attempt, as after run-task.sh.

The task must be in_progress with dispatch_state=running and no process
running its session, and still have its worktree and its session transcript.
If the worker had in fact ended (its log has a result), the attempt is
recorded instead of resumed.

Options:
  --prompt TEXT   message for the resumed session, default: continue where you stopped

Prints: "resumed <task> <worktree> <log>", or record-task.sh's line.
Exit codes: 0 resumed or recorded, 2 invalid arguments or task not resumable.
EOF
}

id="" prompt=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
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
[[ -n "$id" ]] || { usage >&2; exit 2; }
dir=$(dirname "$(readlink -f "$0")")

task=$(bd show "$id" --json 2>/dev/null | jq '.[0]' 2>/dev/null) || { echo "error: no bead $id" >&2; exit 2; }
get() { jq -r "$1 // empty" <<<"$task"; }
session=$(get .metadata.dispatch_session)
branch=$(get .metadata.dispatch_branch)
log="$(git rev-parse --path-format=absolute --git-common-dir)/sdlc/logs/$id-$session.jsonl"

if [[ "$(get .status)" != in_progress || "$(get .metadata.dispatch_state)" != running || -z "$session" ]]; then
  echo "error: $id has no dispatched worker to resume (status $(get .status), dispatch_state: $(get .metadata.dispatch_state))" >&2
  exit 2
fi
if pgrep -f -- "--(session-id|resume) $session" >/dev/null; then
  echo "error: the worker for $id is still running" >&2
  exit 2
fi
if jq -e 'select(.type == "result")' "$log" >/dev/null 2>&1; then
  exec "$dir/record-task.sh" "$id"
fi

wt_path=$(wt list --format json </dev/null 2>/dev/null | jq -r --arg b "$branch" '.items[] | select(.branch == $b) | .worktree.path // empty')
errors=()
[[ -n "$wt_path" && -d "$wt_path" ]] || errors+=("no worktree for branch $branch")
[[ -n "$(find ~/.claude/projects -name "$session.jsonl" -print -quit 2>/dev/null)" ]] || errors+=("no transcript for session $session")
if [[ ${#errors[@]} -gt 0 ]]; then
  printf 'error: %s\n' "${errors[@]}" >&2
  exit 2
fi

prompt=${prompt:-"Your session was interrupted before you finished. Check the state of the worktree, then continue task $id from where you stopped."}
plugin_root=$(cd "$dir/../../.." && pwd)
worker=(env "DISPATCH_TASK=$id" claude -p --resume "$session" --plugin-dir "$plugin_root" --permission-mode auto --output-format stream-json --verbose --forward-subagent-text
  --allowedTools "Bash($dir/finish-task.sh *)")
agent=$(get .metadata.execution_agent_type)
model=$(get .metadata.execution_suggested_model)
effort=$(get .metadata.execution_reasoning_effort)
if [[ -n "$agent" ]]; then worker+=(--agent "$agent"); else worker+=(--model "${model:-sonnet}"); fi
[[ -z "$effort" ]] || worker+=(--effort "$effort")

# setsid: the worker must outlive whoever resumed it.
setsid -f bash -c '
  wt_path=$1 root=$2 log=$3 record=$4 id=$5
  shift 5
  printf "{\"type\":\"dispatch_run\",\"started\":\"%s\"}\n" "$(date -Is)" >>"$log"
  (cd "$wt_path" && "$@") </dev/null >>"$log" 2>>"$log.err"
  cd "$root" && "$record" "$id" >>"$log.record" 2>&1
' resume-task "$wt_path" "$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")" "$log" "$dir/record-task.sh" "$id" \
  "${worker[@]}" "$prompt" </dev/null >/dev/null 2>&1
echo "resumed $id $wt_path $log"
