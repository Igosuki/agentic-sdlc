---
paths:
  - "skills/**/SKILL.md"
  - "agents/*.md"
---

# Skill and agent prompts

- Skills call scripts through `${CLAUDE_PLUGIN_ROOT}/scripts/<name>`, pre-approved in `allowed-tools`, so the script's source stays out of context. A skill doesn't document the flags of the script it calls.
- Context lines use `!` injection ending in `2>&1 || true`: a failing command otherwise aborts the skill.
- Assume `/sdlc:setup` and `/sdlc:init` have run. No "is beads initialized" check, no status line for it, no "send the user to /sdlc:init and stop". Scripts may check; prompts may not.
- Ask with AskUserQuestion when it is available. Otherwise decide, and record the assumption. Never ask in plain text and stop.
- `model:` — planning skills opus, the rest and the worker sonnet. The supervisor is a script and has no model.
- The description says what the skill does and when to use it; `argument-hint` carries the syntax.
