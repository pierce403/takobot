from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def runtime_root() -> Path:
    return repo_root() / ".tako"


def daily_root() -> Path:
    return repo_root() / "daily"


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    keys_json: Path
    operator_json: Path
    locks_dir: Path
    logs_dir: Path
    state_dir: Path
    xmtp_db_dir: Path


def runtime_paths() -> RuntimePaths:
    root = runtime_root()
    return RuntimePaths(
        root=root,
        keys_json=root / "keys.json",
        operator_json=root / "operator.json",
        locks_dir=root / "locks",
        logs_dir=root / "logs",
        state_dir=root / "state",
        xmtp_db_dir=root / "xmtp-db",
    )


def ensure_runtime_dirs(paths: RuntimePaths | None = None) -> RuntimePaths:
    paths = paths or runtime_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.locks_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    paths.xmtp_db_dir.mkdir(parents=True, exist_ok=True)
    return paths

