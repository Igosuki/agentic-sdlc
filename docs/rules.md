# Rule files for this repo

Status: built, in `.claude/rules/`. This records why those files exist, what was left out, and what a rule can't do.

## What a rule is

Verified 2026-09-18 against code.claude.com/docs/en/memory:

- Rule files are markdown in `.claude/rules/` (project, committed, shared) or `~/.claude/rules/` (personal, every project). Discovered recursively, one topic per file.
- A rule with no frontmatter loads at launch, with the same priority as `.claude/CLAUDE.md`.
- A rule with `paths:` globs loads when Claude **reads** a file matching the pattern, and reloads after a compaction the next time one matches.
- User rules load before project rules, so a project rule wins.
- **A plugin cannot ship rules.** The plugin components are skills, commands, agents, workflows, hooks, output-styles, themes, monitors, `bin/`, `.mcp.json`, `.lsp.json`. Rules are a repo feature, so everything here is about *developing* this plugin, not about what it gives its users.

## Where this repo stands

- There is no `CLAUDE.md` and `.claude/` is empty. The conventions live in `docs/development.md`, which nothing loads, and in machine-local auto-memory, which is not shared and whose topic files are only read on demand. A rule file is the first place a convention is both committed and in context.
- The SessionStart hook already injects `bd prime` (~13.7 KB). The always-loaded budget is spent; keep the unconditional rules to a few lines each.
- `.claude/rules/` is committed, so every dispatch worktree under `.worktrees/` carries it: this repo's own workers read the same rules.

## The files

Always loaded, 12 lines in total:

| File | Holds | Why a rule |
|---|---|---|
| `plugin-layout.md` | where a component goes, how it is addressed, the naming ban | asked on nearly every change, and wrong defaults (`commands/`, `bin/`) are plausible |
| `architecture.md` | harness-neutral dispatch, Claude features as extras | a constraint a reader cannot see in the code |
| `scope.md` | build what this stage uses | applies to every plan, not to one directory |

Path-scoped, loaded when Claude opens the files they cover:

| File | `paths:` | Holds |
|---|---|---|
| `skills.md` | `skills/**/SKILL.md`, `agents/*.md` | the prompt contract: script calls, `!` injection, no setup checks, headless branch, models |
| `scripts.md` | `scripts/**`, `skills/**/scripts/**` | bash vs python, the stdin rule, usage and exit codes, one brain many arms |
| `tests.md` | `tests/**/*.py` | real `bd`/git/`wt`, no model in `pytest tests`, what a new script or skill owes |
| `docs.md` | `docs/**/*.md`, `README.md` | hypotheses vs built, prose discipline, keep `development.md` current |

## Not worth a rule

- **Beads usage.** `bd prime` already injects the workflow, the memories and the CLI shape at SessionStart. A rule would pay for it twice.
- **Comments and docstrings.** `~/.claude/DOCSTRINGS.md` covers them for every project.
- **Install and requirements.** The README is read when it is needed.

## Caveats

- A rule is context, not enforcement. What must hold whatever the model decides stays in `hooks/` — that is what `worker-guard.sh` is for.
- Path-scoped rules trigger on reads, not on writes. Creating a brand-new `skills/<name>/SKILL.md` may not load `skills.md`; it loads once a sibling skill has been read, which is the usual order anyway. If that misses too often, move the two lines that matter most into `plugin-layout.md`.
- `paths:` is the documented field. anthropics/claude-code#17204 reports `globs:` matching where `paths:` doesn't in some setups, and path-scoped rules under `~/.claude/rules/` being silently ignored. Keeping these at project level avoids both; `/context` and the `InstructionsLoaded` hook show what actually loaded.
- Seven files that each grow become the large CLAUDE.md the split was meant to avoid. Each file holds the handful of facts that get re-explained, and nothing derivable from the code.

## Rules or a CLAUDE.md

There is no `CLAUDE.md`. The three unconditional rules are what one would have held; the four path-scoped ones cost nothing until Claude opens a skill, a script, a test or a doc.
