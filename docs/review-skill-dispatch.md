## Skill Review: dispatch

### Summary
I read all the code but couldn't run anything, so behaviour that depends on `bd`, `wt` or `gh` is inferred from the code.

The skill is designed well: the supervisor holds no state of its own, the scripts contain all the logic, and it doesn't cost much context. The main problems are in the follow loop (step 4). Three bugs can make the supervisor stop too early or wait forever. Several scripts also take different arguments from what SKILL.md tells the model to pass.

- SKILL.md body: about 550 words
- scripts/: 12 files, about 1,070 lines of bash
- All referenced files exist.

Rating: **Needs Improvement.** Each fix is small, but three of them are critical.

### Description Analysis
**Current:** "Supervise the implementation of beads tasks. Dispatches ready tasks in work order, within the parallel limit, to worker sessions that each implement, merge and close one task in its own worktree; follows them as they end; resumes crashed workers and reports stopped ones. Takes an epic, or all dispatchable work when given none. Use when tasks from sdlc:split-plan or sdlc:split-task are ready to implement, or after a restart to pick up dispatched work."

**Issues:**
- It doesn't mention `sdlc:create-task`, even though that skill's description says its tasks are for dispatch.
- It lacks the words users actually type, like "run the tasks", "start the workers", "resume" or "reboot".
- The "Use when" wording matches your other skills, so I wouldn't switch to "This skill should be used when".

**Suggested:** "Supervise implementation of ready beads tasks: start worker sessions in work order up to the parallel limit (each implements, merges and closes one task in its own worktree), follow them, resume crashed ones and report stopped ones. Takes an epic, or all dispatchable work. Use when tasks from sdlc:split-plan, sdlc:split-task or sdlc:create-task are ready, when the user asks to run, start or resume the work, or after a restart or reboot."

### Content Quality
- **Word count:** about 550. The usual 1,000-word minimum doesn't apply here, because the scripts hold the logic. Don't pad it.
- **Style:** The steps are written as instructions, and "You are the supervisor" is only a one-line role statement.
- **Organization:** The Look → Handle → Dispatch → Follow → Report order is clear. The crash-decision list (resume / not yet / not again / can't) is concrete and prevents endless retries.
- **Issues:** The step-4 event handling has gaps (C2, C3, M2), and the argument instruction on line 18 is wrong (C1).

### Progressive Disclosure
- SKILL.md: about 550 words. There are no `references/` or `examples/` directories, and 12 scripts.
- **Assessment:** This works. Each script's `--help` text is its reference and only loads when needed. SKILL.md runs scripts instead of reading them, and the `!settings.sh` injection can't fail. Nothing needs moving.

### Specific Issues

#### Critical (3)

**C1. The argument instruction breaks most script calls** (`SKILL.md:18`)
- SKILL.md says to pass `--epic` and `--parallel` "in every script call below". Only `dispatch-next.sh` accepts `--parallel`.
- `workers.sh`, `next-tasks.sh` and `watch.sh` stop with exit 2 on `--parallel`. So `/sdlc:dispatch <epic> --parallel 3`, exactly what `argument-hint` suggests, fails in step 1, and the step-4 watch exits immediately.
- `record-task.sh:28` and `resume-task.sh:32` reject `--epic`. `stats.sh:18` takes the epic as a plain positional argument.
- **Fix:** list the flags per script:
  - `--epic` for workers, next-tasks, dispatch-next and watch
  - `--parallel` for dispatch-next only
  - the epic as a positional argument for stats.sh

**C2. The supervisor can stop while a task is still starting** (`run-task.sh:115→194`, `watch.sh:69,86`)
- `run-task.sh` marks the task running before it creates the worktree (`:125`, including any blocking worktrunk post-create hooks). It only starts the worker at `:194`.
- If a watch round lands in that gap, it sees a running task with no process. It prints `crashed <task>`. If no other worker is alive and nothing else is ready, it also prints `idle` and exits, and SKILL.md then reports and stops.
- This can happen at every step of a dependency chain, and especially for the epic-merge integration task, which always starts alone. That task then runs unsupervised, and the tasks waiting on it are never dispatched.
- **Fix:** count a running task as "starting" while its log has no `dispatch_run` line and `dispatch_started` is recent (say under 2 minutes). Put this in one liveness check shared by `watch.sh`, `workers.sh` and `resume-task.sh`. That also fixes M1 and minor issue 2.

**C3. Free worker slots aren't refilled after a stop, failure or unresumed crash** (`SKILL.md:45–47`)
- `dispatch-next.sh` only runs on `ready`, `merged` and `pr-opened` events.
- Suppose every live worker ends without merging while ready tasks are waiting beyond the parallel limit. `watch.sh` already announced those tasks (`:53`), so no new event arrives. With no worker alive and tasks still ready, the watch never reaches `idle`, and the session waits forever.
- With `--parallel 1`, a single stopped worker is enough to cause this.
- **Fix:** after handling `ended … stopped|failed` or `crashed`, run `dispatch-next.sh`. The exception is a cause that would stop any new worker too (usage limit, auth failure, full disk): then stop the watch and report.

#### Major (7)

**M1. Workers on other machines look crashed** (`workers.sh:38,66`, `watch.sh:69`, `resume-task.sh:52`)
- Liveness is a local `pgrep`, and `dispatch_host` is never compared. The merge queue and bd config are explicitly designed for several machines.
- A worker running on another host shows as `crashed`. Step 2 then can't find its worktree or transcript and takes the "Can't" path, offering to reopen a task that is still running.
- `watch.sh` also ignores remote workers when deciding it is idle.
- **Fix:** show tasks with `dispatch_host ≠ uname -n` as `remote`, not crashed.

**M2. Workers that end quickly are never reported** (`watch.sh:76–77`, `SKILL.md:53`)
- `ended` is only printed if the previous round saw the task as `running`.
- A worker started mid-watch that fails within one 10-second interval (usage limit, auth) is first seen already `failed`, so no event is printed. This is exactly the cascade the skill describes.
- Step 5 builds the report from the events it received, so these tasks are left out.
- **Fix:** in watch.sh, print `ended` for a task first seen after round one in a finished state. In step 5, run `workers.sh` again before reporting.

**M3. A failed start leaves the task claimed** (`run-task.sh:118–128`)
- If worktree creation fails after the claim, the script exits 1 and leaves the task `in_progress` and `dispatch_state=running`. It then shows as crashed with no log, and `workers.sh` doesn't show the `$log.wt` error.
- SKILL.md step 3 doesn't say what to do with `not started` lines.
- The "Can't" recovery (`SKILL.md:34`) runs `wt remove <branch>` but keeps an unmerged branch. The next `wt switch --create <id>` probably fails because that branch exists. The result is a loop of prompts asking the user to reopen the task.
- **Fix:**
  - Roll back the claim on any failure after `:118`: set status open and remove the `dispatch_*` metadata.
  - Have step 3 report `not started` reasons.
  - Delete the branch in the reopen command, or have run-task.sh reuse an existing branch.

**M4. The watch never goes idle while a ready task keeps being refused** (`next-tasks.sh` vs `run-task.sh:64–86`)
- "Ready" in next-tasks.sh doesn't mean run-task.sh will start the task. Examples it refuses every time:
  - a misconfigured target branch, which refuses every task
  - an epic-pr integration task with no `origin` remote or no `gh`
  - an integration task whose sibling was added later and has stopped
- dispatch-next prints `not started` each time, but the ready list never empties, so a headless supervisor polls forever.
- **Fix:** apply run-task.sh's preconditions inside next-tasks.sh, so "ready" means "would start".

**M5. A merge queue can stay locked after a crash** (`finish-task.sh:67–68`, `merge-queue.sh:52,63`)
- If a worker dies while holding the queue (SIGKILL, power loss, or a reboot during the up-to-600 s verify step), the EXIT trap doesn't run.
- `release` only works for the same holder. Neither `resume-task.sh` nor SKILL.md releases the queue.
- Every other merge into that branch waits 1800 s and then fails, so those workers stop one after another. The resumed worker may also be blocked if `--claim` refuses a bead that is already claimed.
- **Fix:**
  - In `acquire`, treat "already assigned to this holder" as held.
  - Before resuming or reopening a crashed task, run `merge-queue.sh release <dispatch_base> <task>`.

**M6. Subtasks created by split-task are handled inconsistently** (`workers.sh:40`, `watch.sh:81`, `finish-task.sh:116–117`)
- The epic filter is inconsistent:
  - `--epic` filtering in `workers.sh` and `watch.sh` only matches `.parent == epic`.
  - `next-tasks.sh:41–45` walks up the parents, so it does find subtasks.
  - With `--epic`, a subtask is announced and dispatched, but it is never counted alive and never gets an `ended` or `crashed` event. The watch can go idle while it runs.
- The split task that owns the subtasks is never closed: it has children, so it is never dispatched, and nothing else closes it.
  - In direct mode, the epic never closes.
  - In epic-merge and epic-pr modes, the integration task depends on the split task (`run-task.sh:94`) and never becomes ready.
  - This assumes beads doesn't close parents automatically when their children close.
- **Fix:**
  - Find the epic the same way in every script, by walking up the parents.
  - In `finish-task.sh`, close each parent task whose last child just closed.

**M7. Multiple epics from build don't work** (`build/SKILL.md:37`, `dispatch-next.sh:23`, `watch.sh:35`, `next-tasks.sh:31`)
- Build invokes dispatch "with the epics you created", but the scripts accept a single `--epic` and silently keep the last one.
- **Fix:** have build pass no argument when it created several epics, or accept `--epic` more than once.

#### Minor (9)
1. **stats.sh isn't pre-approved** (`SKILL.md:6,55`): `allowed-tools` doesn't cover `../stats/scripts/stats.sh`, so interactive sessions get a permission prompt. Add `Bash(${CLAUDE_SKILL_DIR}/../stats/scripts/stats.sh *)`.
2. **Inspecting a worker makes it look alive:** the `pgrep` pattern also matches `claude --resume <session> --fork-session`, which `logs.sh:17` and `skills/logs/SKILL.md:13` recommend for opening a worker's conversation. While the user has one open, a crashed worker looks alive, `resume-task.sh` refuses, and it counts toward the parallel limit. The shared liveness check from C2 covers this.
3. **"The log has a result" doesn't prove the worker ended** (`SKILL.md:30`, `resume-task.sh:56`): `record-task.sh:44–46` notes that one process writes a result each time it wakes up. A worker killed after a wake-up gets recorded as `stopped` instead of resumed. Check that the last event after the last `dispatch_run` is a result.
4. **Push error capture pushes twice** (`finish-task.sh:84–85`): it runs `git push` a second time to get the error. If that second push succeeds, the worker gets an empty error message. Capture the output once.
5. **The epic branch is deleted while the PR is open** (`record-task.sh:91–95`): on `pr-opened`, it removes the epic worktree and force-deletes the local epic branch.
6. **settings.sh help is out of date** (`settings.sh:16`): the help for `integration` leaves out `epic-pr`.
7. **Duplicate crash reports** (`watch.sh:16`): the first round prints `crashed` again for tasks step 2 already handled, so they get reported twice. Tell step 4 to skip crashes already decided in step 2.
8. **Double confirmation after build** (`SKILL.md:25`): step 1 asks again after `sdlc:build` already got plan approval that covers dispatching (`build/SKILL.md:21–24`).
9. **The end-to-end test hides these bugs** (`tests/wild/dispatch.sh:3,40–55`): it still treats the supervisor as a single pass and restarts it in a loop. That hides C2, C3 and M4, and it never passes `--epic` or `--parallel`.

**Not verified:** `close-prs.sh:23` closes the task and epic as "pull request merged" whenever the gh:pr gate resolves. If beads also resolves that gate when a PR is closed without merging, a rejected epic gets closed as merged.

### Positive Aspects
- **Nothing lives in the supervisor session:** all state is in beads, worktrees and `.git/sdlc/logs`, so any session can take over.
- **Scripts are documented:** each has `--help` with its exit codes, and SKILL.md runs them without loading them.
- **Workers stay on the finish path:** `setsid` detaches workers, the session id is stored before start, and the hooks force merges and closes through finish-task.sh.
- **Crash decisions are grounded:** `workers.sh` collects the evidence, and step 2 guards against retrying the same failure.
- **Reopening is gated:** it needs AskUserQuestion, and there is an explicit fallback for headless sessions.
- **Logs survive crashes:** parsing skips half-written lines (`fromjson?`), and cost is counted per run using the `dispatch_run` markers.
- **Matches your dispatch rules:** no bypass permissions, one event bead per attempt, `execution_*` metadata, and no sdlc labels.

### Priority Recommendations
1. **Fix `SKILL.md:18` (C1):** state which script accepts which flag.
2. **Close the gaps in the follow loop (C2, C3, M2):**
   - Use one shared liveness check that counts starting tasks as alive, ignores other hosts and ignores `--fork-session`.
   - Run dispatch-next after every `ended` or crash decision.
   - Print `ended` for workers first seen already finished.
   - Rebuild the final report from `workers.sh`.
3. **Make "ready" mean "will start" (M3, M4):** roll back the claim on a failed start, and move run-task's preconditions into next-tasks.sh.
4. **Recover a locked merge queue after a crash (M5).**
5. **Handle subtasks and multiple epics consistently (M6, M7).**

I only had read-only tools, so I couldn't save this as a markdown file. Tell me if you want it written somewhere.
