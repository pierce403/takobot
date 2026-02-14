from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


def engine_root() -> Path:
    """Filesystem location of the installed engine code (not the workspace).

    When running from a wheel this points into site-packages; when running from
    source it points at the repo checkout.
    """

    return Path(__file__).resolve().parents[1]


def find_workspace_root(start: Path | None = None) -> Path:
    """Best-effort workspace root discovery.

    We prefer a `tako.toml` sentinel. If missing, fall back to a minimal doc set.
    If nothing matches, return the start directory (so the app can still run in
    "ad-hoc" mode and emit a helpful health-check warning).
    """

    probe = (start or Path.cwd()).resolve()
    for candidate in [probe, *probe.parents]:
        if (candidate / "tako.toml").exists():
            return candidate
        if (candidate / "AGENTS.md").exists() and (candidate / "SOUL.md").exists() and (candidate / "MEMORY.md").exists():
            return candidate
    return probe


def workspace_root() -> Path:
    return find_workspace_root()


def repo_root() -> Path:
    """Compatibility alias for older code paths.

    Historically the engine ran from the repo root. In the packaged "engine +
    workspace" model, callers really want the workspace root.
    """

    return workspace_root()


def runtime_root() -> Path:
    return workspace_root() / ".tako"


def memory_root() -> Path:
    return workspace_root() / "memory"


def daily_root() -> Path:
    return memory_root() / "dailies"


@dataclass(frozen=True)
class RuntimePaths:
    root: Path
    keys_json: Path
    operator_json: Path
    locks_dir: Path
    logs_dir: Path
    tmp_dir: Path
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
        tmp_dir=root / "tmp",
        state_dir=root / "state",
        xmtp_db_dir=root / "xmtp-db",
    )


def ensure_runtime_dirs(paths: RuntimePaths | None = None) -> RuntimePaths:
    paths = paths or runtime_paths()
    paths.root.mkdir(parents=True, exist_ok=True)
    paths.locks_dir.mkdir(parents=True, exist_ok=True)
    paths.logs_dir.mkdir(parents=True, exist_ok=True)
    paths.tmp_dir.mkdir(parents=True, exist_ok=True)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    paths.xmtp_db_dir.mkdir(parents=True, exist_ok=True)
    return paths
