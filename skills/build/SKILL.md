---
name: build
description: Take a request from idea to merged code in one session. Designs it and splits it into tasks in plan mode, for the user's approval, then creates the tasks and dispatches them to workers. Use when the user wants the whole sdlc workflow for a request.
argument-hint: "<what to build>"
---

# Build

Request: $ARGUMENTS

Settings:
!`${CLAUDE_SKILL_DIR}/../dispatch/scripts/settings.sh`

Run the whole workflow for this request. Each phase is a skill of this plugin: invoke it with the Skill tool and follow it.

## 1. Plan

1. Enter plan mode with the EnterPlanMode tool, unless it is already active. If the tool isn't available (headless session), skip plan mode and go on.
2. Invoke `sdlc:design` with the request. In plan mode, it puts the design document in the plan file.
3. Invoke `sdlc:split-plan` on that design. In plan mode, it puts the task graph in the plan file.
4. Exit plan mode with ExitPlanMode. The plan asks the user to approve:
   - the design document, and where it will be written
   - the task graph
   - what happens next: writing the document, creating the tasks, committing both on the target branch, and dispatching

   If the user asks for changes, revise the plan and ask again.

## 2. Create

Once the plan is approved:
1. Write the design document to its location.
2. Invoke `sdlc:split-plan` to create the approved task graph. It doesn't ask for approval again.
3. Commit the design document and `.beads/` on the target branch from the settings above. Workers branch from committed code, so an uncommitted document is invisible to them. If the current branch isn't the target, tell the user, and ask before switching.

## 3. Dispatch

Invoke `sdlc:dispatch` with the epics you created. It dispatches the tasks, follows the workers until nothing is left, and reports.
