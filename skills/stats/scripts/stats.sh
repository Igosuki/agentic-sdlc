#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: stats.sh [epic-id]

Reports dispatched work from the event beads that record each worker attempt
(record-task.sh): per task its latest state, attempts, cost, duration, models
and agents; per epic and overall the totals. A crashed run that was never
recorded isn't counted.

Exit codes: 0 reported, 2 invalid arguments.
EOF2
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
[[ $# -le 1 && "${1:-}" != -* ]] || { usage >&2; exit 2; }
only="${1:-}"

all=$(bd list --all --limit 0 --json)
events=$(bd list --type event --all --limit 0 --json)

jq -rn --argjson all "$all" --argjson events "$events" --arg only "$only" '
  def money: (. * 100 | round) as $c | "$\($c / 100 | floor).\($c % 100 | tostring | if length < 2 then "0" + . else . end)";
  def dur: (. / 60 | floor | tostring) + "m" + ((. % 60) | tostring | if length < 2 then "0" + . else . end) + "s";
  ($all | map({key: .id, value: .}) | from_entries) as $by
  | [$events[] | select((.event_kind // "") | startswith("dispatch."))
     | (.payload | try fromjson catch {}) as $p
     | {task: .target, state: (.event_kind | ltrimstr("dispatch.")), created: .created_at,
        cost: ($p.cost_usd // 0), seconds: ($p.duration_s // 0), model: ($p.model // ""), agents: ($p.agents // [])}]
  | group_by(.task)
  | map({
      task: .[0].task, title: ($by[.[0].task].title // ""), epic: ($by[.[0].task].parent // null),
      state: (sort_by(.created) | last.state), attempts: length,
      cost: (map(.cost) | add), seconds: (map(.seconds) | add),
      models: (map(.model | split(",")[]) | unique | map(select(. != "")) | join(",")),
      agents: (map(.agents[]) | unique | join(","))})
  | map(select($only == "" or .epic == $only))
  | if length == 0 then "no recorded attempts" else
      (group_by(.epic) | map(
        (.[0].epic) as $e
        | (if $e then "epic \($e) \"\($by[$e].title // "")\" (\($by[$e].status // "?")): \(length) tasks, \(map(.cost) | add | money), \(map(.seconds) | add | dur)"
           else "no epic: \(length) tasks, \(map(.cost) | add | money), \(map(.seconds) | add | dur)" end),
          (.[] | "  \(.task)  \(.state)  \(.attempts) attempt\(if .attempts > 1 then "s" else "" end)  \(.cost | money)  \(.seconds | dur)  \(.models)\(if .agents != "" then "  agents: \(.agents)" else "" end)  \(.title)")
      ) | .[]),
      "total: \(length) tasks, \(map(.cost) | add | money), \(map(.seconds) | add | dur)"
    end'
