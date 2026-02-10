#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -lt 1 ]]; then
  echo "Usage: ./tako.sh <xmtp_address_or_ens> [message]" >&2
  exit 1
fi

TARGET="$1"
MESSAGE="${2:-}"

PYTHON="${PYTHON:-python3}"
VENV="$ROOT/.venv"

if [[ ! -x "$VENV/bin/python" ]]; then
  "$PYTHON" -m venv "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

python -m pip install -U pip >/dev/null

if ! python - <<'PY' >/dev/null 2>&1
import importlib.util
import sys

if importlib.util.find_spec("web3") is None:
    sys.exit(1)
PY
then
  python -m pip install -r "$ROOT/requirements.txt"
fi

install_xmtp_from_source() {
  local repo_url="https://github.com/pierce403/xmtp-py"
  local src_dir="$ROOT/.tako/xmtp-py"

  if ! command -v git >/dev/null; then
    echo "git is required to install xmtp-py from source." >&2
    exit 1
  fi

  if [[ ! -d "$src_dir/.git" ]]; then
    git clone --depth 1 "$repo_url" "$src_dir"
  fi

  # Patch setuptools cmdclass entries for newer setuptools validators.
  XMTP_SRC_DIR="$src_dir" python - <<'PY'
from pathlib import Path
import os

src_dir = Path(os.environ["XMTP_SRC_DIR"])
pyproject = src_dir / "bindings" / "python" / "pyproject.toml"
if pyproject.exists():
    text = pyproject.read_text(encoding="utf-8")
    updated = text.replace("xmtp_bindings.build:", "xmtp_bindings.build.")
    if updated != text:
        pyproject.write_text(updated, encoding="utf-8")

build_py = src_dir / "bindings" / "python" / "src" / "xmtp_bindings" / "build.py"
if build_py.exists():
    text = build_py.read_text(encoding="utf-8")
    updated = text.replace("return Path(__file__).resolve().parents[3]", "return Path(__file__).resolve().parents[2]")
    if updated != text:
        build_py.write_text(updated, encoding="utf-8")
PY

  python -m pip install -e "$src_dir/bindings/python"
  python -m pip install -e "$src_dir/content-types/content-type-primitives"

  for pkg in "$src_dir"/content-types/*; do
    [[ -d "$pkg" ]] || continue
    if [[ "$pkg" == "$src_dir/content-types/content-type-primitives" ]]; then
      continue
    fi
    if [[ -f "$pkg/pyproject.toml" || -f "$pkg/setup.py" ]]; then
      python -m pip install -e "$pkg"
    fi
  done

  python -m pip install -e "$src_dir/sdks/python-sdk"
}

if ! python - <<'PY' >/dev/null 2>&1
import importlib.util
import sys

if importlib.util.find_spec("xmtp") is None:
    sys.exit(1)
PY
then
  if ! python -m pip install xmtp >/dev/null 2>&1; then
    echo "xmtp not available on PyPI; installing from source..." >&2
    install_xmtp_from_source
  fi
fi

args=("--to" "$TARGET")
if [[ -n "$MESSAGE" ]]; then
  args+=("--message" "$MESSAGE")
fi

exec python "$ROOT/tako.py" "${args[@]}"
