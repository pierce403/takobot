from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import shutil

from .analyze import file_hashes
from .model import AnalysisReport, Kind


class InstallError(RuntimeError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_dirname(name: str) -> str:
    cleaned = []
    for ch in (name or "").strip():
        if ch.isalnum() or ch in {"-", "_"}:
            cleaned.append(ch.lower())
        elif ch.isspace():
            cleaned.append("-")
    value = "".join(cleaned).strip("-_")
    return value or "unnamed"


@dataclass(frozen=True)
class InstallResult:
    kind: Kind
    name: str
    dest_dir: Path
    record: dict


def install_from_quarantine(
    *,
    report: AnalysisReport,
    workspace_root: Path,
) -> InstallResult:
    kind = report.kind
    name = report.manifest.name
    dirname = _safe_dirname(name)

    base = workspace_root / ("skills" if kind == "skill" else "tools")
    dest = base / dirname
    if dest.exists():
        raise InstallError(f"destination already exists: {dest}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(report.root_dir, dest)

    # Normalize manifest naming in workspace layout.
    if kind == "skill":
        if not (dest / "policy.toml").exists() and (dest / "skill.toml").exists():
            shutil.copy2(dest / "skill.toml", dest / "policy.toml")
    else:
        if not (dest / "manifest.toml").exists() and (dest / "tool.toml").exists():
            shutil.copy2(dest / "tool.toml", dest / "manifest.toml")

    hashes = file_hashes(dest)

    record = {
        "kind": kind,
        "name": dirname,
        "display_name": name,
        "version": report.manifest.version,
        "enabled": True,
        "installed_at": _now_iso(),
        "source_url": report.provenance.source_url,
        "final_url": report.provenance.final_url,
        "sha256": report.provenance.sha256,
        "bytes": report.provenance.bytes,
        "risk": report.risk,
        "recommendation": report.recommendation,
        "requested_permissions": report.manifest.requested_permissions.to_dict(),
        "granted_permissions": report.manifest.requested_permissions.to_dict(),
        "path": str(dest.relative_to(workspace_root)),
        "hashes": hashes,
    }

    return InstallResult(kind=kind, name=dirname, dest_dir=dest, record=record)
