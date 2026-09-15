Quick update: I've read the skill, the one script it uses, split-plan (its handoff target), and the build skill that invokes it. I found no `scripts/` directory under `skills/design/`. I'm writing up the review now.

## Skill Review: design

### Summary
It's a lean, well-scoped planning skill. The body is about 800 words, all in one file (SKILL.md). Its only script dependency is the `settings.sh` call on line 68, which lives in the dispatch skill. The biggest problem is in the frontmatter, not the text: the skill runs `settings.sh` when it loads, but nothing pre-approves that command. Its handling of external sources in headless sessions, the triggering description and two contradictory docs also need work.

I reviewed statically and didn't run the skill.

### Description Analysis
**Current:** "Turn a product or feature request into a design document that removes ambiguity and fixes contracts, grounded in prior art from the repository, existing beads and (with the user's permission) connected sources such as wikis, Notion or Drive. Output is ready for sdlc:split-plan. Use when starting new work from an idea, before any tasks exist." (~370 chars)

**Issues:**
- **No user phrasing:** it doesn't include the words users actually say ("design", "spec out", "design doc", "RFC", "think through before building").
- **Overlap with split-plan:** split-plan's description says it accepts "a plain prompt", so "plan out feature X" could trigger either skill.
- **Overlap with build:** it takes the same `<what to build>` argument. Nothing in design's description rules either sibling out.
- The "Use when…" style matches the sibling skills. Don't switch to "This skill should be used when…" in this skill alone.

**Suggested description (~440 chars):**
"Write a design document for a product or feature request: find prior art in the repository, existing beads and (with permission) wikis, Notion or Drive, resolve open questions, and fix the contracts separate tasks must agree on. Output feeds sdlc:split-plan. Use when the user asks to design, spec out, or write a design doc or RFC for new work, before tasks exist. Not for splitting an existing design (split-plan) or running the full workflow (build)."

### Content Quality
- **Word count:** about 800. That's below the 1,000-word guideline, but right for a single-workflow skill. Don't pad it.
- **Writing style:** imperative, direct, no filler.
- **Organization:** a Reading rule, then four numbered steps, then plan-mode and headless branches. It's easy to follow.

### Progressive Disclosure
- **SKILL.md:** about 800 words.
- **references/, examples/, scripts/:** none.
- **Assessment:** nothing needs splitting out. The document template is the core output and belongs in the main file.

### Specific Issues

#### Critical (1)
- **SKILL.md frontmatter: the line-68 script call is not pre-approved.** The `!` prefix runs a shell command when the skill loads, and that command needs `allowed-tools` (the frontmatter field that pre-approves commands).
  - `status` already pre-approves this same script (`allowed-tools: Bash(${CLAUDE_SKILL_DIR}/../dispatch/scripts/*)`), and split-plan pre-approves its own `!bd where` the same way.
  - Design has no `allowed-tools`. With default permissions, the command fails its check and the skill stops before it starts. That's also what happens when `build` invokes design.
  - If it works on your machine, your own permissions are probably allowing it.
  - Fix:
    ```yaml
    allowed-tools: Bash(${CLAUDE_SKILL_DIR}/../dispatch/scripts/settings.sh *)
    ```
  - `skills/build/SKILL.md` has the same gap on line 12.

#### Major (3)
- **SKILL.md lines 36 and 46: headless sessions contradict the permission rule.** External sources "need permission first", but in a headless session the skill uses "the external sources the request requires". That listed sources include mail and chat, so an unattended run could read them based on its own judgment.
  - Fix: in headless sessions, use only the sources the request names or links, and record the others under Open questions.
- **SKILL.md lines 19–22 and 37–39: the reader may lack the tools it needs.** Every read goes to `bulk-reader` or `Explore`, but nothing checks that the reader has what these steps require:
  - Bash, to run `bd search`, `bd list` and `bd show`
  - the MCP tools for Notion, Drive and wikis
  - a way to run "skills and commands that fetch knowledge", which a subagent may not be able to invoke

  If it can't, those sources silently disappear from Prior art. I couldn't check `bulk-reader`'s tool list because `~/.claude` was outside my permissions.
  - Fix: let the main session run bd, skills and commands itself, and delegate only the reading of what they return. Alternatively, pick the reader based on which tools it has.
- **Description: triggers overlap with split-plan and build** (see above).

#### Minor (5)
- **SKILL.md line 68: an optional setting can abort the skill.** `init` guards the same call with `|| true`; design doesn't. A missing `design_dir` shouldn't be able to abort the skill.
  - Fix: `` !`${CLAUDE_SKILL_DIR}/../dispatch/scripts/settings.sh design_dir 2>/dev/null || true` ``
  - When the key isn't set, the line also renders as "if set: ; otherwise". Printing `(not set)` would read more clearly.
- **settings.sh line 52: `declare -A` needs bash 4 or later.** macOS ships bash 3.2 at `/bin/bash`, where the script fails. That would abort design, build, status and dispatch unless the call is guarded.
- **settings.sh lines 50–51: extra `bd` calls.** It runs `bd config get` twice even when only `design_dir` is requested. Each design run pays for two `bd` calls it doesn't use. The cost is small.
- **docs/configuration.md line 20 and docs/workflow.md line 26 contradict the skill.** The skill's order for where to write is: the location the request names, then `design_dir`, then the repository's convention, then `docs/design`.
  - `configuration.md` says that without `design_dir` it uses "the location the request names, the repository's convention…", which suggests `design_dir` wins over a location the request names.
  - `workflow.md` lists a different order.
  - Fix: make both docs match the skill.
- **Frontmatter line 6: `effort: high` is unconfirmed.** No other skill in the plugin uses it, including the Opus planning skills split-plan and split-task. I couldn't check it against the skills docs this session.
  - If it's supported, consider the same setting for split-plan and split-task. If not, remove it.

### Positive Aspects
- **Clear boundary:** "not an implementation plan", with tasks and code left to split-plan.
- **The handoff matches split-plan's inputs:** a markdown document (its source 1) or the plan file in plan mode (its source 2).
- **Concrete prior-art vocabulary:** reuse, extend, replace or avoid. "No prior art" is an explicit valid result.
- **Headless and plan-mode paths are handled explicitly,** along with a limit on questions (4 per round, 2 rounds).
- **Only the template sections a request needs** are included, so documents stay short.
- **Follows your model policy:** Opus does the thinking and reading is delegated.

### Overall Rating
Needs Improvement

### Priority Recommendations
1. Add `allowed-tools` for `settings.sh` and guard the line-68 call. Do the same in `build`.
2. Limit external sources in headless sessions to the ones the request names or links.
3. Decide who runs `bd`, MCP tools and fetch skills: the main session or a reader that has them.
4. Tighten the description with trigger phrases and exclusions for split-plan and build.

I only had read tools in this session, so the review is here instead of in a markdown file.
