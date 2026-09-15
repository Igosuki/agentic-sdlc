## Skill review: split-plan

### Summary

The skill is short (about 900 words in the body, estimated), well organised, and in line with the other planning skills. The problems are in what it tells the agent to build. Some of the graph shapes it asks for never finish under `dispatch`. Its rules for verify commands and dependencies don't match what the dispatch scripts do, and the plan-mode instructions are in the wrong place.

- **No `scripts/` directory.** The skill uses `skills/create-task/scripts/create-task.sh`, so I reviewed that script too.
- **Other files checked:** the dispatch scripts that read its output (`next-tasks.sh`, `run-task.sh`, `finish-task.sh`, `close-prs.sh`), plus split-task, create-task, build, init and the docs.
- **Not checked:** I couldn't read the plan file in `~/.claude/plans/` (permission was denied), and I didn't run `bd`. So `bd swarm validate` and `bd list --pretty` are unverified.

### Description analysis

**Current:** "Split a plan into a beads task graph (one or several epics, tasks, subtasks and dependencies, shaped by the agent), each task with acceptance criteria, scope and verify command. The plan can be markdown docs (for example from sdlc:design), a plan made in plan mode earlier in the conversation, or a plain prompt. Use when work needs to become beads tasks."

**Issues:**
- **Overlap:** "Use when work needs to become beads tasks" also describes `create-task` (one task) and `split-task` (an existing bead). Nothing tells the model which of the three to pick.
- **No user phrasings:** it lacks words users actually say, like "break this down", "decompose" or "create the tasks for".
- **Length (about 390 characters) is fine.** All 11 skills use "Use when…", so keep that rather than "This skill should be used when".

**Suggested description** (drops "subtasks", per the critical issue below):
> Split a design document, an approved plan-mode plan or a plain prompt into a beads task graph: epics, tasks and dependencies, each task with acceptance criteria, scope and a verify command that sdlc:dispatch can run. Use when asked to break a design or plan into tasks, decompose a feature, or create the tasks for new work. For a single task use sdlc:create-task; to split an existing bead use sdlc:split-task.

### Content quality

- **Word count:** about 900. That's at the low end of the target range, which suits a skill loaded on every run.
- **Style:** mostly imperative, with some "you". This matches the other skills.
- **Organization:** the three numbered steps read clearly. The exception is plan mode, which is handled in one paragraph at the end of step 2 (see Major 3).

### Progressive disclosure

- SKILL.md: about 900 words; references/: 0; examples/: 0; scripts/: 0 (uses `create-task.sh`, 103 lines).
- **Assessment:** the size is fine. Only one part is worth moving out. `split-task` and `create-task` both read "section 2" of this file for the sizing, scope and task-format rules. That makes the section number load-bearing, and those skills also pull in split-plan's own create template and plan-mode paragraph. Since three skills use these rules, a `references/task-rules.md` file would earn its place.

### Specific issues

#### Critical (1)

- **SKILL.md:39, 60–62: task graphs with more than one level never finish.** The skill asks for "tasks nested under larger tasks" and says "a large task becomes a parent".
  - `next-tasks.sh:52` never dispatches a task that has children.
  - Nothing in the repo closes a parent task once its children close.
  - `finish-task.sh:114–120` and `close-prs.sh:28` only close the nearest epic, and only when all its direct children are closed.
  - **Direct mode:** the epic never closes.
  - **epic-merge / epic-pr:** `run-task.sh:94–96` makes the integration task wait for every open direct child, including the parent task. The integration task never becomes ready, so the epic branch never reaches the target branch.
  - **Nested epics** have the same problem: the outer epic is never closed.
  - **The scope rule (line 84) conflicts too:** a parent shares paths with its children. Adding `--after` between them would deadlock.
  - **Fix:** keep one level under an epic. Split large work into sibling tasks joined with `--after`, not children of a task, and don't nest epics. Rewrite "Task sizing" to match. The other option is to make `finish-task.sh` and `close-prs.sh` close parents as their last child closes.
  - `split-task` creates children under a task bead, so it has the same problem.
  - Caveat: I'm assuming beads doesn't close parents on its own; nothing in the repo relies on that.

#### Major (6)

1. **SKILL.md:80, 84, 93: dependencies across epics break in epic-merge and epic-pr modes.**
   - A task branches from its epic's branch (`run-task.sh:102–108`) and closes when it merges there (`finish-task.sh:110`).
   - So a task in epic B (or with no epic) that waits for a task in epic A becomes ready while A's code exists only on branch A. Line 93 ("only rely on files that exist once … the tasks it waits for are done") is then false.
   - **Fix:** add the rule "To depend on work in another epic, wait for that epic (`--after <epic-id>`), or put the tasks in one epic." Inject the settings the way `build` does (`!${CLAUDE_SKILL_DIR}/../dispatch/scripts/settings.sh`) so the agent knows the mode.
   - Waiting for the epic isn't enough in epic-pr mode: the pull request merges on the remote, so the local target branch also needs a pull.

2. **SKILL.md:91–93: the verify rules leave out how verify commands are run.**
   - `finish-task.sh:79` runs the command with `bash -c` from the worktree root and kills it after 600 seconds.
   - `finish-task.sh:56–58` makes the integration task re-run every task's verify on the finished epic branch. A verify that checks a stub or placeholder a later task replaces will fail there.
   - **Fix:** add two bullets:
     - "Runs from the repository root and must finish within 10 minutes."
     - "In epic modes every verify runs again on the finished epic branch, so it must keep passing after later tasks land."

3. **SKILL.md:35, 107, 115: plan mode is handled in the wrong place.**
   - `bd init` (line 35) is a write, and it comes before the plan-mode note.
   - Step 3 doesn't mention plan mode.
   - `build` calls split-plan a second time after the plan is approved. Line 25 ranks documents named in the arguments above the plan, and steps 1–2 re-read and re-decompose. Line 115 then says "wait for approval", which contradicts line 107.
   - The plan has no way to name dependencies before ids exist.
   - **Fix:** add a block right after the `bd where` line:
     ```markdown
     ## Mode
     - **Plan mode is active:** read and decompose, then write the graph into the plan file with every script field, using labels (T1, T2…) for `--parent` and `--after`. Don't run `bd init`, the script, or step 3.
     - **An approved plan in this conversation holds a task graph:** skip steps 1–2. Create that graph, mapping labels to the ids the script prints, then run step 3 without asking for approval.
     - **Otherwise:** steps 1–3.
     ```

4. **SKILL.md:44, 99–104: the command template wraps values in double quotes.**
   - Task descriptions often contain backticks and `$NAME` (code identifiers, environment variables). Inside double quotes, bash runs the backticks and expands the variables before `create-task.sh` receives the text.
   - **Fix:** use single quotes in the template and example, and add "write an apostrophe as `'\''`". Alternatively, use a `"$(cat <<'EOF' … EOF)"` heredoc for `--description` and `--acceptance`.
   - With the heredoc, check that the allowed-tools rule still pre-approves the command. `tests/wild` runs with `--dangerously-skip-permissions`, so it wouldn't catch that.

5. **Step 1: existing beads are never checked.**
   - `README.md:26` says split-plan "links new tasks to the ones they depend on", but the skill never looks up existing beads.
   - Running it twice on the same document creates the graph twice. `create-task` and `split-task` both check for duplicates first.
   - **Fix:** add to step 1: "Bead commands return little and can run directly: `bd search <terms>` and `bd list --type epic` find an epic that already covers the plan (stop and say so) and open tasks the new ones must wait for (`--after <existing-id>`)."

6. **SKILL.md:89, 95: workers may not be able to see the design document.**
   - Workers branch from committed code (`run-task.sh:123`). The standalone flow in `README.md:99–103` goes design → split-plan → dispatch with no commit.
   - As a result, the `--design` path and the "design sections" that descriptions point to don't exist in the worktrees. Plan-mode plans live in `~/.claude/plans/`, outside the repo entirely.
   - **Fix:** extend line 95's "copy the facts" rule to any source that isn't committed on the target branch, including plan-mode plans. In step 3, list any `--design` document that isn't committed and say it needs a commit before `/sdlc:dispatch`.

#### Minor (6)

- **Frontmatter:** the description overlaps with the sibling skills. Use the version suggested above.
- **SKILL.md:35: bare `bd init` skips what `init.sh` sets up.** It leaves out the target and integration config and the `.gitignore` entries. Dispatch then defaults to the branch `main` (`run-task.sh:57–58`), so a repo on another branch fails at dispatch. Suggest `/sdlc:init`, or run `init.sh` with its defaults and add it to `allowed-tools`.
- **SKILL.md:111–116, step 3:**
  - "If you can ask" is undefined. Name AskUserQuestion and the headless case, as the sibling skills do.
  - After the user asks for changes, run `bd swarm validate` again.
  - Tasks created without an epic are never validated.
  - `bd list --parent --pretty` shows the hierarchy but not the dependencies. Include the `after …` part of `create-task.sh`'s output lines (`create-task.sh:101–103`).
- **SKILL.md:84: the scope rule makes shared manifests serialize everything.** Files like `package.json`, lockfiles or a route index would force nearly every task into one chain or one merged task. Scope only reaches the worker's prompt (`run-task.sh:164–165`), and `finish-task.sh` already handles rebase conflicts. Exempt shared manifests, or give them to the interface task.
- **`--domain` is required but nothing reads it.** Only `create-task.sh` stores it. Either say what uses it or make it optional, per build-minimal.
- **Cross-skill:** move sizing, granularity, shared interfaces, scope and task format to `skills/split-plan/references/task-rules.md`, and point `split-task` and `create-task` at that file instead of "section 2". Separately, `split-task:15` forbids reading files yourself, while line 39 tells the agent to read that section.

### Positive aspects

- The verify rule requires a command that exercises the behaviour and depends only on files the task's dependencies produce.
- Shared interfaces become their own task, with consumers waiting on it through `--after`.
- `create-task.sh` reports every validation error at once and rejects unknown ids before `bd dep add`, which accepts them silently.
- Reading is delegated to a cheap reader, in line with the Opus-only-thinks policy.
- The `!bd where` injection always exits 0, so it can't abort the skill.

### Overall rating

**Needs Improvement.** The structure and length are fine. The critical and major issues come from instructions that don't match how dispatch runs the graph.

### Priority recommendations

1. **Allow only one level under an epic** (or teach dispatch to close parents), so epics close and get integrated.
2. **Add the Mode block** so plan mode and the second call after approval don't write early, re-decompose or ask again.
3. **Match the rules to dispatch:** the verify runtime, the re-runs on the epic branch, and waiting for epics across epics.
4. **Fix the quoting in the create template.**
5. **Check existing beads** before creating, and flag design documents that aren't committed.
