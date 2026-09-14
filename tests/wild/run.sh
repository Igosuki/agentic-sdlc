#!/usr/bin/env bash
# Headless "in the wild" run of the design and split skills. Everything goes under $SDLC_SANDBOX.
set -euo pipefail

plugin_dir="$(cd "$(dirname "$(readlink -f "$0")")/../.." && pwd)"
dry_run=false
[[ "${1:-}" == --dry-run ]] && dry_run=true

base="${SDLC_SANDBOX:-$HOME/dev/sdlc-sandbox}/wild-$(date +%Y%m%d-%H%M%S)"
repo="$base/repo" logs="$base/logs"
mkdir -p "$repo" "$logs"
cd "$repo"
git init -q -b main
printf '# Demo app\n\nA small demo web app.\n' > README.md
git add README.md && git commit -q -m "Initial README"
echo "sandbox: $base"

step() {
  local n="$1" name="$2" session_flag="$3" prompt="$4"
  local cmd=(claude -p --model "${SDLC_MODEL:-sonnet}" --plugin-dir "$plugin_dir" --dangerously-skip-permissions
    --output-format stream-json --verbose $session_flag "$prompt")
  echo "step $n ($name): $prompt"
  if $dry_run; then
    echo "  ${cmd[*]}"
    return
  fi
  "${cmd[@]}" > "$logs/$n-$name.jsonl" 2> "$logs/$n-$name.stderr" || echo "  warning: claude exited non-zero"
  local result
  result=$(grep '"type":"result"' "$logs/$n-$name.jsonl" | tail -1)
  if [[ -z "$result" ]]; then
    echo "  warning: no result line, see $logs/$n-$name.stderr"
    return
  fi
  jq -r --arg n "$n" --arg p "$prompt" \
    '"## Step \($n): \($p)\n\nsession \(.session_id) · cost $\(.total_cost_usd) · turns \(.num_turns) · error \(.is_error)\n\n\(.result)\n"' \
    <<<"$result" >> "$logs/summary.md"
  jq -r '"  cost $\(.total_cost_usd), turns \(.num_turns), error \(.is_error)"' <<<"$result"
}

session_a=$(cat /proc/sys/kernel/random/uuid)
session_b=$(cat /proc/sys/kernel/random/uuid)
session_c=$(cat /proc/sys/kernel/random/uuid)

step 1 design "--session-id $session_a" "/sdlc:design create an app that displays hello world in a web page"
step 2 split-plan "--resume $session_a" "/sdlc:split-plan"
step 3 design "--session-id $session_b" "/sdlc:design add a music player that automatically plays a nice piano tune on the web page"
step 4 split-plan "--resume $session_b" "/sdlc:split-plan"

if $dry_run; then
  echo "step 5: bd create \"add a play queue of piano tunes for the music player\" -t epic --silent"
  step 6 split-task "--session-id $session_c" "/sdlc:split-task <epic id>"
  exit 0
fi

if ! bd where >/dev/null 2>&1; then
  echo "beads not initialized after step 4; skipping steps 5 and 6"
else
  epic=$(bd create "add a play queue of piano tunes for the music player" -t epic --silent)
  echo "step 5: created epic $epic"
  printf '## Step 5: bd create epic\n\n%s\n\n' "$epic" >> "$logs/summary.md"
  step 6 split-task "--session-id $session_c" "/sdlc:split-task $epic"
fi

{
  echo "## Result"
  echo; echo "Design docs:"; find "$repo" -path "$repo/.git" -prune -o -path "$repo/.beads" -prune -o -name '*.md' -newer "$repo/README.md" -print
  echo; echo "Beads:"; bd list --all --pretty 2>/dev/null || echo "(none)"
  echo; echo "Total cost: \$$(grep -h '"type":"result"' "$logs"/*.jsonl 2>/dev/null | jq -s 'map(.total_cost_usd) | add')"
} | tee -a "$logs/summary.md"
echo "summary: $logs/summary.md"
