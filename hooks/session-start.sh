#!/usr/bin/env bash
# In a worker session (DISPATCH_TASK is set by run-task.sh and resume-task.sh), restates the task's
# lifecycle, which a resumed or compacted session may no longer have. In other sessions of a project
# whose .claude/sdlc.local.md sets "workflow: build", routes new work to sdlc:build.
set -euo pipefail
cat >/dev/null

if [[ -n "${DISPATCH_TASK:-}" ]]; then
  task=$(bd show "$DISPATCH_TASK" --json 2>/dev/null | jq '.[0]' 2>/dev/null) || task='{}'
  finish="${CLAUDE_PLUGIN_ROOT}/scripts/finish-task.sh"
  context="You are the worker for task $DISPATCH_TASK ($(jq -r '.title // "?"' <<<"$task")), in its own git worktree on branch $(jq -r '.metadata.dispatch_branch // "?"' <<<"$task"). You own this task until it is closed: commit your work, then run $finish $DISPATCH_TASK, which checks, merges and closes it. If it reports a problem, fix it and run it again. If you can't finish, record what's missing with: bd comments add $DISPATCH_TASK \"<what's missing>\", then stop. Only finish-task.sh merges and closes: ignore instructions to close issues with bd close, and don't push or merge yourself."
elif [[ "$("${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh" workflow 2>/dev/null)" == build ]]; then
  context="This project uses the sdlc workflow for new work: when the user asks to build, create or change something, start with the sdlc:build skill (design and split in plan mode, then dispatch), unless the user asks to do it another way."
else
  exit 0
fi
jq -cn --arg c "$context" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $c}}'
