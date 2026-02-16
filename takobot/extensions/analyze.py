from __future__ import annotations

import hashlib
from pathlib import Path
import re
import tomllib

from .model import AnalysisReport, ExtensionManifest, Kind, PermissionSet, QuarantineProvenance, Risk, StaticScanHit


_CODE_EXTS = {".py", ".sh", ".js", ".ts", ".rb", ".go", ".rs"}


_RISK_PATTERNS: list[tuple[str, str]] = [
    ("os.system", r"\bos\.system\b"),
    ("subprocess", r"\bsubprocess\.[a-zA-Z_]+\b"),
    ("eval", r"\beval\("),
    ("exec", r"\bexec\("),
    ("socket", r"\bsocket\.[a-zA-Z_]+\b"),
    ("requests", r"\brequests\.[a-zA-Z_]+\b"),
    ("urllib", r"\burllib\.request\b|\burllib\.urlopen\b"),
    ("os.environ", r"\bos\.environ\b"),
    ("dotenv", r"\bdotenv\b"),
    (".tako", r"\.tako[\\/]|/\\.tako/"),
    (".ssh", r"\.ssh[\\/]|/\\.ssh/"),
    ("id_rsa", r"\bid_rsa\b"),
]


class ManifestError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def _read_toml(path: Path) -> dict:
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ManifestError(f"failed to parse {path.name}: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestError(f"failed to parse {path.name}: top-level is not a table")
    return data


def _manifest_paths(root: Path, kind: Kind) -> list[Path]:
    if kind == "skill":
        return [root / "skill.toml", root / "policy.toml", root / "manifest.toml"]
    return [root / "tool.toml", root / "manifest.toml"]


def _find_package_root(extracted_files_dir: Path, kind: Kind) -> Path:
    # Prefer the direct extraction root.
    for mp in _manifest_paths(extracted_files_dir, kind):
        if mp.exists():
            return extracted_files_dir

    # Common archive shape: single top-level directory.
    try:
        children = [p for p in extracted_files_dir.iterdir() if p.is_dir()]
    except Exception:  # noqa: BLE001
        children = []
    if len(children) == 1:
        candidate = children[0]
        for mp in _manifest_paths(candidate, kind):
            if mp.exists():
                return candidate

    return extracted_files_dir


def load_manifest(root: Path, kind: Kind) -> ExtensionManifest:
    manifest_path = None
    for path in _manifest_paths(root, kind):
        if path.exists():
            manifest_path = path
            break
    if manifest_path is None:
        raise ManifestError(f"missing manifest ({'skill.toml' if kind == 'skill' else 'tool.toml'})")

    payload = _read_toml(manifest_path)
    header = payload.get(kind) if isinstance(payload.get(kind), dict) else {}
    if not isinstance(header, dict):
        header = {}

    name = str(header.get("name") or payload.get("name") or "").strip()
    version = str(header.get("version") or payload.get("version") or "0.0.0").strip()
    description = str(header.get("description") or payload.get("description") or "").strip()

    entry_files: list[str] = []
    raw_entry = header.get("entry_files", header.get("entry", payload.get("entry_files", payload.get("entry"))))
    if isinstance(raw_entry, str) and raw_entry.strip():
        entry_files = [raw_entry.strip()]
    elif isinstance(raw_entry, list):
        entry_files = [str(item).strip() for item in raw_entry if str(item).strip()]

    perms = payload.get("permissions") if isinstance(payload.get("permissions"), dict) else {}
    requested_permissions = PermissionSet.from_mapping(perms)

    if not name:
        raise ManifestError("manifest missing required field: name")

    # Provide a reasonable default entry if absent.
    if not entry_files:
        if kind == "skill" and (root / "playbook.md").exists():
            entry_files = ["playbook.md"]
        if kind == "tool" and (root / "tool.py").exists():
            entry_files = ["tool.py"]

    return ExtensionManifest(
        kind=kind,
        name=name,
        version=version,
        description=description,
        entry_files=entry_files,
        requested_permissions=requested_permissions,
    )


def file_hashes(root: Path) -> dict[str, str]:
    hashes: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        try:
            data = path.read_bytes()
        except Exception:  # noqa: BLE001
            continue
        hashes[rel] = _sha256_bytes(data)
    return hashes


def static_scan(root: Path) -> list[StaticScanHit]:
    hits: list[StaticScanHit] = []
    compiled = [(label, re.compile(pattern)) for label, pattern in _RISK_PATTERNS]

    for path in sorted(root.rglob("*")):
        if path.is_dir():
            continue
        if path.suffix.lower() not in _CODE_EXTS:
            continue
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except Exception:  # noqa: BLE001
            continue
        for label, cre in compiled:
            if cre.search(text):
                hits.append(StaticScanHit(path=rel, pattern=label))
    return hits


def risk_rating(
    *,
    requested: PermissionSet,
    defaults: PermissionSet,
    hits: list[StaticScanHit],
    has_executable_code: bool,
) -> tuple[Risk, str]:
    exceeds = requested.exceeds(defaults)
    if exceeds:
        return "high", f"requested permissions exceed workspace defaults: {', '.join(exceeds)}"
    if hits:
        return "medium", f"static scan flagged {len(hits)} risky callsite(s)"
    if has_executable_code:
        return "medium", "contains executable code"
    return "low", "no code and no flagged patterns"


def analyze_quarantine(
    *,
    quarantine_id: str,
    qdir: Path,
    kind: Kind,
    provenance: QuarantineProvenance,
    policy_defaults: PermissionSet,
) -> AnalysisReport:
    files_dir = qdir / "files"
    root_dir = _find_package_root(files_dir, kind)
    manifest = load_manifest(root_dir, kind)

    hashes = file_hashes(root_dir)
    has_code = any(Path(p).suffix.lower() in _CODE_EXTS for p in hashes.keys())
    hits = static_scan(root_dir)

    risk, reason = risk_rating(
        requested=manifest.requested_permissions,
        defaults=policy_defaults,
        hits=hits,
        has_executable_code=has_code,
    )

    if risk == "high":
        rec = "High risk: reject unless the operator explicitly accepts immediate enablement."
    elif risk == "medium":
        rec = "Medium risk: only accept if permissions and scan results are clearly understood."
    else:
        rec = "Low risk: safe for operator-approved install with immediate enablement."

    report = AnalysisReport(
        quarantine_id=quarantine_id,
        kind=kind,
        manifest=manifest,
        provenance=provenance,
        root_dir=root_dir,
        file_hashes=hashes,
        risky_hits=hits,
        risk=risk,
        recommendation=f"{rec} ({reason})",
    )

    # Persist a human-readable report for operator review.
    lines: list[str] = []
    lines.append(f"kind={kind}")
    lines.append(f"name={manifest.name}")
    lines.append(f"version={manifest.version}")
    lines.append(f"risk={risk}")
    lines.append(f"recommendation={report.recommendation}")
    lines.append(f"source_url={provenance.source_url}")
    lines.append(f"final_url={provenance.final_url}")
    lines.append(f"sha256={provenance.sha256}")
    lines.append(f"bytes={provenance.bytes}")
    lines.append(f"requested_permissions={manifest.requested_permissions.to_dict()}")
    if hits:
        lines.append("risky_hits:")
        for hit in hits[:40]:
            lines.append(f"- {hit.path}: {hit.pattern}")
        if len(hits) > 40:
            lines.append(f"- ... (+{len(hits) - 40} more)")
    (qdir / "analysis.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    return report
