#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: create-task.sh --title T --description D [options]

Creates one bead and prints: created <id> <type> "<title>"

Options:
  --type task|epic       default: task
  --parent ID            parent epic or task. If it's under an epic that's closed
                         or already integrating, this exits 2 instead of creating
                         anything.
  --acceptance TEXT      required for tasks
  --scope PATHS          required for tasks, comma-separated path prefixes
  --verify CMD           required for tasks, command that exits 0 when done
  --complexity SIZE      required for tasks: small|medium|large
  --design PATH          design or source doc the bead comes from
  --after ID             this bead waits for ID (repeatable)
  --priority N           0-4, default 2
  --agent NAME           execution_agent_type: the worker runs as this agent
  --model MODEL          execution_suggested_model: the worker's model when no agent is set
  --effort LEVEL         execution_reasoning_effort: low|medium|high|xhigh|max
  --review LEVEL         none|agent|human: review before merging (default: bd config
                         custom.dispatch.review, else none)

Exit codes: 0 created, 2 invalid arguments (all problems listed), 1 bd failed.
EOF
}

dir=$(dirname "$(readlink -f "$0")")
tasks_py="$dir/tasks.py"

type=task title="" description="" parent="" acceptance="" scope="" verify=""
complexity="" design="" priority=2 agent="" model="" effort="" review=""
after=()

while [[ $# -gt 0 ]]; do
  [[ "$1" == -h || "$1" == --help ]] && { usage; exit 0; }
  [[ $# -ge 2 ]] || { echo "error: $1 needs a value" >&2; usage >&2; exit 2; }
  case "$1" in
    --type) type="$2" ;;
    --title) title="$2" ;;
    --description) description="$2" ;;
    --parent) parent="$2" ;;
    --acceptance) acceptance="$2" ;;
    --scope) scope="$2" ;;
    --verify) verify="$2" ;;
    --complexity) complexity="$2" ;;
    --design) design="$2" ;;
    --after) after+=("$2") ;;
    --priority) priority="$2" ;;
    --agent) agent="$2" ;;
    --model) model="$2" ;;
    --effort) effort="$2" ;;
    --review) review="$2" ;;
    *) echo "error: unknown option $1" >&2; usage >&2; exit 2 ;;
  esac
  shift 2
done

errors=()
[[ -n "$title" ]] || errors+=("--title is required")
[[ -n "$description" ]] || errors+=("--description is required")
case "$type" in
  epic) ;;
  task)
    for field in acceptance scope verify complexity; do
      [[ -n "${!field}" ]] || errors+=("--$field is required for tasks")
    done
    [[ -z "$complexity" || "$complexity" =~ ^(small|medium|large)$ ]] || errors+=("--complexity must be small, medium or large")
    ;;
  *) errors+=("--type must be task or epic") ;;
esac
[[ "$priority" =~ ^[0-4]$ ]] || errors+=("--priority must be 0-4")
[[ -z "$effort" || "$effort" =~ ^(low|medium|high|xhigh|max)$ ]] || errors+=("--effort must be low, medium, high, xhigh or max")
[[ -z "$review" || "$review" =~ ^(none|agent|human)$ ]] || errors+=("--review must be none, agent or human")
# bd dep add reports success for unknown ids without recording anything.
for ref in "$parent" "${after[@]}"; do
  [[ -z "$ref" ]] || bd show "$ref" --json >/dev/null 2>&1 || errors+=("no bead $ref")
done

# A task added under an epic that has already started integrating (or finished)
# can merge after the epic branch is gone, or never be scheduled at all.
integration_id=""
if [[ -n "$parent" ]] && bd show "$parent" --json >/dev/null 2>&1; then
  parent_json=$(bd show "$parent" --json | jq '.[0]')
  if [[ "$(jq -r '.issue_type' <<<"$parent_json")" == epic ]]; then
    epic_id="$parent"
    epic_json="$parent_json"
  else
    epic_id=$(bd list --all --limit 0 --json | "$tasks_py" epic "$parent")
    epic_json=""
    [[ -z "$epic_id" ]] || epic_json=$(bd show "$epic_id" --json 2>/dev/null | jq '.[0]')
  fi
  if [[ -n "$epic_id" ]]; then
    if [[ "$(jq -r '.status' <<<"$epic_json")" == closed ]]; then
      errors+=("epic $epic_id is closed; create the task without --parent or under a new epic")
    else
      integration_id=$(jq -r '.metadata.dispatch_integration_task // empty' <<<"$epic_json")
      if [[ -n "$integration_id" ]]; then
        integration_status=$(bd show "$integration_id" --json 2>/dev/null | jq -r '.[0].status // empty')
        if [[ "$integration_status" != open ]]; then
          errors+=("epic $epic_id is already integrating; create the task without --parent or under a new epic")
          integration_id=""
        fi
      fi
    fi
  fi
fi

if [[ ${#errors[@]} -gt 0 ]]; then
  printf 'error: %s\n' "${errors[@]}" >&2
  usage >&2
  exit 2
fi

metadata=$(jq -cn --arg scope "$scope" --arg verify "$verify" --arg complexity "$complexity" \
  --arg design "$design" --arg agent "$agent" --arg model "$model" --arg effort "$effort" \
  --arg review "$review" \
  '{scope: $scope, verify: $verify, complexity: $complexity, design: $design,
    execution_agent_type: $agent, execution_suggested_model: $model, execution_reasoning_effort: $effort,
    review: $review}
   | with_entries(select(.value != ""))')

args=(create "$title" --type "$type" --description "$description" --priority "$priority"
  --metadata "$metadata" --silent)
[[ -n "$parent" ]] && args+=(--parent "$parent")
[[ -n "$acceptance" ]] && args+=(--acceptance "$acceptance")
[[ -n "$design" ]] && args+=(--spec-id "$design")
[[ ${#after[@]} -eq 0 ]] || args+=(--deps "$(IFS=,; echo "${after[*]}")")

id=$(bd "${args[@]}") || { echo "error: bd create failed" >&2; exit 1; }

if [[ -n "$integration_id" ]]; then
  bd dep add "$integration_id" "$id" >/dev/null \
    || { echo "error: created $id but could not make $integration_id wait for it" >&2; exit 1; }
fi

line="created $id $type \"$title\""
[[ ${#after[@]} -gt 0 ]] && line+=" after ${after[*]}"
echo "$line"
