#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF2'
Usage: checks.sh

Prints candidate pre-merge check commands found in the current repository,
the pre-merge commands already in .config/wt.toml, the run: commands of the
GitHub Actions workflows, and this machine's wt approval state. Read-only.

  candidate <source> <name> <command>   found in the repository's own tooling
  existing pre-merge <name> <command>   already configured in .config/wt.toml
  ci <file> <run command>               a run: line from .github/workflows/*.yml
  approvals <line>                      wt config approvals list, unchanged

Exit codes: 0 always.
EOF2
}

[[ "${1:-}" == -h || "${1:-}" == --help ]] && { usage; exit 0; }
root=$(git rev-parse --show-toplevel 2>/dev/null) || root=$PWD
cd "$root"

runner() {
  if [[ -f pnpm-lock.yaml ]]; then echo pnpm
  elif [[ -f yarn.lock ]]; then echo yarn
  elif [[ -f bun.lockb ]]; then echo bun
  else echo "npm run"
  fi
}

if [[ -f package.json ]]; then
  r=$(runner)
  for name in test lint typecheck type-check check format:check; do
    jq -e --arg n "$name" '.scripts[$n] // empty' package.json >/dev/null 2>&1 \
      && echo "candidate package.json $name $r $name"
  done
fi

for file in Makefile justfile; do
  [[ -f "$file" ]] || continue
  for target in test lint check; do
    grep -qE "^${target}:" "$file" 2>/dev/null || continue
    [[ "$file" == justfile ]] && echo "candidate justfile $target just $target" || echo "candidate Makefile $target make $target"
  done
done

if [[ -f pyproject.toml ]]; then
  grep -qE '(^|["'"'"'[:space:]])pytest' pyproject.toml && echo "candidate pyproject.toml test pytest"
  grep -qE '(^|["'"'"'[:space:]])ruff' pyproject.toml && echo "candidate pyproject.toml lint ruff check"
  grep -qE '(^|["'"'"'[:space:]])mypy' pyproject.toml && echo "candidate pyproject.toml typecheck mypy"
fi

if [[ -f Cargo.toml ]]; then
  echo "candidate Cargo.toml test cargo test"
  echo "candidate Cargo.toml lint cargo clippy -- -D warnings"
  echo "candidate Cargo.toml format cargo fmt --check"
fi

if [[ -f go.mod ]]; then
  echo "candidate go.mod test go test ./..."
  echo "candidate go.mod lint go vet ./..."
fi

if [[ -f .config/wt.toml ]]; then
  awk '
    /^\[pre-merge\]/ { in_section = 1; next }
    /^\[/ { in_section = 0 }
    in_section && match($0, /^[A-Za-z0-9_.-]+[ \t]*=/) {
      name = $0
      sub(/[ \t]*=.*/, "", name)
      value = $0
      sub(/^[^=]*=[ \t]*/, "", value)
      sub(/^"/, "", value); sub(/"[ \t]*$/, "", value)
      gsub(/\\"/, "\"", value); gsub(/\\\\/, "\\", value)
      print "existing pre-merge " name " " value
    }
  ' .config/wt.toml
fi

if [[ -d .github/workflows ]]; then
  for f in .github/workflows/*.yml; do
    [[ -f "$f" ]] || continue
    { grep -n '^\s*run:' "$f" 2>/dev/null || true; } | head -20 | while IFS=: read -r _ rest; do
      echo "ci $f $(sed -E 's/^\s*run:\s*//' <<<"$rest")"
    done
  done
fi

wt config approvals list 2>&1 | sed 's/^/approvals /'
