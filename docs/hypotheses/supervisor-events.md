# Supervisor events: prior art

Research date: 2026-09-16. Question: how do other supervisors learn that work is ready or a worker ended, without polling their task store all the time? And how short is their fallback?

Context: `docs/plan-supervisor.md`. The signals sdlc has are beads `on_create`/`on_update`/`on_close` hooks, and the wrapper process `start-worker.sh` runs around each worker.

Numbers marked ✓ were checked in upstream source for this document. The others come from docs, or from a research agent's reading, and are marked as such.

## What was measured here

- **Beads hooks (bd 1.2.2, tested in a scratch repo):**
  - `.beads/hooks/on_create`, `on_update` and `on_close` run after every create, update and close. That includes claims, metadata, dependencies, and gate create and resolve. `bd comments add` doesn't trigger them.
  - Arguments are `<id> <event>`. The issue's JSON after the change comes on stdin, along with the caller's environment.
  - They run in the background: `bd update` took 0.15 s while its hook slept 3 s.
  - A write from a git worktree runs the main repository's hooks.
- **What a round costs in this repository (86 beads):** `bd list --all` 0.4 s, `bd ready` 0.25 s, `pgrep` 0.04 s. Any `bd` call costs at least ≈0.4 s, because the embedded Dolt database opens each time.
- **No cheaper way to ask beads for changes:**
  - `bd sql` refuses: "not yet supported in embedded mode".
  - `bd activity` and `bd events` don't exist in 1.2.2.

## Infrastructure

| System | Fast signal | Fallback | Worker liveness | Restart cap | One instance |
|---|---|---|---|---|---|
| Kubernetes controllers | watch stream into a queue that drops duplicate keys | full resync, 10 h default in controller-runtime (docs) | n/a | per-key exponential backoff, 5 ms to 1000 s (source, agent) | leader election |
| kubelet PLEG | polling only; Evented PLEG adds container runtime events | polling: relist every 1 s ✓ (`pkg/kubelet/kubelet.go:216`). Evented: relist every 300 s, threshold 10 min ✓ (v1.30.0 `kubelet.go:184-185`) | runtime state | n/a | n/a |
| s6 / runit | the supervisor is the parent; runs `./finish` on exit; s6 broadcasts state on a FIFO directory | none needed | real exit | none built in: `finish` decides (docs) | one supervise per service directory |
| systemd | SIGCHLD, pidfd for processes that aren't its children | none needed | real exit | `StartLimitBurst=5` in `StartLimitIntervalSec=10s` (docs) | n/a |
| supervisord | SIGCHLD; publishes `PROCESS_STATE_*` events to listeners | none needed | real exit | `startretries=3`, backoff +1 s per try (docs) | pid file |
| Erlang/OTP | monitor or link sends `DOWN`/`EXIT` | none needed | real exit | `intensity 1` per `period 5 s` (docs) | registered name |
| Oban | Postgres LISTEN/NOTIFY | stager every 1 s ✓ (`lib/oban/stager.ex:16`) | Lifeline rescues after 1 h ✓ (`lib/oban/lifeline.ex:38`) | the job's own retry policy | advisory locks |
| River | LISTEN/NOTIFY | fetch poll 1 s, cooldown 100 ms ✓ (`client.go:46-49`) | leader lease, elects every 5 s ✓ (`internal/leadership/elector.go:28`) | job retries | lease row plus advisory lock |
| graphile-worker | LISTEN/NOTIFY | `pollInterval` 2 s ✓ (`src/config.ts:56`); the docs call it a safety net | not checked | job retries | not checked |
| GoodJob | LISTEN/NOTIFY | poll 10 s ✓ (`lib/good_job/configuration.rb:19`) | advisory lock released when its connection drops (agent) | job retries | advisory locks |
| Solid Queue | none, polling only | workers 0.1 to 1 s, dispatcher 1 s (README, agent) | heartbeat 60 s, dead after 5 min (README, agent) | job retries | `SKIP LOCKED` |
| Temporal | long poll for tasks | n/a | activity heartbeat timeout (docs) | retry policy | server side |

## Agent orchestrators

**Gas Town** (on beads; source read at `gastownhall/gastown`):
- **Fast signal:** subscribes to the beads feed, `bd activity --follow` (`internal/daemon/daemon.go:50,512`). A convoy manager also reads the beads events table every 5 s, with backoff up to 60 s and 1 s of overlap, because Dolt timestamps have second precision ✓ (`internal/daemon/convoy_manager.go:21-28`).
- **Fallback:**
  - a scan every 30 s ✓ (`convoy_manager.go:21`)
  - a recovery heartbeat every 3 min ✓ (`internal/config/operational.go:48`), which the code calls "recovery-focused: normal wake is handled by feed subscription"
- **Liveness:** tmux session and Claude process presence are the "source of truth" (agent, `internal/witness/manager.go:33-53`). A session hung for 30 min is treated as dead.
- **Restart cap:** 3 respawns per bead ✓ (`operational.go:112`). The counter is kept on disk under a flock.
- **One instance:** non-blocking flock on `daemon/daemon.lock` before the pid file is written ✓ (`daemon.go:461-466`).

**Gas City** (successor, on beads; source read at `gastownhall/gascity`):
- **It removed its beads hooks.** The previous `on_create`/`on_update`/`on_close` hooks "spawned a gc subprocess per bead write". Its own store wrapper now emits the same events in process ✓ (`cmd/gc/hooks.go:10-14,50-60`). That works because Gas City makes every beads write itself.
- **Delivery:** events are appended to `.gc/events.jsonl` under a flock. Readers check the file every 250 ms, with no inotify ✓ (`internal/events/recorder.go:686`). Events are best effort: recording never fails the caller.
- **Fallback:**
  - reconcile against `bd` every 30 s ✓ (`internal/beads/caching_store.go:171`)
  - health patrol every 30 s ✓ (`internal/config/config.go:2528`)
  - nudge poller every 2 s (agent)
- **One instance:** a blocking flock ✓ (`internal/supervisor/registry.go:341-358`).

**Others** (agent reading, lower confidence):
- **claude-squad:** hashes tmux pane content and matches dialog text, every 500 ms.
- **vibe-kanban:** the child process exit code.
- **Composio agent-orchestrator:** checks the runtime is alive, parses the prompt, and tails the session JSONL, every 30 s (secondary source).
- **agentapi:** classifies terminal output as stable or running.

**Claude Code hooks** (code.claude.com/docs/en/hooks):
- `Stop`, `StopFailure`, `SessionEnd`, `TeammateIdle` and `TaskCompleted` exist.
- The docs don't say whether they fire under `claude -p`, and say nothing about a killed process.
- None of the orchestrators above use them as the signal that a worker died.

## What recurs

1. **Events are never trusted alone.** Every system pairs its fast signal with a sweep. Kubernetes' resync exists "to insure against a bug in the controller"; graphile-worker calls its poll a safety net; Gas City records events best effort.
2. **The sweep is short when a missed event delays work a user is waiting for:** 1 to 2 s in job queues, 30 s in both beads orchestrators. It's long only where the event stream is reliable and a miss means a bug: 300 s for Evented PLEG, 10 h for controller resync.
3. **Liveness comes from the process or runtime, not from the agent reporting on itself.** Supervisors that are the parent get the exit directly. Those that aren't use heartbeats or process checks.
4. **Restart caps are small:** 3 in Gas Town and supervisord, 5 in 10 s in systemd, 1 in 5 s in OTP. Gas Town keeps its counter on disk.
5. **One instance means a flock.** Gas Town and Gas City both refuse a second daemon; neither takes over from the one already running.
6. **Local delivery is a file:** Gas City's JSONL checked every 250 ms, s6's FIFO directory. No broker.

## What this suggests for sdlc

| Signal | Interval | Cost per check | Covers |
|---|---|---|---|
| wake file (beads hooks, worker wrapper) | check its size every 250 ms to 1 s | a `stat` | beads writes from anyone; a worker's process ending, including a crash the wrapper outlives |
| worker liveness | every 5 s | one `pgrep`, 0.04 s, no `bd` | wrapper and worker both killed |
| full round | every 30 s | ≈1 s of `bd` calls | missed hooks, PR merges through `bd gate check`, anything else |

- **The 30 s round follows both beads orchestrators,** and costs ≈1 s every 30 s here. The 5-minute figure was too long, as you said.
- **Keep the hook tiny.** It appends one line, with no `bd` call and no Python, so a hook per write stays cheap. That cost is what made Gas City drop its hooks; it could drop them only because it makes every write itself. sdlc's workers and people write through `bd` directly, so hooks remain the only way to see their writes without polling.
- **If a later bd has `bd activity --follow`** (Gas Town uses it; 1.2.2 doesn't), one subscription could replace the hooks.
- **Restart cap:** prior art says 3. Here that means resuming up to 3 times while the log shows runs with no result. It needs no new state.
- **Takeover goes beyond prior art.** Both orchestrators refuse a second instance. Taking over only matters when the old script outlived its session, since a script that dies releases its flock by itself.
