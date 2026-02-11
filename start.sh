#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOUL_PATH="$ROOT/SOUL.md"
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

  # Keep installer/runtime temp + cache writes inside this repo checkout.
  export TMPDIR="$LOCAL_TMP_DIR"
  export UV_CACHE_DIR="$LOCAL_UV_CACHE_DIR"
  export XDG_CACHE_HOME="$LOCAL_XDG_CACHE_DIR"
  export XDG_CONFIG_HOME="$LOCAL_XDG_CONFIG_DIR"
}

sanitize_line() {
  printf "%s" "$1" | tr '\n' ' ' | tr -s ' ' | sed -e 's/^ *//' -e 's/ *$//'
}

interactive_tty() {
  [[ -r /dev/tty && -w /dev/tty ]]
}

run_with_timeout() {
  local seconds="$1"
  shift
  if command -v timeout >/dev/null 2>&1; then
    timeout --foreground "$seconds" "$@"
  else
    "$@"
  fi
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

prompt_yes_no() {
  local label="$1"
  local default="${2:-n}"
  local input=""
  local normalized_default

  normalized_default="$(printf "%s" "$default" | tr '[:upper:]' '[:lower:]')"
  if [[ "$normalized_default" != "y" && "$normalized_default" != "n" ]]; then
    normalized_default="n"
  fi

  if ! interactive_tty; then
    [[ "$normalized_default" == "y" ]]
    return
  fi

  while true; do
    if [[ "$normalized_default" == "y" ]]; then
      printf "%s [Y/n]: " "$label" > /dev/tty
    else
      printf "%s [y/N]: " "$label" > /dev/tty
    fi
    IFS= read -r input < /dev/tty || true
    input="$(sanitize_line "$input")"
    input="$(printf "%s" "$input" | tr '[:upper:]' '[:lower:]')"

    if [[ -z "$input" ]]; then
      [[ "$normalized_default" == "y" ]]
      return
    fi
    if [[ "$input" == "y" || "$input" == "yes" ]]; then
      return 0
    fi
    if [[ "$input" == "n" || "$input" == "no" ]]; then
      return 1
    fi
    echo "Please answer y or n." > /dev/tty
  done
}

detect_inference_tools() {
  local tool
  local tools=()
  for tool in codex claude gemini; do
    if command -v "$tool" >/dev/null 2>&1; then
      tools+=("$tool")
    fi
  done
  printf "%s\n" "${tools[@]}"
}

build_soul_inference_prompt() {
  local default_name="$1"
  local default_role="$2"
  cat <<EOF
You are assisting first-run onboarding for tako-bot.
Generate suggested identity fields for SOUL.md.

Constraints:
- Name should be short (1-3 words).
- Role should be one sentence, practical, and operator-imprinted.
- Keep role under 180 characters.
- Preserve this direction: highly autonomous agent, Python implementation, docs-first memory, Type 1 / Type 2 thinking, web3-native XMTP/Ethereum/Farcaster path.

Current defaults:
NAME: $default_name
ROLE: $default_role

Return exactly two lines:
NAME: <suggested name>
ROLE: <suggested role sentence>
EOF
}

extract_soul_field() {
  local key="$1"
  local text="$2"
  local value
  value="$(printf "%s\n" "$text" | sed -n -E "s/^[[:space:]]*${key}:[[:space:]]*//p" | head -n 1 || true)"
  sanitize_line "$value"
}

try_inference_command() {
  local output=""
  if output="$(run_with_timeout 30 "$@" 2>/dev/null)"; then
    if [[ -n "$(sanitize_line "$output")" ]]; then
      printf "%s" "$output"
      return 0
    fi
  fi
  return 1
}

run_one_shot_inference() {
  local tool="$1"
  local prompt="$2"
  local output=""

  case "$tool" in
    codex)
      output="$(try_inference_command codex exec "$prompt")" && { printf "%s" "$output"; return 0; }
      output="$(try_inference_command codex -p "$prompt")" && { printf "%s" "$output"; return 0; }
      output="$(try_inference_command codex "$prompt")" && { printf "%s" "$output"; return 0; }
      ;;
    claude)
      output="$(try_inference_command claude -p "$prompt")" && { printf "%s" "$output"; return 0; }
      output="$(try_inference_command claude --print "$prompt")" && { printf "%s" "$output"; return 0; }
      output="$(try_inference_command claude "$prompt")" && { printf "%s" "$output"; return 0; }
      ;;
    gemini)
      output="$(try_inference_command gemini -p "$prompt")" && { printf "%s" "$output"; return 0; }
      output="$(try_inference_command gemini --prompt "$prompt")" && { printf "%s" "$output"; return 0; }
      output="$(try_inference_command gemini "$prompt")" && { printf "%s" "$output"; return 0; }
      ;;
  esac

  return 1
}

choose_inference_tool() {
  local -a tools=("$@")
  local choice=""
  local idx=1

  if [[ ${#tools[@]} -eq 1 ]]; then
    printf "%s" "${tools[0]}"
    return 0
  fi

  if ! interactive_tty; then
    printf "%s" "${tools[0]}"
    return 0
  fi

  echo "Detected local inference CLIs:" > /dev/tty
  for tool in "${tools[@]}"; do
    echo "  $idx) $tool" > /dev/tty
    idx=$((idx + 1))
  done

  while true; do
    printf "Choose a tool [1-%d] (default 1): " "${#tools[@]}" > /dev/tty
    IFS= read -r choice < /dev/tty || true
    choice="$(sanitize_line "$choice")"
    if [[ -z "$choice" ]]; then
      printf "%s" "${tools[0]}"
      return 0
    fi
    if [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#tools[@]} )); then
      printf "%s" "${tools[$((choice - 1))]}"
      return 0
    fi
    echo "Invalid selection." > /dev/tty
  done
}

maybe_suggest_soul_identity() {
  local default_name="$1"
  local default_role="$2"
  local -n suggested_name_ref="$3"
  local -n suggested_role_ref="$4"
  local -a tools=()
  local detected=""
  local tool=""
  local prompt=""
  local output=""
  local inferred_name=""
  local inferred_role=""

  if ! interactive_tty; then
    suggested_name_ref="$default_name"
    suggested_role_ref="$default_role"
    return 0
  fi

  while IFS= read -r detected; do
    detected="$(sanitize_line "$detected")"
    if [[ -n "$detected" ]]; then
      tools+=("$detected")
    fi
  done < <(detect_inference_tools)

  if [[ ${#tools[@]} -eq 0 ]]; then
    suggested_name_ref="$default_name"
    suggested_role_ref="$default_role"
    return 0
  fi

  if ! prompt_yes_no "Use a local inference CLI (${tools[*]}) to suggest SOUL defaults?" "n"; then
    suggested_name_ref="$default_name"
    suggested_role_ref="$default_role"
    return 0
  fi

  tool="$(choose_inference_tool "${tools[@]}")"
  prompt="$(build_soul_inference_prompt "$default_name" "$default_role")"
  echo "Querying $tool for onboarding suggestion..." > /dev/tty
  if ! output="$(run_one_shot_inference "$tool" "$prompt")"; then
    echo "Could not run one-shot inference with $tool; continuing with manual prompts." > /dev/tty
    suggested_name_ref="$default_name"
    suggested_role_ref="$default_role"
    return 0
  fi

  inferred_name="$(extract_soul_field "NAME" "$output")"
  inferred_role="$(extract_soul_field "ROLE" "$output")"

  if [[ -z "$inferred_name" ]]; then
    inferred_name="$default_name"
  fi
  if [[ -z "$inferred_role" ]]; then
    inferred_role="$default_role"
  fi

  echo "Suggested defaults from $tool:" > /dev/tty
  echo "  Name: $inferred_name" > /dev/tty
  echo "  Role: $inferred_role" > /dev/tty

  if prompt_yes_no "Use these suggestions as prompt defaults?" "y"; then
    suggested_name_ref="$inferred_name"
    suggested_role_ref="$inferred_role"
  else
    suggested_name_ref="$default_name"
    suggested_role_ref="$default_role"
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
  mkdir -p "$LOCAL_TMP_DIR"
  tmp="$(mktemp "$LOCAL_TMP_DIR/soul.XXXXXX")"

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
  local suggested_name
  local suggested_role
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

  # Defensive defaults; maybe_suggest_soul_identity may override them.
  suggested_name="$default_name"
  suggested_role="$default_role"
  maybe_suggest_soul_identity "$default_name" "$default_role" suggested_name suggested_role

  name="$(prompt_line "Name" "$suggested_name")"
  purpose="$(prompt_line "Purpose (single line)" "$suggested_role")"

  role="$(sanitize_line "$purpose")"
  if [[ -z "$role" ]]; then
    role="$default_role"
  fi

  update_soul_identity "$name" "$role"
  echo "Updated SOUL.md identity: Name=\"$name\"." > /dev/tty
  echo > /dev/tty
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

  # Ensure all relative operations run from the repo root.
  cd "$ROOT"
  require_repo_layout
  enforce_local_write_policy
  configure_local_runtime_env
  ensure_uv
  run_soul_onboarding

  exec "$ROOT/tako.sh" "$@"
}

main "$@"
