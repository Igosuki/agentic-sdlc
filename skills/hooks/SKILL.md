---
name: hooks
description: Read the project (manifests, lock files, CI, task runners, git hook managers) and suggest optional wt hooks for what sdlc triggers, such as installing dependencies in a new task worktree and running the project's fast checks before a merge, then write the ones you pick to .config/wt.toml. Safe to run again. Use once a project has build files, and again when its toolchain changes.
disable-model-invocation: true
model: sonnet
allowed-tools: Bash(wt hook show)
---

# Hooks

Project hooks:
!`wt hook show 2>&1 || true`

## 1. Look

Read what the project has:
- lock files: which package manager, and its frozen-install command
- manifests and tool config: `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, `deno.json`, gradle/maven files, `mise.toml`, `.tool-versions`
- task runners: Makefile, justfile, Taskfile
- CI: `.github/workflows/*.{yml,yaml}`, `.gitlab-ci.yml`, and the like
- git hook managers: `.husky/`, `lefthook.yml`, `.pre-commit-config.yaml`, and `git config core.hooksPath`

Prefer the project's own commands (its scripts, its targets, what CI runs) over a tool's default command.

## 2. Nothing to check yet

No manifests and no CI: say so, suggest running `/sdlc:hooks` again once the project has a build, and stop.

## 3. Propose

Only suggest hooks that sdlc triggers:
- **pre-start**, when a task's worktree is created: install dependencies from the lock file, generate env files.
- **pre-merge**, before a task merges: the fast checks the project's CI runs (type check, lint, unit tests), never slow end-to-end, deploy or release steps.
- **post-start with pre-remove or post-remove:** only when a worker needs something running, such as a database. post-start starts it, and the remove hook stops it when the finished task's worktree is removed.

Never suggest:
- **pre-commit or post-commit:** they only fire on commits wt makes, and workers commit with git.
- **post-merge:** it runs after every merge an agent makes, and deploy or release steps don't belong there.
- **pre-switch or post-switch:** nothing in sdlc needs them.

The project's own git hooks (husky, lefthook, pre-commit, `.git/hooks`, or whatever `core.hooksPath` points at) stay the project's: workers commit with plain git, so those hooks already run on every worker commit, in every worktree. Don't copy one into a wt hook, don't turn one off, and never suggest `--no-verify` or `--no-hooks`. One interaction is worth pointing out: a git hook that needs installed dependencies (for example husky running `npx lint-staged`) fails in a new worktree unless something installs them first — a pre-start install fixes that, and the user can still decline it.

Skip anything `wt hook show` already lists. When a git hook already runs a check, say so; adding it to pre-merge too is still the user's call, since the git hook runs at commit and pre-merge runs at merge.

## 4. Ask

One AskUserQuestion per proposed hook type, multiSelect. Choosing nothing is a valid answer: that's a normal result, not something to warn about or ask again in this run.

Headless session (AskUserQuestion isn't available): add nothing. Print what would have been suggested.

## 5. Write

Edit `.config/wt.toml` and keep each hook's existing form — a string, a table, or a pipeline. Use a `[[pre-start]]` pipeline only when one step must finish before the next. Run `wt hook show` to confirm the file still parses.

Don't commit `wt.toml`. Tell the user that each machine approves these commands once, by running `wt config approvals add` themselves in a terminal — never with `--yes` or `--dangerously-skip-permissions`.
