#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: init.sh [--integration MODE] [--target BRANCH] [--parallel N]
                [--workflow build|none]

Prepares the current git repository for sdlc. Safe to run again: it fills in
what is missing, and changes a setting only when an option asks for it.

  1. beads: bd init (non-interactive, no git hooks, no AGENTS.md) if there is no beads database
  2. beads config: custom.dispatch.integration (direct, epic-merge or epic-pr; default direct)
     and custom.dispatch.target (default: the current branch)
  3. .claude/sdlc.local.md: parallel (default 2) and workflow when given
  4. .gitignore: .claude/*.local.md and .worktrees/
  5. .beads/hooks/{on_create,on_update,on_close}: writes each hook that wakes the
     supervisor via the wake pipe, leaving alone one that already exists and isn't ours

Prints one line per step, starting with "created", "set", "kept", "added" or "updated".
Exit codes: 0 done, 1 a step failed, 2 invalid arguments, not a git repository,
detached HEAD, or a repository with no commits.
EOF2
}

integration="" target="" parallel="" workflow=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage; exit 0 ;;
    --integration|--target|--parallel|--workflow)
      [[ $# -ge 2 ]] || { echo "error: $1 needs a value" >&2; usage >&2; exit 2; }
      case "$1" in
        --integration) integration="$2" ;; --target) target="$2" ;; --parallel) parallel="$2" ;;
        --workflow) workflow="$2" ;;
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
if common=$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null); then
  root=$(dirname "$common")
else
  errors+=("not inside a git repository (run git init first)")
fi
if [[ ${#errors[@]} -gt 0 ]]; then
  printf 'error: %s\n' "${errors[@]}" >&2
  exit 2
fi
cd "$root"
git rev-parse --verify --quiet HEAD >/dev/null || { echo "error: repository has no commits yet (make an initial commit, then run init again)" >&2; exit 2; }
current_branch=$(git branch --show-current)
[[ -n "$current_branch" ]] || { echo "error: detached HEAD (check out a branch first)" >&2; exit 2; }
[[ -z "$target" ]] || git rev-parse --verify --quiet "refs/heads/$target" >/dev/null || { echo "error: no branch $target" >&2; exit 2; }

command -v bd >/dev/null 2>&1 || { echo "error: bd is not installed (run /sdlc:setup)" >&2; exit 1; }
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
  [[ -n "$wanted" ]] || { [[ "$key" == integration ]] && wanted=direct || wanted=$current_branch; }
  bd config set "custom.dispatch.$key" "$wanted" >/dev/null
  echo "set custom.dispatch.$key=$wanted"
done

settings=.claude/sdlc.local.md
mkdir -p .claude
if [[ ! -f "$settings" ]]; then
  printf -- '---\nparallel: %s\n---\n\nsdlc settings for this machine. Keys: parallel, workflow (build).\n' "${parallel:-2}" > "$settings"
  echo "created $settings (parallel: ${parallel:-2})"
fi
set_key() { # key value; value "none" removes the key
  local key=$1 value=$2 tmp
  [[ "$(head -n1 "$settings")" == "---" ]] || { echo "error: $settings has no frontmatter, refusing to edit" >&2; exit 1; }
  tmp=$(mktemp)
  awk -v key="$key" -v value="$value" '
    NR == 1 && $0 == "---" { infm = 1; print; next }
    infm && $0 == "---" { if (!done && value != "none") print key ": " value; infm = 0; print; next }
    infm && index($0, key ":") == 1 { if (value != "none") print key ": " value; done = 1; next }
    { print }
  ' "$settings" > "$tmp" && mv "$tmp" "$settings"
  if [[ "$value" == "none" ]]; then
    ! grep -qE "^${key}:" "$settings" || { echo "error: failed to remove $key from $settings" >&2; exit 1; }
  else
    grep -qxF "$key: $value" "$settings" || { echo "error: failed to set $key in $settings" >&2; exit 1; }
  fi
  echo "set $key: $value in $settings"
}
[[ -z "$parallel" ]] || set_key parallel "$parallel"
[[ -z "$workflow" ]] || set_key workflow "$workflow"

touch .gitignore
[[ ! -s .gitignore || -z "$(tail -c1 .gitignore)" ]] || echo >> .gitignore
for line in '.claude/*.local.md' '.worktrees/'; do
  if grep -qxF "$line" .gitignore; then
    echo "kept .gitignore entry $line"
  else
    echo "$line" >> .gitignore
    echo "added .gitignore entry $line"
  fi
done

hook_marker="# sdlc: wake the supervisor"
hook_body=$(cat <<HOOK
#!/usr/bin/env bash
$hook_marker
[[ -z "\${SDLC_SUPERVISOR:-}" ]] || exit 0
id=\$1 event=\$2
wake="\$(git rev-parse --path-format=absolute --git-common-dir 2>/dev/null)/sdlc/wake"
[[ -p "\$wake" ]] && printf '%s %s\n' "\$event" "\$id" 1<>"\$wake"
exit 0
HOOK
)
mkdir -p .beads/hooks
for name in on_create on_update on_close; do
  path=".beads/hooks/$name"
  if [[ -f "$path" ]]; then
    if [[ "$(sed -n '2p' "$path")" == "$hook_marker" ]]; then
      if [[ "$(cat "$path")" == "$hook_body" ]]; then
        echo "kept $path"
      else
        printf '%s\n' "$hook_body" > "$path"
        chmod 755 "$path"
        echo "updated $path"
      fi
    else
      echo "kept $path (not ours; add this line to wake the supervisor: wake=\"\$(git rev-parse --path-format=absolute --git-common-dir)/sdlc/wake\"; [[ -p \"\$wake\" ]] && printf '%s %s\\n' \"\$2\" \"\$1\" 1<>\"\$wake\")"
    fi
  else
    printf '%s\n' "$hook_body" > "$path"
    chmod 755 "$path"
    echo "created $path"
  fi
done
