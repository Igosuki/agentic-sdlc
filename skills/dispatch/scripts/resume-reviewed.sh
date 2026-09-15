#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: resume-reviewed.sh

Resumes tasks waiting on a human review whose gate is now resolved: for each
in_progress task with dispatch_state=awaiting-review, whose dispatch_review_gate
is closed and whose worker process isn't alive, sets dispatch_state=running and
resumes its session to read the review and continue. Run by watch.sh.

Prints "resumed <task>" for each one it resumes.
Exit codes: 0 done.
EOF2
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
dir=$(dirname "$(readlink -f "$0")")
finish="$dir/finish-task.sh"

for task in $(bd list --status in_progress --limit 0 --metadata-field dispatch_state=awaiting-review --json | jq -r '.[].id'); do
  bead=$(bd show "$task" --json | jq '.[0]')
  session=$(jq -r '.metadata.dispatch_session // empty' <<<"$bead")
  gate=$(jq -r '.metadata.dispatch_review_gate // empty' <<<"$bead")
  [[ -n "$gate" && -n "$session" ]] || continue
  [[ "$(bd show "$gate" --json 2>/dev/null | jq -r '.[0].status // empty')" == closed ]] || continue
  pgrep -f -- "--(session-id|resume) $session" >/dev/null 2>&1 && continue
  bd update "$task" --set-metadata dispatch_state=running >/dev/null
  if ! out=$("$dir/resume-task.sh" "$task" --ended --prompt \
    "A person reviewed your change (gate $gate resolved). Read the task's comments (bd comments $task). If they ask for changes, make them and commit. Then run $finish $task again." 2>&1); then
    bd update "$task" --set-metadata dispatch_state=awaiting-review >/dev/null
    echo "not resumed $task: $(tail -1 <<<"$out")"
    continue
  fi
  echo "resumed $task"
done
