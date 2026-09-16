# How sdlc uses beads

[Beads](https://github.com/gastownhall/beads) (`bd`) holds all of sdlc's state: the tasks, who works on them, what they cost, the merge queues and the gates. Worktrees share one Dolt database, so a worker in its worktree and the supervisor in the main checkout see the same beads. Full CLI reference: <https://beads.gascity.com/cli-reference>.

## Task fields

`create-task.sh` (used by split and create-task) creates beads with:

| Field | Where | Meaning |
|---|---|---|
| title, description, type, priority, parent | bead | standard beads fields |
| acceptance | `acceptance_criteria` | what must hold for the task to be done |
| `scope` | metadata | comma-separated path prefixes the task changes |
| `verify` | metadata | command that exits 0 when the acceptance is met |
| `complexity` | metadata | `small`, `medium` or `large` |
| `design` | metadata, and the spec id | the design document the task comes from |
| `review` | metadata | `none`, `agent` or `human`: review level before merging, default `bd config custom.dispatch.review` (itself `none`) |
| dependencies | `blocks` edges | tasks this one waits for (`--after`) |

## Execution hints

The keys documented in [beads' metadata page](https://beads.gascity.com/core-concepts/metadata), read by `run-task.sh` and `start-worker.sh`:

| Key | Effect on the worker |
|---|---|
| `execution_agent_type` | the agent the worker hands the implementation to; that agent's frontmatter picks its model |
| `execution_suggested_model` | `--model` for the worker session, overriding the worker agent's own model |
| `execution_reasoning_effort` | `--effort` |

## Dispatch state

Set by the dispatch scripts on each task. They can be queried, for example `bd list --metadata-field dispatch_state=stopped`.

There's no `dispatch_state` value for a running worker. A task's worker is **running** when it is claimed (`in_progress` with `dispatch_session` set), a process exists for it — `run-task.sh <task>` still starting it, or the worker session itself — and no attempt outcome is recorded yet (`dispatch_state` unset). A claimed task with no such process and no outcome has **crashed**.

| Key | Set by | Meaning |
|---|---|---|
| `dispatch_state` | run, finish, record | unset while running; otherwise `merged`, `pr-opened`, `awaiting-review`, `stopped` or `failed` |
| `dispatch_session` | run-task.sh | Claude session id of the worker, set before it starts |
| `dispatch_host` | run-task.sh | machine the worker runs on |
| `dispatch_base` | run-task.sh | branch the task merges into |
| `dispatch_branch` | run-task.sh | branch of the task's worktree |
| `dispatch_started` | run-task.sh | claim time |
| `dispatch_cost`, `dispatch_model`, `dispatch_agents` | record-task.sh | latest attempt: cost in USD over all runs of the session, models used, agents used |
| `dispatch_pr` | finish-task.sh | pull request URL, in `epic-pr` mode |
| `dispatch_role` | run-task.sh | `integration` for an epic's integration task |
| `dispatch_review` | finish-task.sh | `approved` or `changes`, the last review verdict |
| `dispatch_review_patch` | finish-task.sh | stable id (`git patch-id`) of the diff the verdict covers, so a later no-op re-run doesn't ask for review again |
| `dispatch_review_rounds` | finish-task.sh | number of agent review rounds run so far (level `agent`) |
| `dispatch_review_cost` | finish-task.sh | total USD spent on agent review sessions (level `agent`); added into `/sdlc:stats` |
| `dispatch_review_gate`, `dispatch_review_gate_patch` | finish-task.sh | the open human review gate's id, and the patch id it covers (level `human`) |

On epics: `dispatch_branch` (the epic branch), `dispatch_integration` (the mode used, which also overrides the repository's setting for that epic), and `dispatch_integration_task`.

Status stays standard beads:
- `open` means waiting or ready
- `in_progress` means claimed
- `closed` means merged

A task whose worker stopped stays `in_progress`, with `dispatch_state=stopped` and a comment explaining why. A task waiting on a human review stays `in_progress` too, with `dispatch_state=awaiting-review` and its worktree kept.

## Event beads

Every worker attempt adds one closed event bead that targets the task. Metadata only holds the latest attempt, so the events are the history.

```bash
bd list --type event --all --json | jq '.[] | select(.target == "<task>")'
```

- `event_kind`: `dispatch.merged`, `dispatch.pr-opened`, `dispatch.awaiting-review`, `dispatch.stopped` or `dispatch.failed`
- `actor`: the agents or models that worked
- `payload` (JSON): `session`, `model`, `agents`, `cost_usd`, `turns`, `duration_s`, `branch`, `base`, `host`, `result`, `log`
- description: the worker's final message

`/sdlc:stats` adds these up. Event beads are stored in Dolt. `bd audit record` isn't used, because it writes to `.beads/interactions.jsonl` in the working tree.

## Merge queues

One ephemeral bead per branch, titled `merge queue <branch>`. Its id is kept in `bd kv` as `dispatch.queue.<branch>`.
- **Taking it:** `bd update <lock> --claim --actor <task>`, which fails while another task holds it.
- **Releasing it:** set the status back to `open` with an empty assignee.

`bd merge-slot` isn't used, because it allows only one slot per repository.

## Gates

- **`gh:pr`:** created by `finish-task.sh` in `epic-pr` mode, on the integration task.
- **`human`, added by you:** add one yourself, to review before a task can start:
  ```bash
  bd gate create --type=human --blocks <task> --reason "..."
  bd gate resolve <gate>
  ```
- **`human`, the review gate:** for a task with `review=human`, `finish-task.sh` creates this gate itself (`dispatch_review_gate`) instead of merging, and sets `dispatch_state=awaiting-review`. Resolve it the same way, `bd gate resolve <gate>`; `resume-reviewed.sh` then picks the task back up. `workers.py` prints the exact commands for a task waiting in this state.

A gate can block a task but not an epic. `watch.py` runs `bd gate check` on every round.

## Configuration

`bd config set custom.dispatch.integration <mode>`, `bd config set custom.dispatch.target <branch>` and `bd config set custom.dispatch.review <none|agent|human>`. See [configuration](configuration.md).
