from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import hashlib
import importlib.resources
from pathlib import Path

from .daily import append_daily_note, ensure_daily_log


@dataclass(frozen=True)
class MaterializeResult:
    created: list[str]
    drifted: list[str]
    warning: str = ""


def looks_like_workspace(root: Path) -> bool:
    required = ["SOUL.md", "AGENTS.md", "MEMORY.md", "tako.toml"]
    return all((root / name).exists() for name in required)


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def materialize_workspace(root: Path) -> MaterializeResult:
    """Copy engine-shipped templates into the workspace without overwriting."""

    created: list[str] = []
    drifted: list[str] = []
    warning = ""

    try:
        tmpl_root = importlib.resources.files("takobot.templates").joinpath("workspace")
    except Exception as exc:  # noqa: BLE001
        return MaterializeResult([], [], f"workspace templates unavailable: {exc}")

    root = root.resolve()

    def _walk_dir(node, rel: Path) -> None:
        try:
            children = list(node.iterdir())
        except Exception:  # noqa: BLE001
            return
        for child in children:
            child_rel = rel / child.name
            if child.is_dir():
                (root / child_rel).mkdir(parents=True, exist_ok=True)
                _walk_dir(child, child_rel)
                continue

            try:
                data = child.read_bytes()
            except Exception:  # noqa: BLE001
                continue

            target = root / child_rel
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                created.append(str(child_rel))
                continue

            try:
                existing = target.read_bytes()
            except Exception:  # noqa: BLE001
                continue

            if _sha256_bytes(existing) != _sha256_bytes(data):
                drifted.append(str(child_rel))

    _walk_dir(tmpl_root, Path())

    if drifted:
        try:
            workspace_daily_root = root / "memory" / "dailies"
            ensure_daily_log(workspace_daily_root, date.today())
            summary = "Template drift detected (kept your versions): " + ", ".join(drifted[:12])
            if len(drifted) > 12:
                summary += f", ... (+{len(drifted) - 12} more)"
            append_daily_note(workspace_daily_root, date.today(), summary)
        except Exception as exc:  # noqa: BLE001
            warning = f"template drift note failed: {exc}"

    return MaterializeResult(created, drifted, warning)
