---
name: clean
description: Lists worktrees, branches and merge queues left behind by closed, reset or crashed tasks, and removes them once you approve. Use to reclaim worktrees and unstick a merge queue after tasks close, get reset, or a worker crashes mid-merge.
disable-model-invocation: true
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/clean.sh *)
---

# Clean

!`${CLAUDE_PLUGIN_ROOT}/scripts/clean.sh 2>&1 || true`

Show the list above to the user unchanged, in a code block. If it's empty, say there's nothing to clean and stop.

If you can ask the user (interactive session): ask with AskUserQuestion whether to remove everything listed. On yes, run `${CLAUDE_PLUGIN_ROOT}/scripts/clean.sh --apply` and show its output.

If you cannot ask (headless session): list only, and say that `--apply` is available. Don't run it.
