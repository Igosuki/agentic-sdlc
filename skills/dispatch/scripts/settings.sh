#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: settings.sh [key]

Prints the dispatch settings as "key=value" lines, or the value of one key.

  parallel     workers at a time on this machine, from the frontmatter of
               .claude/sdlc.local.md in the main checkout (default 2)
  integration  direct or epic-merge, from bd config custom.dispatch.integration (default direct)
  target       branch tasks end up in, from bd config custom.dispatch.target (default main)

Example .claude/sdlc.local.md:
  ---
  parallel: 3
  ---

Exit codes: 0 printed, 2 unknown key.
EOF2
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
root=$(dirname "$(git rev-parse --path-format=absolute --git-common-dir)")

local_setting() {
  [[ -f "$root/.claude/sdlc.local.md" ]] || return 0
  awk -v key="$1" '
    NR == 1 && $0 != "---" { exit }
    NR > 1 && $0 == "---" { exit }
    NR > 1 && index($0, key ":") == 1 { sub("^" key ":[ \t]*", ""); print; exit }
  ' "$root/.claude/sdlc.local.md"
}
bd_setting() {
  local v
  v=$(bd config get "custom.dispatch.$1" 2>/dev/null) || v=""
  [[ "$v" == *"(not set)" ]] || echo "$v"
}

parallel=$(local_setting parallel)
integration=$(bd_setting integration)
target=$(bd_setting target)
declare -A values=([parallel]="${parallel:-2}" [integration]="${integration:-direct}" [target]="${target:-main}")

if [[ $# -eq 0 ]]; then
  for key in parallel integration target; do echo "$key=${values[$key]}"; done
elif [[ -n "${values[$1]+set}" ]]; then
  echo "${values[$1]}"
else
  echo "error: unknown key $1" >&2
  usage >&2
  exit 2
fi
