---
name: setup
description: Check this machine for what sdlc needs (Claude Code, beads, worktrunk, git, jq and a few system tools), offer to install what is missing, and recommend companions that make the workflow better or cheaper, such as rtk, a reading agent, a reviewer agent and specialist agents. Use once per machine after installing the plugin, or when a dispatch script reports a missing tool.
model: sonnet
allowed-tools: Bash(${CLAUDE_SKILL_DIR}/scripts/check.sh)
---

# Setup

Machine check:
!`${CLAUDE_SKILL_DIR}/scripts/check.sh`

## 1. Report

Summarize the check in three groups: what's required and missing or too old, what's optional, and the recommended companions. Keep what is `ok` to one line.

## 2. Required tools

For each `missing` or `old` tool, give the installation instructions from its own documentation. Read the page with a reading agent if you need the exact commands:
- beads (`bd`): <https://beads.gascity.com/getting-started/installation>
- worktrunk (`wt`): <https://github.com/max-sixty/worktrunk>
- Claude Code: <https://code.claude.com>
- `git`, `jq`, `uuidgen`, `setsid`, `pgrep`, `timeout`: the system package manager (on Debian and Ubuntu: `git jq uuid-runtime util-linux procps coreutils`)

Install only what the user agrees to through AskUserQuestion, one tool at a time, then run the check again. In a headless session, don't install anything: report the instructions.

On a system other than Linux, say that the dispatch scripts don't support it yet.

## 3. Recommended companions

For each companion that isn't installed, say in one line why it helps, and how to find it. An agent type available in this session counts as installed, even under another name: for example, another reading agent can replace `bulk-reader`. Don't install companions without the user's OK.

## 4. Next

Suggest `/sdlc:init` in each project that will use sdlc.
