---
name: design
description: Turn a product or feature request into a design document that removes ambiguity and fixes contracts, grounded in prior art from the repository, existing beads and (with the user's permission) connected sources such as wikis, Notion or Drive. Output is ready for sdlc:split. Use when starting new work from an idea, before any tasks exist.
argument-hint: "<what to build>"
model: opus
effort: high
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh *), Bash(bd *)
---

# Design

Request: $ARGUMENTS

Produce a design document for this request. The document's job is to remove ambiguity and fix the contracts that separate pieces of work must agree on. It is not an implementation plan: tasks, file-by-file steps and code belong to `sdlc:split`.

Be precise only where two people implementing different parts could otherwise build incompatible things, or where the goal itself is unclear.

## Reading

Run `bd` commands yourself. For everything else — files, documents and external sources — don't read them yourself: delegate the read to a subagent, then think over what it returns. If a `bd` result is large (a long `bd list` or a `bd show` with a long description or many comments), delegate reading that result too, instead of loading it into your own context.
- Pick a reading agent from the available agent types: prefer one made for reading or summarizing large content (for example `bulk-reader`); otherwise use `Explore` with `model: haiku`.
- Tell it exactly what to return: paths, contracts and data shapes verbatim, build and test commands, and anything that conflicts with the request.
- Run independent reads in parallel.

## 1. Find prior art

Prior art is anything that already settles part of the request: earlier designs, docs, code, existing beads, or knowledge that lives outside the repository.

### Sources

**Local sources**, always allowed:
- Earlier designs. `docs/design/` is the default location. Also follow the repository's own conventions, such as `docs/adr/`, `specs/`, `rfcs/` or `design/`.
- `README*`, other documentation, and the code the request touches: entry points, data formats, public interfaces, config, and how the project is built and tested. Skim; don't read everything.
- Existing beads, if the repository uses beads. Run them yourself; read-only commands only: `bd search <terms>`, `bd list`, `bd show <id>`.
- Links given in the request.

**External sources**, which need permission first:
- MCP servers: wikis, Notion, Google Drive, Confluence, issue trackers, chat, mail.
- Skills and commands that fetch knowledge.
- Web search.

Find out which ones are available. Look at the MCP tools, skills and commands in your context, and use tool search with terms such as `notion`, `drive`, `wiki`, `confluence`, `jira`, `slack` to find deferred ones.

### Ask before using external sources

- **When you can ask:** use one AskUserQuestion (`multiSelect`) listing the external sources that look relevant to this request. For each option, say what you would look for there. Offer at most 4; group similar sources if there are more. Consult only the sources the user selects.
- **When you cannot ask** (headless session): use only the external sources the request names or links to. List the rest under Open questions and assumptions instead of consulting them.

### Record what you found

Stop searching once you have enough. For each relevant item, note:
- where it lives: a path, `bead:<id>`, or `<source>:<title or url>`
- what it establishes
- how the new design relates to it: **reuse**, **extend**, **replace** or **avoid**

If nothing relevant exists, say so; that is a valid result.

## 2. Remove ambiguity

List the open points whose answer would change a contract, a goal or the scope. Leave out anything prior art already settles, and anything that is an implementation detail.

- If you can ask the user, use AskUserQuestion: concrete options, recommended option first, at most 4 questions per round and 2 rounds.
- If you cannot ask (headless session, or the tool is unavailable), choose the most reasonable option and record it as an assumption.

## 3. Write the document

**Where to write:**
1. the location the request asks for; otherwise
2. the configured design directory, unless this is blank: !`${CLAUDE_PLUGIN_ROOT}/scripts/settings.sh design_dir 2>&1 || true`; otherwise
3. the repository's existing design-doc convention; otherwise
4. `docs/design/<slug>.md`.

The slug is short kebab-case derived from the request. If a design on the same topic already exists, update it instead of creating a second one.

```markdown
# <Title>

<Summary in 2–4 sentences: what is being built and why.>

## Prior art

- `path` | `bead:<id>` | `<source>:<title or url>`: what it establishes. reuse | extend | replace | avoid.

(or "No prior art.")

<!-- Include only the sections that remove real ambiguity for this request. -->

## Goals and non-goals
## Definition of done
Observable outcomes, not steps.
## Glossary
## Contracts
Interfaces, data shapes, file formats, routes, commands, configuration. Exact wherever several parts must agree.
## Decisions
Each choice, the alternatives rejected, and why.

## Open questions and assumptions

- <question or assumption>: impact if wrong.
```

- Contracts that already exist in prior art are referenced, not restated.
- When this design changes something an earlier design defined, say so explicitly and name the earlier design.

## 4. Report

Print:
- the document path
- a summary of at most three lines
- the assumptions you made

Then suggest `/sdlc:split <document path>` as the next step.

Do not create beads, branches or commits.

If plan mode is active, put the complete document in the plan file, and write it to its location once plan mode ends.
