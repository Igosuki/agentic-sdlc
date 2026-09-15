## Skill Review: init

### Summary
The design is right: `init.sh` does the work and SKILL.md only makes the choices. But the instructions in SKILL.md work against the script's keep-or-set logic. On a re-run, following them changes shared settings nobody asked to change. The script also has one bug that can damage the user's `.gitignore`.

- SKILL.md body: about 250 words. `scripts/init.sh`: 99 lines. There's no `references/` or `examples/`, and none are needed.
- The usual 1,000–3,000 word guideline doesn't apply to a skill this small that mostly runs a script. Don't pad it.

### Description Analysis
**Current:** "Prepare the current project for sdlc. Initializes beads, sets the integration mode and target branch, creates .claude/sdlc.local.md, and ignores local files. Safe to run again. Use in a project before its first design or dispatch, or to change these settings." (about 255 characters)

**Issues:**
- It doesn't mention `parallel`, `design_dir` or `workflow: build`. A request like "set parallel to 3" or "route new work to build" won't clearly match it.
- "Safe to run again" isn't true today (see Critical 1).
- The wording ("Use when…") differs from the "This skill should be used when…" template, but every skill in this repo uses it. Keep the repo's style.

**Suggested description:** "Prepare the current project for sdlc: initialize beads, set the integration mode (direct, epic-merge, epic-pr) and target branch, write .claude/sdlc.local.md (parallel, design_dir, workflow) and ignore local files. Safe to run again. Use before a project's first design or dispatch, or to change the integration mode, target branch, parallel limit, design directory or build routing."

### Content Quality
- **Writing style:** imperative and plain, same as the other skills.
- **Organization:** four numbered steps that match the flow. Easy to follow.
- **Problems:** the rules for choosing values (step 1) and the "Current settings" block it relies on (details below).

### Progressive Disclosure
- SKILL.md: about 250 words. `scripts/`: 1 file. `references/` and `examples/`: none.
- This works. Logic lives in the script, and SKILL.md injects the current state and handles the questions. No changes needed.

### Specific Issues

#### Critical (2)

1. **SKILL.md:18–26: re-running, or running headless, overwrites saved settings.**
   - **Headless:** the headless rule says to "use the defaults: `direct`, the current branch, and no workflow routing". Step 2 then passes those as options, so `init.sh` changes them (init.sh:61–66). A project on `epic-pr` targeting `main` gets switched to `direct`, retargeted to whatever branch is checked out, and possibly loses `workflow: build`.
   - **Interactive:** it's the same problem. The skill asks every question the arguments don't answer, and recommends `direct` and "the current branch" instead of the saved values. Running `/sdlc:init --parallel 3` from a feature branch and accepting the recommended answers retargets the repo.
   - **Why it matters:** `custom.dispatch.*` lives in the beads database, shared by everyone who dispatches this repo (docs/configuration.md:27). This also contradicts init.sh:9 ("changes a setting only when an option asks for it") and docs/configuration.md:3.
   - **Fix:**
     - Headless: pass only the options in `$ARGUMENTS`. The script already fills in defaults for unset values and keeps saved ones.
     - Interactive: ask only about settings that aren't saved yet. If you do ask about a saved one, list its saved value first as the recommended option.
     - Say what "no" means for build routing: skip `--workflow` on a first run, pass `--workflow none` to remove a saved `workflow: build`.

2. **init.sh:96: appending to a `.gitignore` with no final newline breaks its last line.**
   - `echo "$line" >> .gitignore` sticks the new entry onto the last line. For example, `.env` becomes `.env.claude/*.local.md`. Now `.env` isn't ignored anymore, and the next `git add -A` can commit secrets.
   - **Fix:** add a newline first when the file doesn't end with one:
     ```bash
     [[ ! -s .gitignore || -z "$(tail -c1 .gitignore)" ]] || echo >> .gitignore
     ```

#### Major (4)

3. **init.sh:42,47: settings are written to the wrong checkout when run from a worktree.**
   - `init.sh` uses `git rev-parse --show-toplevel`, which is the worktree's own root.
   - `settings.sh:31` and the SessionStart hook read `.claude/sdlc.local.md` from the main checkout (via `--git-common-dir`).
   - Run from a `wt` worktree, the settings file lands where nothing reads it, and the `.gitignore` change goes onto that worktree's branch.
   - **Fix:** find the root the same way `settings.sh` does.

4. **init.sh:76–85: `set_key` says "set" even when it wrote nothing.**
   - The awk script only edits inside a frontmatter block that starts on line 1.
   - If the file has no frontmatter (the user made it by hand), the frontmatter isn't closed, or it has CRLF line endings (`---\r`), the file comes back unchanged. The script still prints `set parallel: 3 in …`.
   - **Fix:** if line 1 isn't `---`, exit 1 with an error. After the awk step, check that the key line is actually there.

5. **SKILL.md:13–14: "Current settings" shows defaults as if they were saved.**
   - `settings.sh` fills in defaults (`integration=direct`, `target=main`). In a fresh repo on `master`, the skill sees `target=main` and can't tell "saved" from "not set". That's exactly what Critical 1's fix depends on.
   - The skill also recommends "the current branch" but never shows it. The only git read it's allowed is `git status`.
   - **Fix:** show the raw values and the current branch, e.g. `` !`{ bd config get custom.dispatch.integration; bd config get custom.dispatch.target; git branch --show-current; } 2>&1 || true` ``. Keep `settings.sh` for `parallel`, `design_dir` and `workflow`.

6. **SKILL.md:6,34: the commit can include unrelated changes, and `allowed-tools` pre-approves any commit.**
   - `git add .gitignore && git commit -m …` also commits anything the user had already staged.
   - `Bash(git commit *)` pre-approves `--amend`, `-a` and so on.
   - `Bash(git status *)` is allowed but never used.
   - **Fix:** use `git commit -m "Ignore sdlc local files" -- .gitignore` and allow exactly that command in `allowed-tools`. Either use `git status` (see Minor 2) or remove it.

#### Minor (6)

1. **SKILL.md:5,30: `--parallel` and `--design-dir` can get lost.**
   - `argument-hint` doesn't list `--design-dir`.
   - Step 2 says "the chosen options" but doesn't say to pass along `--parallel` and `--design-dir` from the arguments.

2. **SKILL.md:34: the commit question looks at the wrong signal.**
   - It only asks when `init.sh` printed "added", but `bd init` edits `.gitignore` too. This repo's `.gitignore` has a block "added by bd init".
   - "`bd init` commits the beads files itself" needs checking against beads.
   - **Fix:** decide what to offer from `git status --porcelain -- .gitignore .beads`.

3. **init.sh:65,48: a detached HEAD or a repo with no commits isn't handled.**
   - On a detached HEAD, `git branch --show-current` is empty, so the target is set to `""` (`set custom.dispatch.target=`).
   - In a repo with no commits, `--target main` fails with "no branch main", even though that's the branch the skill recommends.
   - **Fix:** exit 2 with a clear message in both cases.

4. **init.sh:50–53: a missing `bd` gives an unhelpful error.**
   - The script prints `error: bd init failed` without saying `bd` isn't installed.
   - SKILL.md:38's "if `/sdlc:setup` hasn't been run" can't be checked by the model.
   - **Fix:** check `command -v bd` and say "run /sdlc:setup". Suggest setup only when the script reports a missing tool.

5. **init.sh:92: `.worktrees/` may not be needed.** Nothing in the plugin puts worktrees there; `run-task.sh:121–123` uses `wt switch` with worktrunk's own path setting. Check worktrunk's default, then either set that path or drop the entry.

6. **init.sh:17: output doesn't match the documented "one line per step".**
   - When the file already exists and no options are given, step 3 prints nothing.
   - On a fresh file, `--parallel 3` prints both `created … (parallel: 3)` and `set parallel: 3`.
   - `--workflow none` prints `set workflow: none` even though it removed the key.
   - `epic-pr` without a git remote or `gh` gets no warning.

Outside this skill: the help text in `settings.sh:16` lists integration as "direct or epic-merge" and leaves out `epic-pr`.

### What to keep
- The script does all the changes; SKILL.md only chooses. `tests/wild/dispatch.sh:19` runs the script directly.
- Argument checks report every error at once, exit codes are documented, and there's a `--help`.
- The `!` injection ends in `|| true`, so a failing `settings.sh` doesn't abort the skill.
- The script already keeps saved values unless an option changes them. Fixing Critical 1 is just a matter of SKILL.md relying on that.
- `allowed-tools` is tightly scoped except for `git commit`, and the headless path is accounted for.

### Overall Rating
**Needs Improvement.** The structure is fine; the problems are in how the steps behave.

### Priority Recommendations
1. Stop passing defaults on re-runs and headless runs (SKILL.md:18–26), and show raw saved values plus the current branch (SKILL.md:14).
2. Add the missing newline before appending to `.gitignore` (init.sh:96).
3. Find the root through `--git-common-dir`, and make `set_key` exit 1 when it can't write (init.sh:42, 76–85).
4. Commit only `.gitignore` and narrow `allowed-tools` to that command (SKILL.md:6,34).
