---
name: setup
description: Check this machine for what sdlc needs (Claude Code, beads, worktrunk, git, jq, python3 and a few system tools), offer to install what is missing, and recommend companions that make the workflow better or cheaper, such as rtk, a reviewer agent and specialist agents. Use once per machine after installing the plugin, or when a dispatch script reports a missing tool.
disable-model-invocation: true
model: sonnet
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/check.sh)
---

# Setup

Machine check:
!`scripts/setup-checks.sh`

## 1. Report

If the `os` line isn't Linux, say so first: the dispatch scripts don't support it yet, though the planning skills still can. Then summarize the check in three groups: what's required and missing or too old, what's optional, and the recommended companions. Keep what is `ok` to one line.

## 2. Required tools

For each `missing` or `old` tool, give the installation instructions from its own documentation. If you need the exact commands, read the page:
- beads (`bd`): <https://beads.gascity.com/getting-started/installation>
- worktrunk (`wt`): <https://github.com/max-sixty/worktrunk>
- Claude Code: <https://code.claude.com>
- `git`, `jq`, `uuidgen`, `setsid`, `pgrep`, `timeout`, `python3`: the system package manager (on Debian and Ubuntu: `git jq uuid-runtime util-linux procps coreutils python3`)

Install only what the user agrees to through AskUserQuestion, one tool at a time, then run `scripts/setup-checks.sh` again. For a command that needs `sudo` or a password, don't run it yourself: give the command and ask the user to run it, for example with `! <command>` at the prompt. In a headless session (AskUserQuestion isn't available), don't install anything: report the instructions.

## 3. Recommended companions

For each companion that isn't installed, say in one line why it helps:
- rtk: compresses command output, so every session and worker spends fewer tokens — <https://github.com/rtk-ai/rtk> (not `reachingforthejack/rtk`, a different project with the same command name)
- reviewer agent: reviews a worker's change before it merges
- specialist agents: workers hand implementation to a matching agent when your CLAUDE.md asks them to

Don't install companions without the user's OK.

## 4. Next

Suggest `/sdlc:init` in each project that will use sdlc.
