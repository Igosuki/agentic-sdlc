## Skill Review: logs

### Summary
`/sdlc:logs` is a user-only wrapper (`disable-model-invocation: true`). It runs `skills/dispatch/scripts/logs.sh` through `!` and shows the output. `skills/logs/` has no `scripts/` directory of its own; the script is in `dispatch`, next to the scripts that write the logs, so that's the script I reviewed.

- SKILL.md body: about 60 words. Description: 138 characters.
- logs.sh: 80 lines. The field names it reads (`target`, `payload.session`) match `record-task.sh`, `stats.sh` and `docs/beads.md`.

The overall design fits the other report skills. I found one hang, one fragile truncation step and one hint that may not work.

### Description Analysis
**Current:** "Show what the workers of a dispatched task did, for each attempt: messages, tool calls, results and cost, from the worker logs. Read-only."

**Issues:** None that matter. Because model invocation is disabled, the description is only the text in the `/` menu. The usual rules about trigger phrases and "This skill should be used when…" don't apply. Matching the style of `stats` and `status` is the right call.

**Optional:** Mention when to reach for it, so it's easier to tell apart from `/status` in the menu: "…from the worker logs, e.g. to see why a worker crashed or stopped. Read-only."

### Content Quality
- **Word count:** About 60 words. The 1,000–3,000 word guideline is for skills that teach Claude a task. A skill that just shows a script's output should be this short.
- **Writing style:** Plain and direct, like the sibling skills.
- **Organization:** One command, then one instruction. "Don't run anything else" keeps the model from going further.

### Progressive Disclosure
- SKILL.md: about 60 words. references/: none. examples/: none. scripts/: none (it uses `../dispatch/scripts/logs.sh`).
- **Assessment:** Works as intended. The script's output enters the context, never its source. Using `../dispatch` instead of `${CLAUDE_PLUGIN_ROOT}` also keeps plain-skills installs working, which `run-task.sh:185` supports.

### Specific Issues

#### Critical (0)

#### Major (3)

1. **Passing `--follow` hangs the skill** (`logs.sh:77-80`, `SKILL.md:11`).
   - The skill's own hint mentions `--follow`, so `/sdlc:logs <id> --follow` is a likely thing to try.
   - With that flag, `tail -n 0 -F` never exits. `| tail -80` waits for input to end, so the `!` step never returns.
   - **Fix:** after argument parsing (`logs.sh:36`), refuse `--follow` when stdout isn't a terminal:
     ```bash
     if $follow && [[ ! -t 1 ]]; then echo "error: --follow needs a terminal" >&2; exit 2; fi
     ```

2. **`| tail -80` in the `!` line has three problems** (`SKILL.md:11`).
   - **Permissions:** `allowed-tools` only allows `logs.sh *`. Claude Code checks each part of a piped command separately, so `tail` may not be approved, and a refused `!` command aborts the skill. `stats` and `status` call their scripts without a pipe. I didn't test this; if `/sdlc:logs` already runs without a prompt, this point is moot and the other two still apply.
   - **Silent cut:** The model is told only the last 80 lines are kept, but it can't tell whether anything was actually cut.
   - **Lost session:** The cut can drop the `═══ <task> · session <id>` header. The remaining lines then belong to no visible session, and the `claude --resume <session>` hint can't be filled in.
   - **Fix:** Move the truncation into the script with a `--last N` option:
     - If the output is longer than N lines, print `(K earlier lines omitted)`.
     - Repeat the header of the session the first kept line belongs to.
     - The `!` line becomes `logs.sh --last 80 $ARGUMENTS 2>&1`, and the SKILL.md sentence about 80 lines can go.

3. **The resume hint may not work as written** (`SKILL.md:13`, also `docs/workflow.md:119`).
   - Session transcripts are stored per project directory. Workers ran in their worktrees, which is why `resume-task.sh:63,86` searches `~/.claude/projects` and `cd`s into the worktree before resuming.
   - Run from the main checkout, `claude --resume <session> --fork-session` may not find the session.
   - For merged tasks, `record-task.sh:92` has already removed the worktree, so there's no directory to `cd` into.
   - I didn't check this. Test it once from the repo root on a merged task. If it fails, point to the transcript file (`find ~/.claude/projects -name <session>.jsonl`) or give the directory to run from.

#### Minor (5)

- **Multi-line entries use up the 80 lines** (`logs.sh:51-52`).
  - Tool results are collapsed to one line (`gsub("\\s+"; " ")`), but assistant text and tool inputs aren't.
  - A worker's final summary, a `git commit` heredoc, or subagent text from `--forward-subagent-text` can take dozens of lines. The extra lines also lose the 4-space subagent indent.
  - **Fix:** Collapse tool inputs the same way, and cap or indent text.
- **A failed worktree creation shows no reason** (`logs.sh:72-73`). `run-task.sh:115` sets `dispatch_session` before `wt switch`. If `wt switch` fails, only `<log>.wt` exists, and logs.sh prints `(no log at …)`. Print `$log.wt` when the `.jsonl` file is missing.
- **Costs are easy to over-count** (`logs.sh:58`). Each `result` line carries the run's running total, not that step's cost (`record-task.sh:44-46`). A run with several result lines shows growing totals that a reader may add up. Label the figure as a running total, or show only the last result of each run.
- **`--raw` help is inaccurate** (`logs.sh:14`). It says "print the log files", but `ls` only lists their paths. Change it to "list the log files of each attempt".
- **"In a terminal" is incomplete** (`SKILL.md:13`). The script needs `git rev-parse` and `bd`, so it must run from inside the repository (any worktree works). Say "from the repository".

### What works
- **Low cost, read-only:** The script's output is injected directly, the script never enters the context, and the model is told to run nothing else.
- **Complete session list:** It combines the sessions from past events with the current `dispatch_session`, removing duplicates in order. This covers a first attempt that is still running (no event yet), reopened tasks, and resumed runs, which keep the same session.
- **Survives killed workers:** Lines are parsed one at a time with `fromjson?`, so a line cut off by a killed worker doesn't break the output. `record-task.sh` does the same.
- **Works from any worktree:** `--git-common-dir` finds the logs from the main checkout or any worktree.
- **Script basics:** The script has `--help` and documented exit codes, and rejects unknown options and a second task id.

### Overall Rating
Needs Improvement

### Priority Recommendations
1. Make `logs.sh` refuse `--follow` when stdout isn't a terminal. This removes the hang.
2. Replace `| tail -80` with a `--last N` option in `logs.sh` that keeps the session header and says how many lines were left out. This also makes the `!` line match the `allowed-tools` pattern.
3. Run the `claude --resume <session> --fork-session` hint from the repo root on a merged task. If it fails, fix both `SKILL.md:13` and `docs/workflow.md:119`.
