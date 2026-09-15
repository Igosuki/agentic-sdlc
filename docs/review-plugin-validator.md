No critical issues. The plugin passes, with 4 major and 6 minor warnings. Bash was blocked in this session, so I checked everything by reading files. That means I couldn't check file permissions or list directories (see "Not verified" at the end).

## Plugin Validation Report

### Plugin: sdlc
Location: `/home/geps/dev/claude-sdlc`

### Summary
The manifest, marketplace entry, all 11 skills and `hooks/hooks.json` have valid structure. Every script that a hook or skill calls exists. The warnings are about skill permissions, one path that leaves a task in a bad state, and wording that has fallen out of date.

### Critical Issues (0)

### Warnings (10)

**Major**

1. **`skills/status/SKILL.md:12,16` and `skills/stats/SKILL.md:11`: these views abort in a project without beads.** Their `` !`cmd` `` scripts (`workers.sh:37-40`, `next-tasks.sh:37-38`, `stats.sh:21-22`) use `set -euo pipefail`. They exit non-zero when `bd list` or `git rev-parse` fails. According to your saved skills note, a failing `!` command stops the skill. So `/sdlc:status` shows a raw error instead of pointing to `/sdlc:init`.
   - Fix: add `2>&1 || true`, as `init` and `logs` already do. Or have the scripts print "beads not initialized" and exit 0.

2. **Some `!` commands and script calls aren't covered by `allowed-tools`:**
   - `skills/design/SKILL.md:68` runs `settings.sh design_dir`, and the skill has no `allowed-tools`.
   - `skills/build/SKILL.md:12` runs `settings.sh`, and the skill has no `allowed-tools`.
   - `skills/init/SKILL.md:14` runs `../dispatch/scripts/settings.sh`, but its `allowed-tools` only covers `init.sh` and git.
   - `skills/dispatch/SKILL.md:55` calls `../stats/scripts/stats.sh`, which `Bash(${CLAUDE_SKILL_DIR}/scripts/*)` doesn't match.

   Slash commands need matching `allowed-tools` for `!` commands. I couldn't confirm that skills follow the same rule. Your tests wouldn't show the problem: `tests/wild/run.sh:20` runs design and split with `--dangerously-skip-permissions`.
   - Fix: add entries such as `Bash(${CLAUDE_SKILL_DIR}/../dispatch/scripts/settings.sh*)`, then run `/sdlc:design` once with normal permissions.

3. **`skills/dispatch/scripts/run-task.sh:115-128`: a failed worktree creation leaves a task that looks crashed.** The task is claimed (`dispatch_state=running`, session set) before `wt switch` runs. If `wt switch` fails, the task shows as crashed and `resume-task.sh` refuses it ("no worktree"). Recovery then needs the user to approve a manual reopen.
   - Fix: keep claiming first, since that stops two supervisors taking the same task. When the worktree step fails, undo the claim with `bd update <id> --status open --unset-metadata dispatch_state --unset-metadata dispatch_session …`.

4. **Security: anyone who can write to beads can run commands on the machine that dispatches.** Workers run with `--permission-mode auto` (`run-task.sh:183`), and their prompts are built from the bead's title, description and acceptance (`run-task.sh:154-163`). `finish-task.sh:79` runs `metadata.verify` with `bash -c`. Because the beads database is shared through Dolt, a write to it is effectively a command run by the worker.
   - Recommendation: this is by design, but state it under "Worker permissions" in `docs/configuration.md`.

**Minor**

5. **`hooks/worker-guard.sh:14-21`: the deny rules are easy to get around.** `git -C <dir> push`, `/usr/bin/bd close` and `gh pr merge` all get through. It works as a guardrail, not a security boundary.
   - Fix: allow options between `git` and `push`, and add `gh pr merge`. Or describe it as a guardrail in the docs.

6. **`hooks/session-start.sh:12`: slow start for every session.** The hook runs in every session of every project where the plugin is enabled. It calls `settings.sh workflow`, which always runs `bd config get` twice (`settings.sh:47-52`), even though `workflow` only comes from `.claude/sdlc.local.md`.
   - Fix: compute only the key that was asked for, or check that the local file exists before calling `settings.sh`.

7. **`skills/dispatch/scripts/watch.sh:86-89`: epic-pr work can stay open after the PR merges.** The watch prints `idle` and exits while a `pr-opened` task is still waiting. `close-prs.sh` only runs inside `watch.sh`, so the task and epic stay open until someone runs `/sdlc:dispatch` again. The dispatch report (`SKILL.md` step 5) doesn't mention open PRs.
   - Fix: list open PRs in the report with "run `/sdlc:dispatch` after merging". Or keep the watch running while a `pr-opened` task exists.

8. **`skills/dispatch/scripts/settings.sh:16`: incomplete help text.** It says integration is "direct or epic-merge" and leaves out `epic-pr`.

9. **`skills/init/SKILL.md:4`: `argument-hint` leaves out `--design-dir`**, which `init.sh` accepts.

10. **`.claude-plugin/plugin.json` and `marketplace.json` both set version `0.1.0`.** The two can drift apart. Keep the version in `plugin.json` only, or bump both together. You could also add `repository`/`homepage` to `plugin.json`; the README already uses `github.com/Igosuki/claude-sdlc`.

### Component Summary
- **Commands:** 0 (no `commands/`)
- **Agents:** 0 (no `agents/`)
- **Skills:** 11 found, 11 structurally valid: setup, init, build, design, split-plan, split-task, create-task, dispatch, status, stats, logs
- **Hooks:** present and valid. SessionStart, PreToolUse (Bash) and Stop each call a script, and all three scripts exist.
- **MCP servers:** 0

### Positive Findings
- **Manifest:** valid JSON, kebab-case name, semver, license and keywords. The `marketplace.json` source `./` points to the plugin.
- **Skills:**
  - Each skill's `name` matches its directory.
  - Skills Claude can invoke on its own have "Use when…" descriptions.
  - `status`, `stats` and `logs` are read-only views set to `disable-model-invocation: true`.
- **Hooks:**
  - They use `${CLAUDE_PLUGIN_ROOT}`, read stdin, and exit early outside worker sessions.
  - They output valid `hookSpecificOutput` or `decision: block` JSON.
  - The Stop hook checks `stop_hook_active`, so it can't block forever.
- **Scripts:**
  - They follow the conventions in `docs/development.md`: `--help`, exit 2 with all problems listed, and JSON handled with `jq`.
  - Logs are parsed line by line, so a truncated line doesn't break them.
  - `create-task.sh:73-75` checks that ids exist before `bd dep add`, which would otherwise quietly accept unknown ids.
- **Security:** no hardcoded credentials, no MCP endpoints, and workers never use `--dangerously-skip-permissions`.
- **Docs:** `LICENSE` exists, and every doc the README links to exists.

### Recommendations
1. Make the `status` and `stats` `!` commands tolerate a missing beads database (#1).
2. Add `allowed-tools` for the `settings.sh` and `stats.sh` calls, then run `/sdlc:design` and `/sdlc:build` once without skipping permissions (#2).
3. Undo the claim in `run-task.sh` when creating the worktree fails (#3).
4. Document the beads trust boundary (#4).
5. Fix the minor wording and version issues (#8–10) the next time you touch those files.

### Not verified
- **Executable bits.** The hooks call `hooks/*.sh` directly, so a missing `+x` breaks them. Check with: `git ls-files -s hooks skills | grep '\.sh$' | grep -v '^100755'`
- **Stray files** (`.DS_Store`, `node_modules`) and any extra files under `skills/*/`, since I couldn't list directories.

### Overall Assessment
**PASS.** The structure, manifest, skills and hooks are valid, and nothing referenced is missing. Warnings #1–3 affect how it behaves in real use and are worth fixing before a wider release.
