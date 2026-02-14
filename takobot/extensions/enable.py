from __future__ import annotations

from pathlib import Path

from .analyze import file_hashes
from .model import PermissionSet


def verify_integrity(record: dict, *, workspace_root: Path) -> tuple[bool, str]:
    rel = str(record.get("path") or "").strip()
    if not rel:
        return False, "missing installed path in registry"
    dest = workspace_root / rel
    if not dest.exists():
        return False, f"installed path missing: {dest}"

    expected = record.get("hashes")
    if not isinstance(expected, dict) or not expected:
        return False, "missing expected hashes in registry"

    current = file_hashes(dest)
    if current != expected:
        return False, "files changed since install (hash mismatch); re-review required"
    return True, ""


def permissions_ok(record: dict, *, policy_defaults: PermissionSet) -> tuple[bool, str]:
    requested = record.get("requested_permissions")
    requested_set = PermissionSet.from_mapping(requested) if isinstance(requested, dict) else PermissionSet()
    exceeds = requested_set.exceeds(policy_defaults)
    if exceeds:
        return False, "requested permissions exceed workspace defaults: " + ", ".join(exceeds)
    return True, ""

