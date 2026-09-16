# Harnesses

sdlc runs its planning skills, supervisor and workers on Claude Code. Most of the plugin doesn't depend on that: the task graph, work order, merge queues, verification and audit trail are beads, git, worktrunk and bash. This page lists what does depend on Claude Code, and how Codex CLI, OpenCode and Ollama could take its place.

The facts about other harnesses below come from their documentation and source code as of September 2026. Points marked *unconfirmed* weren't found in official documentation.

## What is specific to Claude Code

| Seam | Where | What it relies on |
|---|---|---|
| Start a worker | `run-task.sh` calls `start-worker.sh` | `claude -p --session-id <uuid> --agent sdlc:worker\|sdlc:integrator --permission-mode auto --output-format stream-json --verbose --forward-subagent-text [--model] [--effort] --plugin-dir` |
| Resume a worker | `resume-task.sh` calls `start-worker.sh --resume` | `claude -p --resume <uuid>` in the same worktree |
| Know it is alive | `workers.py`, `watch.py`, `finish-task.sh` | `pgrep` on the session id in the command line |
| Read the outcome | `record-task.sh`, `logs.py` | stream-json lines: `result` (`total_cost_usd`, `num_turns`, `is_error`, `modelUsage`), `assistant` and `user` messages, `Agent` tool calls |
| Keep the worker on track | `hooks/` | SessionStart `additionalContext`, PreToolUse `permissionDecision: deny`, Stop `decision: block` |
| Skills | `skills/*/SKILL.md` | Claude Code skill frontmatter: `model`, `allowed-tools`, `` !`command` `` injection, `${CLAUDE_SKILL_DIR}` |
| Supervisor events | `skills/dispatch` | the Monitor tool running `watch.py` |

A second harness needs a way to do each of these. Starting, resuming and reading the outcome are the core; hooks and skills make it pleasant.

## OpenAI Codex CLI

| Seam | Codex equivalent |
|---|---|
| Start | `codex exec -m <model> -C <worktree> "<prompt>"` |
| Session id | reported as `thread_id` in the first JSON event (`thread.started`); it can't be chosen in advance, so it is recorded after the start |
| Resume | `codex exec resume <SESSION_ID>` |
| Output | `--json`: JSONL events (`thread.started`, `item.*`, `turn.completed` with `usage`, `turn.failed`). Tokens only, with no dollar cost, so cost would come from a price table |
| Unattended runs | `sandbox_mode` (`workspace-write`) combined with `approval_policy` in `config.toml`; `--dangerously-bypass-approvals-and-sandbox` also exists, and removes the sandbox |
| Hooks | SessionStart, PreToolUse, PostToolUse, Stop, SubagentStart, SubagentStop and more, in a `hooks.json` shaped like Claude Code's |
| Agents and skills | `AGENTS.md` instructions, a `spawn_agent` tool, `SKILL.md` skills under `~/.codex/skills` |
| Local models | `codex exec --oss --local-provider ollama -m <model>` |

Codex has an equivalent for every seam. The main differences are the session id read after the start, and cost computed from tokens.

## OpenCode

| Seam | OpenCode equivalent |
|---|---|
| Start | `opencode run --dir <worktree> -m <provider/model> [--agent <name>] "<prompt>"` |
| Resume | `opencode run --session <id> "<prompt>"` (`--continue` for the latest) |
| Output | `--format json`: JSONL events. A `step_finish` event carrying `cost` and `tokens` is *unconfirmed* (community documentation only); `opencode export <id>` dumps a session |
| Unattended runs | `--auto` approves what isn't explicitly denied; `permission` rules in `opencode.json`, per tool or agent, for example denying `git push *` |
| Hooks | plugins in `.opencode/plugins/*.ts`: `tool.execute.before` and `after`, `session.created`, `session.idle`, `session.compacted`, and more |
| Agents and skills | agent files in `.opencode/agent/*.md`, with `mode: subagent`; `AGENTS.md`; native `SKILL.md` skills; custom commands in `opencode.json` |
| Local models | an `@ai-sdk/openai-compatible` provider with `baseURL: http://localhost:11434/v1`, or `ollama launch opencode` |

With OpenCode, PreToolUse and Stop would be written as TypeScript plugins rather than shell hooks, and permissions can take over part of the PreToolUse guard.

## Ollama

Ollama is a model server, not an agent harness. It gives local, or Ollama cloud, models to the harnesses above:
- **Claude Code** (Ollama 0.14 and later exposes an Anthropic-compatible API):
  ```bash
  export ANTHROPIC_BASE_URL=http://localhost:11434
  export ANTHROPIC_AUTH_TOKEN=ollama
  claude --model gpt-oss:20b
  ```
  Whether every Claude Code feature sdlc relies on (tool use, subagents, prompt caching) works this way is *unconfirmed*.
- **Codex:** `--oss --local-provider ollama`.
- **OpenCode:** the OpenAI-compatible provider shown above.
- **`ollama launch claude|codex|opencode`** (Ollama 0.15 and later) configures each one.

sdlc can already run workers on Ollama through Claude Code: set those variables in the environment of the machine that dispatches. Cost would read as 0, and the model has to handle tool use and long contexts; Ollama recommends a context of 32k or more.

## What a harness setting would look like

A first step, not built yet (see the [roadmap](roadmap.md)):
- a `harness` setting, `claude` by default, or `codex` or `opencode`
- each start, resume and read-outcome step moves into a small adapter script per harness under `skills/dispatch/harnesses/<name>/`, with `start.sh`, `resume.sh`, `result.sh` and `alive.sh`
- `record-task.sh` and `logs.py` read a common summary that the adapters produce, instead of Claude's stream-json directly
- hooks are ported per harness: shell hooks for Codex, a TypeScript plugin for OpenCode

The planning skills and the supervisor would stay on Claude Code at first. Workers are where cheaper or local models pay off most.

See also [hypotheses/portability.md](hypotheses/portability.md) for other LLM backends and other trackers.
