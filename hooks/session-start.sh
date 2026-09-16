#!/usr/bin/env bash
# In a project whose .claude/sdlc.local.md sets "workflow: build", routes new work to sdlc:build.
# A worker session (DISPATCH_TASK set by run-task.sh/resume-task.sh) runs as the sdlc:worker or
# sdlc:integrator agent, whose own system prompt carries the lifecycle and survives compaction.
set -euo pipefail
cat >/dev/null
[[ -z "${DISPATCH_TASK:-}" ]] || exit 0

if [[ "$("${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh" workflow 2>/dev/null)" == build ]]; then
  context="This project uses the sdlc workflow for new work: when the user asks to build, create or change something, start with the sdlc:build skill (design and split in plan mode, then dispatch), unless the user asks to do it another way."
else
  exit 0
fi
jq -cn --arg c "$context" '{hookSpecificOutput: {hookEventName: "SessionStart", additionalContext: $c}}'
