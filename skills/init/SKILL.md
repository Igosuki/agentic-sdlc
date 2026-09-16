---
name: init
description: Prepare the current project for sdlc. Initializes beads, sets the integration mode and target branch, creates .claude/sdlc.local.md, and ignores local files. Safe to run again. Use in a project before its first design or dispatch, or to change these settings.
argument-hint: "[--integration direct|epic-merge|epic-pr] [--target BRANCH] [--parallel N] [--workflow build|none]"
disable-model-invocation: true
model: sonnet
---

# Init

Arguments: $ARGUMENTS

Current settings:
!`${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh 2>&1 || true`

Current branch:
!`git branch --show-current 2>&1 || true`

## 1. Choose

A setting given in `$ARGUMENTS` is already decided: don't ask about it, pass it through unchanged.

Headless session (no AskUserQuestion): ask nothing, assume nothing. Pass on to `init.sh` in step 3 only the options `$ARGUMENTS` gives. `init.sh` already keeps every saved value and fills in a default for whatever nobody saved — don't add `--integration direct`, `--target <current branch>` or `--workflow none` as if they were the headless defaults; that overwrites a saved setting nobody asked to change.

Interactive session: ask with one AskUserQuestion about each setting `$ARGUMENTS` doesn't give, listing its current value first as the recommended option.
- **Integration mode:**
  - `direct`: tasks merge straight into the target branch
  - `epic-merge`: each epic has its own branch, merged into the target at the end
  - `epic-pr`: like `epic-merge`, but ends with a pull request; it needs a git remote and `gh`
- **Target branch:** offer the current branch too when it differs from the current target.
- **New work through `/sdlc:build`:** yes sets `workflow: build`, so new sessions in this project start new work with `/sdlc:build`.

"No" to build routing passes `--workflow none` only when the current settings show `workflow=build`; otherwise it passes nothing.

## 2. Project checks

Run `print-merge-checks`. From its `candidate` lines, propose the fast checks as pre-merge hooks: type check, lint, unit tests. Don't propose slow end-to-end, deploy or release steps, even if `checks.sh` finds their commands (e.g. from `ci` lines). Skip a check whose name already appears in an `existing pre-merge` line.

Ask with AskUserQuestion (multiSelect) which of the proposed checks to add as pre-merge hooks. If AskUserQuestion isn't available (headless session), skip this step: add none.

## 3. Run

Run `${CLAUDE_PLUGIN_ROOT}/scripts/init.sh` with only the options settled in step 1 — a setting nobody chose to change gets no flag — plus `--parallel` from `$ARGUMENTS` when given, plus `--pre-merge NAME=COMMAND` for each check chosen in step 2, and show its output.

## 4. Commit

`bd init` commits the beads files itself, but not always: check. Run `git status --porcelain -- .gitignore .beads`. If it prints nothing, there's nothing to commit. Otherwise, in an interactive session, ask with AskUserQuestion whether to commit; on yes, run `git add -- .gitignore .beads` then `git commit -m "Ignore sdlc local files" -- .gitignore .beads`. In a headless session, don't commit: say what is left to commit.

`.config/wt.toml` isn't part of this commit; if a pre-merge entry was added, leave it for the user once they've reviewed the commands.

If any pre-merge hooks were added, tell the user: each machine that runs `wt merge` on this project approves these commands once, by running `wt config approvals add` themselves in a terminal (never with `--yes` or `--dangerously-skip-permissions`).

## 5. Next

If `/sdlc:setup` hasn't been run on this machine, suggest it. Then suggest `/sdlc:build <request>` to start work.
