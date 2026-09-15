I didn't change anything; this review is inline because I have no write tool here. The skill's main text is sound, but one bug in a shared script will break `/sdlc:status` and `/sdlc:dispatch` once the project grows.

## Skill Review: status

### Summary
`skills/status/` has no `scripts/` folder. It runs three scripts that belong to the dispatch skill: `workers.sh`, `next-tasks.sh` and `settings.sh`. I reviewed those as the skill's scripts.

- **SKILL.md body:** about 40 words. The 1,000–3,000 word guideline doesn't apply to a skill that only prints script output; short is right here.
- **Shape:** the same as `logs` and `stats`: read-only, the user runs it (Claude never picks it on its own), and it prints script output.
- **Rating:** Needs Improvement. There is one latent failure in a script, one wrong next step in the text, and two hardening gaps.

### Description Analysis
**Current:** "Show dispatched work at a glance, read-only. Lists where workers run, crashed or stopped tasks, the ready queue in work order, and the dispatch settings."

Because of `disable-model-invocation: true`, the description is only shown in the `/` menu, so trigger phrases and "This skill should be used when…" wording don't matter.

**Issues:**
- It leaves out failed tasks and tasks waiting on a pull request (`pr-opened`), which `workers.sh` also lists.
- It says "dispatch settings", but `settings.sh` also prints `design_dir` and `workflow`.

**Suggested:** "Show dispatched work at a glance, read-only. Lists running, crashed, stopped and failed workers, tasks waiting on a pull request, the dispatch queue in work order, and the sdlc settings."
(Don't write "read-only: running…". A colon followed by a space inside an unquoted YAML value breaks the frontmatter.)

### Content Quality
- **Writing style:** direct and imperative, the same as `logs` and `stats`.
- **Organization:** one section per script, then one instruction. Fine.
- **Content issues:** the next step it suggests for stopped and failed tasks is wrong (Major 1).

### Progressive Disclosure
- **Files:** SKILL.md (about 40 words); no `references/`, `examples/` or `scripts/`.
- **Scripts it runs:** `workers.sh` (105 lines), `next-tasks.sh` (70), `settings.sh` (62), all from `skills/dispatch/scripts/`.
- **Assessment:** fits the skill. Running the scripts inline keeps their code out of context, and reusing dispatch's scripts avoids a second copy.

### Specific Issues

#### Critical (1)
- **`skills/dispatch/scripts/next-tasks.sh:37-40`: the whole beads database is passed to jq as one command-line argument.** It works today and will fail later.
  - Linux limits a single argument to 128 KiB. `bd list --all` includes closed issues and one event bead per worker attempt, and that bead holds the worker's final message. The data only grows.
  - Past that size, jq can't start ("Argument list too long", exit 126). `set -e` then stops the script, and the failed command aborts `/sdlc:status`. It also breaks `/sdlc:dispatch` step 1.
  - `skills/stats/scripts/stats.sh:24` has the same pattern.
  - **Fix:** pipe both outputs into jq instead:
    ```bash
    ordered=$({ bd list --all --limit 0 --json; bd ready --limit 0 --json; } |
      jq -n --arg only "$epic" 'input as $all | input as $ready | ...')
    ```
    Move `def epic_of` and `def started` below the `input as` lines, because `started` uses `$all`. `pipefail` still reports a `bd` failure.

#### Major (3)
1. **`SKILL.md:22`: the wrong next step for stopped and failed tasks.**
   - Dispatch's own instructions say "Don't dispatch it again yourself" for those tasks, so it would only report them back.
   - "Add one line naming it" is also unclear when several tasks need attention.
   - **Replace with:**
     > Show the three sections above to the user unchanged, in code blocks. Then add one line per task that needs attention:
     > - crashed: `/sdlc:dispatch` resumes it or says why it can't.
     > - stopped or failed: its last comment says why. `/sdlc:logs <task>` shows what the worker did. Next step: clarify the task, `/sdlc:split-task <task>`, or fix it by hand in its worktree.
     >
     > Don't run anything else.
2. **`SKILL.md:12,16,20`: if any script fails, the whole skill aborts.**
   - A failing `!` command aborts the skill, so one broken section hides the other two. Error output isn't captured either.
   - Realistic triggers: no beads workspace yet (before `/sdlc:init`), running outside a git repo (`workers.sh:37`), or the Critical bug above.
   - **Fix:** add `2>&1 || true` to each of the three commands (`logs` already uses `2>&1`). Run the skill once afterwards to confirm the permission rule still matches.
3. **`SKILL.md:5`: the permission rule allows every dispatch script.**
   - `Bash(.../dispatch/scripts/*)` also covers scripts that start, resume, merge and close work: `dispatch-next.sh`, `run-task.sh`, `resume-task.sh`, `finish-task.sh`, `merge-queue.sh`, `close-prs.sh`.
   - The only thing keeping the skill read-only is the sentence "Don't run anything else." `logs` and `stats` each allow a single script.
   - **Fix:** list only the three scripts status runs:
     `Bash(${CLAUDE_SKILL_DIR}/../dispatch/scripts/workers.sh), Bash(${CLAUDE_SKILL_DIR}/../dispatch/scripts/next-tasks.sh), Bash(${CLAUDE_SKILL_DIR}/../dispatch/scripts/settings.sh)`

#### Minor (5)
1. **`SKILL.md:22`: output formatting.** `workers.sh` uses two-space columns and indented detail lines. If Claude repeats them as normal text, the spacing collapses. The replacement text in Major 1 asks for code blocks.
2. **Frontmatter: no `model:` line.** The skill only repeats output and adds a line per task. `model: haiku` fits your cheapest-model rule, and `dispatch` already sets `model: sonnet`.
3. **`SKILL.md:14`: "Ready queue" doesn't show every ready task.** `next-tasks.sh` hides tasks that have no `metadata.verify` (unless they're integration tasks) and tasks that have children. A hand-made task without a verify command never appears, and nothing says why. Rename the header to "Dispatch queue" or add a note about the filter.
4. **`workers.sh:66-69`: tasks running on another machine can show as crashed.** "Crashed" only means no worker process runs on this machine; `dispatch_host` is never compared with `uname -n`. If beads is ever shared between machines, the skill would then suggest `/sdlc:dispatch`, which would start a second worker on the same task. There's no remote today, so this is conditional.
5. **`workers.sh:97`: one failing lookup can stop the listing.** If `bd comments` fails, the script exits partway through the list despite the `2>/dev/null`, because a variable assignment keeps the pipeline's failure. Add `|| true`.

### Positive Aspects
- Running the scripts inline keeps script code out of context, and Claude doesn't need to call any tools.
- It reuses dispatch's scripts, so status and dispatch always show the same states.
- `disable-model-invocation` is right for a dashboard the user runs.
- The scripts have `--help` text and documented exit codes. `settings.sh` handles a missing git repo and unset bd config.
- For crashed tasks, `workers.sh` prints evidence (worktree, commits, transcript, last events, errors) that is enough to decide without reading logs.

### Overall Rating
Needs Improvement

### Priority Recommendations
1. Stop passing the beads data to jq as an argument in `next-tasks.sh`, and in `stats.sh` too.
2. Fix the next steps for stopped and failed tasks: `/sdlc:logs`, clarify, `/sdlc:split-task`, or fix by hand. Keep `/sdlc:dispatch` only for crashed tasks.
3. Add `2>&1 || true` to each command and limit `allowed-tools` to the three scripts.
