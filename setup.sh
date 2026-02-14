#!/usr/bin/env bash
set -euo pipefail

# Tako workspace bootstrap (curl | bash friendly).
#
# Creates a local .venv, attempts to install/upgrade the engine (`pip install --upgrade takobot` with a fallback),
# materializes workspace templates, initializes git (if available), then launches
# the interactive TUI main loop with `python -m takobot` (or CLI daemon mode if no interactive TTY exists).

ENGINE_PYPI_NAME="takobot"
ENGINE_FALLBACK_REPO_URL="https://github.com/pierce403/takobot.git"

WORKDIR="$(pwd -P)"
VENV_DIR="$WORKDIR/.venv"
PYTHON="${PYTHON:-python3}"

log() {
  printf "%s\n" "$*" >&2
}

die() {
  printf "Error: %s\n" "$*" >&2
  exit 1
}

is_workspace() {
  [[ -f "$WORKDIR/SOUL.md" && -f "$WORKDIR/AGENTS.md" && -f "$WORKDIR/MEMORY.md" && -f "$WORKDIR/tako.toml" ]]
}

has_non_runtime_entries() {
  local entry base
  while IFS= read -r entry; do
    base="$(basename "$entry")"
    case "$base" in
      .|..|.tako|.venv) continue ;;
    esac
    return 0
  done < <(find "$WORKDIR" -mindepth 1 -maxdepth 1 -print)
  return 1
}

preflight() {
  if is_workspace; then
    log "workspace: existing (templates will only fill missing files)"
    return 0
  fi

  if has_non_runtime_entries; then
    cat >&2 <<'EOF'
Error: refusing to bootstrap here: directory is not empty and does not look like a Tako workspace.

Expected (workspace): SOUL.md, AGENTS.md, MEMORY.md, tako.toml

Tip: run in an empty directory, or cd into an existing Tako workspace.
EOF
    exit 1
  fi

  log "workspace: empty (fresh bootstrap)"
}

ensure_venv() {
  if [[ -x "$VENV_DIR/bin/python" ]]; then
    return 0
  fi
  command -v "$PYTHON" >/dev/null 2>&1 || die "python not found: $PYTHON"
  "$PYTHON" -m venv "$VENV_DIR"
}

upgrade_pip() {
  "$VENV_DIR/bin/python" -m pip install --upgrade pip setuptools wheel >/dev/null
}

engine_installed() {
  "$VENV_DIR/bin/python" - <<'PY' >/dev/null 2>&1
import importlib.util
import sys

sys.exit(0 if importlib.util.find_spec("takobot") else 1)
PY
}

install_engine() {
  local had_engine=0
  if engine_installed; then
    had_engine=1
    log "engine: checking for updates from PyPI ($ENGINE_PYPI_NAME)"
  else
    log "engine: installing from PyPI ($ENGINE_PYPI_NAME)"
  fi

  if "$VENV_DIR/bin/python" -m pip install --upgrade "$ENGINE_PYPI_NAME" >/dev/null 2>&1; then
    if engine_installed; then
      return 0
    fi
    log "engine: PyPI package installed but did not provide takobot; falling back"
  elif [[ "$had_engine" -eq 1 ]] && engine_installed; then
    log "engine: PyPI update check failed; continuing with installed engine"
    return 0
  fi

  log "engine: PyPI install failed; falling back to source clone"
  command -v git >/dev/null 2>&1 || die "git is required for fallback source install"

  mkdir -p "$WORKDIR/.tako/tmp"
  local src_dir="$WORKDIR/.tako/tmp/src"
  if [[ ! -d "$src_dir/.git" ]]; then
    rm -rf "$src_dir" >/dev/null 2>&1 || true
    git clone --depth 1 "$ENGINE_FALLBACK_REPO_URL" "$src_dir" >/dev/null 2>&1 || die "git clone failed"
  fi

  "$VENV_DIR/bin/python" -m pip install "$src_dir" >/dev/null || die "engine install from source failed"
}

materialize_templates() {
  log "workspace: materializing templates (no overwrite)"
  "$VENV_DIR/bin/python" - <<'PY' || die "template materialization failed"
from pathlib import Path
from takobot.workspace import materialize_workspace

root = Path.cwd()
result = materialize_workspace(root)
if result.warning:
    print(result.warning)
PY
}

ensure_git() {
  if ! command -v git >/dev/null 2>&1; then
    log "git: missing (workspace will still run, but versioning is disabled)"
    return 0
  fi

  if [[ -d "$WORKDIR/.git" ]]; then
    return 0
  fi

  log "git: init (main)"
  if git init -b main >/dev/null 2>&1; then
    :
  else
    git init >/dev/null
    git symbolic-ref HEAD refs/heads/main >/dev/null 2>&1 || true
  fi

  if [[ ! -f "$WORKDIR/.gitignore" ]]; then
    cat >"$WORKDIR/.gitignore" <<'EOF'
# Python
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/

# Runtime state (never commit)
.tako/

# Local databases (e.g., XMTP)
*.db3
*.db3-wal
*.db3-shm

# OS/editor noise
.DS_Store
.idea/
.vscode/
EOF
  fi

  git add -A >/dev/null
  if git commit -m "Initialize Tako workspace" >/dev/null 2>&1; then
    log "git: committed initial workspace"
  else
    log "git: commit skipped (operator action requested: configure git user.name/user.email, then retry commit)"
  fi
}

interactive_tty_available() {
  [[ -t 0 || -t 1 || -t 2 ]]
}

launch() {
  if interactive_tty_available; then
    if [[ -t 0 ]]; then
      exec "$VENV_DIR/bin/python" -m takobot
    fi
    if [[ -e /dev/tty ]] && ( : </dev/tty ) 2>/dev/null; then
      exec </dev/tty
      exec "$VENV_DIR/bin/python" -m takobot
    fi
  fi

  log "launch: no interactive TTY detected; starting command-line daemon mode"
  exec "$VENV_DIR/bin/python" -m takobot run
}

main() {
  preflight
  ensure_venv
  upgrade_pip
  install_engine
  materialize_templates
  ensure_git
  launch
}

main "$@"
