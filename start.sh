#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
UV_INSTALL_URL="https://astral.sh/uv/install.sh"
LOCAL_RUNTIME_DIR="$ROOT/.tako"
LOCAL_TMP_DIR="$LOCAL_RUNTIME_DIR/tmp"
LOCAL_UV_BIN_DIR="$LOCAL_RUNTIME_DIR/bin"
LOCAL_UV_CACHE_DIR="$LOCAL_RUNTIME_DIR/uv-cache"
LOCAL_XDG_CACHE_DIR="$LOCAL_RUNTIME_DIR/xdg-cache"
LOCAL_XDG_CONFIG_DIR="$LOCAL_RUNTIME_DIR/xdg-config"

usage() {
  cat <<'EOF'
Usage:
  ./start.sh

Behavior:
  - Verifies this is a valid tako-bot repo checkout.
  - Ensures local runtime env dependencies are available.
  - Launches Tako interactive terminal app (main loop).
EOF
}

require_repo_layout() {
  local missing=()
  local required=(
    "$ROOT/.git"
    "$ROOT/AGENTS.md"
    "$ROOT/ONBOARDING.md"
    "$ROOT/SOUL.md"
    "$ROOT/tako.sh"
  )

  for path in "${required[@]}"; do
    if [[ ! -e "$path" ]]; then
      missing+=("$path")
    fi
  done

  if [[ ${#missing[@]} -gt 0 ]]; then
    echo "Error: start.sh must run from a valid tako-bot repo checkout." >&2
    printf 'Missing:\n' >&2
    printf '  - %s\n' "${missing[@]}" >&2
    exit 1
  fi
}

enforce_local_write_policy() {
  if [[ "$ROOT" == /tmp/* || "$ROOT" == /var/tmp/* ]]; then
    echo "Error: repo directory under /tmp is disallowed by local-write policy: $ROOT" >&2
    exit 1
  fi
  if [[ ! -w "$ROOT" ]]; then
    echo "Error: repo directory is not writable: $ROOT" >&2
    exit 1
  fi
}

configure_local_runtime_env() {
  mkdir -p "$LOCAL_TMP_DIR" "$LOCAL_UV_BIN_DIR" "$LOCAL_UV_CACHE_DIR" "$LOCAL_XDG_CACHE_DIR" "$LOCAL_XDG_CONFIG_DIR"

  export TMPDIR="$LOCAL_TMP_DIR"
  export UV_CACHE_DIR="$LOCAL_UV_CACHE_DIR"
  export XDG_CACHE_HOME="$LOCAL_XDG_CACHE_DIR"
  export XDG_CONFIG_HOME="$LOCAL_XDG_CONFIG_DIR"
}

ensure_uv() {
  if [[ -x "$LOCAL_UV_BIN_DIR/uv" ]]; then
    export PATH="$LOCAL_UV_BIN_DIR:$PATH"
    return 0
  fi

  if command -v uv >/dev/null 2>&1; then
    return 0
  fi

  echo "uv not found. Installing a repo-local copy..." >&2
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf "$UV_INSTALL_URL" | \
      UV_UNMANAGED_INSTALL="$LOCAL_UV_BIN_DIR" UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$UV_INSTALL_URL" | \
      UV_UNMANAGED_INSTALL="$LOCAL_UV_BIN_DIR" UV_NO_MODIFY_PATH=1 INSTALLER_NO_MODIFY_PATH=1 sh
  else
    echo "Error: neither curl nor wget is available to install uv." >&2
    echo "Install uv manually: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
  fi

  if [[ -x "$LOCAL_UV_BIN_DIR/uv" ]]; then
    export PATH="$LOCAL_UV_BIN_DIR:$PATH"
    return 0
  fi

  if command -v uv >/dev/null 2>&1; then
    return 0
  fi

  echo "Error: uv installation did not place uv on PATH." >&2
  echo "Expected local uv path: $LOCAL_UV_BIN_DIR/uv" >&2
  exit 1
}

main() {
  case "${1:-}" in
    -h|--help|help)
      usage
      exit 0
      ;;
  esac

  cd "$ROOT"
  require_repo_layout
  enforce_local_write_policy
  configure_local_runtime_env
  ensure_uv

  exec "$ROOT/tako.sh" "$@"
}

main "$@"
