---
name: recover
description: Pick up a stopped, failed or crashed task. Reads its last comment and a summary of what its worker did, then offers to resume it with new instructions, finish it after a fix made by hand, start it over, or split it. User only.
argument-hint: "<task-id> [instructions]"
disable-model-invocation: true
allowed-tools: Bash(bd *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/logs.py *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/resume-task.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/finish-task.sh *), Bash(${CLAUDE_PLUGIN_ROOT}/scripts/reset-task.sh *)
---

# Recover

Arguments: $ARGUMENTS

The first argument is the task id. The rest, if any, are instructions for a resume.

## 1. What happened

`bd show <task> --json` and `bd comments <task>` for its last comment. `${CLAUDE_PLUGIN_ROOT}/scripts/logs.py <task>` for what the worker did and why it stopped.

## 2. Offer a way forward

Present these with AskUserQuestion, using what step 1 found to say which fits best:
- **Resume**, with the instructions: only works if the task's worktree and its worker's session transcript still exist. Clear `dispatch_state` (`bd update <task> --unset-metadata dispatch_state`), then run `${CLAUDE_PLUGIN_ROOT}/scripts/resume-task.sh <task>`, with `--prompt "<instructions>"` if any were given. If it errors because the worktree or transcript is gone, say so and offer the remaining options instead.
- **Finish**, after a fix made by hand in the task's worktree: clear `dispatch_state` the same way, then run `${CLAUDE_PLUGIN_ROOT}/scripts/finish-task.sh <task>`.
- **Start over**: run `${CLAUDE_PLUGIN_ROOT}/scripts/reset-task.sh <task>`. The next `/sdlc:dispatch` picks the task up from scratch.
- **Split**: hand off to `/sdlc:split <task>`.

If AskUserQuestion isn't available (headless session), don't run anything: report what happened and these four options.
