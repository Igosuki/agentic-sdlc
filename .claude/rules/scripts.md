---
paths:
  - "scripts/**"
  - "skills/**/scripts/**"
---

# Scripts

- Bash + `jq` when the script runs commands and reads a few fields of JSON. Python 3.9+, standard library only, when it walks the task graph, sorts, totals, keeps state across rounds or renders logs.
- Bead JSON is never a command-line argument: Linux caps one argument at 128 KiB. Pipe `bd list --all --limit 0 --json` on stdin.
- A script explains itself: `--help` prints the usage and exits 0; invalid input lists every problem, prints the usage to stderr and exits 2; the usage ends with the exit codes.
- Bash starts `set -euo pipefail` and reaches siblings through `dir=$(dirname "$(readlink -f "$0")")`.
- Shared task-graph logic goes in `tasks.py`, never a second copy.
- A script that reacts to several event sources has one function that decides, with separate functions feeding it and acting for it. A helper script takes one target and doesn't loop.
