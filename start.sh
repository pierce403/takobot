#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOUL_PATH="$ROOT/SOUL.md"
UV_INSTALL_URL="https://astral.sh/uv/install.sh"

usage() {
  cat <<'EOF'
Usage:
  ./start.sh [tako_args...]

Behavior:
  - Verifies this is a valid tako-bot repo checkout.
  - Runs first-wake SOUL prompts (name + purpose) when interactive.
  - Starts Tako via ./tako.sh (arguments are passed through).
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

warn_if_unusual_home() {
  if [[ "$ROOT" == /tmp/* || "$ROOT" == /var/tmp/* ]]; then
    echo "Warning: repo is under a temporary directory: $ROOT" >&2
  fi
  if [[ ! -w "$ROOT" ]]; then
    echo "Error: repo directory is not writable: $ROOT" >&2
    exit 1
  fi
}

sanitize_line() {
  printf "%s" "$1" | tr '\n' ' ' | tr -s ' ' | sed -e 's/^ *//' -e 's/ *$//'
}

interactive_tty() {
  [[ -r /dev/tty && -w /dev/tty ]]
}

prompt_line() {
  local label="$1"
  local default="$2"
  local input=""

  if ! interactive_tty; then
    printf "%s" "$default"
    return 0
  fi

  printf "%s [%s]: " "$label" "$default" > /dev/tty
  IFS= read -r input < /dev/tty || true
  input="$(sanitize_line "$input")"
  if [[ -z "$input" ]]; then
    printf "%s" "$default"
  else
    printf "%s" "$input"
  fi
}

extract_identity_value() {
  local key="$1"
  local fallback="$2"
  local value
  value="$(sed -n "s/^- ${key}: *//p" "$SOUL_PATH" | head -n 1 || true)"
  value="$(sanitize_line "$value")"
  if [[ -z "$value" ]]; then
    printf "%s" "$fallback"
  else
    printf "%s" "$value"
  fi
}

update_soul_identity() {
  local name="$1"
  local role="$2"
  local tmp
  tmp="$(mktemp)"

  awk -v name="$name" -v role="$role" '
    BEGIN { in_identity = 0 }
    /^## Identity$/ { in_identity = 1; print; next }
    /^## / && in_identity == 1 { in_identity = 0 }
    in_identity == 1 && /^- Name:/ { print "- Name: " name; next }
    in_identity == 1 && /^- Role:/ { print "- Role: " role; next }
    { print }
  ' "$SOUL_PATH" > "$tmp"

  mv "$tmp" "$SOUL_PATH"
}

run_soul_onboarding() {
  local default_name
  local default_role
  local name
  local purpose
  local role

  default_name="$(extract_identity_value "Name" "Tako")"
  default_role="$(extract_identity_value "Role" "highly autonomous, operator-imprinted agent with operator-only control for risky changes.")"

  if ! interactive_tty; then
    echo "start.sh: no interactive TTY detected; skipping SOUL prompts." >&2
    return 0
  fi

  echo "First wake: SOUL identity setup" > /dev/tty
  echo "This updates the Identity section in SOUL.md before startup." > /dev/tty
  echo > /dev/tty

  name="$(prompt_line "Name" "$default_name")"
  purpose="$(prompt_line "Purpose (single line)" "$default_role")"

  role="$(sanitize_line "$purpose")"
  if [[ -z "$role" ]]; then
    role="$default_role"
  fi

  update_soul_identity "$name" "$role"
  echo "Updated SOUL.md identity: Name=\"$name\"." > /dev/tty
  echo > /dev/tty
}

ensure_uv() {
  if command -v uv >/dev/null 2>&1; then
    return 0
  fi

  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [[ -x "$candidate" ]]; then
      export PATH="$(dirname "$candidate"):$PATH"
      return 0
    fi
  done

  echo "uv not found. Installing a user-local copy..." >&2
  if command -v curl >/dev/null 2>&1; then
    curl -LsSf "$UV_INSTALL_URL" | sh
  elif command -v wget >/dev/null 2>&1; then
    wget -qO- "$UV_INSTALL_URL" | sh
  else
    echo "Error: neither curl nor wget is available to install uv." >&2
    echo "Install uv manually: https://docs.astral.sh/uv/getting-started/installation/" >&2
    exit 1
  fi

  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [[ -x "$candidate" ]]; then
      export PATH="$(dirname "$candidate"):$PATH"
      return 0
    fi
  done

  if command -v uv >/dev/null 2>&1; then
    return 0
  fi

  echo "Error: uv installation did not place uv on PATH." >&2
  echo "Install uv manually: https://docs.astral.sh/uv/getting-started/installation/" >&2
  exit 1
}

main() {
  case "${1:-}" in
    -h|--help|help)
      usage
      exit 0
      ;;
  esac

  require_repo_layout
  warn_if_unusual_home
  ensure_uv
  run_soul_onboarding

  exec "$ROOT/tako.sh" "$@"
}

main "$@"
