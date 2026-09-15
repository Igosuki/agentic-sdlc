#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: next-tasks.sh [--epic EPIC] [--ids]

Lists ready tasks that can be dispatched, in work order:
  1. tasks of epics already in progress (a task claimed or closed), by epic priority
  2. then tasks of other epics and tasks without an epic, by priority
  3. within an epic: tasks that unblock the most others first, then priority, then oldest

A task can be dispatched when it is ready, is not an epic, has no children,
and has a verify command (metadata.verify) or is an integration task.

Options:
  --epic EPIC   only tasks of that epic
  --ids         print only task ids, one per line

Exit codes: 0 listed (possibly nothing), 2 invalid arguments.
EOF2
}

epic="" ids=false
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --ids) ids=true ;;
    --epic)
      [[ $# -ge 2 ]] || { echo "error: --epic needs a value" >&2; usage >&2; exit 2; }
      epic="$2"; shift ;;
    *) echo "error: unknown argument $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

all=$(bd list --all --limit 0 --json)
ready=$(bd ready --limit 0 --json)

ordered=$(jq -n --argjson all "$all" --argjson ready "$ready" --arg only "$epic" '
  def epic_of($by; $id):
    ($by[$id].parent // null) as $p
    | if $p == null or $by[$p] == null then null
      elif $by[$p].issue_type == "epic" then $p
      else epic_of($by; $p) end;
  def started($e): $all | any(.parent == $e and (.status == "in_progress" or .status == "closed"));
  ($all | map({key: .id, value: .}) | from_entries) as $by
  | ($all | map(.parent // empty) | unique) as $parents
  | [$ready[] | $by[.id] // empty
     | select(.issue_type != "epic" and .issue_type != "event")
     | select((.metadata.verify // "") != "" or .metadata.dispatch_role == "integration")
     | select(.id as $id | $parents | index($id) | not)
     | . + {epic: epic_of($by; .id)}
     | select($only == "" or .epic == $only)
     | (if .epic then $by[.epic] else . end) as $group
     | (.epic != null and started(.epic)) as $in_progress
     | . + {
         epic_started: $in_progress,
         key: [(if $in_progress then 0 else 1 end), $group.priority, $group.created_at,
               -(.dependent_count // 0), .priority, .created_at]
       }]
  | sort_by(.key)')

if $ids; then
  jq -r '.[].id' <<<"$ordered"
elif [[ "$(jq length <<<"$ordered")" -eq 0 ]]; then
  echo "no ready task to dispatch"
else
  jq -r '.[] | "\(.id)  P\(.priority)  unblocks \(.dependent_count // 0)  \(if .epic then "epic \(.epic)\(if .epic_started then " (in progress)" else "" end)" else "no epic" end)  \(.title)"' <<<"$ordered"
fi
