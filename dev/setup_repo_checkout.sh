#!/usr/bin/env bash
set -euo pipefail

# Legacy helper for engine development:
# clones the repo and launches the repo-local start scripts.
#
# New user-facing bootstrap is `./setup.sh` (workspace + venv + pip install).

REPO_URL="https://github.com/pierce403/takobot.git"
CALLER_DIR="$(pwd -P)"
DEFAULT_TARGET="$CALLER_DIR/takobot"
LOCAL_TRACKING_BRANCH="local"

usage() {
  cat <<'EOF'
Usage:
  ./dev/setup_repo_checkout.sh

Behavior:
  - If already inside the Tako git repo, runs ./start.sh.
  - Otherwise bootstraps takobot into ./takobot from your current directory
    (or a timestamped fallback in the same directory)
    and then runs ./start.sh from there.
  - Fresh checkouts are created on a local branch (`local`) tracking `origin/main`.
EOF
}

is_tako_repo() {
  local root="$1"
  [[ -f "$root/AGENTS.md" && -f "$root/ONBOARDING.md" && -f "$root/SOUL.md" && -f "$root/tako.sh" && -f "$root/start.sh" ]]
}

clone_target() {
  local target="$DEFAULT_TARGET"

  if [[ -d "$target/.git" ]]; then
    printf "%s\n" "$target"
    return 0
  fi

  if [[ -e "$target" ]]; then
    target="$CALLER_DIR/takobot-$(date +%Y%m%d-%H%M%S)"
  fi

  printf "%s\n" "$target"
}

set_repo_tmpdir() {
  local root="$1"
  mkdir -p "$root/.tako/tmp"
  export TMPDIR="$root/.tako/tmp"
}

bootstrap_checkout() {
  local target="$1"
  local branch="$LOCAL_TRACKING_BRANCH"

  mkdir -p "$target"
  set_repo_tmpdir "$target"

  git -C "$target" init --quiet
  git -C "$target" remote add origin "$REPO_URL"
  git -C "$target" fetch --depth 1 origin main
  git -C "$target" checkout -b "$branch" FETCH_HEAD >/dev/null 2>&1
  git -C "$target" branch --set-upstream-to=origin/main "$branch" >/dev/null 2>&1 || true
  echo "Initialized local branch '$branch' (tracks origin/main)." >&2
}

ensure_local_tracking_branch() {
  local branch="$LOCAL_TRACKING_BRANCH"

  if ! git rev-parse --verify --quiet refs/remotes/origin/main >/dev/null; then
    if ! git fetch origin main >/dev/null 2>&1; then
      echo "Warning: could not fetch origin/main; leaving current branch unchanged." >&2
      return 0
    fi
  fi

  if ! git rev-parse --verify --quiet refs/remotes/origin/main >/dev/null; then
    echo "Warning: origin/main is unavailable; leaving current branch unchanged." >&2
    return 0
  fi

  if git rev-parse --verify --quiet "refs/heads/$branch" >/dev/null; then
    if ! git checkout "$branch" >/dev/null 2>&1; then
      echo "Warning: failed to switch to branch '$branch'; continuing on current branch." >&2
      return 0
    fi
  else
    if ! git checkout -b "$branch" origin/main >/dev/null 2>&1; then
      echo "Warning: failed to create branch '$branch' from origin/main; continuing on current branch." >&2
      return 0
    fi
    echo "Initialized local branch '$branch' (tracks origin/main)." >&2
  fi

  git branch --set-upstream-to=origin/main "$branch" >/dev/null 2>&1 || true
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
    echo "Error: git is required for dev repo bootstrap." >&2
    exit 1
  fi

  target="$(clone_target)"
  if [[ -d "$target/.git" ]]; then
    set_repo_tmpdir "$target"
    cd "$target"
    ensure_local_tracking_branch
    if ! git pull --ff-only; then
      echo "Warning: git pull failed; continuing with existing local checkout." >&2
    fi
  else
    bootstrap_checkout "$target"
    cd "$target"
  fi

  exec ./start.sh
}

main "$@"
