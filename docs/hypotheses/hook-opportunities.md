# Script commands that could run as hooks

Status: hypothesis. Nothing here is built. This records which commands the plugin's scripts run after some event (a close, a merge, a worktree removal) that could instead be installed as a hook on that event: a beads hook, a worktrunk hook, a git hook or a Claude Code hook.

## Summary

- **One real opportunity, on the beads `on_close` hook:** closing a parent task once its last child closes, and closing an epic once its work is done. Three scripts do this today, and only on the paths they cover. As a hook, it also happens when a person or `/sdlc:recover` closes a task.
- **One small one, on `on_create`:** making an epic's integration task wait for a task created under it.
- **Everything else is sequenced.** The script needs the command's result before it goes on, or a hook would also fire when a person uses git or `wt`. Worktrunk post-* hooks run in the background and only log their errors.
- **Git hooks:** none. They are shared with the project's own hook manager, they run for people too, and git has no hook that runs after a push.

## Where a hook can live

| Kind | Installed by | Fires for | Result |
|---|---|---|---|
| beads `.beads/hooks/on_create`, `on_update`, `on_close` | `init.sh`, already, for the wake pipe | every bd write on this machine, from anyone | background, after the write |
| wt project hooks, `.config/wt.toml` | the project | everyone using `wt` in the repo | need approval; belong to the project (see `/sdlc:hooks`) |
| wt user hooks, `[projects."<id>"]` in `~/.config/worktrunk/config.toml` | each machine | that person's `wt` commands in that repo | no approval; pre-* block, post-* run in the background |
| git hooks | the project's hook manager | every git user of the repo | shared with husky, lefthook, `core.hooksPath` |
| Claude Code hooks, `hooks/hooks.json` | the plugin | Claude sessions, gated on `DISPATCH_TASK` for workers | already used: `worker-guard.sh`, `worker-stop.sh` |

## Worth doing

### Close parents and epics from `on_close`

Today:
- `scripts/finish-task.sh`, after its `bd close`:
  - closes each parent task whose children are all closed (`tasks.py parents-to-close`)
  - closes the epic: when the integration task closes, or in direct mode when no non-event task under it is still open
  - in direct mode, then runs `verify.sh` on the epic and comments on a failure
- `scripts/close-prs.sh` closes the epic once the pull request merges.

A person running `bd close` on the last task, or any path that doesn't go through these two scripts, leaves the parent open.

As a hook, `on_close` for bead X:
1. Skip when X is an `event`: its type is in the JSON on stdin, so this costs no bd call. `record-task.sh` creates and closes one event per run.
2. `bd show X` to find the parent. The JSON on stdin has no parent field (tried).
3. If the parent is a task and none of its non-event children are open, close it.
4. If the parent is an epic: close it when X is its `dispatch_integration_task`, or when it has no integration task and none of its non-event children are open.

Closing the parent fires `on_close` again, so grandparents close in turn. Tried with a two-level tree: the parent closed ≈0.5 s after the child's close returned, and the grandparent ≈0.5 s after that.

Removes:
- `tasks.py` `parents_to_close` and its call
- the epic block at the end of `finish-task.sh`
- the epic close in `close-prs.sh`

That's about 40 lines, and one rule in one place instead of two.

Open questions:
- **Asynchronous.** The close lands a moment after the script returns, so `finish-task.sh` no longer prints "closed epic". Check every reader of an epic's status right after a merge. The supervisor already wakes on the epic's own close.
- **Direct mode's check after closing** runs an epic's verify commands and pre-merge checks, which can be the whole test suite. It shouldn't run inside a background bd hook. The supervisor could run it when it wakes on the epic's close, since deciding what to run stays in `supervise.py`.
- **The hook file is in the project, not the plugin.** Like the wake hook, the body has to be self-contained, or call a path that survives plugin updates. The plugin's install directory changes between versions.
- **It applies to every bead in the database**, including beads a person manages outside sdlc. If that's unwanted, limit it to parents that have dispatched children.
- **Cost:** two bd calls (≈0.6 s) per non-event close, in the background.

### Wire the integration task from `on_create` (small, optional)

`scripts/create-task.sh`, after `bd create`: when the epic has a `dispatch_integration_task`, it runs `bd dep add <integration> <new task>` so integration waits for the new task. As an `on_create` hook, a task made with plain `bd create --parent` gets the same wiring (split's review step allows plain `bd`). The check that refuses a task under an epic that's already integrating stays in `create-task.sh`, because a hook runs after the write and can't refuse it.

## Keep in the scripts

| Script: command | Would-be hook | Why not |
|---|---|---|
| `finish-task.sh`: `bd close` and `dispatch_state=merged` after `wt merge` | wt post-merge | Runs in the background. The worker's `finish-task.sh` and `worker-stop.sh` need the task closed when the script returns. It would also fire when a person merges. |
| `finish-task.sh`: merge queue acquire, then release in the exit trap | wt pre-merge / post-merge | The lock has to cover the rebase and verify before the merge. A failing pre-merge check never reaches post-merge, so the lock would stay held. |
| `record-task.sh`: `git branch -D` after `wt remove` | wt post-remove | It would delete branches when people remove their own worktrees. `wt remove -D` does it in the same call. |
| `run-task.sh`: `start-worker.sh` after `wt switch --create` | wt post-start | Runs in the background with errors only in wt's logs. `run-task.sh` must know the worker started, or it undoes the claim. |
| `start-worker.sh` wrapper: `record-task.sh` and the wake after the worker exits | Claude Code `SessionEnd` in the worker | Doesn't run when the worker is killed or crashes. The wrapper sees every exit. |
| `close-prs.sh`, `resume-reviewed.sh` when a gate closes | beads `on_close` on the gate | Already event-driven: the gate's close wakes the supervisor. Moving them into the hook takes the decision out of `supervise.py`. |
| `stop-task.sh`: kill the worker after `dispatch_state=stopped` | beads `on_update` | The hook runs on the machine that wrote, which may not be where the worker runs. `stop-task.sh` also waits for the kill, releases the queue and comments, in order. |
| `finish-task.sh` in epic-pr mode: `git push`, `gh pr create` | git pre-push | No hook runs after a push, and a pre-push hook would run for people pushing too. |

## Found along the way

These aren't hooks. An earlier pass that misread the question found them:
- `run-task.sh` can read the worktree path from `wt switch --format json`, instead of a second `wt list` call.
- `record-task.sh` can call `wt remove -D` instead of `wt remove` plus a `git branch -D` fallback. wt keeps branches merged into a non-default branch, and `-D` only forces the branch delete, so a worktree with uncommitted files is still kept.
- `clean.sh` can use one `wt list --branches --format json` instead of `wt list` plus `git for-each-ref`.
- Untested: `bd gate check --escalate` is documented to mark a `gh:pr` gate whose pull request closed without merging. If so, `close-prs.sh` could drop its own `gh pr view`.
