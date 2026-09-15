## Skill Review: build

### Summary
`skills/build/` holds only `SKILL.md`, and there is no `scripts/` directory. The only script it runs is `../dispatch/scripts/settings.sh`, injected with `!`. That script can't abort the skill: every lookup it does has a fallback.

The skill is short (about 250 words, description about 250 characters), clear, and leaves the real work to design, split-plan and dispatch. That's the right shape for a skill that only chains others. The problems are in the handoffs between those skills. Two of them start duplicate or wrong work, and one comes from dispatch's scripts but hits nearly every build.

### Description Analysis
**Current:** "Take a request from idea to merged code in one session. Designs it and splits it into tasks in plan mode, for the user's approval, then creates the tasks and dispatches them to workers. Use when the user wants the whole sdlc workflow for a request."

**Issues:**
- Users don't say "the whole sdlc workflow". The hook in `hooks/session-start.sh:13` sends new work here with the wording "build, create or change something", and the description doesn't include that wording.
- "Merged code" is wrong in `epic-pr` mode, where the build ends with an open pull request.
- The generic checklist wants "This skill should be used when…". Every other skill in this plugin uses "Use when…", so staying consistent matters more. No change needed.

**Suggested description:** "Take a request from idea to integrated code: design and task split in plan mode for the user's approval, then write the design, create the beads tasks, commit and dispatch workers. Use when the user asks to build, add or change something end to end with sdlc, or when this project routes new work here (workflow: build). For a single phase, use sdlc:design, sdlc:split-plan or sdlc:dispatch."

### Content Quality
- **Word count:** about 250. That's below the usual 1,000 words, but right for a skill that only chains others. Don't add to it.
- **Writing style:** Imperative, and consistent with the sibling skills.
- **Organization:** Plan → Create → Dispatch is clear.

### Progressive Disclosure
- **Current structure:** only `SKILL.md`. There is no `references/`, `examples/` or `scripts/`.
- **Assessment:** None of those are needed. Reusing dispatch's `settings.sh` is the right call, and design already does the same.

### Specific Issues

#### Critical (3)

**C1. Without plan mode, the task graph can be created twice.** (`SKILL.md:18`, `SKILL.md:32`)
- **Cause:** Step 1.1 allows skipping plan mode (headless session, or the user declines). Outside plan mode, split-plan creates the beads right away in step 1.3, because the rule at `split-plan/SKILL.md:107` only applies in plan mode.
- **What goes wrong:** Step 2.2 then invokes split-plan again "to create the approved task graph", and nothing stops it. Steps 1.4 and 2 ("once the plan is approved") have no branch for this case either.
- **Result:** Headless dispatch runs both copies, so two workers build the same thing and their merges conflict.
- **Fix:** In 1.1, say that without plan mode, design writes the document and split-plan creates the tasks during step 1, so skip 1.4, 2.1 and 2.2.

**C2. Several epics, or none, give dispatch the wrong scope.** (`SKILL.md:37`)
- **Cause:** Step 3 says "with the epics you created". split-plan may create "one epic, several epics, tasks nested under larger tasks" (`split-plan/SKILL.md:39`). Dispatch takes a single `[epic-id]`, and every script reads one `--epic` value, where the last one wins (`dispatch-next.sh:23`, `next-tasks.sh:31`). `epic_of` stops at the nearest ancestor whose type is epic (`next-tasks.sh:41-45`).
- **What goes wrong:**
  - With several epics, one gets dispatched and the others never start.
  - If the top-level bead isn't an epic, or epics are nested, `--epic` matches nothing, and dispatch reports "no ready task" and stops.
  - If dispatch is given no epic, it starts every dispatchable task in the repo, including work nobody approved. In headless mode nobody gets asked.
- **Fix:** In step 1.3, tell split-plan to put the request under exactly one top-level epic, with no nested epics (it can group with parent tasks instead). Then pass that single id to dispatch. This also matches README:27 ("A new epic with `/sdlc:build`").

**C3. Dispatch loses track of subtasks and stops early.** (the bug is in `dispatch/scripts/watch.sh:81` and `workers.sh:40`; build triggers it)
- **Cause:** Both filters use `.parent == $e`, which only matches the epic's direct children. But split-plan turns every large task into a parent of subtasks (`split-plan/SKILL.md:60-62`), and build always passes an epic.
- **What goes wrong:** Subtask workers never count as `alive` and never produce `ended` or `crashed` events. So `watch.sh` prints `idle` while they are still running (`:86-88`), and dispatch sends its report and exits. Nothing dispatches the tasks waiting on those subtasks, and crashes go unhandled.
- **Fix:** Use the same recursive `epic_of` as `next-tasks.sh` in both filters.

#### Major (3)

**M1. split-plan can read an old version of the design.** (`SKILL.md:20`)
- **Cause:** In plan mode, design only writes the document after plan mode ends (`design/SKILL.md:115`). It also updates an existing document on the same topic rather than creating a new one (`:72`).
- **What goes wrong:** If build passes the document path, split-plan's reading agent reads the old version still on disk.
- **Fix:** Tell split-plan to split the design in the plan file, and to set `--design <path the document will be written to>` on the tasks.

**M2. The branch check comes too late and has no fallback.** (`SKILL.md:33`)
- **Cause:** The check runs after the document is written and the tasks are created.
- **What goes wrong:** If the user refuses the branch switch, the tasks already exist and step 3 still dispatches, so workers branch from a target that doesn't have the document. A headless session can't ask at all.
- **Fix:**
  - Add the current branch next to the injected settings: `` !`git branch --show-current` ``.
  - Compare it with the target during step 1, and put any branch switch in the plan.
  - If the switch can't happen, stop before creating anything.
  - Add "dispatch only after the commit succeeds".

**M3. The approval leaves out settings, and dispatch then asks a second time.** (`SKILL.md:21-24`)
- **Cause:** The plan only asks to approve "dispatching". It doesn't show the integration mode or the parallel limit, even though both are already in the injected settings.
- **What goes wrong:** In `epic-pr` mode, the build pushes to origin and opens a pull request that the user never saw in the plan. Dispatch then asks again anyway (`dispatch/SKILL.md:25`). split-plan is told not to re-ask; dispatch isn't.
- **Fix:** List the integration mode, target and parallel limit in the plan. Invoke dispatch with a note that the plan already approved it, and add a one-line exception to dispatch step 1.

#### Minor (3)

**m1. The reason given for committing `.beads/` doesn't hold.**
- The skill says workers need committed files. But tasks live in Dolt, which `.beads/.gitignore:2-4` keeps out of git, and workers read them through `bd`.
- The commit only carries `config.yaml`, `metadata.json` and `interactions.jsonl`.
- Either give the real reason, or commit only the design document.

**m2. No `allowed-tools` for git.**
- In a headless session with default permissions, `git add` and `git commit` are denied.
- `init` already uses `Bash(git add …)` and `Bash(git commit *)`. This only matters once C1 is fixed.

**m3. Unverified: which model runs the nested skills.**
- I couldn't confirm that a skill's `model:` setting applies when it's invoked through the Skill tool from inside build.
- If it doesn't, dispatch's long follow loop runs on the session's model (often Opus) instead of Sonnet. Worth one test.

### Positive Aspects
- Build is only a thin chain of skills, so none of their logic is copied.
- The reason for the commit is correct for the design document, in every integration mode. `run-task.sh:89` creates the epic branch from the local target at first dispatch, so a commit made before dispatch reaches the workers.
- There is a single approval for both the design and the task graph, and split-plan is told not to ask again.
- Settings are injected with `!` instead of making the model run a script.

### Overall Rating
**Needs Improvement.** The text is short and well written. The bugs are in the handoffs between skills.

### Priority Recommendations
1. **C3:** fix the epic filter in `watch.sh` and `workers.sh`. Otherwise almost every build stops following its workers too early.
2. **C2:** one top-level epic per build, no nested epics, one id passed to dispatch.
3. **C1:** a clear path for running without plan mode, so the graph isn't created twice.
4. **M1 and M2:** split-plan reads the design from the plan file; check the branch during planning and stop if it can't be switched.
5. **M3:** show the integration mode, target and parallel limit in the plan, and don't have dispatch confirm again.

I could only read files, so this report isn't saved anywhere. `docs/review-skill-build.md` exists but is empty; it's the natural place for it.
