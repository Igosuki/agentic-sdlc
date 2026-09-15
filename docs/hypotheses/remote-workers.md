# Remote workers

Status: hypothesis. Nothing here is built. This records what it would take to run dispatched workers on other machines, so the number of workers isn't bounded by one computer.

## Summary

- Workers share three things with the supervisor through the local disk: the code (worktrees of one repository), the task state (the embedded beads database) and the worker process itself (found with `pgrep`, with a local log and transcript). Each has to move to something reachable over the network: a git remote, a shared Dolt server, and a **runner**, the command that starts one worker somewhere else and returns.
- Suggested first shape: the same `claude -p` worker in containers you control, or in GitHub Actions; beads on a shared `dolt sql-server`; GitHub as the remote; merges done by pushing to it. The worker contract, hooks and skills stay as they are.
- Claude Code on the web is a poor runner today. Its sandbox sends all traffic through an HTTP/HTTPS proxy, so workers can't reach a Dolt server, and a script has no documented way to learn that a cloud session ended.
- Scaling stops well before compute runs out: model rate limits and cost, the number of ready tasks, one verification at a time per merge target, the supervisor's turns, and human review. See section 5.

## 1. What ties a worker to the supervisor's machine

| Concern | Today | Where | On another machine |
|---|---|---|---|
| Start | `setsid -f` runs `claude -p` in a local `wt` worktree | `run-task.sh` | a runner starts it elsewhere |
| Code | `wt switch --create <branch> --base <base>` from the local base | `run-task.sh` | clone from the remote; the base must be pushed first |
| Task state | embedded Dolt in `.beads/embeddeddolt/`: one writer at a time (file lock), gitignored, no remotes | `.beads/metadata.json` | a shared server |
| Liveness | `pgrep -f -- "--(session-id\|resume) $session"` | `watch.sh`, `workers.sh`, `resume-reviewed.sh` | a local wrapper process, or a heartbeat |
| Log and cost | stream-json appended to `.git/sdlc/logs/<task>-<session>.jsonl` | read by `record-task.sh`, `logs.sh`, `workers.sh`, stats | streamed back or uploaded |
| Resume | `claude -p --resume` needs the worktree and the transcript in `~/.claude/projects` | `resume-task.sh` | both must outlive the worker's machine |
| Merge | merge queue (a claimed bead), then `wt merge` fast-forwards the local base; only `epic-pr` pushes | `finish-task.sh`, `merge-queue.sh` | push to the remote |
| Pre-merge checks | a person runs `wt config approvals add` once per machine | `finish-task.sh` | approvals baked into the worker image |
| Hooks | `session-start.sh`, `worker-guard.sh` and `worker-stop.sh` call `bd` | `hooks/` | `bd` and database access on the worker |

## 2. Code: the git remote

- Base and epic branches live on `origin`. `run-task.sh` checks that the base is pushed before dispatching; `epic-merge` pushes the epic branch when it creates it.
- The worker's machine clones at the base (a partial clone, or a mirror cached on the host) and creates the task branch. The clone replaces the worktree; `wt` is still used for the pre-merge hooks.
- **Merge by pushing.** `finish-task.sh` keeps rebase then verify, and replaces `wt merge` with `git push origin HEAD:<base>`. The remote refuses a push that isn't a fast-forward, so a worker that verified against an old base can't land: it rebases, verifies again and retries. The merge queue stays useful: it stops several workers verifying at once against a base about to move. On a shared Dolt server its claim is atomic across machines.
- `worker-guard.sh` denies `git push` in the worker's own commands. `finish-task.sh` pushes inside its script, so the guard doesn't change.
- **Work in progress.** When a disposable machine dies, uncommitted work dies with it. Either resume from the last pushed commit, or push the task branch after each commit (a `PostToolUse` hook on `git commit`). The second means the guard allows pushing to the task's own branch.

## 3. Task state: a shared beads server

| | Shared `dolt sql-server` | Dolt remotes or federation (push and pull) |
|---|---|---|
| A new machine | connects; nothing to copy | `bd bootstrap` clones the database from the remote |
| `bd update --claim`, merge queue | atomic: one server orders the writes | each copy claims locally; two workers can claim the same task, and the conflict only shows at sync, which stops until a person resolves it |
| Staleness | none | up to one sync interval (the beads docs suggest about 60 s) |
| Needs | a TCP port reachable from workers, TLS, credentials (`BEADS_DOLT_SERVER_HOST`, `BEADS_DOLT_SERVER_PORT`, `BEADS_DOLT_SERVER_USER`, `BEADS_DOLT_PASSWORD`, `BEADS_DOLT_SERVER_TLS`) | a remote: DoltHub, S3, GCS, or a git remote (`refs/dolt/data`) |

Use the shared server. The roadmap's *Several machines* section plans Dolt remotes or federation, with heartbeats and a grace period longer than the sync interval. That was written for push and pull; with a shared server, claims are atomic and heartbeats only need to cover a worker that dies without a trace.

- Setup: `bd init --server` or `--external` (a server managed outside `bd`). Moving this project's existing embedded database to a server wasn't researched.
- The beads docs recommend pinning Dolt to 2.2.0: on 2.3.x, `DOLT_RESET` fails on about 3–5% of new databases.
- The docs mention `bd sync`; the installed `bd` 1.2.2 has no such command.
- Where: a small always-on machine that workers reach over a private network (Tailscale, WireGuard) or TLS.

## 4. Where workers run

| | A. Your containers or VMs | B. GitHub Actions | C. Claude Code on the web | D. Managed Agents API |
|---|---|---|---|---|
| Worker unchanged (plugin, hooks, `bd`) | yes | yes | plugins install from `.claude/settings.json` | no: rebuilt as an agent definition |
| Reaches a Dolt server | yes | yes | no: HTTP/HTTPS proxy | not confirmed |
| Supervisor learns it ended | local wrapper process | `gh run`, a `gh:run` gate | not documented | event stream |
| Log, cost, transcript | piped back or copied | run artifacts | not documented | event stream, cost per session |
| Scale limit | your cluster | job time limit and concurrent jobs per plan | shared subscription rate limits | API rate limits |
| Billing | your machines + model usage | Actions minutes + model usage | subscription | API |

### A. Your containers or VMs (ssh, docker, Kubernetes)

- Same `claude -p` command, with the plugin in the image and `--plugin-dir`.
- Keep the remote command attached: `run-task.sh` detaches a local `ssh host …` or `docker run …` whose stdout is the worker's stream-json. The local wrapper lives as long as the worker, so `pgrep` finds it, the log lands in `.git/sdlc/logs`, and `record-task.sh`, `logs.sh` and stats keep working. A detached Kubernetes Job needs heartbeats instead.
- Resume: copy the transcript back when the worker ends and into the new machine when resuming. Its path under `~/.claude/projects` is derived from the working directory, so every worker runs in the same fixed path, for example `/work/<task>`.
- Auth: `ANTHROPIC_API_KEY`, or `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` (Pro, Max, Team or Enterprise; the token makes model requests only).
- The image carries `claude`, `bd`, `git`, `gh`, `jq`, `wt`, the project's toolchain, the `wt` approvals, and credentials for GitHub and the Dolt server.

### B. GitHub Actions

- `run-task.sh` triggers a `workflow_dispatch` with the task id. The runner has open network access and checks out the repository with the plugin.
- `watch.sh` already runs `bd gate check` every round, and beads has a `gh:run` gate that resolves when a run finishes.
- The log and transcript are uploaded as run artifacts; `record-task.sh` and `resume-task.sh` fetch them with `gh run download`.
- Limits: 6 hours per job on GitHub-hosted runners, and a concurrent job cap per plan. Self-hosted runners lift both.
- Least infrastructure. Every worker starts cold: checkout and tool install.

### C. Claude Code on the web (`claude --cloud "<prompt>"`)

- Works: setup scripts run as root on Ubuntu 24.04 and can install `bd`. Plugins declared in `.claude/settings.json` install at session start. Pushes to branches not prefixed `claude/` are accepted when the branch isn't protected, has no open pull request from someone else, and carries only your commits.
- Blocks: all outbound traffic goes through an HTTP/HTTPS proxy, so a MySQL-protocol connection to Dolt won't work. The docs don't say non-HTTP traffic is refused outright; test before ruling it out. Only push-and-pull remotes over HTTPS would remain, with the claim races of section 3.
- Blocks: `claude -p "<message>" --cloud <session-id>` posts a message and exits. No documented status, end signal or cost for a script to read.
- Workers would have to leave beads alone, with the supervisor as the only writer. That is the shape rejected for the local design.
- Sessions start from the default branch unless the prompt says otherwise, and share the account's rate limits. No separate concurrency cap is documented.

### D. Managed Agents

- The best control from a script: sessions created by API, a stored event stream, cost and a budget per session.
- Doesn't load Claude Code plugins or hooks, so the worker contract becomes a system prompt, skills and tools. Network access, installing tools and git credentials weren't confirmed in the docs read. Worth revisiting if A or B hit their limits.

Routines don't fit: they clone the default branch and have a daily run cap.

## 5. Where scaling stops

1. **Model limits and cost.** On a subscription, every worker draws from one account's rate limits, cloud sessions included. With an API key, limits follow the organization's tier. Cost grows with the number of workers. This is the first limit you hit.
2. **Ready tasks.** Parallel workers can't outnumber tasks without open blockers. The task graph from `split-plan` sets this; a long dependency chain runs one task at a time.
3. **Integration.** The merge queue lets one worker rebase, verify and push per target branch at a time. Merges per hour on a branch are about 3600 / (rebase + verify seconds): a 10-minute verify allows 6 merges an hour, however many workers there are, and the others wait in `merge-queue.sh acquire` (1800 s timeout). Ways out: one branch per epic (`epic-merge` already does this), a faster verify, or pull requests into a GitHub merge queue that tests merges in batches. Conflicts also rise with parallel work on the same files.
4. **The supervisor.** Every `ready` and `ended … merged` event costs a Claude turn to run `dispatch-next.sh`. With hundreds of workers, `watch.sh` should dispatch on those events itself and wake Claude only for crashed, stopped and failed tasks. Once workers are remote, the supervisor needs an always-on machine too: a sleeping laptop drops every ssh wrapper.
5. **Human review**, for tasks with review level `human`.

## 6. Steps, smallest first

Each step is usable on its own.

1. **Shared Dolt server**, local workers unchanged. Check claims and the merge queue from two machines.
2. **Merge by pushing**: `finish-task.sh` pushes a fast-forward to `origin`; `run-task.sh` starts from `origin`'s base. Workers still local.
3. **A `runner` setting**: `local` (today) and `ssh <host>` with a worker image. Stdout piped to the local log, transcript copied back when the worker ends and in when it resumes.
4. **Heartbeats** for runners without a local wrapper, then a GitHub Actions runner using a `gh:run` gate and run artifacts.
5. **At scale**: `watch.sh` handles routine events without Claude; task pull requests go through a merge queue.

## Open questions

- Runner: your own machines (which platform?) or GitHub Actions?
- Auth: a subscription token, with limits shared across all workers, or an API key?
- GitHub only, or other git hosts?
- Where does the supervisor run once workers are remote?
- When a disposable worker dies, resume from the last pushed commit, or push after every commit?
