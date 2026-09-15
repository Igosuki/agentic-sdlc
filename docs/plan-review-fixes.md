# Plan: fixes from the plugin validator and skill reviews

Sources: the 12 `docs/review-*.md` files, about 130 findings. References such as `dispatch C2` or `validator #3` point to a finding in `docs/review-<name>.md`.

Triage rule (build-minimal): fix what breaks a real run. Drop hypothetical edge cases and cosmetic changes, and list them at the end with the reason.

## Facts checked before planning

The reviewers could only read files, so they marked several claims as unverified. These are now settled:

| Claim | Result | How it was checked |
|---|---|---|
| beads closes a parent task when its last child closes | **No.** The parent stays open, and `bd ready` lists it as ready. `bd epic close-eligible` closes only epics, and only when all direct children are closed. | Scratch repo with bd 1.2.2 |
| `bd create` can add dependencies in the same call | **Yes:** `--deps <id>` makes the new bead wait for `<id>` (a `blocks` dependency). | Scratch repo |
| A `!` command in SKILL.md can run without being pre-approved | **No.** It must match `allowed-tools` or one of the user's allow rules. Otherwise the skill aborts. A non-zero exit also aborts it. | code.claude.com/docs/en/skills |
| `!` commands with a pipe are checked as one command | **No.** Each part of the pipe must match a rule, so `logs.sh … \| tail -80` also needs `tail` approved. | code.claude.com/docs/en/permissions |
| `Bash(x.sh *)` matches `x.sh` run with no arguments | Yes | permissions docs |
| `effort:` is a valid skill field | Yes | skills docs |
| A skill's `model:` applies when another skill invokes it | Yes | skills docs |
| `claude --resume <id>` must run from the worker's directory | No, it searches every project (Claude Code ≥ 2.1.223) | sessions docs |
| jq fails once the bead JSON passed as an argument exceeds 128 KiB | Yes. `next-tasks.sh:40` and `stats.sh:24` pass it with `--argjson`. This repo is at 28 KiB today. | Code + Linux `MAX_ARG_STRLEN` |
| `watch.sh` treats a worker as crashed while `record-task.sh` is still running (stats Major 2) | **No.** The wrapper `bash -c` keeps the worker's `--session-id` in its command line until recording ends, so `pgrep` still matches it. Double counting still happens for another reason: a resumed session writes one event per attempt, each carrying the session's running total. | Code |
| The `.worktrees/` entry written by `init.sh` is unused | It is used: your worktrunk config sets `worktree-path = {{ repo_path }}/.worktrees/…` | `~/.config/worktrunk/config.toml` |

Still unverified. Each item is assigned to a task below:
- Does a `gh:pr` gate also resolve when a PR is closed without merging? If it does, `close-prs.sh` closes the epic as merged. (T2)
- Does `bd swarm validate` accept a bead that isn't an epic? (T10)

## Decisions for you

1. **Nested tasks.** A task that has children is never dispatched and never closed, so everything waiting on it blocks, and so does the epic's integration.
   - **(a) Recommended:** keep parent tasks. `finish-task.sh` closes a parent once its last child closes. This costs about 15 lines, and `split-task` on a task depends on it.
   - (b) Allow only one level under an epic. `split-task` would then replace a task with sibling tasks and rewire everything that waited on it.
   - Either way: no nested epics.
2. **A task that is being started.** `run-task.sh` claims the task before it creates the worktree, so `watch.sh` can see a "running" task with no worker yet.
   - **(a) Recommended:** a new `dispatch_state=starting`, set at the claim and switched to `running` just before the worker starts. It is visible in status and beads.
   - (b) Keep `running` and treat a task as alive for N minutes after `dispatch_started`.
3. **Shared task rules.** `split-task` and `create-task` currently read "section 2" of split-plan's SKILL.md.
   - **(a) Recommended:** move those rules to `skills/split-plan/references/task-rules.md`, read by all three skills. It is one source of truth, and renumbering sections can no longer break the pointer.
   - (b) `create-task` keeps its own ~80 words of rules for a single task.
4. **`--domain`.** It is required, but nothing reads it: only `docs/beads.md` describes it. Should it become optional, or stay required for choosing agents later?
5. **Workers on another machine** (dispatch M1, status minor 4). They show as crashed because `dispatch_host` is never compared. **Recommended:** defer this until beads is shared between machines. Nothing does that today.

The tasks below assume the recommended options.

## Tasks

Tasks are grouped so that no two tasks edit the same file. That way the ones with no dependencies can run in parallel. Each skill's task also rewrites that skill's description, using the reviewer's suggested wording with its trigger phrases and its "not for…" exclusions.

### T1. Bead data reaches jq through stdin; stats counts correctly
- **Why:** status Critical, stats Critical, stats Major 1 and 2. `/sdlc:status`, `/sdlc:stats` and dispatch step 1 all break once the beads data passes 128 KiB. Stats also credits nested tasks to the wrong epic and counts resumed sessions twice.
- **Change:**
  - `next-tasks.sh` and `stats.sh`: pipe the `bd` output into `jq -n` and read it with `input as $all | input as $ready`. `pipefail` still reports a `bd` failure.
  - `stats.sh`: find each task's epic by walking up its parents. Keep only the latest event per session.
  - `stats/SKILL.md`: add `2>&1 || true` to the `!` line.
- **Files:** `skills/dispatch/scripts/next-tasks.sh`, `skills/stats/scripts/stats.sh`, `skills/stats/SKILL.md`
- **Check:** in a sandbox with more than 128 KiB of beads (for example 200 beads with 1 KB descriptions), both scripts still print results. A resumed task is counted once.

### T2. Finishing closes parent tasks; the merge queue recovers
- **Why:** split-plan Critical, split-task Critical, dispatch M5 and M6, dispatch minor 4.
- **Change:**
  - `finish-task.sh`: after closing the task, walk up its parents and close each parent task (not an epic) whose children are all closed. Then run the existing epic check against the nearest epic.
  - `finish-task.sh`: capture the push error from the first push instead of pushing a second time.
  - `merge-queue.sh acquire`: a queue already held by the same holder counts as acquired, so a resumed worker isn't blocked by its own earlier claim.
  - `close-prs.sh`: settle the `gh:pr` question. If the gate also resolves when a PR is closed without merging, check the PR state before closing the task and epic as merged.
- **Files:** `finish-task.sh`, `merge-queue.sh`, `close-prs.sh`
- **Check:** sandbox epic E with task P split into P.1 and P.2, and task X `--after` P. Run it in direct mode and in epic-merge mode. P closes when P.2 merges, X then starts, and E closes or is integrated.

### T3. Starting, liveness and the watch loop
- **Why:** dispatch C2, M2, M3 and M6 (the epic filter), minor 2, validator #3, logs minor 2, and status minor 5.
- **Change:**
  - `run-task.sh`:
    - Claim the task with `dispatch_state=starting`, and set `running` just before `setsid`.
    - On any failure after the claim, undo it (status open, remove the `dispatch_*` metadata) and print `not started <id>: <reason>`, including the `$log.wt` error.
  - New `worker-alive.sh <session> <state> <started>`: exits 0 when the task's worker is running or still starting. It ignores `claude --resume <session> --fork-session`, the command a user runs to inspect a worker. A task still `starting` after 5 minutes counts as not alive. The script takes its values from the JSON the caller already loaded, so it makes no `bd` call. `watch.sh`, `workers.sh` and `resume-task.sh` use it instead of three copies of `pgrep`.
  - `watch.sh` and `workers.sh`: filter by epic by walking up the parents, as `next-tasks.sh` does.
  - `watch.sh`: print `ended <task> <state>` for a task that is already ended the first time a later round sees it.
  - `resume-task.sh`: run `merge-queue.sh release <dispatch_base> <task>` before resuming.
  - `workers.sh:97`: add `|| true` so that one failed `bd comments` call can't end the listing.
- **Files:** `run-task.sh`, `watch.sh`, `workers.sh`, `resume-task.sh`, new `worker-alive.sh`, and the state table in `docs/beads.md`
- **Check (sandbox):**
  - Make `wt switch` fail: the task goes back to open and the reason is shown.
  - Start a worker whose model is invalid, so it exits within seconds: `ended … failed` is printed.
  - Kill a worker during verify, then resume it: the queue is released and the merge goes through.
  - Watch with `--epic` while a subtask runs: it stays alive until the subtask ends.

### T4. Dispatch skill text (waits for T2 and T3)
- **Why:** dispatch C1, C3, M3 (recovery), M4 and M7, dispatch minors 1, 7 and 8, validator #7, stats Major 3.
- **Change to `dispatch/SKILL.md`:**
  - List the flags per script: `--epic` for workers, next-tasks, dispatch-next and watch; `--parallel` for dispatch-next only; `stats.sh <epic>` takes the epic as a plain argument.
  - Step 1: don't ask for confirmation again when `sdlc:build` invoked the skill after plan approval.
  - "Can't" recovery: release the merge queue, run `wt remove -D <branch>` (so the next `wt switch --create` works), then reopen the task.
  - Step 3: report the reason for each `not started` line. If nothing started and no worker is alive, stop and report instead of watching.
  - Step 4:
    - After `ended … stopped|failed`, or after deciding a crash, run `dispatch-next.sh`. The exception is a cause that would stop any new worker too (usage limit, authentication, full disk): then stop the watch and report.
    - Skip crashes already decided in step 2.
  - Step 5:
    - Run `workers.sh` again before reporting.
    - List tasks waiting on a PR, with "run `/sdlc:dispatch` after the PR merges".
  - `allowed-tools`: add `Bash(${CLAUDE_SKILL_DIR}/../stats/scripts/stats.sh *)`.
- **Files:** `skills/dispatch/SKILL.md`

### T5. settings.sh computes only the key it's asked for
- **Why:** validator #6 and #8, design minors (bash 3.2, extra `bd` calls).
- **Change:**
  - Compute only the requested key: no `bd config get` for `workflow` or `design_dir`, and no `declare -A`, so the planning skills also run with macOS bash 3.2.
  - The help text lists `epic-pr`.
- **Files:** `skills/dispatch/scripts/settings.sh`
- **Check:** `settings.sh workflow` makes no `bd` call, and the SessionStart hook stays fast.

### T6. Read-only views: status and logs
- **Why:**
  - status: Majors 1–3, minor 1 and minor 3.
  - logs: Majors 1 and 2, minors on multi-line entries, running-total cost, the `--raw` help and "from the repository".
- **Change:**
  - `status/SKILL.md`:
    - Add `2>&1 || true` to each of the three `!` lines.
    - `allowed-tools` lists only `workers.sh`, `next-tasks.sh` and `settings.sh`.
    - Show the output in code blocks, then one next step per task: crashed → `/sdlc:dispatch`; stopped or failed → its last comment, `/sdlc:logs <task>`, then clarify the task, `/sdlc:split-task` or fix it by hand.
    - Rename the header to "Dispatch queue".
  - `logs.sh`:
    - Refuse `--follow` when stdout isn't a terminal.
    - New `--last N`: says how many lines were left out and repeats the header of the session the first kept line belongs to.
    - Print `$log.wt` when there is no `.jsonl`.
    - Collapse tool inputs and text to one line.
    - Label cost as a running total, and fix the `--raw` help.
  - `logs/SKILL.md`:
    - The `!` line becomes `logs.sh --last 80 $ARGUMENTS 2>&1`.
    - The resume hint says "from the repository". It needs no other change (see checked facts).
- **Files:** `skills/status/SKILL.md`, `skills/logs/SKILL.md`, `skills/dispatch/scripts/logs.sh`

### T7. setup
- **Why:** setup Majors 1–3, minors on rtk detection, the OS note, usage text and the headless test.
- **Change:**
  - `SKILL.md`:
    - Name `${CLAUDE_SKILL_DIR}/scripts/check.sh` in the re-check step.
    - Commands that need `sudo` or a password: give the command and ask the user to run it with `! <command>`.
    - Companions: give the rtk URL (not reachingforthejack/rtk), and one line on the role of each agent instead of "how to find it".
    - Say first when the OS isn't Linux.
    - Headless means AskUserQuestion isn't available.
  - `check.sh`:
    - Detect rtk with `rtk gain`.
    - The usage text matches the actual output.
- **Files:** `skills/setup/SKILL.md`, `skills/setup/scripts/check.sh`

### T8. init
- **Why:** init Criticals 1 and 2, Majors 3–6, minors 1–4, validator #9.
- **Change:**
  - `SKILL.md`:
    - Headless: pass only the options given in `$ARGUMENTS`.
    - Interactive: ask only about settings that aren't saved. When asking about a saved one, put its value first as the recommended option.
    - "No" to build routing: omit `--workflow` on a first run, and pass `--workflow none` to remove a saved value.
    - Show the raw saved values and the current branch, not the defaults from `settings.sh`.
    - Decide whether to commit from `git status --porcelain -- .gitignore .beads`, and commit with `git commit -m … -- .gitignore`.
    - `allowed-tools` names exactly those commands plus `settings.sh`. `argument-hint` adds `--design-dir`.
  - `init.sh`:
    - Add a newline before appending to a `.gitignore` that doesn't end with one.
    - Find the root through `--git-common-dir`.
    - `set_key` exits 1 when it didn't write the key.
    - Exit 2 with a message on a detached HEAD or in a repo with no commits.
    - If `bd` is missing, say "run /sdlc:setup".
- **Files:** `skills/init/SKILL.md`, `skills/init/scripts/init.sh`
- **Check (sandbox):**
  - A `.gitignore` without a final newline keeps its last entry.
  - Re-running headless on an `epic-pr` repo from a feature branch changes nothing.
  - Running from a `wt` worktree writes to the main checkout.

### T9. split-plan and the shared task rules
- **Why:** split-plan Majors 1–6, minors (bare `bd init`, step 3, shared manifests, cross-skill rules), and the nesting rule from decision 1.
- **Change:**
  - New `references/task-rules.md`, moved out of SKILL.md section 2: sizing, scope, shared interfaces, task format and verify rules. It adds:
    - Graph shape: no nested epics. A large task may be a parent. Never add `--after` between a parent and its own children. Tasks that depend on each other go in the same epic.
    - Verify: runs from the repository root and must finish within 10 minutes. In epic modes it runs again on the finished epic branch, so it must still pass after later tasks land.
    - Scope: shared manifests and lockfiles don't count as overlap.
  - `SKILL.md`:
    - A **Mode** block after the `bd where` line:
      - In plan mode: decompose into the plan file, using labels (T1, T2…) for `--parent` and `--after`, and write nothing to beads.
      - When an approved plan in this conversation already holds a graph: create it without asking again.
      - Otherwise: steps 1–3.
    - The create template uses single quotes, and says to write an apostrophe as `'\''`.
    - Step 1: `bd search` and `bd list --type epic` run directly. Stop if an existing epic already covers the plan, and add `--after` for open tasks the new ones need.
    - Sources not committed on the target branch (uncommitted docs, plan-mode plans): copy their facts into descriptions. Step 3 lists any `--design` document that needs a commit before dispatch.
    - When beads isn't initialized, send the user to `/sdlc:init` instead of running `bd init`.
    - Step 3: use AskUserQuestion, with a headless fallback. Validate again after changes, and show the dependencies from `create-task.sh`'s output.
- **Files:** `skills/split-plan/SKILL.md`, new `skills/split-plan/references/task-rules.md`

### T10. split-task (waits for T9)
- **Why:** split-task Majors 1 and 2 and its minors.
- **Change:**
  - Stopped or failed task: read its last comment, and have the reader summarize the commits in its worktree. After the split, offer the reset: `wt remove -D <branch>`, then `bd update <id> --status open --unset-metadata dispatch_state --unset-metadata dispatch_session`. Ask first with AskUserQuestion; in a headless session, only report it. Add `Bash(wt remove *)` to `allowed-tools`.
  - Put every acceptance check of the parent into some child's acceptance, and report any check that didn't land.
  - Read `task-rules.md` directly, not through the reader.
  - Find "the nearest epic above it, or the bead itself".
  - Check "children that aren't closed".
  - Check sibling scopes with `bd list --parent <p> --json`.
  - Settle the `bd swarm validate` question for a bead that isn't an epic.
- **Files:** `skills/split-task/SKILL.md`

### T11. create-task (waits for T9)
- **Why:** create-task Critical, Majors 1–4, minors 1 and 2.
- **Change:**
  - `create-task.sh`:
    - Pass dependencies to `bd create --deps`, so the bead is never ready without them. Keep the existence check.
    - Walk up to the epic. If its `dispatch_integration_task` isn't open, exit 2 ("epic X is already integrating"). If it is open, run `bd dep add <integration> <new-id>`.
  - `SKILL.md`:
    - Large requests: create nothing, and hand off to `/sdlc:split-plan "<request>"`.
    - Exit 2 means fix the arguments and rerun. Exit 1 after "created <id>" means don't rerun.
    - Compare `--scope` with the `metadata.scope` of open and in-progress tasks, and add `--after` for any overlap.
    - Add a `bd where` check and `[--priority 0-4]`.
    - Point to `task-rules.md`.
- **Files:** `skills/create-task/SKILL.md`, `skills/create-task/scripts/create-task.sh`

### T12. build
- **Why:** build C1, C2, M1–M3, m1 and m2, validator #2 (for build).
- **Contracts with T4 and T9:** dispatch skips its confirmation when build invokes it. split-plan's Mode block handles the second call after approval.
- **Change to `SKILL.md`:**
  - Without plan mode: design writes the document and split-plan creates the tasks during step 1. Skip 1.4, 2.1 and 2.2.
  - Exactly one top-level epic, with no nested epics. Pass that id to dispatch.
  - In plan mode, split-plan splits the design from the plan file and sets `--design <path the document will be written to>`.
  - Inject `git branch --show-current` and compare it with the target in step 1. A branch switch goes into the plan. If the switch can't happen, stop before creating anything. Dispatch only after the commit succeeds.
  - The plan shows the integration mode, target branch and parallel limit, and says that dispatching is approved.
  - The reason for the commit is the design document (tasks live in Dolt).
  - `!` settings line gets `2>&1 || true`. `allowed-tools`: `settings.sh`, `git branch --show-current`, and `git add`/`git commit` for the document.
- **Files:** `skills/build/SKILL.md`

### T13. design
- **Why:** design Critical, Major 1, the reader part of Major 2, minor on the docs contradiction, validator #2 (for design).
- **Change:**
  - `SKILL.md`:
    - `allowed-tools: Bash(${CLAUDE_SKILL_DIR}/../dispatch/scripts/settings.sh *)`. The line-68 call gets `2>/dev/null || true` and prints `(not set)` when the key is empty.
    - Headless: use only the sources the request names or links, and list the others under Open questions.
    - `bd` commands run directly; delegate only the reading of large results.
  - Docs: `docs/configuration.md:20` and `docs/workflow.md:26` follow the skill's order for where to write the document.
- **Files:** `skills/design/SKILL.md`, `docs/configuration.md` (design_dir paragraph only), `docs/workflow.md`

### T14. Trust boundary and worker guard (links to sdlc-714.6)
- **Why:** validator #4 and #5.
- **Change:**
  - `docs/configuration.md` "Worker permissions": anyone who can write to beads can run commands on the machine that dispatches. The reasons: worker prompts come from bead text, workers run in auto mode, and `verify` runs through `bash -c`.
  - `worker-guard.sh`: also deny `git <options> push` and `gh pr merge`. The docs call the guard a guardrail, not a security boundary.
- **Files:** `docs/configuration.md` (Worker permissions section only; T13 owns the design_dir paragraph, so run T14 after T13), `hooks/worker-guard.sh`

### T15. Tests that would have caught these (extends sdlc-714.5; waits for all)
- **Why:** dispatch minor 9, and validator #2's point that `tests/wild/run.sh` hides permission gaps.
- **Change:**
  - `tests/wild/dispatch.sh` runs the supervisor once as a real follow loop with `--epic` and `--parallel 2`, instead of restarting it in a loop.
  - New scenarios: a split task that another task waits on (epic-merge), and more than 128 KiB of beads.
  - Run design, split-plan, status and stats once without `--dangerously-skip-permissions`, so `allowed-tools` gaps show up.
- **Files:** `tests/wild/dispatch.sh`, `tests/wild/run.sh`

## Order

| Task | Waits for |
|---|---|
| T1, T2, T3, T5, T6, T7, T8, T9, T12, T13 | nothing |
| T4 | T2, T3 |
| T10, T11 | T9 |
| T14 | T13 (same file) |
| T15 | all |

Priority when working in sequence, by what breaks runs today:
1. T1 (certain to break as history grows)
2. T2 and T3 (epics never close; the supervisor stops or waits forever)
3. T4
4. T13 and T12 (design and build abort under default permissions; build creates the task graph twice)
5. T9 (quoting runs backticks; duplicate graphs)
6. T8 (overwrites shared settings; corrupts `.gitignore`)
7. The rest

After implementation: one `reviewer` pass per task, then T15 in the sandbox.

## Deferred

- **Workers on another machine** (dispatch M1, status minor 4): wait until beads is shared between machines (decision 5).

## Dropped

| Finding | Reason |
|---|---|
| design minor: `effort: high` unconfirmed | Supported field |
| build m3: nested skill model | `model:` applies when a skill is invoked by another skill |
| logs Major 3: resume hint | `claude --resume` finds sessions from any directory |
| stats minor: `stats.sh ` with a trailing space | `Bash(x *)` matches the bare command |
| stats Major 2, race with `record-task.sh` | The wrapper keeps the worker's args in its command line until recording ends. Double counting is fixed for the resumed-session cause in T1. |
| init minor 5: `.worktrees/` entry | Used by your worktrunk config |
| dispatch minor 3: a result written after a wake-up | Needs a kill in the seconds after a wake-up; recovery is a manual resume |
| dispatch minor 5: epic branch deleted while the PR is open | The branch is on origin; the PR is unaffected |
| validator #10: version in both manifests | No drift yet |
| stats minors: sort order, "worker time" label, stale state note, no-argument size, unknown id | Cosmetic |
| init minor 6: one output line per step | Cosmetic |
| setup minors: `~/.claude/agents` double count, "version unknown", the `missing claude` clause | Cosmetic |
| status minor 2: `model: haiku` | Short, user-run view |
| split-plan: `--domain` unused | Decision 4 |
