## Skill Review: setup

### Summary
This is a small, well-built skill: a SKILL.md with a ~220-word body and a single 47-line `check.sh` whose output is inserted into the prompt. I found no critical issues and three major ones. All three are about what happens after the check runs: running it again, installing things that need `sudo`, and telling the user where to find companions. I compared the tool list in `check.sh` with what the dispatch scripts actually call, and it matches. I couldn't run the script because I only had read access, so the notes on version parsing come from reading the code.

### Description Analysis
**Current:** "Check this machine for what sdlc needs (Claude Code, beads, worktrunk, git, jq and a few system tools), offer to install what is missing, and recommend companions… Use once per machine after installing the plugin, or when a dispatch script reports a missing tool."

**Issues:**
- It's about 380 characters, says what the skill does, and gives two clear moments to use it. That's good.
- I didn't flag the "This skill should be used when…" wording from the review template. All 11 skills in this repo use the imperative "…. Use when…" style, and consistency matters more.
- It doesn't include the error text that would actually trigger the skill, like "`bd`/`wt` not found". It also says "Claude Code" where it means the `claude` CLI on PATH, which isn't the same thing (see Minor).

**Recommendations:**
- Suggested description: "Check this machine for what sdlc needs (the `claude` CLI, beads, worktrunk, git, jq and a few system tools), offer to install what is missing, and recommend companions such as rtk, a reading agent, a reviewer agent and specialist agents. Use once per machine after installing the plugin, when a dispatch script reports a missing tool, or when `bd`, `wt` or `claude` is not found."

### Content Quality

**SKILL.md Analysis:**
- Word count: ~220. That's right for a skill that runs a check and reports. The template's 1,000–3,000 words is meant for knowledge skills; don't pad this one.
- Writing style: imperative, plain, and matches `init`.
- Organization: Report → Required → Companions → Next. Clear, with one ordering problem (the OS note, see Minor).

### Progressive Disclosure

**Current Structure:**
- SKILL.md: ~220 words
- references/: 0
- examples/: 0
- scripts/: 1 (`check.sh`), run through `` !`cmd` `` and pre-approved in `allowed-tools`

**Assessment:** This is right. The script's source never enters the context, and it always exits 0, so the inserted command can't abort the skill. You don't need references/ or examples/.

### Specific Issues

#### Critical (0)

#### Major (3)
- **SKILL.md:25, "run the check again": the skill never gives the command.** The `` !`…` `` block is replaced by its output, so the model never sees the script path. It has to rebuild the path itself. `allowed-tools` only approves the exact string `${CLAUDE_SKILL_DIR}/scripts/check.sh`, so a rebuilt variant (`bash …/check.sh`, a relative path) triggers a permission prompt. `init` avoids this by naming its script.
  Fix: "…then run `${CLAUDE_SKILL_DIR}/scripts/check.sh` again."
- **SKILL.md:23–25, installs that need `sudo`.** The Debian line leads straight to `sudo apt install …`. The Bash tool can't answer a password prompt, so the install hangs or fails.
  Fix: add "For commands that need `sudo` or a password, don't run them: give the command and ask the user to run it (for example with `! <command>` at the prompt)."
- **SKILL.md:31, "say … how to find it" with no sources.** Required tools come with URLs, but companions don't, so the model will guess. For rtk that's a real risk: RTK.md warns about a different `rtk` (Rust Type Kit). The skill also allows installing companions, but there's nothing to install from.
  Fix (keep it small): list the URLs you want cited, e.g. `rtk: <repo URL> (not reachingforthejack/rtk)`. For the reading, reviewer and specialist agents, say what role each fills and drop "how to find it". Or make companions recommend-only and remove "Don't install companions without the user's OK".

#### Minor (7)
- **check.sh:40, rtk false positive.** `command -v rtk` reports "installed" even when the wrong `rtk` is installed. Use `rtk gain >/dev/null 2>&1`, which is the check RTK.md itself suggests.
- **check.sh:9–13, usage doesn't match the output.**
  - The usage documents `missing <tool> <why>`, but lines 25 and 36 print only `missing <tool>`.
  - The `os` line isn't documented.
  - The `specialist-agents` line has no status word.
  - Fix the usage text; there's no need to add `why` to the output.
- **check.sh:39, 45, project-relative checks in a per-machine skill.** `.claude/agents` depends on the current directory. If it's run from `$HOME`, line 45 counts each agent twice. SKILL.md:31 already counts agent types available in the session, which covers project agents. Check only `~/.claude/agents`.
- **SKILL.md:27, the non-Linux note comes last.** On macOS the model walks through installing `bd`/`wt` and only then says dispatch won't run. Move it to step 1: "If the `os` line isn't Linux, say so first: dispatch won't run, though the planning skills still can."
- **SKILL.md:25, "headless session" isn't defined.** `init` defines it as "If AskUserQuestion isn't available (headless session)". Use the same test here.
- **SKILL.md:22, `missing claude` is confusing when run from inside Claude Code.** Add one clause: workers need the `claude` CLI on PATH, even when this session runs in an IDE or the desktop app.
- **check.sh:27, an unreadable version passes as ok.** If the version command prints nothing the regex matches, the tool shows as `ok <tool> present` and the minimum version is never checked. Printing `ok <tool> version unknown` would make that visible. Optionally, add a one-line comment on lines 31–35 naming the feature that sets each minimum (e.g. which `bd` subcommand needs 1.2.2).

### Positive Aspects
- The required tools match what the scripts really use:
  - `setsid`: run-task and resume-task
  - `uuidgen`: run-task
  - `pgrep`: workers, watch and resume-task
  - `timeout`: finish-task
  - `gh`: only in epic-pr code paths
- The output uses a small fixed set of prefixes (`ok`/`missing`/`old`/`optional`/`recommended`), so the model groups results without guessing.
- "An agent type available in this session counts as installed, even under another name" handles cases the script can't see, such as plugin-provided or renamed agents.
- Installs need the user's consent, and headless runs install nothing.
- It fits the repo's pattern: numbered steps, a script that's run rather than read, and a Next step that points to `/sdlc:init` (and `init` points back).

### Overall Rating
Needs Improvement. The fixes are small, mostly one-line edits.

### Priority Recommendations
1. Name the script path in the re-check step (SKILL.md:25).
2. Hand `sudo` installs to the user instead of running them (SKILL.md:25).
3. Give companion sources or make companions recommend-only, and fix the rtk false positive (SKILL.md:31, check.sh:40).
