# Portability: other LLMs, other trackers

Status: hypothesis. Nothing here is in the MVP. This records what it would take to drop two hard dependencies: Claude as the only model, and beads as the only tracker. It also lists cheap seams that keep these options open.

## 1. Any LLM for any agent

### Where Claude is coupled

- **Headless roles** (worker, reviewer, dedup judge) depend on `claude -p` flags:
  - `--agent`, `--session-id`
  - `--output-format json`, which carries `session_id`, `total_cost_usd`, `modelUsage` and `num_turns`
  - `--json-schema`, `--max-budget-usd`, `--disallowedTools`, `--settings` (hooks)
- **Interactive skills** (orchestrate, design, split-plan, dedup) depend on the Claude Code harness: plugins, skills, the Monitor tool, and AskUserQuestion.

### Option A: keep Claude Code, change the endpoint

Point each role at a gateway that speaks the Anthropic `/v1/messages` format, for example a LiteLLM proxy. Recent versions of local servers (Ollama, vLLM) are reported to offer the same format; verify before relying on it. Local Qwen models could then serve some roles.

- **Change:** `run-claude.sh` sets `ANTHROPIC_BASE_URL`, `ANTHROPIC_AUTH_TOKEN` and `--model` per role, taken from config.
- **Unchanged:** skills, subagents, hooks and the denylist all keep working.
- **Cost:** `total_cost_usd` is computed from Claude prices, so it is wrong for other models. Record token counts instead and apply a price table per model (0 for local).
- **Quality:**
  - Smaller models handle Claude Code's large system prompt and tool set poorly. They may cope with small beads and fail on long ones.
  - Structured output needs schema validation, with one retry on invalid JSON.
- **Throughput:** a single local GPU runs jobs one after another, so `max_workers` drops to 1–2.

### Option B: swap the agent CLI per role

Candidates: Codex (`codex exec --json`), Qwen Code (`qwen -p`), Gemini CLI, opencode.

- `run-claude.sh` becomes `launch-agent.sh <role> <bead>`, which dispatches to `adapters/<runtime>.sh`.
- Every adapter takes the same inputs: prompt file, cwd, model, budget, tool policy, output schema.
- Every adapter returns the same JSON: `{session_id, model, tokens_in, tokens_out, cost_usd, turns, is_error, result, structured_output}`.
- Each adapter fills in what its CLI lacks:
  - its own sandbox or approval flags in place of the denylist
  - a wall-clock timeout when there is no budget flag
  - jq schema validation for structured output
- **Hooks do not carry over.** The design already re-checks everything after the fact (verify, scope, review sha, merge preconditions), so the gates still hold. The Stop hook only saves a retry.
- Prompts stay runtime-neutral in `references/prompts/`. `agents/*.md` are thin Claude-specific wrappers.
- **Prior art:** dsifry/metaswarm ships bash adapters for Codex and Gemini (`skills/external-tools/adapters/`).
- **Effort:** roughly 100–200 lines of bash per adapter, plus one e2e scenario each.

### Option C: take the orchestrator off Claude

- The loop (`sdlc run`) is already a script. The branch choice is a config rule.
- Only design and split-plan need a strong interactive model. They could run in another harness that supports the SKILL.md format. The beads plugin already ships a `.codex-plugin/` next to its Claude plugin.

A side benefit of mixing backends: a reviewer running a different model from the worker catches more mistakes.

## 2. A tracker other than beads

### Coupling points

| Where | Beads dependency | Portable replacement |
|---|---|---|
| Scripts | `create --graph`, dependency-aware `ready`, atomic `--claim`, custom statuses, typed metadata | Tracker adapter verbs: `create-graph, ready, get, claim, set-status, set-meta, label, comment, close, link, hold-for-human, release-human` |
| Merge serialization | `bd merge-slot` | `flock` on a file in the git common dir (single host only) |
| Audit | `bd audit record`, Dolt history, comment authors | JSONL in the run dir, plus the tracker's own activity log |
| Memory | `bd remember`, `bd prime` | `.sdlc/memory.md`, or the tracker's equivalent |
| Agents | none: agents only call `sdlc` verbs | nothing to change, because `sdlc` is already the only command surface |

### Gaps in other trackers

- **GitHub Issues:**
  - No computed "ready" list, so the adapter walks dependencies itself.
  - No arbitrary metadata. Store it in a fenced block in the issue body, or in Projects custom fields.
  - Assignment is not atomic, so the adapter needs a local lock.
  - API rate limits bite when many agents are active.
- **Linear, Jira:** statuses and links fit better. Custom metadata is still awkward, and Jira statuses need admin setup.

### Cheaper path: keep beads and sync outward

bd 1.2.2 has `bd github`, `bd gitlab`, `bd jira`, `bd linear`, `bd ado` and `bd notion`. Their sync direction and field coverage are not yet checked; that needs a spike. If they fit, humans see and comment in their usual tool and the plugin stays unchanged.

Abstract the tracker only when there is a concrete need to run without beads.

## 3. Do we need a CLI that reads config?

The official `security-guidance` plugin has no CLI:

- Its hooks call `bash sg-python.sh <script>.py` via `${CLAUDE_PLUGIN_ROOT}`.
- The Python modules share `_base.py` and `extensibility.py`.
- Config comes from environment variables (`SECURITY_REVIEW_MODEL`, `ANTHROPIC_BASE_URL`, …) plus layered files: `~/.claude/<name>`, then `<cwd>/.claude/<name>`, then `<cwd>/.claude/<name>.local.<ext>`.

`sdlc` already follows that pattern: `lib.sh`, plus config layered as defaults, `~/.claude/sdlc.json`, `.claude/sdlc.json`, `.claude/sdlc.local.json`. The `sdlc` dispatcher is the CLI entry point.

A compiled CLI becomes worth it when any of these holds:

- Agents run outside Claude Code: they have no `${CLAUDE_PLUGIN_ROOT}` and need `sdlc` on PATH as a real binary.
- A tracker abstraction is added: adapter dispatch, capability checks, retries.
- Bash stops being comfortable: config merging, schema validation, concurrency and adapters all at once.

## Cheap seams to keep

1. `run-claude.sh` is the only place that starts a model session. Renaming it to `launch-agent.sh` with a `runtime` key per role costs nothing later.
2. Record `tokens_in` and `tokens_out` next to `cost_usd`.
3. Scripts call tracker functions in `lib.sh` (`bd_get`, `bd_meta_set`, …), never raw `bd` scattered everywhere.
4. Agents only ever see `sdlc` verbs.
5. Prompts stay runtime-neutral.
