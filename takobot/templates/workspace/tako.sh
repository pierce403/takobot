#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/requirements.txt" && -d "$SCRIPT_DIR/takobot" ]]; then
  ROOT="$SCRIPT_DIR"
  REPO_MODE="1"
else
  ROOT="$(pwd)"
  REPO_MODE="0"
fi
cd "$ROOT"
LOCAL_RUNTIME_DIR="$ROOT/.tako"
LOCAL_TMP_DIR="$LOCAL_RUNTIME_DIR/tmp"
LOCAL_UV_BIN_DIR="$LOCAL_RUNTIME_DIR/bin"
LOCAL_UV_CACHE_DIR="$LOCAL_RUNTIME_DIR/uv-cache"
LOCAL_XDG_CACHE_DIR="$LOCAL_RUNTIME_DIR/xdg-cache"
LOCAL_XDG_CONFIG_DIR="$LOCAL_RUNTIME_DIR/xdg-config"

mkdir -p "$LOCAL_TMP_DIR" "$LOCAL_UV_BIN_DIR" "$LOCAL_UV_CACHE_DIR" "$LOCAL_XDG_CACHE_DIR" "$LOCAL_XDG_CONFIG_DIR"

export TMPDIR="$LOCAL_TMP_DIR"
export UV_CACHE_DIR="$LOCAL_UV_CACHE_DIR"
export XDG_CACHE_HOME="$LOCAL_XDG_CACHE_DIR"
export XDG_CONFIG_HOME="$LOCAL_XDG_CONFIG_DIR"
export PATH="$LOCAL_UV_BIN_DIR:$PATH"

ensure_tui_stdin() {
  if [[ "${ARGS[0]:-}" != "app" ]]; then
    return 0
  fi
  if [[ -t 0 ]]; then
    return 0
  fi
  if [[ -e /dev/tty ]] && ( : </dev/tty ) 2>/dev/null; then
    exec </dev/tty
    return 0
  fi
  echo "Error: interactive app mode requires a TTY on stdin." >&2
  echo "Run ./start.sh from a terminal (avoid piping stdin into the launcher)." >&2
  exit 1
}

case "${1:-}" in
  -h|--help|help)
    cat <<'EOF'
Usage:
  ./tako.sh [start]                                  # start interactive terminal app (default)
  ./tako.sh app                                      # same as default; interactive main loop
  ./tako.sh run                                      # (dev) start daemon loop directly
  ./tako.sh bootstrap                                # (dev) legacy terminal bootstrap + daemon
  ./tako.sh doctor                                   # (dev) environment checks
  ./tako.sh hi <xmtp_address_or_ens> [message]        # (dev) one-off DM
EOF
    exit 0
    ;;
esac

SUBCMD=""
case "${1:-}" in
  start|app|bootstrap|hi|run|doctor)
    SUBCMD="$1"
    shift
    ;;
esac

TARGET=""
MESSAGE=""
ARGS=()

if [[ -z "$SUBCMD" ]]; then
  if [[ $# -eq 0 ]]; then
    ARGS=("app")
  else
    TARGET="$1"
    MESSAGE="${2:-}"
    ARGS=("hi" "--to" "$TARGET")
    if [[ -n "$MESSAGE" ]]; then
      ARGS+=("--message" "$MESSAGE")
    fi
  fi
else
  if [[ "$SUBCMD" == "start" ]]; then
    SUBCMD="app"
  fi
  if [[ "$SUBCMD" == "hi" ]]; then
    if [[ $# -ge 1 && "${1:-}" != --* ]]; then
      TARGET="$1"
      shift
      ARGS=("hi" "--to" "$TARGET")
      if [[ $# -ge 1 && "${1:-}" != --* ]]; then
        MESSAGE="$1"
        shift
        ARGS+=("--message" "$MESSAGE")
      fi
      ARGS+=("$@")
    else
      ARGS=("hi" "$@")
    fi
  else
    ARGS=("$SUBCMD" "$@")
  fi
fi

ensure_tui_stdin

if [[ "$REPO_MODE" != "1" ]]; then
  if [[ -x "$ROOT/.venv/bin/takobot" ]]; then
    exec "$ROOT/.venv/bin/takobot" "${ARGS[@]}"
  fi
  if command -v takobot >/dev/null 2>&1; then
    exec takobot "${ARGS[@]}"
  fi
  PYTHON="${PYTHON:-python3}"
  exec "$PYTHON" -m takobot "${ARGS[@]}"
fi

PYTHON="${PYTHON:-python3}"
if [[ -n "${UV:-}" ]]; then
  UV="$UV"
elif [[ -x "$LOCAL_UV_BIN_DIR/uv" ]]; then
  UV="$LOCAL_UV_BIN_DIR/uv"
else
  UV="uv"
fi
VENV="$ROOT/.venv"
VENV_PY="$VENV/bin/python"

if ! command -v "$UV" >/dev/null 2>&1; then
  echo "Error: uv is required to manage Tako Python dependencies." >&2
  echo "Run ./start.sh once to install a repo-local uv at .tako/bin/uv." >&2
  exit 1
fi

if [[ ! -x "$VENV_PY" ]]; then
  "$UV" venv --python "$PYTHON" "$VENV"
fi

if ! "$VENV_PY" - <<'PY' >/dev/null 2>&1
import importlib.util
import sys

if importlib.util.find_spec("web3") is None:
    sys.exit(1)
if importlib.util.find_spec("textual") is None:
    sys.exit(1)
PY
then
  "$UV" pip install --python "$VENV_PY" -r "$ROOT/requirements.txt"
fi

exec "$VENV_PY" -m takobot "${ARGS[@]}"
