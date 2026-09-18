# Dispatch: what existing tools already do

Hypothesis, nothing built. Checked on 2026-09-17 against Claude Code 2.1.274, worktrunk 0.77.0 and bd 1.2.2. "Verified" means run on this machine; "documented" means read in the tool's docs only.

Constraint: workers, their subtasks and reviews may run on other harnesses (Codex, OpenCode, Ollama; see docs/harnesses.md). Dispatch decisions can't depend on a Claude Code feature. Claude Code features can only be optional extras, for people debugging or stepping in.

## The job

Start a worker on a task in its own worktree. The worker implements, gets a review, verifies, merges and closes the task. Something notices and starts the next task.

The normal path already uses existing tools from start to end: `bd update --claim`, `wt switch --create`, `claude -p --agent sdlc:worker`, `wt merge`, `bd close`, and the beads `on_close` hook that wakes the supervisor. Most of the other code handles the abnormal paths: a worker that dies, ends without closing its task, or has to be stopped, resumed or inspected.

## Current code, one problem per row

| # | Problem | Our code (lines) | Existing tool |
|---|---|---|---|
| 1 | Pick the next tasks, respect the parallel limit | `tasks.py` `dispatch_order` (242), `supervise.py` `_decide_starts` (614) | `bd ready` sorts by priority; `bd swarm status` groups tasks into completed, active, ready and blocked. Neither puts epics already in progress first, or tasks that unblock others first (beads-worktrunk-overlap.md). **Not covered.** |
| 2 | Claim, create the worktree, undo the claim if that fails | `run-task.sh` (180) | Already `bd update --claim` and `wt switch --create`. The undo is ours. |
| 3 | Keep the worker running after its launcher exits | `start-worker.sh` `setsid -f` (100) | `claude --bg` and its daemon (verified, with the gaps under option B). `wt switch -x` waits until the program exits (verified); worktrunk's own recipe wraps it in `tmux new-session -d` (documented). |
| 4 | Tell whether a worker is running | `tasks.py` `worker_running`: `pgrep -af` regex on `--session-id`/`--resume` | `claude agents --json` lists every live Claude process on the machine, including a detached `claude -p`, with `pid`, the `sessionId` given with `--session-id`, and `status` (busy, idle, waiting). The row disappears when the process exits. Verified; 0.16 s per call. worktrunk markers are set by hooks and stay after a kill (documented). beads has no heartbeat or agent registry (verified). |
| 5 | Restart a crashed worker | `supervise.py` `_decide_crashes`, `resume-task.sh` (79) | The `--bg` daemon restarts a session that exits unexpectedly while the daemon runs; after a reboot the session shows `failed` and restarts on a reply or `claude --resume <id> --bg` (documented, not tested). |
| 6 | Record the attempt: outcome, cost, turns | wrapper in `start-worker.sh`, then `record-task.sh` (157) reading the stream-json `result` line | Nothing writes to beads for us. A `--bg` session can't use `-p` (the changelog says the combination is rejected), so it has no `result` line. |
| 7 | Learn that a task is done | beads `on_close` hook writes to the wake pipe | Already beads. |
| 8 | Learn that a worker ended without closing its task | wrapper writes `ended <id>`; `worker-stop.sh` sends the worker back to finish | In a `--bg` session the `Stop` hook fires at the end of each turn and `Notification` when it goes idle; `claude agents --json` shows `state` done, blocked or failed (verified: done, blocked). |
| 9 | Wake the supervisor without polling | named pipe fed by beads hooks and the wrapper | Cross-session messages reach Claude sessions only; a script can post only to its own session's socket (documented). The background-session docs tell scripts to poll `claude agents --json`. |
| 10 | One supervisor per repository, takeover when one is killed | `flock` and SIGTERM in `supervise.py` | **Not covered.** |
| 11 | One merge at a time per target branch | `merge-queue.sh` (70) | `bd merge-slot` is one slot per repository; `wt merge` has no lock and relies on git refusing a non-fast-forward (documented). **Not covered.** |
| 12 | Review gate | `finish-task.sh` (280) with `bd gate` | Already beads gates. |
| 13 | Stop a worker | `stop-task.sh` (111): TERM, KILL, release the merge queue, mark `stopped` | `claude stop <id>` for `--bg` sessions (verified). Releasing the queue and marking the task stay ours. |
| 14 | Watch or step into a worker | `logs.py` (286), `claude --resume <session> --fork-session` | `claude attach <id>` and `claude logs <id>` for `--bg` sessions (verified). worktrunk's Claude plugin sets 🤖/💬 markers on the branch of any session that loads it (documented; not checked on a worker). |
| 15 | Remove leftovers | `clean.sh` (98) | `claude rm` removes a background session and the worktrees it created itself; worktrees made by someone else are left alone (documented). |

## Option A: keep the current runtime

The current runtime was verified end to end on 2026-09-16: crash resume, review gates, takeover. Rows 3, 4, 5, 13 and 14 are process handling that Claude Code now provides.

Under the constraint, rows 3 to 5 have to stay ours: every harness needs a detached process, a liveness check and a resume. They should also stop depending on Claude:
- Today `worker_running` matches `claude` flags (`--session-id`, `--resume`) in `pgrep` output. Matching the `start-worker` wrapper process, which runs for every harness, would keep the check working for any harness.
- `claude agents --json` lists our detached `claude -p` workers, so a status display can show it for Claude workers, but decisions shouldn't read it.

## Option B: workers as Claude Code background sessions

How it would work:

1. `run-task.sh` claims the task and creates the worktree. From inside the worktree it runs `claude --bg --plugin-dir <root> --agent sdlc:worker --permission-mode auto --name <task-id> [--model] [--effort] "<prompt>"` and stores the printed id on the task.
2. The daemon keeps the session alive and restarts it after a crash. `claude agents --json` gives its state, and `claude stop`, `attach` and `logs` replace our kill and log handling.
3. `finish-task.sh` records the attempt when it closes the task, since no process exit follows the work.
4. `supervise.py` still decides: start the next task, resume or give up, gates, and a blocked worker goes to a person. It reads liveness from `claude agents --json`.

What would go: the `setsid` wrapper and its wake line in `start-worker.sh`, the `pgrep` liveness check, most of `resume-task.sh`, the TERM/KILL part of `stop-task.sh`, and the `--fork-session` advice for inspecting a worker. Rows 1, 2, 7, 10, 11 and 12 stay, and so does the decision code.

### Spike, 2026-09-17

A throwaway plugin (agent `spk:w`, hooks that log their environment), launched 4 times with `claude --bg` from a linked worktree, on Haiku and Sonnet.

| Question | Result |
|---|---|
| Plugin agent through `--plugin-dir` and `--agent plugin:name` | Applied: the session banner showed `@spk:w` on every launch checked (1, 3, 4). Launches 2 to 4 also printed `warning: no agent named 'spk:w' — spawning with default template`, which was wrong on the launches checked. |
| Runs in our worktree | Yes when launched from inside it. No extra worktree was created; the docs say isolation is skipped in a linked worktree. |
| Plugin hooks | `SessionStart`, `Stop` (end of each turn) and `Notification` (idle, about a minute after the turn) fired. |
| `--session-id` | Ignored: `warning: --bg manages the session id; ignoring --session-id`. The printed short id is the first 8 characters of `sessionId`. |
| Per-worker environment variables | **Not passed.** Launches with `DISPATCH_TASK=t2`, `t3` and `t4` all saw `t1`, the value from the shell that started the daemon. `worker-guard.sh`, `worker-stop.sh` and `session-start.sh` depend on `DISPATCH_TASK`. |
| End of the work | `state: done`, `status: idle`, process still alive. The docs say an idle session is retired after about an hour. No process exit to hang a record step on. |
| Permission prompt | Haiku has no auto mode ("auto mode unavailable for this model"), so the first Bash call left the session `blocked` with `waitingFor: permission prompt` until someone attaches. A `-p` worker gets a denial and carries on. |
| Daemon | Transient: `claude daemon status` showed it was started on demand by the first `claude --bg`. Installing it as a service is disabled in this version. |

### Under the harness constraint

Every other harness runs a worker as a process that exits when done (`codex exec`, `opencode run`). A `--bg` worker doesn't exit, ignores per-launch environment variables and a chosen session id, and has no result line, so Claude would become a special case in the supervisor, the hooks and the stats. Its daemon would also restart crashed sessions while the supervisor's own resume keeps running for other harnesses. With two restarters, one session could end up running twice: the docs say `--resume <id> --bg` on a running session starts a copy.

What a `--bg` worker adds that a `-p` worker lacks is a person attaching to a running worker and steering it. That doesn't need `--bg` at dispatch: stop the worker (`/sdlc:stop` marks it `stopped`, so the supervisor leaves it alone), then `claude --resume <session> --bg` and `claude attach <id>`, or plain `claude --resume <session>`.

### Still open

- Background sessions carry built-in rules (documented: commit without asking, push when there's a remote, never merge or push to main/master). It's unknown whether they apply when `--agent` replaces the system prompt. If they do, a worker may refuse to run `finish-task.sh`, which merges into main in `direct` mode.
- Restart after `kill -9` of a session process, and what happens to sessions when the daemon itself dies.
- Where cost and turn totals come from without a `result` line. `record-task.sh`, `logs.py` and `stats.py` read it.
- Whose environment and flags win when `supervise.py` and a person's `claude agents` share one daemon.
- Maturity: 285 changelog lines mention background sessions, the daemon or agent view, many of them fixes for lost, stuck or duplicated sessions.

### What B needs that we don't have

- A way to find the task without an environment variable, for example hooks mapping the worktree's branch to the task through `dispatch_branch`.
- A rule for a `blocked` session: comment on the task and wake a person, or stop it and resume with other permissions.
- A source for cost and turn stats.

## Option C: cross-session messaging for "done"

Documented, Claude Code 2.1.224 and later:
- Sessions on one machine, including `claude -p` and `--bg` sessions, find each other with `ListAgents` and write with `SendMessage`.
- A message is read between tool calls, or starts a new turn when the receiving session is idle.
- A receiver in auto mode accepts messages by default. For an unattended `-p` worker the docs say to pass `crossSessionInbound: accept` through `--settings`.
- `notify_when_idle` sends one notice when another session next goes idle or exits. Only the main conversation can ask for it, only for local sessions, and the request expires after 12 hours.

As the supervisor's "done" signal: the receiver has to be a Claude session. Every worker event then costs a model turn in the dispatch session, and that session has to stay alive for the whole run. That is the background-agent supervisor that failed on 2026-09-16 (plan-supervisor.md: duplicate supervisors, wrong "crashed" and "idle" reports). `supervise.py` can't receive messages.

Where it fits: live coordination between the workers of one epic ("X landed, rebasing is safe"), and a worker telling the person's session that it's blocked. `--name <task-id>` would make sibling workers addressable by task id.

## Option D: worktrunk markers

A marker is stored in git config as `worktrunk.state.<branch>.marker` and shows in `wt list` and its JSON. worktrunk's Claude plugin sets 🤖 when a prompt is submitted, 💬 on `Stop`, `Notification` and permission requests, and clears it on `SessionEnd`. A killed session leaves its marker behind (documented).

It gives people a per-branch view in `wt list` at no cost, but it isn't a liveness signal to base decisions on. `wt config state vars` could hold per-branch data, but the audit trail is agreed to live in beads.

## Option E: beads

- No agent registry, heartbeat or stale-claim check. `bd stale` measures time since the last update.
- `bd mail` hands off to an external mail provider.
- `bd swarm status` computes completed, active, ready and blocked tasks live.
- `bd merge-slot` is one slot per repository.
- Gate types are human, timer, gh:run, gh:pr and bead.

We already use what fits (claim, gates, hooks), the same result as beads-worktrunk-overlap.md.

## Option F: Gas City

Gas City (https://docs.gascity.com, https://github.com/gastownhall/gascity) comes from the beads authors and is a full orchestrator. It has a dispatcher (Mayor), a per-repository watcher that detects stuck workers and recovers them (Witness), a merge queue (Refinery) and one-per-task workers (Polecats). Documented only; not installed or tried. It would replace dispatch as a whole, not one part of it, and it's the closest existing tool to what we built.

## Where this leaves the design

- Not reinvented: task ordering, the per-branch merge queue, the review and finish steps, one supervisor per repository. None of the tools checked does these.
- Overlapping with Claude Code: process handling, meaning detach, liveness, restart, stop and inspect (rows 3 to 5, 13, 14). Other harnesses need it too, so it stays ours and should stop matching `claude` flags.
- Claude Code as an optional extra for people: `claude agents` to see Claude workers, and `claude --resume <session> --bg` with `claude attach` to step into a stopped worker. Workers keep being dispatched as processes that exit.
- Cross-session messaging fits communication between Claude workers, not the supervisor's wake-up.

Next steps, each independent of the others:

1. Make liveness independent of the harness: match the `start-worker` wrapper process instead of `claude` flags in `worker_running`.
2. Document the step-in path for Claude workers in `/sdlc:stop` or `/sdlc:logs`: stop, then `claude --resume <session> --bg` and `claude attach <id>`.
3. Read Gas City's docs far enough to decide whether it could replace dispatch or is only prior art.
