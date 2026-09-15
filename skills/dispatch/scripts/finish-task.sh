#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: finish-task.sh <task-id>

Run by a task's worker once its work is committed. While holding the merge
queue of the task's base branch:
  1. checks that the branch has commits and no tracked file has uncommitted changes
  2. reviews the change, per the task's review level (metadata review, else
     bd config custom.dispatch.review, default none):
       none    no review
       agent   a separate reviewer session judges the diff; on requested
               changes, the worker fixes them and runs this again (up to 3
               rounds, then a person is needed)
       human   a human gate blocks the task until a person reviews the diff
               and resolves it; the worker stops and is resumed afterwards
  3. rebases the branch onto the base
  4. runs the verify command (for an integration task, the verify command of
     every task in the epic)
  5. fast-forwards the base to the branch
Then closes the task, and closes the epic when it is done: after its last task
in direct mode, after its integration task in epic-merge mode. In epic-pr mode,
the integration task runs the project's pre-merge checks and pushes the epic
branch and opens a pull request instead of step 5, and gates this task on the
pull request (gh:pr); close-prs.sh closes the task and the epic once the pull
request is merged.

The merge itself runs the project's pre-merge checks (wt merge / wt hook
pre-merge, from .config/wt.toml). An unapproved check needs a person to run
wt config approvals add once on this machine; a failing check is a problem for
the worker to fix, like a failing verify command.

On a problem the worker can fix, it prints what to fix and exits 1: fix it,
commit, run it again. On a problem only a person can resolve, it exits 3: the
worker records it with bd comments add and stops.
The worktree is removed later, by record-task.sh, once the worker has ended.

Exit codes: 0 merged and closed, 1 something the worker fixes,
  2 invalid arguments or no dispatched worker, 3 a person is needed.
EOF
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
[[ $# -eq 1 && "$1" != -* ]] || { usage >&2; exit 2; }
id="$1"
dir=$(dirname "$(readlink -f "$0")")

show() { bd show "$1" --json 2>/dev/null | jq '.[0]' 2>/dev/null; }
get() { jq -r "$2 // empty" <<<"$1"; }
problem() { echo "not merged: $1"; exit 1; }
person() { echo "needs a person: $1"; exit 3; }

# stderr of wt merge / wt hook pre-merge for a project command nobody has approved on this
# machine yet, vs. any other failure (a failing hook, a real merge conflict).
needs_approval() { grep -q "needs approval" <<<"$1" && grep -q "Cannot prompt for approval in non-interactive environment" <<<"$1"; }

task=$(show "$id") || { echo "error: no bead $id" >&2; exit 2; }
base=$(get "$task" .metadata.dispatch_base)
branch=$(get "$task" .metadata.dispatch_branch)
role=$(get "$task" .metadata.dispatch_role)
if [[ "$(get "$task" .status)" != in_progress || "$(get "$task" .metadata.dispatch_state)" != running || -z "$base" || -z "$branch" ]]; then
  echo "error: $id has no dispatched worker (status $(get "$task" .status), dispatch_state: $(get "$task" .metadata.dispatch_state))" >&2
  exit 2
fi
wt_path=$(wt list --format json </dev/null 2>/dev/null | jq -r --arg b "$branch" '.items[] | select(.branch == $b) | .worktree.path // empty')
[[ -n "$wt_path" ]] || { echo "error: no worktree for branch $branch" >&2; exit 2; }
main_root=$(dirname "$(git -C "$wt_path" rev-parse --path-format=absolute --git-common-dir)")

epic="" epic_bead="" parent=$(get "$task" .parent)
while [[ -n "$parent" ]]; do
  bead=$(show "$parent") || break
  if [[ "$(get "$bead" .issue_type)" == epic ]]; then epic="$parent" epic_bead="$bead"; break; fi
  parent=$(get "$bead" .parent)
done
mode=$( [[ -n "$epic_bead" ]] && get "$epic_bead" .metadata.dispatch_integration || true)

if [[ "$role" == integration ]]; then
  verifies=$(bd list --parent "$epic" --all --limit 0 --json |
    jq -c --arg id "$id" '[.[] | select(.id != $id and (.metadata.verify // "") != "") | {id, verify: .metadata.verify}]')
else
  verifies=$(jq -cn --arg id "$id" --arg v "$(get "$task" .metadata.verify)" '[{id: $id, verify: $v}]')
fi

[[ "$(git -C "$wt_path" rev-list --count "$base..$branch")" -gt 0 ]] || problem "nothing committed on $branch since $base"
dirty=$(git -C "$wt_path" status --porcelain --untracked-files=no | cut -c4- | paste -sd' ' -)
[[ -z "$dirty" ]] || problem "uncommitted changes to tracked files: $dirty. Commit or discard them."

review=$(get "$task" .metadata.review)
if [[ -z "$review" ]]; then
  review=$(bd config get custom.dispatch.review 2>/dev/null) || review=""
  [[ "$review" != *"(not set)" ]] || review=""
  review=${review:-none}
fi

if [[ "$review" == agent || "$review" == human ]]; then
  patch=$(git -C "$wt_path" diff "$base...$branch" | git patch-id --stable | cut -d' ' -f1)
fi

if [[ "$review" == agent ]] && ! { [[ "$(get "$task" .metadata.dispatch_review)" == approved && "$(get "$task" .metadata.dispatch_review_patch)" == "$patch" ]]; }; then
  logs="$(git -C "$wt_path" rev-parse --path-format=absolute --git-common-dir)/sdlc/logs"
  mkdir -p "$logs"
  session=$(get "$task" .metadata.dispatch_session)
  rounds=$(get "$task" .metadata.dispatch_review_rounds); rounds=${rounds:-0}; rounds=$((rounds + 1))

  schema='{"type":"object","properties":{"verdict":{"type":"string","enum":["approve","changes"]},"summary":{"type":"string"},"findings":{"type":"array","items":{"type":"object","properties":{"file":{"type":"string"},"line":{"type":"integer"},"severity":{"type":"string","enum":["blocker","major","minor"]},"problem":{"type":"string"},"fix":{"type":"string"}},"required":["file","severity","problem"]}}},"required":["verdict","summary","findings"]}'
  prompt="Task $id: $(get "$task" .title)

$(get "$task" .description)

Acceptance:
$(get "$task" .acceptance_criteria)
"
  [[ -z "$(get "$task" .metadata.scope)" ]] || prompt+="
Scope: $(get "$task" .metadata.scope)"
  prompt+="
Verify command:
$(get "$task" .metadata.verify)

Review the change on branch $branch against $base: run git diff $base...$branch and read the code you need. Report only problems that matter: bugs, acceptance not met, security issues, changes outside the scope, missing tests for new behaviour. Don't report style preferences or problems that were already there. Approve when nothing should block merging."

  reviewer=(env -u DISPATCH_TASK timeout 900 claude -p --output-format json --permission-mode auto \
    --disallowedTools "Edit Write NotebookEdit" --json-schema "$schema")
  if [[ -f "$HOME/.claude/agents/reviewer.md" || -f "$main_root/.claude/agents/reviewer.md" ]]; then
    reviewer+=(--agent reviewer)
  else
    reviewer+=(--model "${SDLC_REVIEW_MODEL:-sonnet}" --append-system-prompt \
      "You are reviewing another agent's change before it merges. Report only problems that block merging.")
  fi
  if review_json=$(cd "$wt_path" && "${reviewer[@]}" "$prompt" 2>"$logs/$id-$session.review-$rounds.err"); then
    review_exit=0
  else
    review_exit=$?
  fi
  echo "$review_json" > "$logs/$id-$session.review-$rounds.json"

  cost=$(jq -r '.total_cost_usd // 0' <<<"$review_json" 2>/dev/null) || cost=0
  verdict=$(jq -r '.structured_output.verdict // empty' <<<"$review_json" 2>/dev/null) || verdict=""
  summary=$(jq -r '.structured_output.summary // empty' <<<"$review_json" 2>/dev/null) || summary=""
  findings=$(jq -c '.structured_output.findings // []' <<<"$review_json" 2>/dev/null) || findings="[]"
  prev_cost=$(get "$task" .metadata.dispatch_review_cost); prev_cost=${prev_cost:-0}
  total_review_cost=$(jq -n --argjson a "$prev_cost" --argjson b "${cost:-0}" '$a + $b')
  bd update "$id" --set-metadata "dispatch_review_rounds=$rounds" --set-metadata "dispatch_review_cost=$total_review_cost" >/dev/null

  if [[ -z "$verdict" ]]; then
    reason="the review returned no verdict"
    [[ $review_exit -ne 124 ]] || reason="the review timed out after 900s"
    [[ $review_exit -eq 0 || $review_exit -eq 124 ]] || reason="the review exited $review_exit"
    problem "the review didn't complete ($reason); run this again"
  fi

  findings_lines=$(jq -r '.[] | "\(.severity)  \(.file)\(if .line then ":\(.line)" else "" end)  \(.problem)\(if .fix then " -- fix: \(.fix)" else "" end)"' <<<"$findings")

  if [[ "$verdict" == approve ]]; then
    bd update "$id" --set-metadata dispatch_review=approved --set-metadata "dispatch_review_patch=$patch" >/dev/null
    bd comments add "$id" "review round $rounds approved: $summary" >/dev/null
  else
    bd update "$id" --set-metadata dispatch_review=changes >/dev/null
    bd comments add "$id" "review round $rounds requested changes: $summary
$findings_lines" >/dev/null
    if [[ "$rounds" -lt 3 ]]; then
      echo "not merged: review round $rounds requested changes:"
      [[ -z "$findings_lines" ]] || echo "$findings_lines"
      echo "Fix them, commit, and run this again."
      exit 1
    else
      echo "needs a person: the review still requests changes after 3 rounds"
      [[ -z "$findings_lines" ]] || echo "$findings_lines"
      exit 3
    fi
  fi
fi

if [[ "$review" == human ]]; then
  approved=false
  if [[ "$(get "$task" .metadata.dispatch_review)" == approved && "$(get "$task" .metadata.dispatch_review_patch)" == "$patch" ]]; then
    approved=true
  else
    gate=$(get "$task" .metadata.dispatch_review_gate)
    gate_status=""
    [[ -z "$gate" ]] || gate_status=$(get "$(show "$gate")" .status)
    if [[ -n "$gate" && "$gate_status" == closed && "$(get "$task" .metadata.dispatch_review_gate_patch)" == "$patch" ]]; then
      bd update "$id" --set-metadata dispatch_review=approved --set-metadata "dispatch_review_patch=$patch" >/dev/null
      approved=true
    elif [[ -n "$gate" && "$gate_status" != closed ]]; then
      # A gate is already open for this task: don't stack a second one on top of it.
      person "$id waits for a human review (gate $gate). Stop now: you'll be resumed after the review."
    else
      gate=$(bd gate create --type=human --blocks "$id" --reason "review $id: git diff $base...$branch in $wt_path" --json | jq -r .id)
      bd update "$id" --set-metadata "dispatch_review_gate=$gate" --set-metadata "dispatch_review_gate_patch=$patch" \
        --set-metadata dispatch_state=awaiting-review >/dev/null
      person "$id waits for a human review (gate $gate). Stop now: you'll be resumed after the review."
    fi
  fi
  [[ "$approved" == true ]] || problem "internal error: human review neither approved nor gated $id"
fi

"$dir/merge-queue.sh" acquire "$base" "$id"
trap '"$dir/merge-queue.sh" release "$base" "$id" >/dev/null 2>&1 || true' EXIT

if ! git -C "$wt_path" rebase "$base" >/dev/null 2>&1; then
  conflicts=$(git -C "$wt_path" diff --name-only --diff-filter=U | paste -sd' ' -)
  git -C "$wt_path" rebase --abort >/dev/null 2>&1 || true
  problem "rebasing $branch onto $base conflicts in: $conflicts. Run git rebase $base, resolve the conflicts, then run this again."
fi

for ((i = 0; i < $(jq length <<<"$verifies"); i++)); do
  check_id=$(jq -r ".[$i].id" <<<"$verifies")
  check=$(jq -r ".[$i].verify" <<<"$verifies")
  out=$(cd "$wt_path" && timeout 600 bash -c "$check" 2>&1) \
    || problem "verify for $check_id failed after rebasing onto $base: $(tail -5 <<<"$out")"
done

if [[ "$role" == integration && "$mode" == epic-pr ]]; then
  if ! hook_out=$(wt hook pre-merge -C "$wt_path" 2>&1); then
    if needs_approval "$hook_out"; then
      person "the project's pre-merge checks aren't approved on this machine; a person runs wt config approvals add in $main_root. Record it with bd comments add $id and stop."
    fi
    problem "the project's pre-merge checks failed: $(tail -5 <<<"$hook_out")"
  fi
  git -C "$wt_path" push --force-with-lease -u origin "$branch" >/dev/null 2>&1 \
    || problem "pushing $branch to origin failed: $(git -C "$wt_path" push --force-with-lease -u origin "$branch" 2>&1 | tail -3)"
  if ! url=$(cd "$wt_path" && gh pr view "$branch" --json url --jq .url 2>/dev/null); then
    body="Epic $epic: $(get "$epic_bead" .title)

$(get "$epic_bead" .description)

Tasks:
$(bd list --parent "$epic" --all --limit 0 --json | jq -r --arg id "$id" '.[] | select(.id != $id and .issue_type != "event") | "- \(.id): \(.title)"')"
    url=$(cd "$wt_path" && gh pr create --base "$base" --head "$branch" --title "$(get "$epic_bead" .title)" --body "$body" 2>&1 | tail -1) \
      || problem "opening the pull request failed: $url"
  fi
  number=$(cd "$wt_path" && gh pr view "$branch" --json number --jq .number 2>/dev/null) || number="${url##*/}"
  # Beads doesn't let a gate block an epic, so the gate blocks this task, which close-prs.sh
  # closes, with its epic, once the gate resolves.
  bd gate create --type=gh:pr --blocks "$id" --await-id="$number" --reason "pull request $url merged" >/dev/null
  bd update "$id" --set-metadata "dispatch_pr=$url" --set-metadata dispatch_state=pr-opened >/dev/null
  echo "opened $url for $epic; $id and $epic close once the pull request is merged"
  exit 0
fi

merge_log=$(mktemp)
if ! wt merge "$base" -C "$wt_path" --no-squash --no-rebase --stage none --no-remove --format json </dev/null >/dev/null 2>"$merge_log"; then
  merge_out=$(cat "$merge_log")
  rm -f "$merge_log"
  if needs_approval "$merge_out"; then
    person "the project's pre-merge checks aren't approved on this machine; a person runs wt config approvals add in $main_root. Record it with bd comments add $id and stop."
  fi
  problem "merge into $base failed: $(tail -5 <<<"$merge_out")"
fi
rm -f "$merge_log"

bd close "$id" --reason "merged into $base" >/dev/null
bd update "$id" --set-metadata dispatch_state=merged >/dev/null
echo "merged $id into $base and closed it"

if [[ -n "$epic" && "$(show "$epic" | jq -r .status)" != closed ]]; then
  integration=$(show "$epic" | jq -r '.metadata.dispatch_integration_task // empty')
  open=$(bd list --parent "$epic" --all --limit 0 --json | jq '[.[] | select(.issue_type != "event" and .status != "closed")] | length')
  if [[ "$role" == integration || ( -z "$integration" && "$open" -eq 0 ) ]]; then
    bd close "$epic" --reason "all tasks merged into $base" >/dev/null
    echo "closed epic $epic"
  fi
fi
