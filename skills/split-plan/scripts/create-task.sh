#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: create-task.sh --title T --description D [options]

Creates one bead and prints: created <id> <type> "<title>"

Options:
  --type task|epic       default: task
  --parent ID            parent epic or task
  --acceptance TEXT      required for tasks
  --scope PATHS          required for tasks, comma-separated path prefixes
  --verify CMD           required for tasks, command that exits 0 when done
  --complexity SIZE      required for tasks: small|medium|large
  --domain NAME          required for tasks, e.g. frontend, backend, infra
  --design PATH          design or source doc the bead comes from
  --after ID             this bead waits for ID (repeatable)
  --priority N           0-4, default 2

Exit codes: 0 created, 2 invalid arguments (all problems listed), 1 bd failed.
EOF
}

type=task title="" description="" parent="" acceptance="" scope="" verify=""
complexity="" domain="" design="" priority=2
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
    --domain) domain="$2" ;;
    --design) design="$2" ;;
    --after) after+=("$2") ;;
    --priority) priority="$2" ;;
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
    for field in acceptance scope verify complexity domain; do
      [[ -n "${!field}" ]] || errors+=("--$field is required for tasks")
    done
    [[ -z "$complexity" || "$complexity" =~ ^(small|medium|large)$ ]] || errors+=("--complexity must be small, medium or large")
    ;;
  *) errors+=("--type must be task or epic") ;;
esac
[[ "$priority" =~ ^[0-4]$ ]] || errors+=("--priority must be 0-4")
# bd dep add reports success for unknown ids without recording anything.
for ref in "$parent" "${after[@]}"; do
  [[ -z "$ref" ]] || bd show "$ref" --json >/dev/null 2>&1 || errors+=("no bead $ref")
done

if [[ ${#errors[@]} -gt 0 ]]; then
  printf 'error: %s\n' "${errors[@]}" >&2
  usage >&2
  exit 2
fi

metadata=$(jq -cn --arg scope "$scope" --arg verify "$verify" --arg complexity "$complexity" \
  --arg domain "$domain" --arg design "$design" \
  '{scope: $scope, verify: $verify, complexity: $complexity, domain: $domain, design: $design}
   | with_entries(select(.value != ""))')

args=(create "$title" --type "$type" --description "$description" --priority "$priority"
  --labels sdlc --metadata "$metadata" --silent)
[[ -n "$parent" ]] && args+=(--parent "$parent")
[[ -n "$acceptance" ]] && args+=(--acceptance "$acceptance")
[[ -n "$design" ]] && args+=(--spec-id "$design")

id=$(bd "${args[@]}") || { echo "error: bd create failed" >&2; exit 1; }

for dep in "${after[@]}"; do
  bd dep add "$id" "$dep" >/dev/null || { echo "error: created $id but could not make it wait for $dep" >&2; exit 1; }
done

line="created $id $type \"$title\""
[[ ${#after[@]} -gt 0 ]] && line+=" after ${after[*]}"
echo "$line"
