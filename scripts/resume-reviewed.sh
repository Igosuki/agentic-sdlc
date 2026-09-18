#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: resume-reviewed.sh <task-id>

Resumes a task waiting on a human review whose gate is now resolved: the task
must be in_progress with dispatch_state=awaiting-review. Once its
dispatch_review_gate is closed and no process runs its worker, clears
dispatch_state and resumes its session, with the same prompt, to read the
review and continue. Run by supervise.py.

Prints "resumed <task>" once resumed, or "not resumed <task>: <reason>" if
the resume itself fails, restoring dispatch_state=awaiting-review and the
branch's worktrunk state marker. Prints nothing when its gate is still open
or its worker still runs.
Exit codes: 0 done (including nothing to do), 2 invalid arguments or the task
isn't awaiting review.
EOF2
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
[[ $# -eq 1 && "$1" != -* ]] || { usage >&2; exit 2; }
id="$1"
dir=$(dirname "$(readlink -f "$0")")
finish="$dir/finish-task.sh"

bead=$(bd show "$id" --json 2>/dev/null | jq '.[0]') || { echo "error: no bead $id" >&2; exit 2; }
get() { jq -r "$1 // empty" <<<"$bead"; }
dispatch_state=$(get .metadata.dispatch_state)
if [[ "$(get .status)" != in_progress || "$dispatch_state" != awaiting-review ]]; then
  echo "error: $id is not awaiting review (status $(get .status), dispatch_state: $dispatch_state)" >&2
  exit 2
fi

session=$(get .metadata.dispatch_session)
gate=$(get .metadata.dispatch_review_gate)
[[ -n "$gate" && -n "$session" ]] || exit 0
[[ "$(bd show "$gate" --json 2>/dev/null | jq -r '.[0].status // empty')" == closed ]] || exit 0
pgrep -f -- "--(session-id|resume) $session" >/dev/null 2>&1 && exit 0

bd update "$id" --unset-metadata dispatch_state >/dev/null
if ! out=$("$dir/resume-task.sh" "$id" --ended --prompt \
  "A person reviewed your change (gate $gate resolved). Read the task's comments (bd comments $id). If they ask for changes, make them and commit. Then run $finish $id again." 2>&1); then
  bd update "$id" --set-metadata dispatch_state=awaiting-review >/dev/null
  branch=$(get .metadata.dispatch_branch)
  [[ -z "$branch" ]] || "$dir/mark-branch.sh" "$branch" awaiting-review
  echo "not resumed $id: $(tail -1 <<<"$out")"
  exit 0
fi
echo "resumed $id"
