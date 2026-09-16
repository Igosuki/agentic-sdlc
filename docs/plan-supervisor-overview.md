# Dispatch, supervisor and workers: how they fit

This is the picture behind `docs/plan-supervisor.md`.

## The three kinds of pieces

- **Skill:** a prompt that runs in the Claude session where you type it, such as `/sdlc:dispatch`.
- **Agent:** a system prompt for a separate Claude session, such as `sdlc:worker`.
- **Script:** a program with no model. It costs no tokens and does the same thing every time.

## Today, and why it breaks

```mermaid
flowchart TD
  you([You]) -->|types| dispatch["/sdlc:dispatch<br/>skill, in your session"]
  dispatch -->|"Agent tool, in the background"| agent["sdlc:supervisor<br/>agent, a background subagent"]
  agent -->|"Monitor, 30 min at most"| watch["watch.py<br/>polls beads every 10 s"]
  agent -->|on each event| next["dispatch-next.sh"]
  next -->|starts| worker["worker session"]
  agent -->|report| dispatch
  dispatch -->|"starts another supervisor<br/>on every report"| agent
```

1. The supervisor is a subagent, and a subagent has to hand back as soon as it stops to wait. It reports "done" while its watch keeps running.
2. Its watch dies after 30 minutes, and nothing starts it again.
3. `/sdlc:dispatch` starts a new supervisor for every report, so several of them run at once.
4. The agent starts tasks while `watch.py` is reading beads, so `watch.py` misreads the task's state and reports false `crashed` and `idle` events.

## Planned: who starts what

```mermaid
flowchart TD
  you([You])

  subgraph session["Your Claude session"]
    dispatch["/sdlc:dispatch<br/>skill"]
  end

  subgraph supervisor["Supervisor: a script, no model"]
    supervise["supervise.py<br/>sleeps until notified"]
  end

  subgraph taskbox["One worker per task, in the task's own worktree"]
    worker["worker session<br/>claude -p --agent sdlc:worker<br/>(sdlc:integrator for an epic's integration task)"]
    impl["implementation agent<br/>one you installed, named by the task"]
    finish["finish-task.sh<br/>review, verify, merge, close"]
    wrapper["wrapper<br/>record-task.sh, then notifies"]
  end

  beads[("beads<br/>tasks, claims, outcomes")]
  pipe[/".git/sdlc/wake<br/>named pipe"/]

  you -->|types| dispatch
  dispatch -->|"starts, as a background Bash command"| supervise
  supervise -->|"exits: blocked, or new work"| dispatch
  dispatch -->|"tells you what's blocked,<br/>suggests /sdlc:review or /sdlc:recover"| you

  supervise -->|"run-task.sh, resume-task.sh<br/>(detached)"| worker
  worker -->|Agent tool| impl
  worker -->|when committed| finish
  worker -. "process ends" .-> wrapper

  finish -->|"closes the task"| beads
  wrapper -->|"records the outcome"| beads
  beads -. "on_create, on_update,<br/>on_close hooks" .-> pipe
  wrapper -. "ended task" .-> pipe
  pipe -. wakes .-> supervise
```

| Piece | Kind | Runs where | Model | Lives until |
|---|---|---|---|---|
| `/sdlc:dispatch` | skill | your session | your session's | the end of each turn; it's woken again only when the script exits |
| `supervise.py` | script | a background command of your session | none | something is blocked, new work shows up, or another supervisor takes over |
| `sdlc:worker` / `sdlc:integrator` | agent | its own `claude -p` process, in the task's worktree | Sonnet, unless the task says otherwise | its task merges, or it stops for a person |
| implementation agent | agent you installed | inside the worker session | its own frontmatter | its piece of work is done |
| beads hooks | scripts `/sdlc:init` installs | run by `bd` after every write | none | one line written |
| `run-task.sh`, `resume-task.sh`, `finish-task.sh`, `record-task.sh` | scripts | called by the pieces above | none | one call |
| `/sdlc:review`, `/sdlc:recover` | skills | your session, when you type them | your session's | one call |

The only model left in supervision is your session, and it runs only when a person is needed.

## Inside supervise.py: one brain, several arms

```mermaid
flowchart LR
  hooks["beads hooks"] -->|a line| pipe
  wrapper["worker wrapper"] -->|a line| pipe

  subgraph feed["Arms that bring events"]
    pipe["wake pipe"]
    timer["sweep timer<br/>60 s after the last round"]
    startup["start"]
    term["SIGTERM<br/>from a newer supervisor"]
  end

  brain{"decide(event)<br/>looks at beads and processes,<br/>returns actions"}

  subgraph act["Arms that act"]
    run["run-task.sh"]
    resume["resume-task.sh"]
    rec["record-task.sh<br/>(--failed)"]
    reviewed["resume-reviewed.sh task"]
    prs["bd gate check<br/>close-prs.sh task"]
    wake["print blocked / new-work<br/>and exit"]
  end

  pipe --> brain
  timer --> brain
  startup --> brain
  term --> brain
  brain --> run
  brain --> resume
  brain --> rec
  brain --> reviewed
  brain --> prs
  brain --> wake
```

- **Events only say why to look.** The brain decides from a fresh look at beads and the processes, so a lost or doubled event can't cause a wrong decision. A lost event only waits for the next sweep.
- **The sweep is the only polling.** It runs 60 s after the last round. It logs any change no event announced, which shows whether it can be stretched.
- **Swapping an event source touches one arm.** For example, a future `bd activity --follow` would replace the beads hooks without changing the brain.

## Life of a task that merges

```mermaid
sequenceDiagram
  actor You
  participant D as /sdlc:dispatch (your session)
  participant S as supervise.py
  participant P as wake pipe
  participant B as beads
  participant W as worker session

  You->>D: /sdlc:dispatch epic-1
  D->>You: these tasks, parallel limit, merge mode. Go?
  You->>D: yes
  D->>S: start in the background
  Note over D: your session is free
  S->>B: look
  S->>W: run-task.sh task-1 (claim, worktree, start)
  Note over S: sleeps on the pipe
  W->>W: implement, commit
  W->>B: finish-task.sh merges, closes task-1
  B-->>P: on_close hook writes "close task-1"
  P-->>S: wakes
  Note over S: task-1's process still runs,<br/>its slot stays taken
  W-->>P: wrapper writes "ended task-1" once recorded
  P-->>S: wakes
  S->>B: look
  S->>W: run-task.sh task-2, now unblocked
  Note over S: merged: nothing to tell you
```

## When your session wakes

```mermaid
sequenceDiagram
  actor You
  participant D as /sdlc:dispatch (your session)
  participant S as supervise.py
  participant W as worker session

  W->>W: finish-task.sh needs a human review
  W-->>S: wrapper writes "ended task-3"
  S->>D: exits with "blocked task-3 awaiting-review"
  D->>S: start again, same arguments
  Note over S: task-3 isn't reported again,<br/>other tasks keep going
  D->>You: task-3 waits for your review: /sdlc:review task-3
```

The script exits, and wakes your session, only for:
- **Blocked:** awaiting review, stopped, failed, a pull request waiting for a person to merge, or a ready task that won't start.
- **New work:** tasks outside the ids you dispatched became ready. It asks whether to dispatch them too.
- **Taken over:** another session started its own supervisor.

Starts, merges, epics closing and everything finishing don't wake it.

## A worker whose process is gone

```mermaid
flowchart TD
  gone["worker process gone,<br/>no outcome recorded"] --> result{"log has a result?"}
  result -->|yes: it ended normally| rec["record-task.sh<br/>merged, stopped or failed"]
  result -->|no: a crash| again{"already resumed 3 times<br/>since the last result?"}
  again -->|no| exists{"worktree and<br/>transcript still there?"}
  exists -->|yes| res["resume-task.sh<br/>no one is told"]
  exists -->|no| failed["record-task.sh --failed"]
  again -->|yes| failed
  failed --> wake["exits: blocked task failed<br/>you run /sdlc:recover"]
```

A crash means the process died without writing how it ended: it was killed, the machine restarted, or the Claude CLI itself died. API errors and usage limits aren't crashes. The worker writes its result, and the task shows as `failed`.

## Supervising from another session

Only one supervisor runs per repository. It holds a lock file, `.git/sdlc/supervise.lock`.

```mermaid
sequenceDiagram
  participant A as supervise.py (session A)
  participant L as supervise.lock
  participant B2 as supervise.py (session B)

  A->>L: holds the lock
  Note over A: session A is killed,<br/>or still open
  B2->>L: locked by A's pid
  B2->>A: SIGTERM
  A-->>A: finishes its current action, exits "taken over"
  B2->>L: takes the lock
  Note over B2: supervises from now on,<br/>workers keep running throughout
```

Workers run detached, so killing a session or its supervisor never stops them. A new `/sdlc:dispatch` picks them up where they are.
