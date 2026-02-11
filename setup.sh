#!/usr/bin/env bash
set -euo pipefail

REPO_URL="https://github.com/pierce403/tako-bot.git"
CALLER_DIR="$(pwd -P)"
DEFAULT_TARGET="$CALLER_DIR/tako-bot"

usage() {
  cat <<'EOF'
Usage:
  ./setup.sh

Behavior:
  - If already inside the Tako git repo, runs ./start.sh.
  - Otherwise clones tako-bot into ./tako-bot from your current directory
    (or a timestamped fallback in the same directory)
    and then runs ./start.sh from there.
EOF
}

is_tako_repo() {
  local root="$1"
  [[ -f "$root/AGENTS.md" && -f "$root/ONBOARDING.md" && -f "$root/SOUL.md" && -f "$root/tako.sh" ]]
}

clone_target() {
  local target="$DEFAULT_TARGET"

  if [[ -d "$target/.git" ]]; then
    printf "%s\n" "$target"
    return 0
  fi

  if [[ -e "$target" ]]; then
    target="$CALLER_DIR/tako-bot-$(date +%Y%m%d-%H%M%S)"
  fi

  printf "%s\n" "$target"
}

main() {
  case "${1:-}" in
    -h|--help|help)
      usage
      exit 0
      ;;
  esac

  if command -v git >/dev/null 2>&1 && git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    repo_root="$(git rev-parse --show-toplevel)"
    if is_tako_repo "$repo_root"; then
      cd "$repo_root"
      exec ./start.sh
    fi
  fi

  if ! command -v git >/dev/null 2>&1; then
    echo "Error: git is required for setup.sh." >&2
    exit 1
  fi

  target="$(clone_target)"
  if [[ -d "$target/.git" ]]; then
    cd "$target"
    if ! git pull --ff-only; then
      echo "Warning: git pull failed; continuing with existing local checkout." >&2
    fi
  else
    git clone "$REPO_URL" "$target"
    cd "$target"
  fi

  exec ./start.sh
}

main "$@"
