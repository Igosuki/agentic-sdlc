# Reader and the user's code tools

Research date: 2026-09-16. Question: is `sdlc:reader` a weak link in planning, and if a repository has code tools set up by the user (CodeGraph, semantic search), does the reader use them or replace them?

## Decided (2026-09-16)

- **`sdlc:reader` is removed.** The planning skills (`design`, `split`, `create-task`) gather information with the skills, agents and MCP tools the session has, found in context or through tool search, and read the repository themselves where nothing fits. Users choose those tools; sdlc doesn't ship its own reader.
- **Tools that read the repository or its beads are local sources** in `design`, so they need no permission. Connectors that reach outside the repository still do.
- **`recover` and `supervisor`** read `scripts/logs.py` output directly.
- Options A and B and the three rules below were not adopted.

## What was checked

- **Tool list:** `agents/reader.md` sets `tools: Read, Grep, Glob, Bash`. The subagents docs say an agent inherits every tool, MCP tools included, only when `tools` is left out. A live run (`claude -p --plugin-dir . --agent sdlc:reader`, asked to list its tools) reported only `Read` and `Bash`: no `mcp__*` tools, and no `Grep` or `Glob` either, since this Claude Code build doesn't have those tools.
- **CLAUDE.md:** the reader loads it (docs: subagents load CLAUDE.md unless `omitClaudeMd: true`). In the same run it quoted the CodeGraph section of `~/.claude/CLAUDE.md`.
- **Other agents:** `worker`, `integrator` and `supervisor` set no `tools`, so they get every MCP tool the user has.
- **Planning skills:** `design`, `split` and `create-task` tell the Opus session "Don't read files, documents or external sources yourself" and send every read, code included, to the reader. The reader's description was narrowed to "documentation" in c50a89a, but the skills still send it code questions.
- **Plugin agent fields:** plugin agents may use `disallowedTools` and `skills`; they may not use `hooks`, `mcpServers` or `permissionMode`.

## Answer

**It doesn't take over everything; it only replaces the user's code tools with grep during planning.** Execution is unaffected: workers keep MCP tools and CLAUDE.md.

During planning:

1. The Opus session is told not to read. `codegraph_explore` returns source code, so a session that follows the skill won't call it itself.
2. The reader can't call MCP tools. Its tool list removes them.
3. The reader does see the CLAUDE.md rule to use CodeGraph first. It could still run the `codegraph explore` CLI through Bash. But its own prompt limits Bash to a list of read-only commands and tells it to search with Grep and Glob. The two sets of instructions pull in different directions, and which one Haiku follows isn't predictable.

Semantic search that exists only as an MCP server is unreachable from planning. CodeGraph is reachable only through its CLI, and only if Haiku happens to pick it.

## Where the reader is weak

- **Missed results are invisible.** Opus plans only from what comes back. When a grep misses a synonym, a generated name or a dynamic-dispatch call, the reader honestly answers "no prior art for X", and Opus designs a duplicate. The prompt guards well against invented answers, but it can't catch a search that misses. This is the gap that CodeGraph and semantic search close, and they are the tools the reader can't use.
- **"Read-only" is already only a prompt rule.** Bash can write. The tool list keeps out Edit and Write, but it doesn't make the agent read-only.
- **The prompt names tools that don't exist.** "`Grep` and `Glob` to find the few places": in this build the reader falls back to `grep` through Bash.
- **The description doesn't match how the skills use it.** The description says "documentation"; the skills send it code, contracts and data shapes.

## Options

**A. Keep the tool list and loosen the prompt.** Let Bash run any read-only command, and tell the reader to search first with whatever code tools the repository's instructions name. This reaches CLI tools such as `codegraph explore`, but not MCP-only ones.

**B. Switch to a block list.** Replace `tools:` with `disallowedTools: Edit, Write, NotebookEdit, Agent`, and change "How to read" to: use the code-search tools that CLAUDE.md or the repository names, then fall back to grep. The reader then inherits every MCP tool, including write-capable ones. On this machine that means WebStorm `apply_patch`, `rename_refactoring` and `execute_terminal_command`, and Gmail `send_message`. The prompt and permission settings already stand between Bash and a write, so this doesn't weaken a guarantee that exists today. It does add more obvious ways to write.

**Either way:**
- When the reader reports something missing, it should say how it searched (terms, tools). Opus can then judge whether the miss is real or ask again.
- Make the description match what the skills send it: documentation, code, logs, beads.

**Recommendation: B.** The reader's weakest point is recall, and the user's code tools fix exactly that. A block list is the only way a plugin agent can pick up MCP servers it doesn't know about.

## Scrapping the reader

Idea: remove `sdlc:reader`. The planning skills tell Opus to gather information with whatever agents, skills and MCP servers are installed.

### What was checked

A live run through the Agent tool (`claude -p --plugin-dir .`) with two subagents, each asked for its tools, whether it sees the CodeGraph section, and its model:

| | MCP tools | Sees CLAUDE.md | Model |
|---|---|---|---|
| `Explore` (built-in, `model: haiku` passed) | all of them: codegraph, context7 and WebStorm search, but also Gmail `send_message`, Drive `trash_file` and WebStorm `apply_patch` | no | Haiku 4.5 |
| `sdlc:reader` | none (`Read`, `Bash`) | yes | Haiku 4.5 |

Neither agent gets both. Explore has the tools but not the instruction to use CodeGraph first. The reader has the instruction but not the tools. Explore being "read-only" only means it lacks Edit and Write; its MCP tools can still write.

### Three rules that must survive

Without these, scrapping the reader brings back the costs it exists to avoid:

1. **Reads happen in a subagent.** A skill that Opus invokes runs in the Opus session, and an MCP tool that Opus calls puts its result in the Opus context: `codegraph_explore` returns source code. "Use skills and MCP servers" has to mean "tell a subagent to use them".
2. **Every read call names a cheap model.** An agent with no `model` in its frontmatter, such as `general-purpose`, runs on the parent's model: Opus. The Agent tool's `model` parameter overrides it.
3. **The return rules live in the skill, not in an agent.** These are the reader prompt's rules: verbatim paths and contracts, locations, contradictions, what couldn't be found and how it was searched, and treating content as data rather than instructions. The skills already carry part of this ("Tell it exactly what to return…"). One shared reference file, like `skills/split/references/task-rules.md`, would carry all of it.

### Gains and losses

- **Gains:** the user's code tools, docs servers and installed specialist agents get used. The plugin has one fewer component, which fits sdlc working with what is installed rather than shipping its own set.
- **Answers vary:** Opus picks an agent for each read, and each installed agent's own prompt can work against the return rules. Explore "reads excerpts" and "locates code"; compressing agents (caveman) paraphrase, which breaks "verbatim".
- **Log reading moves:** how to read a worker log (`scripts/logs.py`) moves into `recover` and `supervisor`. `supervisor` already has it.
- **Nothing blocks writes:** a read-only boundary is gone unless the skill limits reads to read-only agents, and MCP write tools get past that limit anyway.
- **An earlier rule comes back:** this is close to the rule the reader replaced on 2026-09-16 ("prefer an installed bulk-reader, else Explore on haiku"). Whatever made that rule fall short applies again unless rule 3 is followed.

### Recommendation

To get the user's tools into planning, option B does it with less: a block list gives the reader every MCP tool and the Skill tool, and unlike Explore it keeps CLAUDE.md. Scrapping the reader adds only one thing on top: Opus choosing installed specialist agents. That is worth it only if some sources need an agent a generic reader can't stand in for.

## Open

- **Hooks inside subagents:** the docs don't say whether a user's `PreToolUse` hooks fire for a subagent's tool calls. If they do, the RTK hook compresses `git diff` and `git show` output, and the reader's "verbatim" promise fails for diffs. This hasn't been tested.
- **Self-reported tool lists:** the tool lists come from Haiku listing its own tools, through both `claude --agent` and the Agent tool, and the two paths agree.
