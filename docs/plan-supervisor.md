# Plan: the supervisor becomes a script

- Diagrams: `docs/plan-supervisor-overview.md`
- Prior art and measurements: `docs/hypotheses/supervisor-events.md`

## Why the agent doesn't work

- **A background subagent can't wait.** When its turn ends, Claude Code makes it hand back a report. Monitor events wake it again anyway, so each run reports "done" while it still works. That is how one hand-back turned into several reports, and the made-up "please re-invoke me".
- **Monitor has no `persistent` option.** A watch lasts 30 minutes at most (code.claude.com/docs/en/tools.md), and `agents/supervisor.md:47` never says to start it again.
- **Restarting on every report starts duplicates.** `skills/dispatch/SKILL.md:42` starts a new supervisor for each report. Nothing checks whether the previous one still runs. The tester ended up with three supervisors and three `watch.py` processes, and only `bd update --claim` stopped a task from starting twice.
- **The "crashed" reports are wrong.** `tasks.worker_running` returns false for any task that isn't `in_progress`. `finish-task.sh:253-254` closes the task and only then sets `dispatch_state=merged`, in two `bd` calls, while the worker is still running. A watch round between those two calls sees a closed task with no outcome and a "dead" worker, so it prints `crashed`. The next round sees `merged` and prints `ended merged`. `tests/test_watch.py:123-141` expects that crashed-then-ended sequence.
- **The "idle" reports are a race.** The agent ran `dispatch-next.sh` while `watch.py` was in the middle of a round. `watch.py` reads `bd list`, then `bd ready`. If a task gets claimed between those two reads, it is neither ready nor running, so the round counts nothing left to do and prints `idle`.
- **Almost none of the agent's work needs judgment.** Its crash rules come down to three checks: the log has a result, the worktree and transcript exist, it already crashed again after a resume.

## The shape

- **Where it runs.** The session that runs `/sdlc:dispatch` is the supervisor, as it was before commit 5790946. Its loop is `supervise.py`, started as a background Bash command in that session.
- **How it hears about changes.**
  - The beads hooks and the worker wrapper write a line to a named pipe. The script sleeps on that pipe.
  - Polling is the last resort: a sweep 60 s after the last round.
- **When it exits.** Only when the session is needed: for work that is blocked, or new work it isn't allowed to start. That exit is what wakes the session. The session starts the script again, then helps the person.

```
beads hooks ────┐
worker wrapper ─┴─ a line ─> .git/sdlc/wake ─> supervise.py: decides start, resume, record
                                                    │ sleeps until a line, or 60 s
/sdlc:dispatch ── confirm, start in background ───> │
               <── exits: "blocked ..." or "new-work ..."
   starts it again, then suggests /sdlc:review or /sdlc:recover, or asks about the new work
```

- **Why background Bash and not Monitor:**
  - Monitor expires after 30 minutes and wakes the session each time, even when nothing happened.
  - A background Bash command in the main session runs for hours and wakes the session only when it exits.
- **No agent is left.** `agents/supervisor.md` is deleted.

## `scripts/supervise.py`: one brain, several arms

`supervise.py` replaces `watch.py` and `dispatch-next.sh`. It has one function that decides, arms that feed it events, and arms that carry out what it decided.

### Arms that bring events

Each one hands the brain an event: what woke it, and the lines read, if any.
- **The wake pipe `.git/sdlc/wake`.**
  - `supervise.py` creates it if it's missing and opens it read-write and non-blocking before its first round, so it never sees end-of-file. It then waits on it with `select`, with a timeout that ends when the sweep is due.
  - Every line waiting is read in one go. Lines that arrive during a round wake the next one.
  - Tested on Linux: writing takes 4 ms and never blocks, even with no reader, and nothing is left behind for a later reader.
- **The sweep timer:** 60 s after the last round, whatever woke that round.
- **Start:** once, before anything else. It covers a machine restart and events that happened while no supervisor ran.
- **SIGTERM** from a newer supervisor (see takeover).

### The brain: `decide(event)`

The only place that decides.
- **It looks, then decides.** It takes a fresh look at beads and the processes (`bd list --all`, `bd ready`, which worker processes run, and each crashed task's log, worktree and transcript), then returns a list of actions. The decision is a pure function of that look, of what it remembers from earlier events in this run, and of the event. So it's tested without `bd`.
- **The event's lines aren't trusted.** They only say why it looked, and go to the log. A lost or doubled line can't cause a wrong decision.

**What it decides, in order:**
1. **A worker's process is gone and no outcome was recorded:**
   - Its log has a result: record it (`record-task.sh`).
   - Its worktree or transcript is gone: record it failed with that reason.
   - Its log shows 3 resumes since the last result: record it failed, "crashed again after 3 resumes". The count comes from the log's `dispatch_run` lines, so nothing new is stored.
   - Otherwise: resume it.
2. **A task awaiting review whose gate is closed and whose process is gone:** resume it with the review prompt.
3. **A task with an open pull request:**
   - On a sweep event: `bd gate check`. GitHub is called at most once a minute, not on every pipe line.
   - Its gate is closed: close the task and the epic, or stop the task when the PR closed without merging.
4. **Ready tasks in work order** (`tasks.dispatch_order`, within `--under`) while fewer than `--parallel` workers run: start them. A worker runs when its session's process runs, whatever the task's status says.
5. **What to wake the session for.** Only things that happened during this run, so starting it again never repeats them:
   - `blocked <task> <state>: <reason>` for a worker that ended awaiting review, stopped, failed or with a pull request opened, or a ready task that `run-task.sh` refused
   - `new-work <task>...` for tasks outside `--under` that became ready

   If there's any, it prints them after the other actions and exits 0.

**What it remembers, in memory only:**
- the tasks and ready work present at start, which it never reports
- what it already reported
- its last look, for the log

### Arms that act

| Action | Arm |
|---|---|
| start a task | `run-task.sh <task>` |
| resume a crashed task | `resume-task.sh <task>` |
| record a finished worker | `record-task.sh <task>` |
| record a crash as failed | `record-task.sh <task> --failed REASON` (new option: records the attempt with the reason as a comment and as the event bead's description) |
| resume after a review | `resume-reviewed.sh <task>` (now takes one task; its loop moves into the brain) |
| check pull request gates | `bd gate check` |
| close or stop after a pull request | `close-prs.sh <task>` (now takes one task; its loop moves into the brain) |
| wake the session | print the lines and exit |

### Arms that write to the pipe

- **The beads hooks.** `/sdlc:init` installs `.beads/hooks/on_create`, `on_update` and `on_close`.
  - Each one writes `<event> <id>` to the pipe when the pipe exists, and nothing else: no `bd` call, no Python.
  - The hook skips writes made with `SDLC_SUPERVISOR=1`, which `supervise.py` sets for its own `bd` calls. The supervisor's own writes don't wake it.
  - Init doesn't overwrite an `on_*` hook it didn't write. It prints the line to add to it instead.
  - bd runs hooks in the background, for writes from any worktree, so writes by workers, scripts and people all arrive. That was tested with bd 1.2.2.
- **The worker wrapper** in `start-worker.sh` writes `ended <task>` after `record-task.sh`. That covers a crash, where nothing is written to beads. `start-worker.sh` starts the worker and its wrapper without `SDLC_SUPERVISOR`, so their writes wake the supervisor.

### Log

`.git/sdlc/supervise.log` gets one line per round: what woke it and the actions taken. When a sweep round finds a change that no pipe line announced, it logs `missed: <task> <what changed>`. An empty `missed` log in real runs means the sweep can be stretched; a non-empty one points at the missing event.

### One supervisor per repository, and the latest takes over

- **The lock.** `supervise.py` holds `flock` on `.git/sdlc/supervise.lock`, with its pid and arguments in the file.
- **Takeover.** A new supervisor sends SIGTERM to that pid and waits for the lock. The old one finishes its current action, prints `taken over`, and exits.
- **After a crash.** If the first session was killed, its script either died with it and released the lock, or was left running and gets taken over.
- **`supervise.py --running`** prints `supervisor running: pid <n>, <arguments>`, or `no supervisor running`.

### When it exits

| Line | What the session does |
|---|---|
| `blocked <task> awaiting-review: <gate>` | suggests `/sdlc:review <task>` |
| `blocked <task> stopped: <last comment>` or `blocked <task> failed: <last comment>` | suggests `/sdlc:recover <task>` |
| `blocked <task> pr-opened: <url>` | gives the URL for a person to merge |
| `blocked <task> not started: <reason>` | relays the reason |
| `new-work <task>...` | asks with AskUserQuestion whether to dispatch them too |
| `taken over` | says so once, and doesn't start it again |

Nothing else wakes the session. `/sdlc:status` and `/sdlc:stats` show progress and cost on demand.

## Other changes

- **`tasks.worker_running`:** a worker runs when its session's process runs, whatever the task's status or `dispatch_state` says.
  - The wrapper keeps the session id on its command line until `record-task.sh` has finished. So a task that is closed but still being recorded counts as running. That fixes the false `crashed` and keeps its slot counted.
  - `workers.py --alive-count` counts every claimed task with a running process.
- **Removed:** `scripts/watch.py`, `scripts/dispatch-next.sh`, `agents/supervisor.md`.
- **Unchanged:** `run-task.sh`, `resume-task.sh`, `workers.py`, `next-tasks.py`, `stats.py`.

## `skills/dispatch/SKILL.md`

- **Top of the skill:** add `!supervise.py --running` next to the workers and dispatch queue.
- **Steps 1 and 2 (check what's named, confirm):** unchanged. The confirmation also says when this replaces a running supervisor.
- **Step 3:** run `${CLAUDE_PLUGIN_ROOT}/scripts/supervise.py`, adding the `--under` and `--parallel` options, with Bash `run_in_background: true`. `allowed-tools` drops `Agent` and allows `supervise.py`.
- **Step 4:** when it exits, first start it again with the same arguments. Then act on each line as the table says. If the person agrees to dispatch `new-work` tasks, start it once more with those ids added to `--under`. The newer run takes over, and the `taken over` exit that follows needs no reply.
- **Removed:** the `Can't` case, the reset-task question and the already-reported list.

The skill keeps `model: sonnet`.

## Tests

- **`tests/test_supervise.py`, the brain,** from hand-built looks with no `bd`:
  - a closed task whose process runs is neither crashed nor ended
  - a crash whose log has a result is recorded
  - a crash is resumed; after 3 resumes with no result it's recorded failed
  - a missing worktree or transcript records failed
  - ready tasks start in work order, up to `--parallel`
  - an ended or ready task present at start doesn't wake; one that changes during the run does, once
  - `new-work` only for tasks outside `--under`
  - a closed review gate resumes the task
  - `bd gate check` only on sweep events, and only with an open pull request gate
- **The arms, with real processes and `bd`:**
  - a pipe write with no reader returns at once
  - a write wakes the loop, and several writes make one round
  - the sweep fires with no writes
  - init installs the hooks, a `bd update` writes a line, and one with `SDLC_SUPERVISOR=1` doesn't
  - a second supervisor takes over
- **`tests/test_tasks.py`:** `worker_running` is true for a closed task whose process runs.
- **`tests/test_close_prs.py` and the review tests:** follow the one-task arguments.
- **`tests/wild/dispatch.sh`:** runs `supervise.py --under <epic> --parallel 2` in the foreground, starts it again after each `blocked` exit, and stops once the epic is closed.

## Docs

The README (line 30) and these docs describe the agent or the polling. They get updated:
- `docs/workflow.md`: the Dispatch section
- `docs/harnesses.md`: the rows for watch.py and supervisor events
- `docs/development.md`: the layout, and "the supervisor runs on Sonnet"
- `docs/beads.md`: the hooks init installs, and line 95
- `docs/roadmap.md:52`, which the process-based check now covers
- `skills/init`: its step list gains the hooks

The working tree already has uncommitted edits in README and docs. The implementers build on them.

## Not covered

- **macOS.** Opening a pipe read-write is documented on Linux and undefined in POSIX. Check it on macOS before relying on it there.
- **Orphaned scripts.** The docs don't say whether a background Bash command dies with its session. Takeover covers either case.
- **A beads feed.** A later bd with `bd activity --follow` (Gas Town uses it) could replace the hooks as the beads arm. Only that arm would change.
