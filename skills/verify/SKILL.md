---
name: verify
description: Run the checks that finishing a task, parent task or epic would run, on demand. On a failure, reads the output and the commits since the failing task merged, and says which change broke which check. Argument is a task, parent task or epic id. Use to check work before it's done, after a fix, while reviewing, or to see whether an earlier task's check still passes.
argument-hint: "<task-id|parent-id|epic-id>"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/verify.sh *), Bash(bd *), Bash(git *)
---

# Verify

Argument: $ARGUMENTS

Run:
!`${CLAUDE_PLUGIN_ROOT}/scripts/verify.sh $ARGUMENTS 2>&1 || true`

If it passed, show the output above and stop.

If a check failed, find what broke it:
1. From the output, take the id of the task whose check failed (or, for the pre-merge checks, the task, parent or epic given as `$ARGUMENTS`).
2. `bd show <that id> --json` for `metadata.dispatch_base`, `metadata.dispatch_branch` and `closed_at`.
3. **If it's already closed** (an earlier task's check, broken by work that landed after it): `git log --since=<closed_at> <base>` for the commits that merged into `<base>` since, in the worktree the check ran in.
4. **If it's still open** (its own change broke its own check): `git diff <base>...<branch>` in its worktree, since nothing else has landed on top of it yet.
5. Read those commits or that diff against the failing check's output, and say which change broke which check.
