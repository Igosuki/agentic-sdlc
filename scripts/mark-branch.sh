#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: mark-branch.sh <branch> <state>

Sets a task branch's worktrunk state marker (wt config state marker set /
clear), so wt list shows what a dispatched task is doing. States:
  running          🚧
  awaiting-review   👀
  merged            ✅
  pr-opened         📬
  failed            ❌
  stopped           🛑
  crashed           💥
  clear             removes the marker

A wt failure (wt missing, wt errors) never fails the caller.

Exit codes: 0 always, unless the arguments are wrong (2).
EOF
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
[[ $# -eq 2 ]] || { usage >&2; exit 2; }
branch="$1" state="$2"

case "$state" in
  running) marker="🚧" ;;
  awaiting-review) marker="👀" ;;
  merged) marker="✅" ;;
  pr-opened) marker="📬" ;;
  failed) marker="❌" ;;
  stopped) marker="🛑" ;;
  crashed) marker="💥" ;;
  clear) marker="" ;;
  *) usage >&2; exit 2 ;;
esac

if [[ "$state" == clear ]]; then
  wt config state marker clear --branch "$branch" >/dev/null 2>&1 || true
else
  wt config state marker set "$marker" --branch "$branch" >/dev/null 2>&1 || true
fi
exit 0
