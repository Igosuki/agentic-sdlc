# Remote workers

Status: hypothesis. Nothing here is built. This records what it would take to run dispatched workers on other machines, so the number of workers isn't bounded by one computer.

## Summary

- Workers share three things with the supervisor through the local disk: the code (worktrees of one repository), the task state (the embedded beads database) and the worker process itself (found with `pgrep`, with a local log and transcript). Each has to move to something reachable over the network: a git remote, a shared Dolt server, and a **runner**, the command that starts one worker somewhere else and returns.
- Suggested first shape: the same `claude -p` worker in a serverless sandbox that can pause a stopped worker (E2B first, Fly Sprites worth testing), or in GitHub Actions; beads on a shared `dolt sql-server`; GitHub as the remote; merges done by pushing to it. The worker contract, hooks and skills stay as they are.
- Claude Code on the web is a poor runner today. Its sandbox sends all traffic through an HTTP/HTTPS proxy, so workers can't reach a Dolt server, and a script has no documented way to learn that a cloud session ended.
- No open-source project runs headless Claude Code workers across machines yet. Gas Town, built on beads, has an open design issue for it that compares the same options (section 7).
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

- Setup, per repository: `bd init --server --external --server-host … --server-port …`, `--external` meaning the server is run outside `bd`. Each project gets its own database on the server, named after its issue prefix, so two repositories only collide if they share a prefix. `bd init --database <name>` overrides the name.
- Workers get `BEADS_DOLT_SERVER_HOST`, `_PORT`, `_USER`, `_DATABASE`, `_TLS` and `BEADS_DOLT_PASSWORD`; these outrank `.beads/metadata.json` and `config.yaml`.
- **In server mode, Dolt's auto-commit is off**, because committing after every write under concurrent load produces "database is read only" errors. Run with `--dolt-auto-commit batch` or commit explicitly with `bd dolt commit`. This changes how every script's `bd` call behaves and needs testing before anything else is built.
- Each worker sets its own `BEADS_ACTOR` (for example the task id), since claims and `bd merge-slot --holder` default to it and every worker would otherwise share one OS user name.
- Moving this project's embedded database onto a server: `bd backup init <dir>`, `bd backup sync`, `bd init --server`, `bd backup restore --force <dir>`. Back the server up with `bd dolt push` to a Dolt remote; a JSONL export is not a backup.
- Ports: 3307 by default, 3308 by convention for a shared server; `BEADS_DOLT_MAX_CONNS` sets the connection limit (a sample config uses 100).
- The beads docs recommend pinning Dolt to 2.2.0: on 2.3.x, `DOLT_RESET` fails on about 3–5% of new databases.
- The docs mention `bd sync`; the installed `bd` 1.2.2 has no such command.
- Where: a small always-on machine that workers reach over a private network (Tailscale, WireGuard) or TLS.

## 4. Where workers run

| | A. Serverless sandboxes and jobs | B. GitHub Actions | C. Claude Code on the web | D. Managed Agents API |
|---|---|---|---|---|
| Worker unchanged (plugin, hooks, `bd`) | yes | yes | plugins install from `.claude/settings.json` | no: rebuilt as an agent definition |
| Reaches a Dolt server | depends on the platform | yes | no: HTTP/HTTPS proxy | not confirmed |
| Supervisor learns it ended | the runner's stream and exit code | `gh run`, a `gh:run` gate | not documented | event stream |
| Log, cost, transcript | streamed back; transcript stays in the paused sandbox | run artifacts | not documented | event stream, cost per session |
| Scale limit | concurrency per plan | job time limit and concurrent jobs per plan | shared subscription rate limits | API rate limits |
| Billing | per second + model usage | Actions minutes + model usage | subscription | API |

### A. Serverless sandboxes and jobs

A worker is a long process that mostly waits on the model API and runs tests now and then. From a platform it needs a custom image, runs of 2 hours or more, its output streamed back with the exit code, a plain TCP connection to the Dolt server, and ideally a way to keep a stopped worker's disk so it can be resumed.

Figures below come from vendor docs and pricing pages read on 2026-09-15. Several prices are estimates from per-second rates; recheck before choosing.

| Platform | Longest run | Output and exit code | TCP to Dolt | Keeps a stopped worker | Concurrency | ~$/h, 2 vCPU 4 GB |
|---|---|---|---|---|---|---|
| E2B | 1 h Hobby, 24 h Pro | background command with stdout callbacks, exit code, reconnect | yes: ports other than 80/443 are filtered by CIDR only | pause and resume, memory included, kept until killed | 20 Hobby to 1,100 Pro++ | 0.17, plus the Pro plan fee |
| Modal Sandboxes | 24 h | SDK stream, `returncode`; `Sandbox.from_id()` reattaches from a new script | yes, open by default | filesystem snapshot, restored into a new sandbox | containers per plan: 100 Starter, 5,000 Team | ~0.24 |
| Fly Sprites | none: persistent machines | `sprite exec`, detachable sessions | not documented | persistent disk, checkpoints in ~300 ms | not documented | $0.07 per CPU-hour actually used |
| Fly Machines | none | `fly machine run` output, `fly machine exec` (check streaming) | yes, and a private WireGuard network inside the org | volumes, reattached by hand | soft limits, API rate limits | ~0.09 (dedicated CPUs) |
| Northflank | none stated | exec API with stdout stream and exit code | yes, and private networking inside a project | volumes | not documented | ~0.07 |
| Daytona | none stated | session log streams, reconnect | CIDR allowlist on tiers 3–4; non-HTTP not explicit | snapshots; pausing a running sandbox not confirmed | vCPU pool per tier | 0.17 |
| Morph Cloud | none stated | synchronous exec; its Claude Code example runs the CLI in tmux over SSH | not documented | pause keeps memory and processes | 8 to 128 by plan | 0.15 |
| ECS Fargate | none in practice | CloudWatch tail, exit code, ECS Exec | yes, VPC | an EFS volume, by hand | 1,000 tasks per region; new accounts start at 6 vCPU | ~0.10 |
| Cloud Run Jobs | 7 days | log tail, exit code, no exec | yes, Direct VPC egress | none | regional quota | ~0.20–0.26 |

Ruled out:
- **Cloudflare Sandbox and Containers:** outbound traffic is HTTP/HTTPS only, disks are wiped on sleep, and snapshots aren't available yet.
- **Vercel Sandbox:** automatic snapshots on stop and billing only for active CPU fit well, but TCP beyond HTTP is unconfirmed. Recheck.
- **AWS Lambda:** 15-minute limit.
- **Railway:** no one-shot job to start from a script.
- **GitHub Codespaces:** made for interactive development, not jobs.
- **Runloop:** $0.32/h, plus $250/month for suspend and resume.
- **Azure Container Apps Jobs:** longest run unclear.

Notes:
- The Claude integrations these vendors publish (E2B, Daytona, Modal, Vercel, Cloudflare, Sprites) are for Managed Agents: Anthropic runs the agent loop and the sandbox only executes tool calls, so plugins and hooks don't load (option D). For a `claude -p` worker, Anthropic's Agent SDK hosting cookbook covers Docker, Modal and Kubernetes, and Morph's example runs the CLI itself.
- Model usage dominates the cost of a worker-hour; compute is the small part. Choose on fit, not on compute price.
- To try first: **E2B**, whose docs confirm all four needs (TCP, streaming with reconnect, pause and resume, 24 h). **Fly Sprites** is worth a test: billing by CPU used matches a worker that mostly waits, and the disk persists. Its networking and concurrency aren't documented.

What a sandbox changes:
- **Resume without copying.** On a platform that keeps a stopped machine (E2B, Morph, Sprites, Modal snapshots), the transcript and uncommitted work stay where they are. When a worker ends without closing its task, pause its sandbox; resuming reopens it and runs `claude -p --resume` there. Delete the sandbox when the task closes. This replaces copying transcripts back and pushing after every commit.
- **A runner script per platform**, with four verbs:
  - `start <task>`: creates a sandbox from the worker image, clones at the base, runs the worker, appends its output to `.git/sdlc/logs/<task>-<session>.jsonl`, and exits with the worker's exit code.
  - `alive <task>`: says whether the worker process is still running in its sandbox.
  - `resume <task> <prompt>`: reopens the sandbox and runs `claude -p --resume` with the prompt, appending to the same log.
  - `end <task> keep|delete`: pauses or deletes the sandbox.

  The sandbox id goes in task metadata (`dispatch_sandbox`). E2B, Modal and Daytona stream output through Python or TypeScript SDKs; Fly, Sprites and Morph can be driven from bash through their CLI or SSH.
- **Liveness moves to the runner.** If the local `start` process dies (a laptop sleeping), the sandbox keeps running. `watch.sh` and `workers.sh` ask `alive` before calling a task crashed, and `start` reattaches to stream again.
- **Where Dolt runs.** On Fly or Northflank, the Dolt server can sit on the same private network as the workers, and the supervisor joins through WireGuard or a proxy. Sandboxes that don't join a private network (E2B, Modal) need a public TLS endpoint with credentials.
- **The image** carries `claude`, `bd`, `git`, `gh`, `jq`, `wt`, the project's toolchain, and the `wt` approvals. Credentials for GitHub, the Dolt server and Claude (`ANTHROPIC_API_KEY`, or `CLAUDE_CODE_OAUTH_TOKEN` from `claude setup-token` for Pro, Max, Team or Enterprise) are injected as secrets. Anthropic's hosting guide starts from 1 CPU, 1 GiB RAM and 5 GiB disk per agent; tests need more.
- **Docker on your own VMs** (Hetzner, DigitalOcean) fits the same four verbs from bash, and is the cheapest per worker, since idle workers pack many to a VM:
  - `start`: `ssh host docker run -d` with two named volumes per task, one for the clone and one for `~/.claude`; `ssh host docker logs --follow` appends to the local log, and `docker wait` gives the exit code. Both can be re-run after the stream drops, so a sleeping laptop loses nothing.
  - `alive`: `docker inspect`.
  - `resume`: a new container on the same volumes runs `claude -p --resume`; the transcript and uncommitted work live in the volumes.
  - `end`: remove the container, and the volumes too once the task is closed.

  What you give up is scaling on demand: adding capacity means creating VMs (`hcloud` or `doctl` with cloud-init), and `start` picks a host with a free slot from a per-host limit. Tailscale between hosts, supervisor and the Dolt server covers networking.
- **k3s on those same VMs** replaces host-picking with a scheduler, at the price of running a cluster and an image registry. A worker is a Job: `kubectl logs -f` streams, `kubectl wait` gives the end, a volume claim keeps the disk for a resume. [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) (section 7) offers hibernate-and-resume and warm pools if plain Jobs aren't enough. Worth it once the number of hosts makes manual placement annoying, not before.

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
4. **The supervisor.** Every `ready` and `ended … merged` event costs a Claude turn to run `dispatch-next.sh`. With hundreds of workers, `watch.sh` should dispatch on those events itself and wake Claude only for crashed, stopped and failed tasks. Once workers are remote, the supervisor needs an always-on machine too: a sleeping laptop stops every runner stream, and while it sleeps nothing dispatches or resumes.
5. **Human review**, for tasks with review level `human`.

## 6. Steps, smallest first

Each step is usable on its own.

1. **Shared Dolt server**, local workers unchanged. Check what auto-commit being off in server mode does to the scripts, then claims and the merge queue from two machines.
2. **Merge by pushing**: `finish-task.sh` pushes a fast-forward to `origin`; `run-task.sh` starts from `origin`'s base. Workers still local.
3. **A `runner` setting**: `local` (today) and one sandbox platform with a worker image, through the four runner verbs. A stopped worker's sandbox is paused and resumed in place.
4. **Heartbeats** for runners without a local wrapper, then a GitHub Actions runner using a `gh:run` gate and run artifacts.
5. **At scale**: `watch.sh` handles routine events without Claude; task pull requests go through a merge queue.
6. **Several repositories**: one supervisor service per repository first; a registry and one loop only when that becomes silly, which is also when the loop stops being a shell script (section 9).

## 7. Prior art

Surveyed on 2026-09-15 from GitHub (`gh repo view`) and project docs. Star counts are as of that day.

### Gas Town, then Gas City (Steve Yegge, MIT)

The same lineage at two stages, both on beads, and the closest projects to sdlc's dispatch half.

[gastownhall/gastown](https://github.com/gastownhall/gastown) (18k stars) is the original orchestrator: fixed roles (mayor, watchdog, merge queue, workers), a Dolt SQL server, worktrees sharing the database through `.beads/redirect`, and `bd merge-slot`. Its `main` branch has had no commits since 2026-07-23 and its last release was 2026-06-06, so treat it as frozen.

[gastownhall/gascity](https://github.com/gastownhall/gascity) (1.3k stars, since 2026-02) is the successor: the same machinery with the roles pulled out into configuration over six primitives (agent, bead, formula, rig, pack, event), so Gas Town becomes one "pack" on top of it. Committed to daily.

What both say about the problems in this document:

- **Workers.** Gas Town's are interactive Claude Code sessions in tmux, and its headless request ([#1382](https://github.com/gastownhall/gastown/issues/1382)) was closed as superseded by Gas City, which has `subprocess` and `exec` runtimes besides tmux, ACP and Kubernetes. tmux is still required as the fallback runtime. Headless interaction mode still has open bugs ([#3682](https://github.com/gastownhall/gascity/issues/3682)).
- **Completion** is reported by the worker itself (push the branch, mark the issue ready to merge); the watchdog only nudges or cleans up stuck workers and never decides whether work is done. sdlc splits the same way: `finish-task.sh` closes, `watch.sh` detects crashes.
- **Merges.** Gas Town's "Refinery" is Bors-style by design: rebase a stack of branches, test the tip, fast-forward them all, bisect on failure. Only per-branch checks were built. Batching like that answers the integration limit of section 5. In Gas City it isn't core: a merge queue is an agent plus a formula in a pack.
- **Multiple machines** are unfinished in both. Gas Town's plan ([#2801](https://github.com/gastownhall/gastown/issues/2801)) compares bursting to Daytona containers, a fleet over SSH or Tailscale where SSH runs only at startup and later calls go through an mTLS proxy, and Kubernetes. Gas City's Kubernetes runtime works by giving each pod its own `bd` pointed at **one shared Dolt server**, which is the arrangement of section 3. A general off-host worker reaching the store over HTTP is specified but not implemented ([#5737](https://github.com/gastownhall/gascity/issues/5737)).
- **Shape.** Gas City is a Go CLI and daemon (`gc init`, `gc start`, `gc rig add`) needing tmux, git, jq, dolt and `bd`, not a Claude Code plugin. An existing beads repository can be registered as a rig, but its orchestration means adopting its packs, formulas and agent config.

[gastownhall/beads](https://github.com/gastownhall/beads) is a separate project both consume; its docs sit at beads.gascity.com for branding, not because it merged into Gas City.

### Libraries that could be the runner

None replaces the four runner verbs.

- [SWE-agent/SWE-ReX](https://github.com/SWE-agent/SWE-ReX) (Python, MIT, active): one interface over local, Docker, Modal, Fargate, Daytona and your own VM, built to run many agents in parallel. It runs commands and returns their exit codes, but has no live streaming and no pause or resume, which are the two things sdlc needs.
- [rivet-dev/sandbox-agent](https://github.com/rivet-dev/sandbox-agent) (Rust binary, Apache-2.0, quiet since June 2026): runs inside an E2B, Daytona, Modal, Vercel or Docker sandbox and streams agent events in one schema over SSE. It exists to normalize several agents; sdlc only runs Claude Code, which already streams JSON. It doesn't provision sandboxes or keep sessions.
- [superagent-ai/vibekit](https://github.com/superagent-ai/vibekit) (TypeScript, MIT): runs `claude -p --output-format stream-json`, with pause, resume and kill per provider (E2B, Daytona, Modal, Northflank, Cloudflare, Dagger, Beam, Blaxel) and pull request creation. The closest feature match, but its main branch hasn't moved in about 10 months. Read its provider packages for the pause and resume calls; don't depend on it.

### Designs worth reading

- [BloopAI/vibe-kanban](https://github.com/BloopAI/vibe-kanban) (28k stars): a board that dispatches issues to agents in worktrees, with a self-hosted remote server and relay that routes work to paired remote hosts. The company shut down in April 2026, and the project is now community-maintained.
- [terragon-labs/terragon-oss](https://github.com/terragon-labs/terragon-oss): code release of a background-agent product that shut down in January 2026. It had a sandbox provider per agent, streaming through a tunnel, a CLI to take over a task locally, and a branch and pull request per task.
- [kubernetes-sigs/agent-sandbox](https://github.com/kubernetes-sigs/agent-sandbox) (Apache-2.0, v1): a Kubernetes resource for a stateful pod that hibernates, resumes on the next connection, keeps its storage and has warm pools. The best resume-in-place primitive found, if running k3s on your VMs is acceptable.
- [coder/coder](https://github.com/coder/coder) (AGPL-3.0): workspaces on any backend Terraform reaches, and "Agent Boundaries", a per-process egress firewall with an allowlist and audit log. Its "Tasks" feature, which wrapped agent CLIs, is being removed in favor of an agent loop inside Coder.
- Anthropic's [reference devcontainer](https://github.com/anthropics/claude-code/tree/main/.devcontainer): a default-deny iptables firewall in `init-firewall.sh`, usable as the worker image's egress policy once a rule for the Dolt port is added.

### tmux and worktree tools

Single-machine and human-driven, apart from remote tmux attach:
- [smtg-ai/claude-squad](https://github.com/smtg-ai/claude-squad) (8k stars)
- [raine/workmux](https://github.com/raine/workmux) (3k): marks a worker interrupted after 10 s without output, as a fallback to hook-reported status.
- [kbwo/ccmanager](https://github.com/kbwo/ccmanager) (1k): classifies busy, waiting and idle by matching terminal output.
- [mixpeek/amux](https://github.com/mixpeek/amux) (small): reaches a remote fleet over Tailscale or SSH, with tmux sessions that survive disconnects.
- [manaflow-ai/cmux](https://github.com/manaflow-ai/cmux) (27k, macOS): attaches to remote tmux sessions over SSH.

For sdlc's headless workers, `docker logs --follow` and `docker wait` give the same survival across disconnects, with an exit code.

Local dev-container wrappers, useful for designing the worker image only: [dagger/container-use](https://github.com/dagger/container-use), [RchGrav/claudebox](https://github.com/RchGrav/claudebox), [imbue-ai/sculptor](https://github.com/imbue-ai/sculptor), and Docker Sandboxes (`sbx run claude`).

Full platforms with their own agent loop, not a way to run `claude -p` workers: [OpenHands](https://github.com/OpenHands/OpenHands), and Coder's new agents.

Dead or archived: `coder/agentapi` (drove agents by scraping a terminal), `boldsoftware/sketch`, `devflowinc/uzi`, `stravu/crystal`, `textcortex/claude-code-sandbox`, `wandb/catnip` (repository gone).

## 8. Several repositories

One server already holds several projects: a database per repository, named after its issue prefix. Nothing else is shared, which decides most of the design.

- **Dispatch stays per repository.** Every script starts from the current repository (`git rev-parse`), and `bd list` and `bd ready` read the routed repository only. The first version of several repositories is therefore several supervisors: one service per repository, same scripts, same server. Nothing new to build.
- **One loop over a registry** is the version after that, and it needs: a registry of repositories (path or remote, target branch, integration mode, runner, worker image), selecting the right database per repository (`bd --repo <path>`, or the `BEADS_DOLT_SERVER_DATABASE` of that repository), a parallel limit per repository and overall, and a `--repo` argument on the dispatch, status and stats skills. That is when the loop stops being a shell script comfortably (section 9).
- **Dependencies across repositories aren't first-class.** `bd dep` doesn't cross databases. Beads offers `bd ship <capability>` on a closed issue plus `bd dep add <issue> external:<project>:<capability>`, or `bd repo add` to hydrate another repository's issues into a local read view. Gas City does the same thing at its own level: one database per rig, with a `routes.jsonl` mapping prefixes to paths.
- **Worker images are per repository**, since each project's tests need its own toolchain. A base image with `claude`, `bd`, `git`, `gh`, `jq` and `wt`, plus a per-repository setup step, keeps that manageable.

## 9. Skills, or a binary?

Keep the skills. Move only the unattended loop into a program, and only when it earns it.

- **What only skills can do.** The supervisor is a Claude session: it reads a crashed worker's log and decides whether to resume it, asks through `AskUserQuestion`, and runs the agents, hooks and permissions already configured on the machine. The planning skills are prompts. A binary would have to invent policy for all of that, or shell out to `claude` anyway, and the result would be a smaller Gas City competing with a project that has a year's head start.
- **What bash is bad at**, and what remote workers add: a process running for days unattended, across repositories and hosts, with timers, retries, backoff, heartbeats and many output streams to keep alive and reattach. Today that is `watch.sh`, polling every 10 s for as long as a session stays open, and one supervisor per repository.
- **The split:** skills stay the interface and the judgment; the loop becomes a service on an always-on machine. It stays in bash while it's one repository and a handful of workers per host.
- **Rewrite the loop when both are true:** more than one repository dispatching at once, and workers on more than one host needing heartbeats. Rewrite the loop only: `watch.sh`, `dispatch-next.sh`, `workers.sh`, the runners and the registry. The skills, hooks and `finish-task.sh` stay as they are, and the binary stays a dispatcher rather than growing roles of its own.
- **Go rather than Rust**, for the clients this needs: Kubernetes, Docker, SSH and MySQL for Dolt. It also matches beads, Gas City and Dolt, so their code is readable as reference.

## Open questions

- Follow Gas Town's multi-machine design (#2801) when it lands, or build sdlc's own runner now?

- Runner: a sandbox platform (E2B, Sprites, Modal, Fly Machines, Northflank) or GitHub Actions? Python SDK runners are acceptable, or bash only?
- Auth: a subscription token, with limits shared across all workers, or an API key?
- GitHub only, or other git hosts?
- Where does the supervisor run once workers are remote?
- On a platform that can't pause a sandbox, resume from the last pushed commit, or push after every commit?
