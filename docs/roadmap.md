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

- **Review before merging:**
  - a reviewer agent run by the worker (today the worker decides)
  - optional human gates on tasks or integration tasks
  - QA agents checking the definition of done, security and guidelines
- **A stopped task goes back to a person:** `bd human` to flag a decision (for example a merge that agents couldn't resolve), and a way to retry a stopped task in its kept worktree.
- **Custom statuses** from the original design: `in_review`, `qa_testing`, `on_hold` and `archived`.
- **Policies:** per-repository rules such as requiring a review or a human gate.

## Planning

- **Deduplication:** a semantic search over existing beads when splitting. Duplicates are linked; the first one implemented wins, and the other is reduced to what remains.
- **Communication between workers** of the same epic through beads graph links, for decisions that affect siblings.
- **Swarms and molecules** from beads, where they simplify the task graph.

## Operations

- **macOS support:** replace `setsid`, GNU `stat` and `date -r` with portable equivalents.
- **A dashboard** for status, stats and logs across projects.
- **Retention of worker logs** in `.git/sdlc/logs`.

## From the original design

The first design listed agents and skills that exist today under other names:

| Original | Today |
|---|---|
| orchestrator agent, `sdlc:orchestrate` | `/sdlc:dispatch` (supervisor) |
| worker agent, `sdlc:dispatch` | the worker session started by `run-task.sh` |
| resolver agent, `sdlc:merge` | `finish-task.sh`, and the integration task's worker |
| `sdlc:create-merge-queue` | `merge-queue.sh` |
| reviewer agent, `sdlc:review` | the worker's discretionary review; a dedicated step is planned above |
| `sdlc:dedup` | planned above |
| `sdlc:open` | `/sdlc:init` |
