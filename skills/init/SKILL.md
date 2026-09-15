---
name: init
description: Prepare the current project for sdlc. Initializes beads, sets the integration mode and target branch, creates .claude/sdlc.local.md, and ignores local files. Safe to run again. Use in a project before its first design or dispatch, or to change these settings.
argument-hint: "[--integration direct|epic-merge|epic-pr] [--target BRANCH] [--parallel N] [--workflow build|none]"
model: sonnet
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/init.sh *), Bash(${CLAUDE_SKILL_DIR}/scripts/checks.sh *), Bash(git status *), Bash(git add .gitignore), Bash(git add .config/wt.toml), Bash(git commit *)
---

# Init

Arguments: $ARGUMENTS

Current settings:
!`${CLAUDE_SKILL_DIR}/../dispatch/scripts/settings.sh 2>&1 || true`

## 1. Choose

For the choices the arguments don't settle, ask with one AskUserQuestion:
- **Integration mode:**
  - `direct` (recommended to start): tasks merge straight into the target branch
  - `epic-merge`: each epic has its own branch, merged into the target at the end
  - `epic-pr`: like `epic-merge`, but ends with a pull request; it needs a git remote and `gh`
- **Target branch:** the current branch is recommended.
- **New work through `/sdlc:build`:** yes sets `workflow: build`, so new sessions in this project start new work with `/sdlc:build`.

If AskUserQuestion isn't available (headless session), use the defaults: `direct`, the current branch, and no workflow routing.

## 2. Project checks

Run `${CLAUDE_SKILL_DIR}/scripts/checks.sh`. From its `candidate` lines, propose the fast checks as pre-merge hooks: type check, lint, unit tests. Don't propose slow end-to-end, deploy or release steps, even if `checks.sh` finds their commands (e.g. from `ci` lines). Skip a check whose name already appears in an `existing pre-merge` line.

Ask with AskUserQuestion (multiSelect) which of the proposed checks to add as pre-merge hooks. If AskUserQuestion isn't available (headless session), skip this step: add none.

## 3. Run

Run `${CLAUDE_SKILL_DIR}/scripts/init.sh` with the chosen options, plus `--pre-merge NAME=COMMAND` for each check chosen in step 2, and show its output.

## 4. Commit

`bd init` commits the beads files itself. If `init.sh` added `.gitignore` entries or `.config/wt.toml` pre-merge entries, ask with AskUserQuestion whether to commit them. On yes, run `git add .gitignore` and, if it changed, `git add .config/wt.toml`, then `git commit -m "Ignore sdlc local files"` (or a message covering both). In a headless session, don't commit: say what is left to commit.

If any pre-merge hooks were added, tell the user: each machine that runs `wt merge` on this project approves these commands once, by running `wt config approvals add` themselves in a terminal (never with `--yes` or `--dangerously-skip-permissions`).

## 5. Next

If `/sdlc:setup` hasn't been run on this machine, suggest it. Then suggest `/sdlc:build <request>` to start work.
