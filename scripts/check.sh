#!/usr/bin/env bash
set -uo pipefail

usage() {
  cat <<'EOF2'
Usage: check.sh

Checks this machine for what sdlc needs, one line per item:
  os <name>                    operating system, with a warning appended if not Linux
  ok <tool> <version>          present, recent enough
  missing <tool>               required and not found
  old <tool> <version> <min>   required and too old
  optional <tool> <status>     only needed for some features
  recommended <name> <status>  companion that makes the workflow better or cheaper

Always exits 0; read the lines.
EOF2
}
[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }

at_least() { [[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" == "$2" ]]; }
version_of() { "$@" 2>/dev/null | grep -oE '[0-9]+\.[0-9]+(\.[0-9]+)?' | head -1; }

need() { # tool min-version version-command...
  local tool=$1 min=$2; shift 2
  if ! command -v "$tool" >/dev/null; then echo "missing $tool"; return; fi
  local v; v=$(version_of "$@")
  if [[ -n "$min" && -n "$v" ]] && ! at_least "$v" "$min"; then echo "old $tool $v $min"; else echo "ok $tool ${v:-present}"; fi
}

echo "os $(uname -s)$( [[ "$(uname -s)" == Linux ]] || echo " (not supported yet: the scripts need setsid, GNU stat and GNU date)")"
need claude 2.1 claude --version
need bd 1.2.2 bd version
need wt 0.77 wt --version
need git 2.30 git --version
need jq 1.6 jq --version
need python3 3.9 python3 --version
for tool in uuidgen setsid pgrep timeout; do command -v "$tool" >/dev/null && echo "ok $tool present" || echo "missing $tool"; done
command -v gh >/dev/null && echo "optional gh $(version_of gh --version) (epic-pr mode)" || echo "optional gh not installed (only needed for epic-pr mode)"

agent_file() { [[ -f "$HOME/.claude/agents/$1.md" || -f ".claude/agents/$1.md" ]]; }
rtk gain >/dev/null 2>&1 && echo "recommended rtk installed" || echo "recommended rtk not installed: compresses command output, so every session and worker spends fewer tokens"
agent_file reviewer && echo "recommended reviewer-agent installed" \
  || echo "recommended reviewer-agent not found: workers can review their change before merging"
count=$(ls "$HOME/.claude/agents"/*.md .claude/agents/*.md 2>/dev/null | wc -l)
echo "recommended specialist-agents $count agent files in ~/.claude/agents and .claude/agents: workers hand implementation to matching agents when your CLAUDE.md asks them to"
exit 0
