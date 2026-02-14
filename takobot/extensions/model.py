from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


Kind = Literal["skill", "tool"]
Risk = Literal["low", "medium", "high"]


@dataclass(frozen=True)
class PermissionSet:
    network: bool = False
    shell: bool = False
    xmtp: bool = False
    filesystem: bool = False

    def to_dict(self) -> dict[str, bool]:
        return {
            "network": bool(self.network),
            "shell": bool(self.shell),
            "xmtp": bool(self.xmtp),
            "filesystem": bool(self.filesystem),
        }

    @staticmethod
    def from_mapping(value: object) -> "PermissionSet":
        if not isinstance(value, dict):
            return PermissionSet()
        def _b(key: str) -> bool:
            raw = value.get(key)
            if isinstance(raw, bool):
                return raw
            if isinstance(raw, (int, float)):
                return bool(raw)
            if isinstance(raw, str):
                lowered = raw.strip().lower()
                if lowered in {"1", "true", "yes", "y", "on"}:
                    return True
                if lowered in {"0", "false", "no", "n", "off"}:
                    return False
            return False
        return PermissionSet(
            network=_b("network"),
            shell=_b("shell"),
            xmtp=_b("xmtp"),
            filesystem=_b("filesystem"),
        )

    def exceeds(self, other: "PermissionSet") -> list[str]:
        """Return permission names that are true here but false in other."""

        out: list[str] = []
        if self.network and not other.network:
            out.append("network")
        if self.shell and not other.shell:
            out.append("shell")
        if self.xmtp and not other.xmtp:
            out.append("xmtp")
        if self.filesystem and not other.filesystem:
            out.append("filesystem")
        return out


@dataclass(frozen=True)
class ExtensionManifest:
    kind: Kind
    name: str
    version: str
    description: str
    entry_files: list[str] = field(default_factory=list)
    requested_permissions: PermissionSet = field(default_factory=PermissionSet)


@dataclass(frozen=True)
class QuarantineProvenance:
    source_url: str
    fetched_at: str
    final_url: str
    content_type: str
    sha256: str
    bytes: int

    @staticmethod
    def now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()


@dataclass(frozen=True)
class StaticScanHit:
    path: str
    pattern: str


@dataclass(frozen=True)
class AnalysisReport:
    quarantine_id: str
    kind: Kind
    manifest: ExtensionManifest
    provenance: QuarantineProvenance
    root_dir: Path
    file_hashes: dict[str, str]
    risky_hits: list[StaticScanHit]
    risk: Risk
    recommendation: str

