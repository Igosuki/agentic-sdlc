---
name: review
description: Review a task, parent task, epic or pull request against its acceptance criteria. Summarizes the diff, reports bugs, unmet acceptance, security issues, changes outside the scope and missing tests for new behaviour, then, while a human review gate waits, asks a person for a verdict and resolves it. Argument is a task id, an epic id, or a pull request number or URL. Use when asked to review a task, an epic or a pull request, to resolve a review gate, or when `review=agent` needs a headless verdict.
argument-hint: "<task-id|epic-id|pr>"
allowed-tools: Bash(bd *), Bash(git *), Bash(gh *)
---

# Review

Argument: $ARGUMENTS

## Criteria

Report only problems that matter: bugs, acceptance not met, security issues, changes outside the scope, missing tests for new behaviour. Don't report style preferences or problems that were already there. Approve when nothing should block merging.

## 1. Find the level

- A number, or a URL containing `/pull/`: pull request level.
- Otherwise, `bd show <id> --json`: `issue_type: epic` is epic level; a task with children (`bd list --parent <id> --all --limit 0 --json`) is parent task level; anything else is task level.

## 2. Task

Diff: `git diff <metadata.dispatch_base>...<metadata.dispatch_branch>`, from `bd show <id> --json`. Run it in the task's worktree — `finish-task.sh` already starts you there; otherwise find it with `wt list --format json` and the branch.
Reviewed against: the task's `description`, `acceptance_criteria`, `metadata.scope` and `metadata.verify`.

Read the diff and whatever code you need to judge it against the criteria above and the task's acceptance, scope and verify command.

## 3. Parent task

Read-only: children merge on their own, so there's no branch to gate.

Diff: the combined commits of its children — `bd list --parent <id> --all --limit 0 --json` for the children, then each closed child's merge commit on the base it merged into.
Reviewed against: the parent's `acceptance_criteria`, checking that nothing fell between the children.

## 4. Epic

Diff: `git diff <target>...<epic-branch>`.
Reviewed against: the epic's `description` and `acceptance_criteria`.

Runs before integration, from `metadata.review` on the epic (agent or human), applied by the integration task's `finish-task.sh` to the epic diff.

## 5. Pull request

Diff: the pull request's diff (`gh pr diff <pr>`) and its review comments (`gh pr view <pr> --json comments,reviews`).
Reviewed against: the epic.

Either post a review with `gh pr review <pr> --approve|--request-changes --body "..."`, or, if the pull request already carries reviewer comments, read them and turn them into `bd comments add` on the relevant task instead of reviewing it yourself.

## 6. Verdict

**A person, while a human review gate waits** (`bd show <id> --json` has `metadata.dispatch_review_gate`, and that gate is open): use AskUserQuestion.
1. Summarize the diff against the acceptance.
2. Show the verify command's result and any earlier agent findings: `metadata.dispatch_review*` and `bd comments <id>`.
3. Ask for the verdict:
   - **approve:** `bd gate resolve <gate>`
   - **request changes:** ask what to change, `bd comments add <id> "<the changes>"`, then `bd gate resolve <gate>`

   `resume-reviewed.sh` resumes the worker once the gate resolves.

**Otherwise** (no gate — `review=agent`'s headless run, a parent task, or AskUserQuestion isn't available): state your verdict as your final answer — approve or request changes, a short summary, and any findings (file, line, severity, problem, fix). Don't touch `bd`; the caller records the verdict.
