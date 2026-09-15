# Roadmap

What exists today is described in [workflow](workflow.md). This is what comes next, roughly in order of value. Items come from building and testing the plugin, and from the original design notes.

## Trackers

- **GitHub Issues** alongside beads, then Linear and Jira:
  - an issue becomes a task
  - an epic becomes a milestone or a parent issue
  - dependencies become task lists or sub-issues
  - dispatch metadata goes in issue fields or labels
  - worker comments go in issue comments
  - `epic-pr` already produces pull requests

  The likely shape is a tracker adapter with the handful of verbs the scripts use: create, show, list ready, claim, update metadata, comment, close, gate. Beads could stay the local engine, kept in sync with GitHub. See [hypotheses/portability.md](hypotheses/portability.md).
- **Two-way sync.** Issues created on GitHub become dispatchable tasks, and task state is mirrored back to GitHub.

## Harnesses and models

- **A `harness` setting** with adapters for Codex CLI and OpenCode workers (see [harnesses](harnesses.md)).
- **Local models through Ollama** for workers, with the cost recorded as tokens.
- **Cost from tokens** for harnesses that don't report dollars.

## Several machines

- **Heartbeats:** a running worker updates `dispatch_heartbeat`, so stale workers on other machines can be told apart from live ones.
- **Stale claims:** each machine only resumes its own workers (`dispatch_host`). A task from another machine whose heartbeat is older than a grace period longer than the Dolt sync interval is reported to a person.
- **Federation:** Dolt remotes or beads federation between machines, one supervisor per machine sharing the queue.

## Quality

- **Dedicated QA agents** checking the definition of done, security and guidelines, beyond what an `agent`-level review covers.
- **A stopped task goes back to a person:** `bd human` to flag a decision (for example a merge that agents couldn't resolve), and a way to retry a stopped task in its kept worktree.
- **Custom statuses** from the original design: `in_review`, `qa_testing`, `on_hold` and `archived`.

## Planning

- **Deduplication:** a semantic search over existing beads when splitting. Duplicates are linked; the first one implemented wins, and the other is reduced to what remains.
- **Communication between workers** of the same epic through beads graph links, for decisions that affect siblings.
- **Swarms and molecules** from beads, where they simplify the task graph.

## Operations

- **macOS support:** replace `setsid`, GNU `stat` and `date -r` with portable equivalents.
- **A dashboard** for status, stats and logs across projects.
- **Retention of worker logs** in `.git/sdlc/logs`.
- **Channels** (a Claude Code research preview) as an optional event transport:
  - an sdlc channel that the scripts push events to (a worker ending, a merge, a merged pull request), so the supervisor reacts without polling, with `watch.sh` as the fallback
  - pairing the supervisor with the official Telegram or Discord channel, for review approvals, alerts about stopped tasks and permission prompts from a phone

  Channels still need the session to be open, and during the preview a custom channel needs `--dangerously-load-development-channels`.
- **Cleanup after a crash between merge and record:** a closed task whose attempt was never recorded keeps its worktree. The supervisor should record what it can and remove the worktree.

## From the original design

The first design listed agents and skills that exist today under other names:

| Original | Today |
|---|---|
| orchestrator agent, `sdlc:orchestrate` | `/sdlc:dispatch` (supervisor) |
| worker agent, `sdlc:dispatch` | the worker session started by `run-task.sh` |
| resolver agent, `sdlc:merge` | `finish-task.sh`, and the integration task's worker |
| `sdlc:create-merge-queue` | `merge-queue.sh` |
| reviewer agent, `sdlc:review` | the worker's discretionary review, plus `finish-task.sh`'s `agent`/`human` review levels; dedicated QA agents are planned above |
| `sdlc:dedup` | planned above |
| `sdlc:open` | `/sdlc:init` |
