# Plan: `/sdlc:hooks`, project hooks from instructions

Replace `skills/init/scripts/print-merge-checks.sh` and `init.sh --pre-merge` with a skill of its own that reads the project and suggests `wt` hooks. `/sdlc:init` stops handling checks.

## Why

- **The scan can't cover every project.** It only finds `package.json` scripts named `test`, `lint`, `typecheck`, `check` or `format:check`. It greps `pyproject.toml` for the word "pytest", always suggests clippy for Rust, reads only `.yml` workflows, and misses bun, uv, poetry, nx, turbo, mise, tox, nox, gradle, deno, and the git hook managers. The model already judges the `ci` lines, so the script collects data for a decision the model makes anyway.
- **Only one of wt's three hook formats works.** wt accepts a string (`pre-merge = "just check"`), a table (`[pre-merge]`) or a pipeline (`[[pre-merge]]`). Both scripts only understand the table. With the string form, `init.sh` appends a second `[pre-merge]`, and the TOML becomes invalid.
- **Init can run before the project has anything to check.** Hooks need rerunning whenever the toolchain changes. Rerunning `/sdlc:init` re-asks the integration, target and workflow questions.

## Rules

1. **Hooks are optional.** sdlc works with no `.config/wt.toml`: `wt hook pre-merge` prints "No pre-merge hooks configured" and exits 0, and so does `wt merge` (checked on wt 0.77). When the user picks no hooks, that's a normal result: no warning, and no asking again in the same run.
2. **The project's own git hooks stay the project's.** Workers commit with plain git, so husky, lefthook, pre-commit and `.git/hooks` already run on every worker commit, in every worktree (these hooks live in the shared git dir or in `core.hooksPath`). The skill doesn't copy them into wt hooks, doesn't turn them off, and never suggests `--no-verify` or `--no-hooks`. It does point out one interaction: a git hook that needs installed dependencies (e.g. husky running `npx lint-staged`) fails in a new worktree unless something installs them. A pre-start install fixes that, and the user can still decline it.
3. **Suggest only hooks that sdlc triggers.**

   | sdlc runs | Hooks that fire | Suggest |
   |---|---|---|
   | `run-task.sh`: `wt switch --create` | pre-start, post-start, pre-switch, post-switch | **pre-start**: install dependencies from the lock file, generate env files |
   | `finish-task.sh`: `wt merge --no-squash --stage none`, `wt hook pre-merge` | pre-merge, post-merge | **pre-merge**: the fast checks the project's CI runs (type check, lint, unit tests) |
   | `record-task.sh`: `wt remove` | pre-remove, post-remove | Only to stop something that post-start started |

   Never suggest:
   - **pre-commit or post-commit:** they only fire on commits wt makes, and workers commit with git.
   - **post-merge:** it runs after every merge an agent makes. Deploy and release steps don't belong there.
   - **pre-switch or post-switch:** nothing in sdlc needs them.
4. **Headless:** add nothing. Print what would have been suggested.

## The skill: `skills/hooks/SKILL.md`

Frontmatter: `disable-model-invocation: true`, `model: sonnet`. Context injected with `!`: `wt hook show 2>&1`.

1. **Look.** Read what the project has:
   - lock files: which package manager, and its frozen-install command
   - manifests and tool config: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `deno.json`, gradle/maven files, `mise.toml`, `.tool-versions`
   - task runners: Makefile, justfile, Taskfile
   - CI: `.github/workflows/*.{yml,yaml}`, `.gitlab-ci.yml`, and the like
   - git hook managers: `.husky/`, `lefthook.yml`, `.pre-commit-config.yaml`, and `git config core.hooksPath`

   Prefer the project's own commands (its scripts, its targets, what CI runs) over a tool's default command.
2. **Nothing to check yet** (no manifests, no CI): say so, suggest running `/sdlc:hooks` again once the project has a build, and stop.
3. **Propose.** Group the suggestions by hook type, following rule 3. Skip anything `wt hook show` already lists. When a git hook already runs a check, say so. Adding the same check to pre-merge is still the user's call: the git hook runs at commit, pre-merge runs at merge.
4. **Ask.** One AskUserQuestion per proposed hook type, multiSelect. Choosing nothing is a valid answer.
5. **Write.** Edit `.config/wt.toml` and keep each hook's existing format. Use a `[[pre-start]]` pipeline only when one step must finish before the next. Run `wt hook show` to confirm the file still parses. Don't commit `wt.toml`. Tell the user that each machine approves these commands once, with `wt config approvals add`, run by a person in a terminal (never `--yes`).

## Changes elsewhere

- **`skills/init/`:**
  - Delete `scripts/print-merge-checks.sh`, step 2 of `SKILL.md`, and `init.sh`'s `--pre-merge` option (usage step 5 and the awk block).
  - Step 5 (Next) mentions `/sdlc:hooks` as optional, for once the project has build files.
  - Update the description.
- **`scripts/run-task.sh`:** when a project hook isn't approved, `wt switch --create` exits 1 with "Cannot prompt for approval in non-interactive environment" and creates no worktree (checked on wt 0.77). The supervisor already handles a failed start: it undoes the claim, adds a "not started" comment and wakes the session. But the reason it shows is the last line of stderr, and here that's wt's hint to add `--yes`. Detect the approval error the way `finish-task.sh`'s `needs_approval` does, and fail with "the project's hooks aren't approved on this machine; a person runs wt config approvals add in <main checkout>".
- **Docs:**
  - `docs/configuration.md`: rename "Project checks" to "Project hooks" and describe `/sdlc:hooks`.
  - `docs/workflow.md`: update "Project checks"; it still mentions a `checks.sh` that doesn't exist.
  - `README.md`: in the commands table, add `/sdlc:hooks` and drop checks from the `/sdlc:init` row.
- **Tests:**
  - No test covers `print-merge-checks.sh` or `--pre-merge`, so nothing to delete.
  - `tests/wild/*.sh` call `init.sh` without `--pre-merge`, so they're unaffected.
  - Add a `run-task.sh` test: an unapproved pre-start hook gives the approval message and leaves the task open.
