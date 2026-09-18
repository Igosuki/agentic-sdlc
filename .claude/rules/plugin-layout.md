# Plugin layout

- A new entry point is `skills/<name>/SKILL.md`. `commands/` is the older flat form; don't add to it.
- Executables live in `scripts/` at the plugin root and are called as `${CLAUDE_PLUGIN_ROOT}/scripts/<name>`. `bin/` is on the Bash PATH but unused here.
- Agents are addressed `sdlc:<name>`. A plugin agent may not declare `hooks`, `mcpServers` or `permissionMode`; worker hooks live in `hooks/hooks.json`, gated on `DISPATCH_TASK`.
- Nothing is named "sdlc" in bead statuses or labels. Runtime metadata keys are prefixed `dispatch_`.
- The layout, the conventions and the test commands are in `docs/development.md`; change it when they change.
