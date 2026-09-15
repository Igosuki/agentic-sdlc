I couldn't write a file or run anything here (only read/search tools were available), so the review is below. The bd JSON field names are taken from `docs/beads.md` and `logs.sh`.

## Skill Review: stats

### Summary
The SKILL.md itself is fine: 6 lines of frontmatter, about 15 words of body, and the output comes straight from `stats.sh` into the prompt. Every real problem is in `stats.sh` (48 lines) and in how `dispatch` calls it. The script will stop working once the bead history grows, and it can give wrong totals.

### Description Analysis
**Current:** "Show the cost, duration, models and agents of dispatched work, per task and per epic, from the attempts recorded in beads. Read-only."

**Issues:** None that matter. The usual advice about trigger phrases and "This skill should be used when…" only applies to skills the model can load on its own. This one has `disable-model-invocation: true`, so the description is just the line shown in the `/` menu. It's clear, 139 characters, and matches `status` and `logs`.

**Recommendations:** Leave it as is.

### Content Quality
- **Word count:** about 15 words. The usual 1,000–3,000 word target doesn't apply here: `docs/development.md` says scripts explain themselves and skills don't describe them.
- **Writing style:** instructions are direct commands ("Show the report above… Don't run anything else.").
- **Organization:** the same shape as `status` and `logs`.

**Issues:** only the `!` line (see Minor 6).

### Progressive Disclosure
**Current structure:**
- SKILL.md: about 15 words
- references/: 0 files
- examples/: 0 files
- scripts/: 1 file (`stats.sh`)

**Assessment:** This is the right shape. The script's source never enters the context. No changes needed.

### Specific Issues

#### Critical (1)
- **`stats.sh:21-24`: the whole bead database is passed to `jq` as a command-line argument, which breaks once it passes 128 KiB.**
  - **Cause:** on Linux, a single argument can be at most 128 KiB. `$all` holds the full JSON of every bead: descriptions, acceptance criteria, metadata, and every event's final worker message.
  - **When it breaks:** after roughly 100 beads, `jq` fails with "Argument list too long" and the script exits 126.
  - **What breaks:** both `/sdlc:stats` and the cost line in dispatch's report. Growing history is the feature's whole point, so this is certain to happen.
  - **Same bug elsewhere:** `next-tasks.sh:40` does the same thing, so dispatch itself will break too.
  - **Fix:** pipe the data in on stdin instead. `printf` is a shell builtin, so no argument limit applies, and `set -e` still catches `bd` failures:
    ```bash
    printf '%s\n%s\n' "$all" "$events" | jq -rn --arg only "$only" '
      def money: ...; def dur: ...;
      input as $all | input as $events
      | ($all | map({key: .id, value: .}) | from_entries) as $by
      | ...'
    ```
    Don't use `--slurpfile <(bd …)` instead: it hides `bd` failures and prints "no recorded attempts".

#### Major (3)
- **`stats.sh:34`: tasks nested under a large task are credited to the wrong epic.**
  - **Cause:** `epic` is set to the task's direct parent. But `split-plan/SKILL.md:62` and `split-task` create children under a *task*, and `run-task.sh:50-55` walks up the parents to find the real epic.
  - **Effect:** `/sdlc:stats <epic>` leaves those tasks out. The full report lists the large task as if it were an epic, with the task's status.
  - **Fix:** walk up the parents the same way:
    ```jq
    def epic_of($id): ($by[$id].parent // null) as $p
      | if $p == null then null elif $by[$p].issue_type == "epic" then $p else epic_of($p) end;
    ```
  - `workers.sh:40` and `watch.sh:81` have the same direct-parent filter.
- **`stats.sh:28-32`: one worker session can be counted twice.**
  - **Cause:** events are grouped by task only. Each event already holds the session's total cost and duration across all its runs (`record-task.sh:47-55`), but nothing stops two events for the same session:
    1. `record-task.sh` never checks whether the session was already recorded.
    2. `watch.sh:69-74` reports `crashed` as soon as the worker process is gone. That happens while the wrapper is still running `record-task.sh` (bd calls, `wt remove`).
    3. `dispatch/SKILL.md:30` then tells the supervisor to run `record-task.sh` itself.
  - **Effect:** cost, duration and attempts all doubled for that task.
  - **Fix in stats:** add `session: $p.session, id: .id` to each event, then keep only the latest event per session with `group_by(.session // .id) | map(sort_by(.created) | last)` before grouping by task. The deeper fix is making `record-task.sh` skip a session it already recorded.
- **`dispatch/SKILL.md:18,55` and `:6`: dispatch calls `stats.sh` in a way that fails.**
  - **Wrong flag:** line 18 says to pass `--epic <id>` to "every script call below", and line 55 is below it. But `stats.sh:18` rejects any argument starting with `-` and exits 2.
  - **Not pre-approved:** dispatch's `allowed-tools` only covers `${CLAUDE_SKILL_DIR}/scripts/*`, so `../stats/scripts/stats.sh` isn't allowed. That means a permission prompt, or a denial in a headless run.
  - **Fix:** make `stats.sh` accept `--epic EPIC` like the other four dispatch scripts (keeping the bare id for the slash command). Then add `Bash(${CLAUDE_SKILL_DIR}/../stats/scripts/stats.sh *)` to dispatch's `allowed-tools`.

#### Minor (6)
- **`SKILL.md:13`: the no-argument report has no size limit, and the model has to retype all of it.** With no epic, every task ever dispatched is listed. Dispatch's report loads the same full history, which doesn't isolate the current run's cost. Suggestion: with no epic, print only per-epic lines and the total; show task lines only when an epic is given.
- **`stats.sh:39-40`: a mistyped id or a task id prints "no recorded attempts".** The project convention is to report invalid input and exit 2. Suggestion: exit 2 when `$by[$only]` doesn't exist, and match tasks where `$only` is the task itself or any of its parents. That makes task ids work too, with the same walk as the nested-epic fix.
- **`stats.sh:35`: numbers and states can be stale or incomplete, and the report doesn't say so.** `state` is the last *recorded* state: a task that stopped, was re-dispatched and is now running still shows `stopped`. Crashed and running sessions aren't counted. The usage text says this, but the report doesn't. Suggestion: add a line such as "N tasks running or crashed, not counted", using `metadata.dispatch_state == "running"` from `$all`.
- **`stats.sh:26`: the duration total reads like elapsed time.** It is the sum of all worker times, which is more than wall-clock time when workers run in parallel, and it shows as `412m05s`. Suggestion: label it "worker time" and show hours past 60 minutes.
- **`stats.sh:32`: tasks sort alphabetically by id**, so `x.10` comes before `x.2`. Suggestion: sort by first attempt time.
- **`SKILL.md:6,11`: errors may not reach the user, and the no-argument call may not be pre-approved (not tested).**
  - **Errors:** `logs` adds `2>&1` to its `!` line; this skill doesn't. The usage text and `bd` errors go to stderr, so a bad argument or a missing beads database may never be shown.
  - **Permissions:** `$ARGUMENTS` is usually empty, which makes the command `stats.sh ` (trailing space). Check once that `Bash(…/stats.sh *)` matches it, or use `scripts/*` as `status` does.

### Positive Aspects
- The skill is a thin wrapper: output is loaded with `!`, the script is pre-approved, the model can't invoke it by itself, and no script source enters the context.
- `stats.sh` follows the script conventions: `--help`, usage and exit 2 on bad arguments, `set -euo pipefail`.
- It copes with bad data: `try fromjson catch {}` and `// 0` mean one broken event doesn't sink the report.
- Money is rounded in cents before formatting, so no float artifacts appear.

### Overall Rating
**Needs Improvement.** The SKILL.md wrapper passes. The script has one bug that will certainly break it and two that give wrong totals.

### Priority Recommendations
1. Pipe the bead data into `jq` on stdin instead of passing it as an argument, in `stats.sh` and `next-tasks.sh`.
2. Find each task's epic by walking up its parents.
3. Count each worker session once.
4. Make dispatch's call work: accept `--epic` in `stats.sh`, and pre-approve the script in dispatch's `allowed-tools`.
