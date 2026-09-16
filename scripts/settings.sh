#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: settings.sh [key]

Prints the dispatch settings as "key=value" lines, or the value of one key.

  parallel     workers at a time on this machine, from the frontmatter of
               .claude/sdlc.local.md in the main checkout (default 2)
  workflow     "build" routes new work in this project to sdlc:build (SessionStart hook);
               from the same frontmatter, no default
  integration  direct, epic-merge or epic-pr, from bd config custom.dispatch.integration (default direct)
  target       branch tasks end up in, from bd config custom.dispatch.target (default main)
  review       none, agent or human: the review level for tasks with no review
               metadata of their own, from bd config custom.dispatch.review (default none)

Example .claude/sdlc.local.md:
  ---
  parallel: 3
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

# Computes only the requested key, so a caller that wants one key (e.g. the
# SessionStart hook asking for "workflow") never pays for a bd call it
# doesn't need.
value_for() {
  local v
  case "$1" in
    parallel)    v=$(local_setting parallel); echo "${v:-2}" ;;
    workflow)    local_setting workflow ;;
    integration) v=$(bd_setting integration); echo "${v:-direct}" ;;
    target)      v=$(bd_setting target); echo "${v:-main}" ;;
    review)      v=$(bd_setting review); echo "${v:-none}" ;;
    *)           return 2 ;;
  esac
}

if [[ $# -eq 0 ]]; then
  for key in parallel workflow integration target review; do
    echo "$key=$(value_for "$key")"
  done
elif v=$(value_for "$1" 2>/dev/null); then
  echo "$v"
else
  echo "error: unknown key $1" >&2
  usage >&2
  exit 2
fi
