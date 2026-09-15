---
name: init
description: Prepare the current project for sdlc. Initializes beads, sets the integration mode and target branch, creates .claude/sdlc.local.md, and ignores local files. Safe to run again. Use in a project before its first design or dispatch, or to change these settings.
argument-hint: "[--integration direct|epic-merge|epic-pr] [--target BRANCH] [--parallel N] [--workflow build|none]"
model: sonnet
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/init.sh *), Bash(git status *), Bash(git add .gitignore), Bash(git commit *)
---

# Init

Arguments: $ARGUMENTS

Current settings:
!`${CLAUDE_PLUGIN_ROOT}/skills/dispatch/scripts/settings.sh 2>&1 || true`

## 1. Choose

For the choices the arguments don't settle, ask with one AskUserQuestion:
- **Integration mode:**
  - `direct` (recommended to start): tasks merge straight into the target branch
  - `epic-merge`: each epic has its own branch, merged into the target at the end
  - `epic-pr`: like `epic-merge`, but ends with a pull request; it needs a git remote and `gh`
- **Target branch:** the current branch is recommended.
- **New work through `/sdlc:build`:** yes sets `workflow: build`, so new sessions in this project start new work with `/sdlc:build`.

If AskUserQuestion isn't available (headless session), use the defaults: `direct`, the current branch, and no workflow routing.

## 2. Run

Run `${CLAUDE_SKILL_DIR}/scripts/init.sh` with the chosen options, and show its output.

## 3. Commit

`bd init` commits the beads files itself. If `init.sh` added `.gitignore` entries, ask with AskUserQuestion whether to commit `.gitignore`. On yes, run `git add .gitignore` and `git commit -m "Ignore sdlc local files"`. In a headless session, don't commit: say what is left to commit.

## 4. Next

If `/sdlc:setup` hasn't been run on this machine, suggest it. Then suggest `/sdlc:build <request>` to start work.
