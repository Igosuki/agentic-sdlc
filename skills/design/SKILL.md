---
name: design
description: State a design for a product or feature request in the session, removing ambiguity and fixing the contracts that separate pieces of work must agree on, grounded in prior art from the repository, existing beads and (with the user's permission) connected sources such as wikis, Notion or Drive. Edits existing docs where the design makes them wrong or incomplete; writes a new document only if asked. Follow with sdlc:split in the same session. Use when starting new work from an idea, before any tasks exist.
argument-hint: "<what to build>"
model: opus
effort: high
allowed-tools: Bash(bd *)
---

# Design

Request: $ARGUMENTS

State the design for this request. Its job is to remove ambiguity and fix the contracts that separate pieces of work must agree on. It is not an implementation plan: tasks, file-by-file steps and code belong to `sdlc:split`.

Be precise only where two people implementing different parts could otherwise build incompatible things, or where the goal itself is unclear.

## Reading

Gather information with the skills, agents and MCP tools this session has. Users install the ones that fit their projects, such as code search, code graphs, documentation lookups or bulk readers. Find them in your context, and through tool search for deferred tools. Use what fits each source; where nothing does, read and search the repository yourself.

Tools that read the repository or its beads are local sources. Anything that reaches outside the repository is an external source.

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

## 3. State the design

State the design directly in your reply, in this form:

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

**Doc edits:** list the changes existing files need because this design makes them wrong or incomplete — a README, an ADR, API docs, an earlier design. Each entry: the file, and what changes. Make the edits. This is the only side effect.

**A new document, only if the user asks for one:** write it to the location the request names; otherwise the repository's existing design-doc convention; otherwise `docs/design/<slug>.md`. The slug is short kebab-case derived from the request. If a design on the same topic already exists, update it instead of creating a second one.

## 4. Report

Print:
- a summary of at most three lines
- the assumptions you made
- the doc edits made, or that none were needed
- the new document's path, if the user asked for one

Then suggest `/sdlc:split` in the same session as the next step.

Do not create beads, branches or commits.

If plan mode is active, put the complete design — the stated design and the doc edits — in the plan file, and apply the doc edits (and write a new document, if asked for) once plan mode ends.
