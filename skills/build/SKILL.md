---
name: build
description: "Take a request from idea to integrated code: design in plan mode for the user's approval, then write and commit the design, split it into beads tasks for the user to approve, and dispatch workers. Use when the user asks to build, add or change something end to end with sdlc, or when this project routes new work here (workflow: build). For a single phase, use sdlc:design, sdlc:split or sdlc:dispatch."
argument-hint: "<what to build>"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh *), Bash(git branch --show-current), Bash(git add -- *.md), Bash(git commit -m *)
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

1. Enter plan mode with the EnterPlanMode tool, unless it is already active. If the tool isn't available (headless session), skip plan mode: `sdlc:design` writes the document in step 2, so skip step 3 here and step 1 under Create.
2. Invoke `sdlc:design` with the request. In plan mode, it puts the design document in the plan file.
3. Exit plan mode with ExitPlanMode. The plan asks the user to approve:
   - the design document, and where it will be written
   - the branch switch above, if any
   - the integration mode, target branch, parallel limit and default review level, from the settings above
   - what happens next: writing the document and committing it on the target branch, splitting it into tasks for their approval, and dispatching

   If the user asks for changes, revise the plan and ask again.

## 2. Create

1. Write the design document to its location.
2. Switch to the target branch if step 1 found a switch was needed — already approved with the plan, so no need to ask again. Then commit the design document there: `git add -- <path>`, then `git commit -m <message>`. Tasks live in beads, not git, so the document is the only thing to commit. Workers branch from committed code, so an uncommitted document is invisible to them.
3. Invoke `sdlc:split` on the committed document, so the request becomes exactly one top-level epic (no nested epics — group large work with parent tasks instead). Split shows the task graph and asks the user to approve it. If the user doesn't, stop here. Carry the epic's id to Dispatch below.

## 3. Dispatch

Invoke `sdlc:dispatch` with the epic id from Create. The plan already covered dispatching, the integration mode, target branch, parallel limit and review level, so dispatch doesn't need to ask again. It dispatches the tasks, follows the workers until nothing is left, and reports.
