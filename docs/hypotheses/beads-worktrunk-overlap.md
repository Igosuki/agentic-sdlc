# Script code that beads, worktrunk or git hooks already cover

Status: hypothesis. Nothing here is built. This records which parts of the plugin's scripts could call `bd` 1.2.2 or `wt` 0.77, or move to a git hook, instead of doing the work themselves. Each item was checked against the tool's `--help`, and most were also tried in a throwaway repository.

## Summary

- **Git hooks:** nothing moves there. Git hooks are shared with the project's own hooks (husky, lefthook, `core.hooksPath`), and they would also run for people working in the repository, not just workers.
- **Beads:** nothing to replace. The commands that look similar are shaped differently: one merge slot per repository, epic closing that ignores parent tasks, sorting with no "epics in progress first", state set one dimension per call. One thing needs a test against a real pull request: `bd gate check --escalate`.
- **Worktrunk:** three small simplifications, each removing a call or a fallback, and one addition to `/sdlc:hooks`. Worktrunk's own "merged" check compares against the default branch only. Epic branches aren't the default branch, so leftover and cleanup decisions keep coming from bead state.

## Worth doing

| Where | Change | Evidence | Saves |
|---|---|---|---|
| `scripts/run-task.sh`, worktree path lookup after `wt switch` | Read `.path` from the `wt switch --format json` output instead of a second `wt list --format json` | Tried: `wt switch --create … --format json` prints `{"action":"created","branch":…,"path":…}` | one `wt list` call per task start |
| `scripts/record-task.sh`, worktree removal after a merge | `wt remove -D "$branch"` instead of `wt remove` followed by a `git branch -D` fallback | Tried: after a merge into a non-default branch, `wt remove` keeps the branch (`retained_unmerged`). `-D` only forces the branch delete. Without `-f`, a worktree with uncommitted files is still kept, so the "worktree kept" note still works. | the fallback and its comment |
| `scripts/clean.sh`, leftover listing | One `wt list --branches --format json` instead of `wt list` plus `git for-each-ref refs/heads` | Tried: each item carries a `worktree` object, or `false` when the branch has no worktree | the second loop, ~13 lines |
| `skills/hooks/SKILL.md`, pre-start suggestion | Suggest `wt step copy-ignored` for `.env` and other ignored files a worker needs, alongside the dependency install | `wt step copy-ignored --help`; `--require-include` limits it to files listed in `.worktreeinclude` | — |

## Worth testing

- **`bd gate check --escalate` for a pull request closed without merging.** `close-prs.sh` calls `gh pr view` itself to spot a closed pull request, because `supervise.py` runs `bd gate check` without `--escalate`. The help says a `gh:pr` gate is escalated when `state=CLOSED`. If an escalated gate shows up in `bd show`, adding `--escalate` would let `close-prs.sh` drop its own `gh` call. This needs a real GitHub remote and pull request to see what escalation writes.

## Keep

- **`scripts/merge-queue.sh`**, not `bd merge-slot`: "Each rig has one merge slot bead: `<prefix>-merge-slot`". That's one lock for the whole repository. sdlc needs one per branch, so tasks merging into different epic branches don't wait on each other.
- **`tasks.py` `parents_to_close` and the epic close in `close-prs.sh`**, not `bd epic close-eligible`. Tried: close-eligible doesn't close a parent task whose children are all closed, it counts an open `event` bead as unfinished work, and it takes no epic id.
- **Dispatch order in `tasks.py`**, not `bd ready --sort`. Tried: no sort puts tasks of an epic already in progress first. `bd ready` also returns epic and event beads. A small optional change: `--exclude-type epic,event` would replace the filter, with the same number of calls.
- **`dispatch_state` metadata**, not `bd set-state`. `set-state` sets one dimension per call, so `record-task.sh` and `finish-task.sh`, which set it together with another field in one `bd update`, would need two calls (≈0.3 s each). It also can't unset the state, which `resume-reviewed.sh` does. And it stores state as labels.
- **Worker liveness in `workers.py`**:
  - `bd stale` goes by the age of `updated_at`, not whether a process is running.
  - `wt step tether` is experimental and works the other way round: it kills a process when its worktree is removed, while sdlc removes the worktree after the worker ends. It could still guard against someone removing a worktree by hand while its worker runs.
- **`git rebase` in `finish-task.sh`**, not `wt step rebase`. Tried: on a conflict, `wt step rebase` leaves the rebase open and prints no structured list of conflicting files. `finish-task.sh` needs the file list and an aborted rebase to hand the worker a clean instruction.
- **`hooks/worker-guard.sh`** as a Claude Code hook, not a git pre-push hook. It only applies to worker sessions and never interferes with the project's own git hooks.
- **`stats.py`, `logs.py`**, not `bd audit` or `bd history`. Those record bead changes and agent interactions. Cost, turns and duration live in the worker transcripts.
- **`clean.sh` leftover decisions**, not `bd orphans` or `wt step prune`:
  - `bd orphans` finds open beads mentioned in commits.
  - `wt step prune` only removes branches merged into the default branch.
- **`dispatch_*` metadata**, not `wt config state vars`, which is stored under `.git/` of one clone. A task's state has to be readable from any machine that shares the beads database.
- **`verify.sh`** already runs `wt hook pre-merge`, and **`create-task.sh`** already passes its fields straight to `bd create`.
