#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: settings.sh [key]

Prints the dispatch settings as "key=value" lines, or the value of one key.

  parallel     workers at a time on this machine, from the frontmatter of
               .claude/sdlc.local.md in the main checkout (default 2)
  design_dir   where sdlc:design writes documents, from the same frontmatter (no default:
               the design skill falls back to the repository's convention, then docs/design)
  workflow     "build" routes new work in this project to sdlc:build (SessionStart hook);
               from the same frontmatter, no default
  integration  direct or epic-merge, from bd config custom.dispatch.integration (default direct)
  target       branch tasks end up in, from bd config custom.dispatch.target (default main)
  review       none, agent or human: the review level for tasks with no review
               metadata of their own, from bd config custom.dispatch.review (default none)

Example .claude/sdlc.local.md:
  ---
  parallel: 3
  design_dir: docs/specs
  workflow: build
  ---

Exit codes: 0 printed, 2 unknown key.
EOF2
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
if common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null); then root=$(dirname "$common"); else root=$PWD; fi

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
design_dir=$(local_setting design_dir)
workflow=$(local_setting workflow)
integration=$(bd_setting integration)
target=$(bd_setting target)
review=$(bd_setting review)
declare -A values=([parallel]="${parallel:-2}" [design_dir]="$design_dir" [workflow]="$workflow" [integration]="${integration:-direct}" [target]="${target:-main}" [review]="${review:-none}")

if [[ $# -eq 0 ]]; then
  for key in parallel design_dir workflow integration target review; do echo "$key=${values[$key]}"; done
elif [[ -n "${values[$1]+set}" ]]; then
  echo "${values[$1]}"
else
  echo "error: unknown key $1" >&2
  usage >&2
  exit 2
fi
