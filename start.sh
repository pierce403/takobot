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
INFERENCE_TIMEOUT_S=300
TRY_INFERENCE_LAST_EXIT=0
TRY_INFERENCE_LAST_ERROR=""
TRY_INFERENCE_LAST_OUTPUT=""
INFERENCE_FAILURE_REPORT=""
INFERENCE_OUTPUT=""
ONBOARDING_INFERENCE_TOOL=""

usage() {
  cat <<'EOF'
Usage:
  ./start.sh [--interval N] [--once]

Behavior:
  - Verifies this is a valid tako-bot repo checkout.
  - Runs first-wake SOUL prompts (name + purpose) when interactive.
  - Runs terminal-first bootstrap pairing, then starts the daemon.
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

build_identity_refinement_prompt() {
  local name="$1"
  local role="$2"
  cat <<EOF
You are assisting first-run onboarding for tako-bot.
The user answered these questions conversationally:

NAME: $name
ROLE: $role

Task:
- Keep user intent exactly.
- Tighten wording only if needed.
- Name should stay short (1-3 words).
- Role should be one practical sentence under 180 characters.

Return exactly two lines:
NAME: <name>
ROLE: <role sentence>
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
  local output_file=""
  local error_file=""
  local output=""
  local error=""
  local status=0

  mkdir -p "$LOCAL_TMP_DIR"
  output_file="$(mktemp "$LOCAL_TMP_DIR/infer.out.XXXXXX")"
  error_file="$(mktemp "$LOCAL_TMP_DIR/infer.err.XXXXXX")"

  if run_with_timeout "$INFERENCE_TIMEOUT_S" "$@" >"$output_file" 2>"$error_file"; then
    output="$(cat "$output_file" || true)"
    error="$(cat "$error_file" || true)"
    rm -f "$output_file" "$error_file"

    if [[ -n "$(sanitize_line "$output")" ]]; then
      TRY_INFERENCE_LAST_EXIT=0
      TRY_INFERENCE_LAST_ERROR=""
      TRY_INFERENCE_LAST_OUTPUT="$output"
      return 0
    fi

    TRY_INFERENCE_LAST_EXIT=0
    TRY_INFERENCE_LAST_OUTPUT=""
    if [[ -n "$(sanitize_line "$error")" ]]; then
      TRY_INFERENCE_LAST_ERROR="$(sanitize_line "$error")"
    else
      TRY_INFERENCE_LAST_ERROR="command succeeded but produced no output"
    fi
    return 1
  else
    status=$?
  fi

  output="$(cat "$output_file" || true)"
  error="$(cat "$error_file" || true)"
  rm -f "$output_file" "$error_file"

  TRY_INFERENCE_LAST_EXIT="$status"
  TRY_INFERENCE_LAST_OUTPUT=""
  if [[ -n "$(sanitize_line "$error")" ]]; then
    TRY_INFERENCE_LAST_ERROR="$(sanitize_line "$error")"
  elif [[ -n "$(sanitize_line "$output")" ]]; then
    TRY_INFERENCE_LAST_ERROR="$(sanitize_line "$output")"
  else
    TRY_INFERENCE_LAST_ERROR="command failed without stderr output"
  fi
  return 1
}

reset_inference_failures() {
  INFERENCE_FAILURE_REPORT=""
}

shorten_inference_error() {
  local text="$1"
  local max_len=220
  if (( ${#text} <= max_len )); then
    printf "%s" "$text"
  else
    printf "%s..." "${text:0:$((max_len - 3))}"
  fi
}

append_inference_failure() {
  local label="$1"
  local exit_code="$2"
  local detail="$3"
  local clean_detail

  clean_detail="$(shorten_inference_error "$(sanitize_line "$detail")")"
  if [[ -z "$clean_detail" ]]; then
    clean_detail="no diagnostic output"
  fi

  if [[ -n "$INFERENCE_FAILURE_REPORT" ]]; then
    INFERENCE_FAILURE_REPORT+=$'\n'
  fi
  INFERENCE_FAILURE_REPORT+="- ${label} (exit ${exit_code}): ${clean_detail}"
}

try_inference_variant() {
  local label="$1"
  shift

  if try_inference_command "$@"; then
    return 0
  fi

  append_inference_failure "$label" "$TRY_INFERENCE_LAST_EXIT" "$TRY_INFERENCE_LAST_ERROR"
  return 1
}

inference_hint_for_failures() {
  local tool="$1"
  local report="$2"

  if [[ "$report" == *"does not exist or you do not have access"* ]]; then
    case "$tool" in
      codex)
        echo "Tip: onboarding does not create a new token; it only runs \`codex exec\`. Your current codex model/account config rejected the request. Try: \`codex exec --model gpt-5 'ping'\`."
        ;;
      *)
        echo "Tip: the CLI appears installed, but model/account access failed. Re-authenticate and verify your default model."
        ;;
    esac
    return 0
  fi

  if [[ "$report" == *"command failed without stderr output"* || "$report" == *"exit 124"* ]]; then
    echo "Tip: the command likely timed out after ${INFERENCE_TIMEOUT_S}s or failed silently. Try running it directly once to validate auth/network."
    return 0
  fi

  return 1
}

run_one_shot_inference() {
  local tool="$1"
  local prompt="$2"

  reset_inference_failures
  INFERENCE_OUTPUT=""

  case "$tool" in
    codex)
      if try_inference_variant "codex exec <prompt>" codex exec "$prompt"; then
        INFERENCE_OUTPUT="$TRY_INFERENCE_LAST_OUTPUT"
        return 0
      fi
      ;;
    claude)
      if try_inference_variant "claude -p <prompt>" claude -p "$prompt"; then
        INFERENCE_OUTPUT="$TRY_INFERENCE_LAST_OUTPUT"
        return 0
      fi
      if try_inference_variant "claude --print <prompt>" claude --print "$prompt"; then
        INFERENCE_OUTPUT="$TRY_INFERENCE_LAST_OUTPUT"
        return 0
      fi
      if try_inference_variant "claude <prompt>" claude "$prompt"; then
        INFERENCE_OUTPUT="$TRY_INFERENCE_LAST_OUTPUT"
        return 0
      fi
      ;;
    gemini)
      if try_inference_variant "gemini -p <prompt>" gemini -p "$prompt"; then
        INFERENCE_OUTPUT="$TRY_INFERENCE_LAST_OUTPUT"
        return 0
      fi
      if try_inference_variant "gemini --prompt <prompt>" gemini --prompt "$prompt"; then
        INFERENCE_OUTPUT="$TRY_INFERENCE_LAST_OUTPUT"
        return 0
      fi
      if try_inference_variant "gemini <prompt>" gemini "$prompt"; then
        INFERENCE_OUTPUT="$TRY_INFERENCE_LAST_OUTPUT"
        return 0
      fi
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

maybe_select_inference_tool() {
  local -a tools=()
  local detected=""

  ONBOARDING_INFERENCE_TOOL=""
  if ! interactive_tty; then
    return 0
  fi

  while IFS= read -r detected; do
    detected="$(sanitize_line "$detected")"
    if [[ -n "$detected" ]]; then
      tools+=("$detected")
    fi
  done < <(detect_inference_tools)

  if [[ ${#tools[@]} -eq 0 ]]; then
    return 0
  fi

  if ! prompt_yes_no "Can I use a local inference CLI (${tools[*]}) during onboarding?" "n"; then
    return 0
  fi

  ONBOARDING_INFERENCE_TOOL="$(choose_inference_tool "${tools[@]}")"
}

maybe_refine_identity_with_inference() {
  local initial_name="$1"
  local initial_role="$2"
  local -n out_name_ref="$3"
  local -n out_role_ref="$4"
  local prompt=""
  local output=""
  local inferred_name=""
  local inferred_role=""

  out_name_ref="$initial_name"
  out_role_ref="$initial_role"

  if [[ -z "$ONBOARDING_INFERENCE_TOOL" ]]; then
    return 0
  fi

  prompt="$(build_identity_refinement_prompt "$initial_name" "$initial_role")"
  echo "Tako: Thanks. I’ll quickly refine that wording with $ONBOARDING_INFERENCE_TOOL." > /dev/tty
  if ! run_one_shot_inference "$ONBOARDING_INFERENCE_TOOL" "$prompt"; then
    echo "Tako: I couldn't use $ONBOARDING_INFERENCE_TOOL right now; I'll keep your wording as-is." > /dev/tty
    if [[ -n "$INFERENCE_FAILURE_REPORT" ]]; then
      echo "Inference attempts:" > /dev/tty
      printf "%s\n" "$INFERENCE_FAILURE_REPORT" > /dev/tty
      inference_hint_for_failures "$ONBOARDING_INFERENCE_TOOL" "$INFERENCE_FAILURE_REPORT" > /dev/tty || true
    fi
    return 0
  fi
  output="$INFERENCE_OUTPUT"

  inferred_name="$(extract_soul_field "NAME" "$output")"
  inferred_role="$(extract_soul_field "ROLE" "$output")"
  if [[ -z "$inferred_name" ]]; then
    inferred_name="$initial_name"
  fi
  if [[ -z "$inferred_role" ]]; then
    inferred_role="$initial_role"
  fi

  echo "Tako: Suggested final identity:" > /dev/tty
  echo "  Name: $inferred_name" > /dev/tty
  echo "  Purpose: $inferred_role" > /dev/tty
  if prompt_yes_no "Use this suggested wording?" "y"; then
    out_name_ref="$inferred_name"
    out_role_ref="$inferred_role"
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
  local chosen_name
  local chosen_role
  local refined_name
  local refined_role
  local name
  local purpose
  local role

  default_name="$(extract_identity_value "Name" "Tako")"
  default_role="$(extract_identity_value "Role" "Help the operator think clearly, decide wisely, and act safely.")"

  if ! interactive_tty; then
    echo "start.sh: no interactive TTY detected; skipping SOUL prompts." >&2
    return 0
  fi

  echo "First wake: SOUL identity setup" > /dev/tty
  echo "This updates the Identity section in SOUL.md before startup." > /dev/tty
  echo > /dev/tty

  maybe_select_inference_tool

  echo "Tako: Before I fully wake up, I have two questions." > /dev/tty
  echo "Tako: What should I be called?" > /dev/tty
  name="$(prompt_line "You" "$default_name")"
  echo "Tako: And what should my purpose be? (one sentence is great)" > /dev/tty
  purpose="$(prompt_line "You" "$default_role")"

  role="$(sanitize_line "$purpose")"
  if [[ -z "$role" ]]; then
    role="$default_role"
  fi

  chosen_name="$(sanitize_line "$name")"
  if [[ -z "$chosen_name" ]]; then
    chosen_name="$default_name"
  fi
  chosen_role="$role"
  refined_name="$chosen_name"
  refined_role="$chosen_role"
  maybe_refine_identity_with_inference "$chosen_name" "$chosen_role" refined_name refined_role

  update_soul_identity "$refined_name" "$refined_role"
  echo "Updated SOUL.md identity: Name=\"$refined_name\"." > /dev/tty
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

  exec "$ROOT/tako.sh" bootstrap "$@"
}

main "$@"
