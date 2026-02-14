from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .model import AnalysisReport, Kind


REGISTRY_VERSION = 1


def load_registry(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": REGISTRY_VERSION, "pending": {}, "installed": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {"version": REGISTRY_VERSION, "pending": {}, "installed": {}}
    if not isinstance(data, dict):
        return {"version": REGISTRY_VERSION, "pending": {}, "installed": {}}
    data.setdefault("version", REGISTRY_VERSION)
    data.setdefault("pending", {})
    data.setdefault("installed", {})
    if not isinstance(data.get("pending"), dict):
        data["pending"] = {}
    if not isinstance(data.get("installed"), dict):
        data["installed"] = {}
    return data


def save_registry(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def pending_key(quarantine_id: str) -> str:
    return quarantine_id


def installed_key(kind: Kind, name: str) -> str:
    return f"{kind}:{name}"


def record_pending(path: Path, report: AnalysisReport, *, qdir: Path) -> None:
    data = load_registry(path)
    data["pending"][pending_key(report.quarantine_id)] = {
        "id": report.quarantine_id,
        "kind": report.kind,
        "name": report.manifest.name,
        "version": report.manifest.version,
        "risk": report.risk,
        "recommendation": report.recommendation,
        "requested_permissions": report.manifest.requested_permissions.to_dict(),
        "source_url": report.provenance.source_url,
        "final_url": report.provenance.final_url,
        "sha256": report.provenance.sha256,
        "bytes": report.provenance.bytes,
        "quarantine_dir": str(qdir),
    }
    save_registry(path, data)


def list_pending(path: Path) -> list[dict[str, Any]]:
    data = load_registry(path)
    pending = data.get("pending", {})
    if not isinstance(pending, dict):
        return []
    items = [value for value in pending.values() if isinstance(value, dict)]
    return sorted(items, key=lambda x: str(x.get("id") or ""))


def get_pending(path: Path, quarantine_id: str) -> dict[str, Any] | None:
    data = load_registry(path)
    pending = data.get("pending", {})
    if not isinstance(pending, dict):
        return None
    value = pending.get(pending_key(quarantine_id))
    return value if isinstance(value, dict) else None


def drop_pending(path: Path, quarantine_id: str) -> None:
    data = load_registry(path)
    pending = data.get("pending", {})
    if isinstance(pending, dict):
        pending.pop(pending_key(quarantine_id), None)
    save_registry(path, data)


def record_installed(path: Path, record: dict[str, Any]) -> None:
    kind = str(record.get("kind") or "").strip()
    name = str(record.get("name") or "").strip()
    if kind not in {"skill", "tool"} or not name:
        raise ValueError("invalid installed record")
    data = load_registry(path)
    data["installed"][installed_key(kind, name)] = record
    save_registry(path, data)


def get_installed(path: Path, *, kind: Kind, name: str) -> dict[str, Any] | None:
    data = load_registry(path)
    installed = data.get("installed", {})
    if not isinstance(installed, dict):
        return None
    value = installed.get(installed_key(kind, name))
    return value if isinstance(value, dict) else None


def set_enabled(path: Path, *, kind: Kind, name: str, enabled: bool) -> None:
    data = load_registry(path)
    installed = data.get("installed", {})
    if not isinstance(installed, dict):
        installed = {}
        data["installed"] = installed
    key = installed_key(kind, name)
    record = installed.get(key)
    if not isinstance(record, dict):
        raise KeyError(f"extension not installed: {kind} {name}")
    record["enabled"] = bool(enabled)
    installed[key] = record
    save_registry(path, data)


def list_installed(path: Path, *, kind: Kind | None = None) -> list[dict[str, Any]]:
    data = load_registry(path)
    installed = data.get("installed", {})
    if not isinstance(installed, dict):
        return []
    items = [value for value in installed.values() if isinstance(value, dict)]
    if kind:
        items = [item for item in items if str(item.get("kind")) == kind]
    return sorted(items, key=lambda x: (str(x.get("kind") or ""), str(x.get("name") or "")))

