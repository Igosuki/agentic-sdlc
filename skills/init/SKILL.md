---
name: init
description: Prepare the current project for sdlc. Initializes beads, sets the integration mode and target branch, creates .claude/sdlc.local.md, ignores local files, and installs the beads hooks that wake the supervisor. Safe to run again. Use in a project before its first design or dispatch, or to change these settings.
argument-hint: "[--integration direct|epic-merge|epic-pr] [--target BRANCH] [--parallel N] [--workflow build|none]"
disable-model-invocation: true
model: sonnet
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh *), Bash(git branch --show-current)
---

# Init

Arguments: $ARGUMENTS

Current settings:
!`${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh 2>&1 || true`

Current branch:
!`git branch --show-current 2>&1 || true`

## 1. Choose

A setting given in `$ARGUMENTS` is already decided: don't ask about it, pass it through unchanged.

Headless session (no AskUserQuestion): ask nothing, assume nothing. Pass on to `init.sh` in step 2 only the options `$ARGUMENTS` gives. `init.sh` already keeps every saved value and fills in a default for whatever nobody saved — don't add `--integration direct`, `--target <current branch>` or `--workflow none` as if they were the headless defaults; that overwrites a saved setting nobody asked to change.

Interactive session: ask with one AskUserQuestion about each setting `$ARGUMENTS` doesn't give, listing its current value first as the recommended option.
- **Integration mode:**
  - `direct`: tasks merge straight into the target branch
  - `epic-merge`: each epic has its own branch, merged into the target at the end
  - `epic-pr`: like `epic-merge`, but ends with a pull request; it needs a git remote and `gh`
- **Target branch:** offer the current branch too when it differs from the current target.
- **New work through `/sdlc:build`:** yes sets `workflow: build`, so new sessions in this project start new work with `/sdlc:build`.

"No" to build routing passes `--workflow none` only when the current settings show `workflow=build`; otherwise it passes nothing.

## 2. Run

Run `${CLAUDE_SKILL_DIR}/scripts/init.sh` with only the options settled in step 1 — a setting nobody chose to change gets no flag — plus `--parallel` from `$ARGUMENTS` when given, and show its output.

## 3. Commit

`bd init` commits the beads files itself, but not always: check. Run `git status --porcelain -- .gitignore .beads`. If it prints nothing, there's nothing to commit. Otherwise, in an interactive session, ask with AskUserQuestion whether to commit; on yes, run `git add -- .gitignore .beads` then `git commit -m "Ignore sdlc local files" -- .gitignore .beads`. In a headless session, don't commit: say what is left to commit.

## 4. Next

If `/sdlc:setup` hasn't been run on this machine, suggest it. Once the project has build files, suggest `/sdlc:hooks` (optional: project hooks for dependency installs and merge checks). Then suggest `/sdlc:build <request>` to start work.
