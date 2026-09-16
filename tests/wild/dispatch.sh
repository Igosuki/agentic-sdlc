#!/usr/bin/env bash
# Headless run of the whole flow on a new project: design, split, add a
# split task another task waits on, then dispatch until the epic is idle.
# /sdlc:dispatch only confirms and starts the supervisor, and there's no one
# here to confirm with, so this drives the sdlc:supervisor agent directly,
# with --under and --parallel 2. The supervisor ends its run as soon as a
# task needs a person, same as /sdlc:dispatch would restart it, so this
# calls it again until nothing is running and nothing is ready.
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
"$plugin_dir/scripts/init.sh" --integration "$mode"
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

attempt=0
while :; do
  attempt=$((attempt + 1))
  step "4-dispatch-$attempt" "--agent sdlc:supervisor" "$epic --parallel 2"
  running=$("$scripts/workers.py" --under "$epic" --alive-count)
  ready=$("$scripts/next-tasks.py" --under "$epic" --ids)
  [[ "$running" == 0 && -z "$ready" ]] && break
  (( attempt < 20 )) || { echo "dispatch: gave up after $attempt supervisor runs"; break; }
done

{
  echo "## Result"
  echo; echo "Beads:"; bd list --all --pretty 2>/dev/null
  echo; echo "Workers not closed:"; "$scripts/workers.py" --under "$epic"
  echo; echo "main:"; git log --oneline main
  echo; echo "Worker stats:"; "$scripts/stats.py" --under "$epic"
  echo; echo "Planning and supervisor sessions: \$$(for f in "$logs"/*.jsonl; do jq -s 'map(select(.type == "result")) | last | .total_cost_usd // 0' "$f"; done | jq -s add)"
} | tee -a "$logs/summary.md"
echo "summary: $logs/summary.md"
