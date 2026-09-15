#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: init.sh [--integration MODE] [--target BRANCH] [--parallel N] [--design-dir DIR]
                [--workflow build|none] [--pre-merge NAME=COMMAND]...

Prepares the current git repository for sdlc. Safe to run again: it fills in
what is missing, and changes a setting only when an option asks for it.

  1. beads: bd init (non-interactive, no git hooks, no AGENTS.md) if there is no beads database
  2. beads config: custom.dispatch.integration (direct, epic-merge or epic-pr; default direct)
     and custom.dispatch.target (default: the current branch)
  3. .claude/sdlc.local.md: parallel (default 2), design_dir and workflow when given
  4. .gitignore: .claude/*.local.md and .worktrees/
  5. .config/wt.toml: adds NAME=COMMAND under [pre-merge] for each --pre-merge, without
     touching a key that is already there

Prints one line per step, starting with "created", "set", "kept" or "added".
Exit codes: 0 done, 1 a step failed, 2 invalid arguments or not a git repository.
EOF2
}

integration="" target="" parallel="" design_dir="" workflow=""
pre_merge=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --integration|--target|--parallel|--design-dir|--workflow|--pre-merge)
      [[ $# -ge 2 ]] || { echo "error: $1 needs a value" >&2; usage >&2; exit 2; }
      case "$1" in
        --integration) integration="$2" ;; --target) target="$2" ;; --parallel) parallel="$2" ;;
        --design-dir) design_dir="$2" ;; --workflow) workflow="$2" ;;
        --pre-merge) pre_merge+=("$2") ;;
      esac
      shift ;;
    *) echo "error: unknown argument $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

errors=()
[[ -z "$integration" || "$integration" =~ ^(direct|epic-merge|epic-pr)$ ]] || errors+=("--integration must be direct, epic-merge or epic-pr")
[[ -z "$parallel" || "$parallel" =~ ^[1-9][0-9]*$ ]] || errors+=("--parallel must be a positive number")
[[ -z "$workflow" || "$workflow" =~ ^(build|none)$ ]] || errors+=("--workflow must be build or none")
for entry in "${pre_merge[@]}"; do
  [[ "$entry" =~ ^[A-Za-z0-9_-]+=.+$ ]] || errors+=("--pre-merge must be NAME=COMMAND, got: $entry")
done
root=$(git rev-parse --show-toplevel 2>/dev/null) || errors+=("not inside a git repository (run git init first)")
if [[ ${#errors[@]} -gt 0 ]]; then
  printf 'error: %s\n' "${errors[@]}" >&2
  exit 2
fi
cd "$root"
[[ -z "$target" ]] || git rev-parse --verify --quiet "refs/heads/$target" >/dev/null || { echo "error: no branch $target" >&2; exit 2; }

if bd where >/dev/null 2>&1; then
  echo "kept beads database ($(bd where 2>/dev/null | head -1))"
else
  bd init --non-interactive --skip-agents --skip-hooks >/dev/null || { echo "error: bd init failed" >&2; exit 1; }
  echo "created beads database"
fi

bd_value() { local v; v=$(bd config get "custom.dispatch.$1" 2>/dev/null) || v=""; [[ "$v" == *"(not set)" ]] || echo "$v"; }
for key in integration target; do
  wanted=${!key}
  current=$(bd_value "$key")
  if [[ -z "$wanted" && -n "$current" ]]; then
    echo "kept custom.dispatch.$key=$current"
    continue
  fi
  [[ -n "$wanted" ]] || { [[ "$key" == integration ]] && wanted=direct || wanted=$(git branch --show-current); }
  bd config set "custom.dispatch.$key" "$wanted" >/dev/null
  echo "set custom.dispatch.$key=$wanted"
done

settings=.claude/sdlc.local.md
mkdir -p .claude
if [[ ! -f "$settings" ]]; then
  printf -- '---\nparallel: %s\n---\n\nsdlc settings for this machine. Keys: parallel, design_dir, workflow (build).\n' "${parallel:-2}" > "$settings"
  echo "created $settings (parallel: ${parallel:-2})"
fi
set_key() { # key value; value "none" removes the key
  local key=$1 value=$2 tmp
  tmp=$(mktemp)
  awk -v key="$key" -v value="$value" '
    NR == 1 && $0 == "---" { infm = 1; print; next }
    infm && $0 == "---" { if (!done && value != "none") print key ": " value; infm = 0; print; next }
    infm && index($0, key ":") == 1 { if (value != "none") print key ": " value; done = 1; next }
    { print }
  ' "$settings" > "$tmp" && mv "$tmp" "$settings"
  echo "set $key: $value in $settings"
}
[[ -z "$parallel" ]] || set_key parallel "$parallel"
[[ -z "$design_dir" ]] || set_key design_dir "$design_dir"
[[ -z "$workflow" ]] || set_key workflow "$workflow"

touch .gitignore
for line in '.claude/*.local.md' '.worktrees/'; do
  if grep -qxF "$line" .gitignore; then
    echo "kept .gitignore entry $line"
  else
    echo "$line" >> .gitignore
    echo "added .gitignore entry $line"
  fi
done

if [[ ${#pre_merge[@]} -gt 0 ]]; then
  toml=.config/wt.toml
  mkdir -p .config
  touch "$toml"
  for entry in "${pre_merge[@]}"; do
    name=${entry%%=*} value=${entry#*=}
    if awk -v name="$name" '
        /^\[pre-merge\]/ { insec = 1; next }
        /^\[/ { insec = 0 }
        insec && $0 ~ "^" name "[ \t]*=" { found = 1 }
        END { exit !found }
      ' "$toml"; then
      echo "kept pre-merge $name"
      continue
    fi
    escaped=${value//\\/\\\\}
    escaped=${escaped//\"/\\\"}
    if grep -qxF '[pre-merge]' "$toml"; then
      tmp=$(mktemp)
      awk -v name="$name" -v val="$escaped" '
        { print }
        /^\[pre-merge\]/ && !done { print name " = \"" val "\""; done = 1 }
      ' "$toml" > "$tmp" && mv "$tmp" "$toml"
    else
      { [[ -s "$toml" ]] && echo; echo "[pre-merge]"; echo "$name = \"$escaped\""; } >> "$toml"
    fi
    echo "added pre-merge $name"
  done
fi
