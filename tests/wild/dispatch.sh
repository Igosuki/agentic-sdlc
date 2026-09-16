#!/usr/bin/env bash
# Headless run of the whole flow on a new project: design, split, add a
# split task another task waits on, then dispatch until the epic is closed.
# /sdlc:dispatch only confirms and starts the supervisor, and there's no one
# here to confirm with, so this runs the supervisor script directly, with
# --under and --parallel 2, in the foreground: no Claude session is needed
# for supervision. supervise.py exits as soon as a person is needed or new
# work appears, same as /sdlc:dispatch would restart it, so this calls it
# again in a loop until the epic closes or a person would be needed.
set -euo pipefail

plugin_dir="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
scripts="$plugin_dir/scripts"
request="${1:-create an app that displays hello world in a web page}"
mode="${SDLC_INTEGRATION:-epic-merge}"

base="${SDLC_SANDBOX:-$HOME/dev/sdlc-sandbox}/flow-$(date +%Y%m%d-%H%M%S)"
repo="$base/repo" logs="$base/logs"
mkdir -p "$repo" "$logs"
cd "$repo"
git init -q -b main
printf '# Demo app\n\nA small demo web app.\n' > README.md
git add README.md && git commit -q -m "Initial README"
"$plugin_dir/skills/init/scripts/init.sh" --integration "$mode"
echo "sandbox: $base"

step() {
  local name="$1" session_flag="$2" prompt="$3"
  echo "[$(date +%T)] $name: $prompt"
  claude -p --model "${SDLC_MODEL:-sonnet}" --plugin-dir "$plugin_dir" --permission-mode auto \
    --output-format stream-json --verbose $session_flag "$prompt" \
    </dev/null > "$logs/$name.jsonl" 2> "$logs/$name.stderr" || echo "  warning: claude exited non-zero"
  jq -r 'select(.type == "result") | "  $\(.total_cost_usd) · \(.num_turns) turns · error \(.is_error)"' "$logs/$name.jsonl" | tail -1
  jq -r --arg name "$name" 'select(.type == "result") | "## \($name)\n\n\(.result)\n"' "$logs/$name.jsonl" >> "$logs/summary.md"
}

planning=$(cat /proc/sys/kernel/random/uuid)
step 1-design "--session-id $planning" "/sdlc:design $request"
step 2-split "--resume $planning" "/sdlc:split as exactly one top-level epic"

bd where >/dev/null 2>&1 || { echo "no beads after split, stopping"; exit 1; }
git add -A && git commit -q -m "Design and tasks" && echo "committed design and tasks"

epic=$(bd list --type epic --no-parent --json 2>/dev/null | jq -r '.[0].id // empty')
[[ -n "$epic" ]] || { echo "no epic after split, stopping"; exit 1; }

# Split one of the plan's tasks further, and add a task that waits for it, to
# exercise dependency resolution across a task split after the initial plan.
split_target=$(bd list --parent "$epic" --json 2>/dev/null | jq -r '[.[] | select(.issue_type == "task")][0].id // empty')
if [[ -n "$split_target" ]]; then
  splitting=$(cat /proc/sys/kernel/random/uuid)
  step 3-split "--session-id $splitting" "/sdlc:split $split_target"
  "$plugin_dir/scripts/create-task.sh" --parent "$epic" \
    --title "Wait for $split_target" \
    --description "Depends on $split_target closing once its own children close." \
    --acceptance "no-op, exercises dependency resolution" \
    --scope "README.md" --verify "true" --complexity small \
    --after "$split_target" \
    && echo "added task waiting on $split_target"
else
  echo "no task under $epic to split, skipping"
fi

# supervise.py never exits just because work finished (see plan-supervisor.md,
# "When it exits"): it only stops for a person or for new-work outside --under.
# Run it in the background and poll separately for the two reasons this test
# stops it itself: the epic closed, or nothing is running and nothing is ready.
dispatch_log="$logs/4-dispatch.log"
attempt=0
while :; do
  attempt=$((attempt + 1))
  attempt_out="$logs/4-dispatch-$attempt.out"
  echo "[$(date +%T)] 4-dispatch-$attempt: $epic --parallel 2" | tee -a "$dispatch_log"
  "$scripts/supervise.py" --under "$epic" --parallel 2 > "$attempt_out" 2>&1 &
  pid=$!

  idle_polls=0
  stop_reason=""
  while kill -0 "$pid" 2>/dev/null; do
    sleep 15
    kill -0 "$pid" 2>/dev/null || break

    epic_status=$(bd show "$epic" --json 2>/dev/null | jq -r '.[0].status // empty')
    if [[ "$epic_status" == closed ]]; then
      stop_reason="epic closed"
      break
    fi

    running=$("$scripts/workers.py" --under "$epic" --alive-count)
    ready=$("$scripts/next-tasks.py" --under "$epic" --ids)
    if [[ "$running" == 0 && -z "$ready" ]]; then
      idle_polls=$((idle_polls + 1))
    else
      idle_polls=0
    fi
    (( idle_polls < 2 )) || stop_reason="nothing running and nothing ready: a person would be needed"
    [[ -n "$stop_reason" ]] && break
  done

  if [[ -n "$stop_reason" ]]; then
    kill -TERM "$pid" 2>/dev/null || true
    wait "$pid" 2>/dev/null || true
    echo "$stop_reason, stopping" | tee -a "$dispatch_log"
    break
  fi

  set +e
  wait "$pid"
  status=$?
  set -e
  cat "$attempt_out" | tee -a "$dispatch_log"

  if [[ "$status" -ne 0 ]]; then
    echo "supervise.py exited $status, stopping" | tee -a "$dispatch_log"
    break
  fi

  if grep -qx "taken over" "$attempt_out"; then
    echo "taken over by another supervisor, stopping" | tee -a "$dispatch_log"
    break
  fi

  (( attempt < 20 )) || { echo "dispatch: gave up after $attempt supervisor runs" | tee -a "$dispatch_log"; break; }
done

{
  echo "## Result"
  echo; echo "Beads:"; bd list --all --pretty 2>/dev/null
  echo; echo "Workers not closed:"; "$scripts/workers.py" --under "$epic"
  echo; echo "main:"; git log --oneline main
  echo; echo "Worker stats:"; "$scripts/stats.py" --under "$epic"
  echo; echo "Planning sessions: \$$(for f in "$logs"/*.jsonl; do jq -s 'map(select(.type == "result")) | last | .total_cost_usd // 0' "$f"; done | jq -s add)"
} | tee -a "$logs/summary.md"
echo "summary: $logs/summary.md"
