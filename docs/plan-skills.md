# Plan: skills, agents and hooks

## What the docs and Anthropic's plugins say

- **Commands and skills are the same thing.** Claude Code 2.1.3: "Merged slash commands and skills, simplifying the mental model with no change in behavior." The plugins page describes `commands/` as "Skills as flat Markdown files. Use `skills/` for new plugins" (code.claude.com/docs/en/plugins). Only skills get a directory for supporting files and `${CLAUDE_SKILL_DIR}`.
- **Who can start a skill is set in frontmatter, not by the directory it's in.** "By default, both you and Claude can invoke any skill. `disable-model-invocation: true` means only you can invoke the skill. `user-invocable: false` means only Claude can invoke the skill." A skill with `disable-model-invocation` also keeps its description out of context: "Use `disable-model-invocation: true` for skills with side effects. This saves context and ensures only you trigger them" (features-overview).
- **Hooks are for rules that must hold every time.** "Put guardrails in hooks … If a rule must hold every time, make it a hook rather than a prompt instruction." Anthropic's plugins use hooks for:
  - guards: hookify and security-guidance, on PreToolUse and PostToolUse
  - loops: ralph-loop, on Stop
  - injected instructions: the output-style plugins, on SessionStart

  None of them uses a hook to start a workflow.
- **Subagents** are for "verbose output you don't need in your main context", tool restrictions, and self-contained work that returns a summary. A plugin agent can't declare `hooks`, `mcpServers` or `permissionMode`.
- **In practice:**
  - The older plugins (feature-dev, code-review, commit-commands) still keep their entry points in `commands/`, because they predate the merge.
  - The newer claude-security uses a skill with `disable-model-invocation: true` as its entry point.
  - Reference knowledge is always a skill: plugin-dev, frontend-design, hookify's writing-rules.

So there is no separate "command" type anymore. For each piece, what's left to decide is whether it's a skill both you and Claude can start, a skill only you can start, an agent, a hook or a script.

## When a step gets its own skill

A step gets a skill when at least one of these holds:
1. **A person acts there.** Something in the lifecycle waits on a decision or a command typed by hand.
2. **The same procedure is written in more than one place.** One skill (for judgment) or one script (for fixed steps) replaces the copies.
3. **It needs judgment and has more than one caller**, for example `finish-task.sh` and a person, or several levels such as task and epic.

Fixed steps with a single caller stay scripts: rebase, merge queue, `record-task.sh`, `dispatch-next.sh`, `run-task.sh`, `start-worker.sh`. The worker hooks exist precisely so a model can't do these another way.

A skill that another skill starts through the Skill tool must stay startable by Claude, since `disable-model-invocation` blocks that too.

## Components

`commands/` goes away. Every entry point becomes `skills/<name>/SKILL.md`.

| Component | Today | Should be | Started by | Why |
|---|---|---|---|---|
| design | skill | skill | user or Claude | Claude should pick it up when you describe new work. Its only side effect is editing existing docs, and in build that happens after the plan is approved. |
| split | skill | skill | user or Claude | build starts it. It asks for approval before anything goes further. |
| build | command | skill | user or Claude | The SessionStart hook sends new work here. Plan mode and split's approval guard its side effects. |
| dispatch | command | skill | user or Claude | build starts it. Its own confirmation is the guard, skipped only after build's plan covered it. |
| create-task | command | skill | user or Claude | "Add a task for X" should work in plain words. It runs on Sonnet, so it's cheaper than split for one task. |
| review | — | new skill | user or Claude | A person reviews while a gate waits; `finish-task.sh` runs it headless for `review=agent`. |
| verify | — | new skill | user or Claude | Checks on demand at task, parent and epic level. It explains failures. |
| recover | — | new skill, user only | user | Resume, finish after a fix by hand, or start over a stopped, failed or crashed task. |
| stop | — | new skill, user only | user | Ends running workers, which today nothing can stop. |
| clean | — | new skill, user only | user | Removes leftover worktrees, branches and merge queues. |
| init | command | skill, user only | user | Runs once per project, with side effects: `bd init`, config, a commit. Every other skill assumes it has run. |
| setup | command | skill, user only | user | Runs once per machine and installs tools. A different job from init. |
| status, stats, logs | command | skill, user only | user | Read-only views over scripts. User-only keeps their descriptions out of every session. dispatch and the supervisor run the scripts they need themselves. |
| worker, integrator, supervisor | agent | agent, unchanged | skills, dispatch, `claude --agent` | Isolated context, their own model and tools. The worker's prompt must survive compaction, which only an agent's system prompt does. |
| `session-start.sh` (SessionStart) | hook | hook, unchanged | Claude Code | Injects the one opt-in project rule "start new work with `sdlc:build`". Costs no tokens when the project hasn't opted in, and runs again after compaction. |
| `worker-guard.sh` (PreToolUse on Bash) | hook | hook, unchanged | Claude Code | A guardrail: workers must not close, merge or push outside `finish-task.sh`. Plugin agents can't declare hooks, so it lives in `hooks.json`, gated on `DISPATCH_TASK`. |
| `worker-stop.sh` (Stop) | hook | hook, unchanged | Claude Code | Keeps a worker from ending with its task still claimed and no comment. Same pattern as ralph-loop's Stop hook. |

No new hooks, and no skills that only Claude can start.

## design without a design document

The design lives in the session: the conversation, or the plan file in plan mode. design edits existing docs only where the change makes them wrong or incomplete (a README, an ADR, API docs, an earlier design). It writes a new document only when the user asks for one.

- **skills/design:**
  - "Write the document" becomes "State the design". Its sections stay: prior art, goals, contracts, decisions, open questions and assumptions.
  - Doc edits are a list of changes to existing files.
  - The Report suggests `/sdlc:split` in the same session, with no path.
  - The `design_dir` lookup goes away.
- **skills/split:** source 3 becomes "a design or plan earlier in this conversation", from `sdlc:design` or plan mode. The uncommitted-source rule already copies the facts each task needs into its description. `--design` is set only when a committed document covers the task.
- **skills/build:**
  - Plan mode: design goes into the plan, and the plan lists the doc edits.
  - After approval:
    1. apply the doc edits
    2. switch branch, and commit only if something changed
    3. split from the approved plan
    4. dispatch
  - `git add -- *.md` is still right for doc edits.
  - Headless: design states the design in the conversation and edits docs. Then the same order: commit if needed, split, dispatch.
- **`design_dir` setting:** removed from `settings.sh`, `init.sh`, init's argument-hint, `docs/configuration.md` and `README.md`.
- **Docs:** `docs/workflow.md` §1 "Output: a document" becomes the in-session design plus edits to existing docs. The README walkthrough changes to match.

One thing changes for users: design and split must run in the same session, unless design updated committed docs that split can read. That's how build and the wild test already run.

## dispatch: sending tasks and epics to the workers

dispatch is the skill that hands work to the workers. split only writes beads.

What happens today:
- **The loop moved, it wasn't deleted.** Commit 5790946 moved dispatch's loop almost word for word into `agents/supervisor.md`: look, handle crashes, dispatch, follow, report. It runs in the background so worker events don't fill the user's session. `/sdlc:dispatch` kept confirming, starting the supervisor, and making the decisions that need a person.
- **Person-needed events now wait for the final report.** The old skill told the user right away when a task waited for review or stopped. The supervisor now "notes it for the report", and that report only comes when the watch goes idle, which can be hours later, while a review gate holds up the work.
- **There's no single-task dispatch.** `/sdlc:dispatch` takes one epic or nothing (all ready work). `run-task.sh <task>` dispatches one task, but nothing starts it for a person. Every script takes `--epic` only.

Recommended: `/sdlc:dispatch [id...] [--parallel N]`, started by the user or by build.
- **Scope:**
  - Any mix of tasks, parent tasks and epics, or nothing for all ready work. The scope is the named beads and their descendants.
  - `--epic <id>` becomes a repeatable `--under <id>` in `workers.py`, `next-tasks.py`, `dispatch-next.sh`, `watch.py` and `stats.py`. `tasks.py` checks "is a descendant of" instead of "its epic is".
- **A named bead that isn't ready:** say what it waits for, and offer to include those blockers.
- **In epic modes:** the first task dispatched creates the epic branch and the integration task (`run-task.sh:90-102`), and that integration task waits for every other task of the epic. The confirmation says so.
- **Person needed:** the supervisor returns as soon as a person is needed (awaiting review, stopped, failed, Can't) instead of saving it for the end. dispatch relays it, starts the supervisor again straight away so the other work continues, then acts:
  - awaiting review: `/sdlc:review <task>`
  - stopped or failed: `/sdlc:recover <task>`
  - Can't: `reset-task.sh`, after asking
- **Unchanged:** the confirmation, and the supervisor as a background agent.

Not in this plan: two supervisors with overlapping scopes can go over the parallel limit, since each counts running workers and then starts more. `docs/hypotheses/dispatch-controller.md` covers that.

## review: task, parent task, epic, pull request

What happens today:
- **Agent review:** the criteria, the prompt and the JSON schema are written as bash strings inside `finish-task.sh:111-127`.
- **Human review:** has no entry point. A person runs `git diff base...branch` in the worktree, then `bd gate resolve <gate>` (`docs/beads.md:91`, `workers.py:243-247`).
- **Epic review:** means creating a gate by hand (`docs/workflow.md:107-111`).
- **Parent tasks:** close on their last child's merge, and nothing reviews them.
- **Pull requests:** nothing reads review feedback on a pull request.

`skills/review/SKILL.md` holds the review criteria once. They're today's: bugs, acceptance not met, security, changes outside the scope, missing tests for new behaviour, and no style comments. The skill takes a task, parent, epic or PR:

| Level | Diff | Reviewed against | When |
|---|---|---|---|
| task | `base...branch` in its worktree | its description, acceptance, scope and verify | `review=agent`: `finish-task.sh` runs `claude -p "/sdlc:review <task>"` with the installed `reviewer` agent and today's `--json-schema`. `review=human`: a person types `/sdlc:review <task>` while the gate waits. |
| parent task | the combined commits of its children | the parent's acceptance, checking that nothing fell between children | On request only, read-only. Children merge on their own, so there's no branch to gate. |
| epic | `target...<epic branch>` | the epic's description and acceptance | Before integration. `metadata.review` on the epic (agent or human) replaces the gate added by hand: the integration task's `finish-task.sh` applies it to the epic diff. |
| pull request | the pull request's diff and its review comments | the epic | epic-pr mode. Either post a review with `gh pr review`, or read the reviewers' comments and turn them into work (see open questions). |

When a person runs it:
1. The skill summarizes the diff against the acceptance.
2. The skill shows the verify result and any earlier agent findings (`dispatch_review*` metadata and comments).
3. It asks for a verdict:
   - **approve:** `bd gate resolve`
   - **request changes:** `bd comments add` with the changes, then `bd gate resolve`

   Once the gate is resolved, `resume-reviewed.sh` resumes the worker.

Workers don't start it: `finish-task.sh` runs the review for them (`agents/worker.md:17`). Claude can start it from your session, for example when you ask it to review a task.

## verify: task, parent task, epic

What happens today:
- Verify commands run only inside `finish-task.sh`: the task's own after the rebase, and every task's on the epic branch for an integration task.
- There's no way to run them on demand. A person fixing a stopped task, or reviewing, can't run the checks that finishing will run.
- **Direct mode never re-runs earlier tasks' verify commands once later tasks land.** An epic can close with an earlier task's check broken.

Changes:
- **New `scripts/verify.sh <task|parent|epic>`** runs:
  - a task's verify command in its worktree
  - for a parent, every descendant's
  - for an epic, every task's on the epic branch (epic modes) or the target (direct), plus the pre-merge checks (`wt hook pre-merge`)

  `finish-task.sh` calls it, so "what verify means" is defined once.
- **The skill** runs `verify.sh`. On a failure, it reads the output and the commits since the failing task merged, and says which change broke which check.
- **Direct mode:** when `finish-task.sh` closes an epic, it runs `verify.sh <epic>` on the target and comments any failure on the epic. The code has already merged, so this reports the problem rather than blocking.

## recover: a stopped, failed or crashed task

What happens today:
- A stopped or failed task can only be split, or "fixed by hand in its worktree" (`commands/status.md:24`, `agents/supervisor.md:31`).
- **Fixing by hand is a dead end.** `finish-task.sh` exits 2 once `dispatch_state` is `stopped` or `failed` (`finish-task.sh:66-69`).
- `resume-task.sh` exists, but only the supervisor uses it, and only for crashes.
- **Reset is written three times, differently:**
  - `agents/supervisor.md:27` describes it
  - `commands/dispatch.md:38` releases the merge queue and unsets five keys
  - `skills/split/SKILL.md:105-107` skips the queue release but unsets every `dispatch_*` key

Changes:
- **New `scripts/reset-task.sh <task>`:** releases the merge queue, runs `wt remove -D`, reopens the task and unsets every `dispatch_*` key. dispatch, split and recover all call it.
- **`/sdlc:recover <task> [instructions]`** first reads the last comment and a summary of the worker log. Then it offers:
  - **resume** with the instructions, if the worktree and transcript exist: clear `dispatch_state`, then `resume-task.sh`
  - **finish** after a fix by hand: clear `dispatch_state`, then `finish-task.sh`
  - **start over:** `reset-task.sh`, and the next dispatch picks the task up
  - **split:** hand off to `/sdlc:split <task>`

## stop: running workers

What happens today: workers run detached (`setsid`, `start-worker.sh:86-93`). Stopping the supervisor leaves them running, and no script stops one.

Changes:
- **New `scripts/stop-task.sh <task|epic>`:**
  1. ends the worker process for the task's session
  2. releases the merge queue
  3. records the task as `stopped`, with a comment saying a person stopped it
- **`/sdlc:stop [task|epic]`** shows which workers will stop, asks, then runs the script. `/sdlc:recover` picks them up later.

Anthropic's ralph-loop has the same kind of skill, `cancel-ralph`.

## clean: leftovers

What's left behind today:
- worktrees and branches of closed tasks, after a crash between merge and record (an open follow-up)
- worktrees of tasks that were reset
- merge queues held by dead sessions

Changes:
- **New `scripts/clean.sh`** lists all of these, and removes them with `--apply`.
- **`/sdlc:clean`** shows the list, asks, then applies it.

Anthropic's commit-commands has the same kind of skill, `clean_gone`.

## Script fixes found along the way (no skill)

- **A pull request closed without merging** leaves epic-pr hanging: the `gh:pr` gate never resolves, and `close-prs.sh` only handles merged ones. `close-prs.sh` should record the integration task as `stopped`, with a comment, so `/sdlc:recover` can pick it up.
- **Direct mode:** re-run every task's verify command when the epic closes (under verify above).

## Considered, not a skill

- **integrate:** the integration task already runs on its own as the `sdlc:integrator` agent. Its manual moments (the epic gate, pull request feedback) belong to review.
- **Changing a task's or epic's settings** (review level, integration mode, agent hints: `docs/configuration.md:41-48`): one `bd update --set-metadata` command, with the keys documented. create-task could later also change existing tasks.
- **`wt config approvals add`:** once per machine per project. init already says so.
- **task-rules:** stays a file that split and create-task read verbatim. A knowledge skill would leave it to auto-loading.

## Order

1. **Move commands to skills.**
   - `git mv commands/<name>.md skills/<name>/SKILL.md` for build, dispatch, create-task, setup, init, status, stats and logs.
   - `disable-model-invocation: true` stays on setup, init, status, stats and logs.
   - Update `docs/development.md`'s layout and the component memory.
2. **Design without a document:** design, split, build, the `design_dir` removal, workflow and README.
3. **dispatch:** single-task and multi-bead scope, and returning early when a person is needed.
4. **review.** It covers the biggest manual gaps: human review, the epic gate, criteria written as bash strings.
5. **recover, with `reset-task.sh`.** It removes the reset copies and fixes the dead end after a hand fix.
6. **verify, with `verify.sh`.** Checks on demand, and the direct-mode gap.
7. **stop.**
8. **clean,** and the closed-PR fix in `close-prs.sh`.
9. **One wild run at the end.** `tests/wild/run.sh` covers design, split, status, stats and logs, and `tests/wild/dispatch.sh` covers dispatch. build still needs a manual run.

## Open questions

- **Pull request feedback in epic-pr mode.** `record-task.sh` removes the integration worktree once the pull request is open, and `create-task.sh` refuses new tasks under an epic that is already integrating. Two ways to handle review comments:
  - reopen the integration task and resume the integrator with the comments (recreating its worktree)
  - allow follow-up tasks under an integrating epic
- **Unverified:** whether `claude -p --agent reviewer "/sdlc:review <task>"` expands the plugin skill and still honours `--json-schema`. Check it in the test run.
