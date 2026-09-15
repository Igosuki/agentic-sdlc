#!/usr/bin/env bash
# Headless run of the whole flow on a new project: design, split-plan, then dispatch until no work is left.
# The supervisor runs one pass per claude -p call; this loop calls it again whenever a worker ends.
set -euo pipefail

plugin_dir="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
scripts="$plugin_dir/skills/dispatch/scripts"
request="${1:-create an app that displays hello world in a web page}"
mode="${SDLC_INTEGRATION:-epic-merge}"
max_rounds="${SDLC_MAX_ROUNDS:-30}"

base="${SDLC_SANDBOX:-$HOME/dev/sdlc-sandbox}/flow-$(date +%Y%m%d-%H%M%S)"
repo="$base/repo" logs="$base/logs"
mkdir -p "$repo" "$logs"
cd "$repo"
git init -q -b main
printf '# Demo app\n\nA small demo web app.\n' > README.md
git add README.md && git commit -q -m "Initial README"
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
step 2-split-plan "--resume $planning" "/sdlc:split-plan"

bd where >/dev/null 2>&1 || { echo "no beads after split-plan, stopping"; exit 1; }
git add -A && git commit -q -m "Design and tasks" && echo "committed design and tasks"
bd config set custom.dispatch.integration "$mode" >/dev/null
parallel=$("$scripts/settings.sh" parallel)

for round in $(seq "$max_rounds"); do
  step "3-dispatch-$round" "" "/sdlc:dispatch"
  while :; do
    alive=$("$scripts/workers.sh" --alive-count)
    ready=$("$scripts/next-tasks.sh" --ids | wc -l)
    (( alive > 0 && (ready == 0 || alive >= parallel) )) || break
    sleep 15
  done
  # One more pass after the last worker ends, so the supervisor sees stopped or crashed tasks.
  if (( alive == 0 && ready == 0 )); then
    [[ -z "${idle:-}" ]] || { echo "[$(date +%T)] no worker running and no ready task"; break; }
    idle=1
  else
    idle=""
  fi
done

{
  echo "## Result"
  echo; echo "Beads:"; bd list --all --pretty 2>/dev/null
  echo; echo "Workers not closed:"; "$scripts/workers.sh"
  echo; echo "main:"; git log --oneline main
  echo; echo "Worker stats:"; "$plugin_dir/skills/stats/scripts/stats.sh"
  echo; echo "Planning and supervisor sessions: \$$(for f in "$logs"/*.jsonl; do jq -s 'map(select(.type == "result")) | last | .total_cost_usd // 0' "$f"; done | jq -s add)"
} | tee -a "$logs/summary.md"
echo "summary: $logs/summary.md"
