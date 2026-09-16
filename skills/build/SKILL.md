---
name: build
description: "Take a request from idea to integrated code: design in plan mode for the user's approval, then apply the doc edits and commit them if anything changed, split the approved plan into beads tasks for the user to approve, and dispatch workers. Use when the user asks to build, add or change something end to end with sdlc, or when this project routes new work here (workflow: build). For a single phase, use sdlc:design, sdlc:split or sdlc:dispatch."
argument-hint: "<what to build>"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh *), Bash(git branch --show-current), Bash(git status --porcelain -- *.md), Bash(git add -- *.md), Bash(git commit -m *)
---

# Build

Request: $ARGUMENTS

Settings:
!`${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh 2>&1 || true`

Current branch:
!`git branch --show-current 2>&1 || true`

Run the whole workflow for this request. Each phase is a skill of this plugin: invoke it with the Skill tool and follow it.

## 1. Plan

Compare the current branch above with the target from the settings above. If they differ, a switch is needed: note it for the plan below. If it can't happen (for example the target branch doesn't exist, or local changes block it), stop here and report why — don't create anything.

1. Enter plan mode with the EnterPlanMode tool, unless it is already active. If the tool isn't available (headless session), skip plan mode and follow Headless below instead of steps 2 and 3 here.
2. Invoke `sdlc:design` with the request. In plan mode, it puts the stated design and the doc edits in the plan file.
3. Exit plan mode with ExitPlanMode. The plan asks the user to approve:
   - the design and the doc edits
   - the branch switch above, if any
   - the integration mode, target branch, parallel limit and default review level, from the settings above
   - what happens next: applying the doc edits and committing them if anything changed, splitting the plan into tasks for their approval, and dispatching

   If the user asks for changes, revise the plan and ask again.

## 2. Create

1. Apply the doc edits from the approved plan.
2. Switch to the target branch if step 1 found a switch was needed — already approved with the plan, so no need to ask again. Then, only if the doc edits changed anything (`git status --porcelain -- *.md`), commit them there: `git add -- *.md`, then `git commit -m <message>`. Tasks live in beads, not git, so doc edits are the only thing to commit. Workers branch from committed code, so uncommitted edits are invisible to them.
3. Invoke `sdlc:split` on the approved plan, so the request becomes exactly one top-level epic (no nested epics — group large work with parent tasks instead). Split shows the task graph and asks the user to approve it. If the user doesn't, stop here. Carry the epic's id to Dispatch below.

## 3. Dispatch

Invoke `sdlc:dispatch` with the epic id from Create. The plan already covered dispatching, the integration mode, target branch, parallel limit and review level, so dispatch doesn't need to ask again. It dispatches the tasks and reports the moment a task needs a person, restarting itself to keep the rest going, until nothing is left.

## Headless

No plan mode, no approvals. Invoke `sdlc:design` with the request: it states the design in the conversation and makes the doc edits directly. Then follow the same order as Create and Dispatch above: commit the doc edits if anything changed, split, dispatch.
