# External review

Research date: 2026-09-16. Hypothesis only, nothing implemented. Question: how can a project use review skills beyond sdlc's own (Alibaba's Open Code Review, other installed review skills, people, comments on a GitHub pull request), chosen per kind of work, without running them on every review?

## Decided (2026-09-16)

- **Default:** no reviewer. A bead with no review list merges without review, as today.
- **Review lists:** a bead's `review` is a list of reviewers, and they all run at once.
- **Kinds of reviewer:** only `agent`, `human` and `skill`. Without a named skill, `agent` is a plain review prompt, and Claude picks a relevant installed review skill itself.
- **`agent` and `skill` reviewers** run as subagents of the worker session by default.
- **Beads gates** block a task or epic that waits on a review. When a review asks for changes, the worker fixes its own code; a worker stopped for a person's review is resumed first.
- **Defaults per kind of work:** task, epic, pull request.
- **Verdict:** every reviewer's verdict counts, and any reviewer can block the merge. Review skills return structured data.
- **Out of scope:** ultrareview and anything else charged per run. In scope: Open Code Review, GitHub comments and a few installed skills.
- **Changing reviewers:** can happen at any time. For example, a person can be assigned to review a task that turned out too complex or didn't finish.
- **Pull requests:** sdlc acts on comments, but only from a shortlist of trusted accounts, written by hand for now.
- **Finding waiting reviews:** a person looks up the gates assigned to them in beads. A single notification that fans out to other systems comes later.

## Today

- **Levels:** a task's `review` metadata (default `custom.dispatch.review`, itself `none`) is `none`, `agent` or `human`. An epic's `review` metadata applies to the epic diff, in its integration task, and defaults to `none`.
- **`agent`:** `finish-task.sh` runs `claude -p "/sdlc:review <bead>"` inside the worker's own `finish-task.sh` call. It uses a `--json-schema` verdict and `timeout 900`, and requested changes exit 1. That call goes through the worker's Bash tool, which has a 10-minute limit, below the 900-second timeout. The worker's prompt forbids it from reviewing its own change.
- **`human`:** `finish-task.sh` creates a `human` gate, sets `dispatch_state=awaiting-review` and exits 3, and the worker stops. The person runs `/sdlc:review`, which comments and resolves the gate. `resume-reviewed.sh`, run by `watch.py`, then resumes the worker with `resume-task.sh`.
- **Pull requests:** in `epic-pr` mode the integration task opens the pull request with a `gh:pr` gate and ends. Nothing reads comments on it.

## Tools in scope

- **Open Code Review** ships a Claude Code plugin (marketplace `alibaba/open-code-review`, plugin `open-code-review`) with two skills:
  - `open-code-review` runs the `ocr` CLI against a model endpoint you configure.
  - `open-code-review-delegate` uses `ocr` only to pick files and review rules, and the Claude session reviews with its own model. That needs no extra API key.

  Both need the `ocr` CLI installed.
- **Installed review skills:** for example `gitnexus-review`, `caveman-review` and `mattpocock-skills:code-review`. Only model-invocable skills can be picked by an `agent` prompt: roborev's skills say "use only when the user explicitly invokes", so they must be named with `skill:`.
- **GitHub:** reviews and comments on the epic's pull request, from trusted accounts. People, and a bot such as `copilot-pull-request-reviewer[bot]` if the repository's own ruleset has it review pull requests. sdlc never requests a review on GitHub.

## Proposal

### Terms

- **Reviewer:** one entry of a review list:
  - `agent`: a review subagent; Claude picks the review skill
  - `skill:<plugin>:<skill>`: a review subagent told to use that skill
  - `human`: any person
  - `human:<name>`: that person
- **Review list:** the reviewers a bead's diff must pass: `review=skill:open-code-review:open-code-review-delegate,human:alice`. Empty (`none`) by default.
- **Review subagent:** a subagent the worker starts with the Agent tool: the installed `reviewer` agent if there is one, otherwise `general-purpose`. It gets the diff range, the bead's acceptance and the skill to use. It ends with `{verdict, summary, findings[]}`.
- **Verdict:** one reviewer's `approve` or `changes` for one diff, identified by its `git patch-id`. It is stored in the task's metadata and as a bd comment.
- **Review gate:** a `human`-type beads gate that blocks a task until a person has reviewed its diff.

### Choosing reviewers

| Key | Applies to | Default |
|---|---|---|
| `custom.dispatch.review` | a task's diff | `none` |
| `custom.dispatch.review.epic` | the epic diff (`target...epic-branch`), before merging or opening the pull request | `none` |
| `custom.dispatch.pr.trusted` | pull request comments: GitHub logins, written by hand | empty: comments are ignored |

- **Per bead:** `review` metadata overrides the default.
- **At split:** `/sdlc:split` sets `review` on tasks whose risk calls for it: auth, migrations, public API.
- **At any time:** anyone except a worker can edit `review`; the worker hook already denies workers that. `finish-task.sh` reads the list each time it runs, so an added reviewer applies to the next diff reviewed.
- **Assigning a person to a task that isn't finishing:** when a task is stopped, failed, `Can't`, or still has changes requested after 3 rounds, `/sdlc:recover` and `/sdlc:dispatch` offer "Ask a person to review". That adds `human:<name>` and opens a review gate assigned to them straight away. The gate carries what the worker last said, and doesn't wait for a finished diff. When the person resolves it, the worker resumes with their comments.

### Flow for a task

1. The worker commits and runs `finish-task.sh`. With an empty review list, it merges as today.
2. `finish-task.sh` computes the diff's patch id, then checks every reviewer in the list for a verdict on that patch id:
   - **`human` reviewer without an open gate for this patch id:** it opens one, assigned to `<name>` if given (`bd update <gate> --assignee <name>`). Every person's gate opens at the same time as the subagent reviews run.
   - **`agent` or `skill:` reviewer without a verdict:** it exits 1 and lists them: "run these reviewers as subagents, all at once, record each verdict with `record-review.sh`, then run this again."
   - **Any verdict is `changes`:** it exits 1 with the findings, and increments `dispatch_review_rounds`. The worker fixes the code, commits and runs it again. The new patch id means every reviewer reviews again. After 3 rounds it exits 3: a person is needed.
   - **All subagent verdicts approve, but a review gate is still open:** it sets `dispatch_state=awaiting-review` and exits 3. The worker stops.
   - **Every reviewer approved this patch id:** merge queue, rebase, verify, merge, as today.
3. The worker runs the listed reviewers as subagents in one message, so they run in parallel. It passes each subagent's final answer to `record-review.sh`.
4. `record-review.sh <task> <reviewer> <answer-file>` (new) checks the answer has a verdict, summary and findings. It stores the verdict for the task's current patch id, and comments the summary and findings on the task. An answer without a valid verdict exits 1, and the worker runs that reviewer again.
5. **A person** runs `/sdlc:review <task>` on the gate assigned to them. It records the verdict explicitly (`approve` or `changes`, for that patch id), comments, and resolves the gate. Today an approval is inferred from the patch id staying the same after the gate resolves.
6. `resume-reviewed.sh` resumes the worker once none of the review gates blocking its task is open. The worker runs `finish-task.sh` again, which merges or reports the requested changes.

With subagents, a review no longer runs inside a Bash call, so the conflict between the 10-minute Bash limit and the 900-second timeout goes away.

The worker writes the subagent's prompt and records its verdict, so it could shade either. Like the worker hook, this is a guardrail, not a security boundary.

### Epics

An epic's `review` list (default `custom.dispatch.review.epic`) runs in its integration task:
- The integrator runs the subagent reviewers on `target...epic-branch`, against the epic's description and acceptance.
- A person's review gate blocks the integration task: beads doesn't let a gate block an epic.

### Pull requests (`epic-pr`)

- **Collecting:** `pr-comments.sh` (new, run by `watch.py` each round) handles each `pr-opened` integration task. It fetches the pull request's reviews, inline comments and conversation comments newer than the last ones it handled (`dispatch_pr_seen`), and keeps only authors in `custom.dispatch.pr.trusted`.
- **Resuming:** if any trusted comments are new, it copies them to the integration task as bd comments and resumes the integrator. The integrator addresses each comment by fixing and committing, or by replying on the pull request, then runs `finish-task.sh`, which pushes to the same pull request.
- **Why only trusted accounts:** comment text becomes part of the integrator's prompt, and the integrator runs in `--permission-mode auto`.
- **Re-runs:** `finish-task.sh` must not create a second `gh:pr` gate when the pull request is already open. Today it creates one on every run.
- **Merging** stays with people. The `gh:pr` gate and `close-prs.sh` are unchanged.

### Finding waiting reviews

A person lists what waits for them in beads:

```bash
bd list --type gate --assignee <name>
```

A gate without an assignee (plain `human`) shows up in `bd gate list`.

## What changes

| File | Change |
|---|---|
| `scripts/finish-task.sh` | the review inside the worker's own call is replaced: it checks a verdict per reviewer and patch id, opens person gates, and exits 1 to ask for subagent reviews or fixes, or 3 while a gate is open; in `epic-pr`, one `gh:pr` gate per pull request |
| `scripts/record-review.sh` (new) | checks a review subagent's answer and stores its verdict for the task's current diff |
| `agents/worker.md`, `agents/integrator.md` | "don't review" becomes: run the reviewers `finish-task.sh` lists as subagents, all at once, and record each with `record-review.sh` |
| `scripts/resume-reviewed.sh` | resumes once none of the task's review gates is open, instead of checking one gate |
| `scripts/pr-comments.sh` (new), `scripts/watch.py` | copies trusted pull request comments to the integration task and resumes the integrator; `watch.py` runs it each round |
| `skills/review/SKILL.md` | the format a review subagent ends with; a person's verdict is recorded explicitly; the pull request section reads only trusted accounts |
| `skills/recover/SKILL.md`, `skills/dispatch/SKILL.md` | "Ask a person to review" |
| `skills/split/SKILL.md` | sets `review` on risky tasks |
| `../../skills/init/scripts/init.sh`, init skill | sets the scope defaults; proposes installed review skills from `claude plugin list --json` |
| `docs/workflow.md`, `docs/configuration.md` | review lists, scope keys, trusted accounts |

`hooks/worker-guard.sh` doesn't change: it already denies workers `bd gate resolve` and setting `review` or `dispatch_review*` metadata directly. `record-review.sh` is a script, like `finish-task.sh`.

## Build order

Each step works on its own:

1. **Subagent reviewers at task scope:** `agent` and `skill:`, plus `record-review.sh` and `finish-task.sh`'s check. Test with `open-code-review-delegate` and one other installed skill.
2. **People as reviewers:** `human` and `human:<name>` gates, opened at the same time as the subagents; resuming the worker; `/sdlc:review` recording its verdict; "Ask a person to review".
3. **Epic scope**, the scope defaults, and `/sdlc:split` setting `review`.
4. **Trusted pull request comments** in `epic-pr`.

## Later

- **Review in a separate session:** `agent` or `skill:` reviewers run as a detached `claude -p` session with `--json-schema`, instead of in the worker session. A script collects the verdict, and the worker waits behind a gate. This is for reviews the worker shouldn't be able to shade, since it would write neither the prompt nor the recorded verdict.
- **Checking a recorded verdict:** `record-review.sh` could read the verdict from the subagent's own transcript (`<session>/subagents/`), instead of trusting what the worker passes it.
- **Notifications:** one notification point for "a review is assigned to you", fanning out to whatever system a team uses (channels, chat, mail).

## Unconfirmed

- Whether a plugin skill loads and runs inside a subagent, rather than the main session. This is checked first, in step 1.
- A subagent has no `--json-schema`: the verdict format is requested in its prompt and checked by `record-review.sh`.
- Open Code Review's delegate skill: not run here yet. Also not checked whether `ocr` needs configuring beyond installing it.
- Which skill an `agent` prompt picks when several review skills are installed. It isn't controlled; use `skill:` to pin one.

## Sources

- Open Code Review: [alibaba/open-code-review](https://github.com/alibaba/open-code-review): `.claude-plugin/marketplace.json`, `skills/open-code-review/SKILL.md`, `skills/open-code-review-delegate/SKILL.md`
- Copilot as a pull request reviewer: [automatic review](https://docs.github.com/en/copilot/how-tos/copilot-on-github/set-up-copilot/configure-automatic-review); it only leaves `COMMENTED` reviews, as `copilot-pull-request-reviewer[bot]`
- beads: local `bd gate create --help`, `bd gate list --help`, `bd list --help` (`--type gate`, `--assignee`), `bd update --help` (`--assignee`)
- Plugin listing: local `claude plugin list --help` (2.1.273, `--json`)
