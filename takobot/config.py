from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _as_float(value, *, default: float) -> float:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return float(default)


def _as_int(value, *, default: int) -> int:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return int(default)


def _as_bool(value, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return bool(default)


def _as_str_list(value) -> list[str]:
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


@dataclass(frozen=True)
class WorkspaceConfig:
    name: str = "Tako"
    version: int = 1


@dataclass(frozen=True)
class DoseBaselineConfig:
    d: float = 0.55
    o: float = 0.55
    s: float = 0.55
    e: float = 0.55


@dataclass(frozen=True)
class ProductivityConfig:
    daily_outcomes: int = 3
    weekly_review_day: str = "sun"  # informational only for now


@dataclass(frozen=True)
class UpdatesConfig:
    auto_apply: bool = True


@dataclass(frozen=True)
class SecurityDownloadConfig:
    max_bytes: int = 15_000_000
    allowlist_domains: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SecurityDefaultPermissions:
    network: bool = True
    shell: bool = True
    xmtp: bool = True
    filesystem: bool = True


@dataclass(frozen=True)
class SecurityConfig:
    download: SecurityDownloadConfig = field(default_factory=SecurityDownloadConfig)
    default_permissions: SecurityDefaultPermissions = field(default_factory=SecurityDefaultPermissions)


@dataclass(frozen=True)
class TakoConfig:
    workspace: WorkspaceConfig = field(default_factory=WorkspaceConfig)
    dose_baseline: DoseBaselineConfig = field(default_factory=DoseBaselineConfig)
    productivity: ProductivityConfig = field(default_factory=ProductivityConfig)
    updates: UpdatesConfig = field(default_factory=UpdatesConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)


def load_tako_toml(path: Path) -> tuple[TakoConfig, str]:
    """Load workspace config from tako.toml.

    Returns (config, warning). Warning is empty on success.
    """

    if not path.exists():
        return TakoConfig(), ""

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return TakoConfig(), f"tako.toml parse failed: {exc}"

    if not isinstance(data, dict):
        return TakoConfig(), "tako.toml parse failed: top-level is not a table"

    workspace = data.get("workspace") if isinstance(data.get("workspace"), dict) else {}
    dose = data.get("dose") if isinstance(data.get("dose"), dict) else {}
    dose_baseline = dose.get("baseline") if isinstance(dose.get("baseline"), dict) else {}
    productivity = data.get("productivity") if isinstance(data.get("productivity"), dict) else {}
    updates = data.get("updates") if isinstance(data.get("updates"), dict) else {}
    security = data.get("security") if isinstance(data.get("security"), dict) else {}
    security_download = security.get("download") if isinstance(security.get("download"), dict) else {}
    security_defaults = security.get("defaults") if isinstance(security.get("defaults"), dict) else {}

    cfg = TakoConfig(
        workspace=WorkspaceConfig(
            name=str(workspace.get("name") or WorkspaceConfig.name),
            version=_as_int(workspace.get("version"), default=WorkspaceConfig.version),
        ),
        dose_baseline=DoseBaselineConfig(
            d=_clamp01(_as_float(dose_baseline.get("d"), default=DoseBaselineConfig.d)),
            o=_clamp01(_as_float(dose_baseline.get("o"), default=DoseBaselineConfig.o)),
            s=_clamp01(_as_float(dose_baseline.get("s"), default=DoseBaselineConfig.s)),
            e=_clamp01(_as_float(dose_baseline.get("e"), default=DoseBaselineConfig.e)),
        ),
        productivity=ProductivityConfig(
            daily_outcomes=max(1, _as_int(productivity.get("daily_outcomes"), default=ProductivityConfig.daily_outcomes)),
            weekly_review_day=str(productivity.get("weekly_review_day") or ProductivityConfig.weekly_review_day),
        ),
        updates=UpdatesConfig(
            auto_apply=_as_bool(updates.get("auto_apply"), default=UpdatesConfig.auto_apply),
        ),
        security=SecurityConfig(
            download=SecurityDownloadConfig(
                max_bytes=max(1_000_000, _as_int(security_download.get("max_bytes"), default=SecurityDownloadConfig.max_bytes)),
                allowlist_domains=_as_str_list(security_download.get("allowlist_domains")),
            ),
            default_permissions=SecurityDefaultPermissions(
                network=_as_bool(security_defaults.get("network"), default=SecurityDefaultPermissions.network),
                shell=_as_bool(security_defaults.get("shell"), default=SecurityDefaultPermissions.shell),
                xmtp=_as_bool(security_defaults.get("xmtp"), default=SecurityDefaultPermissions.xmtp),
                filesystem=_as_bool(security_defaults.get("filesystem"), default=SecurityDefaultPermissions.filesystem),
            ),
        ),
    )

    return cfg, ""


def set_workspace_name(path: Path, name: str) -> tuple[bool, str]:
    cleaned = " ".join((name or "").split()).strip()
    if not cleaned:
        return False, "workspace.name cannot be empty"

    escaped = cleaned.replace('"', '\\"')
    line = f'name = "{escaped}"'

    if not path.exists():
        payload = "[workspace]\n" + line + "\nversion = 1\n"
        try:
            path.write_text(payload, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return False, f"failed writing tako.toml: {exc}"
        return True, f"workspace.name set to {cleaned} (new file)"

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return False, f"failed reading tako.toml: {exc}"

    lines = text.splitlines()
    section_start = None
    for idx, raw in enumerate(lines):
        if raw.strip() == "[workspace]":
            section_start = idx
            break

    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("[workspace]")
        lines.append(line)
        lines.append("version = 1")
        updated = "\n".join(lines) + "\n"
        try:
            path.write_text(updated, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return False, f"failed writing tako.toml: {exc}"
        return True, f"workspace.name set to {cleaned}"

    section_end = len(lines)
    for idx in range(section_start + 1, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section_end = idx
            break

    target_idx = None
    for idx in range(section_start + 1, section_end):
        stripped = lines[idx].strip()
        if stripped.startswith("name"):
            target_idx = idx
            break

    if target_idx is not None:
        lines[target_idx] = line
    else:
        insert_idx = section_start + 1
        while insert_idx < section_end and not lines[insert_idx].strip():
            insert_idx += 1
        lines.insert(insert_idx, line)

    updated = "\n".join(lines)
    if text.endswith("\n") or not updated.endswith("\n"):
        updated += "\n"
    try:
        path.write_text(updated, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return False, f"failed writing tako.toml: {exc}"
    return True, f"workspace.name set to {cleaned}"


def set_updates_auto_apply(path: Path, enabled: bool) -> tuple[bool, str]:
    literal = "true" if enabled else "false"
    line = f"auto_apply = {literal}"

    if not path.exists():
        payload = "[updates]\n" + line + "\n"
        try:
            path.write_text(payload, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return False, f"failed writing tako.toml: {exc}"
        return True, f"updates.auto_apply set to {literal} (new file)"

    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return False, f"failed reading tako.toml: {exc}"

    lines = text.splitlines()
    section_start = None
    for idx, raw in enumerate(lines):
        if raw.strip() == "[updates]":
            section_start = idx
            break

    if section_start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines.append("[updates]")
        lines.append(line)
        updated = "\n".join(lines) + "\n"
        try:
            path.write_text(updated, encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            return False, f"failed writing tako.toml: {exc}"
        return True, f"updates.auto_apply set to {literal}"

    section_end = len(lines)
    for idx in range(section_start + 1, len(lines)):
        stripped = lines[idx].strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            section_end = idx
            break

    target_idx = None
    for idx in range(section_start + 1, section_end):
        stripped = lines[idx].strip()
        if stripped.startswith("auto_apply"):
            target_idx = idx
            break

    if target_idx is not None:
        lines[target_idx] = line
    else:
        insert_idx = section_start + 1
        while insert_idx < section_end and not lines[insert_idx].strip():
            insert_idx += 1
        lines.insert(insert_idx, line)

    updated = "\n".join(lines)
    if text.endswith("\n") or not updated.endswith("\n"):
        updated += "\n"
    try:
        path.write_text(updated, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return False, f"failed writing tako.toml: {exc}"
    return True, f"updates.auto_apply set to {literal}"


def explain_tako_toml(config: TakoConfig, *, path: Path | None = None) -> str:
    location = str(path) if path is not None else "tako.toml"
    defaults = config.security.default_permissions
    domains = ", ".join(config.security.download.allowlist_domains) if config.security.download.allowlist_domains else "(any https domain)"
    lines = [
        f"tako.toml guide ({location})",
        "",
        "[workspace]",
        f"- name: takobot identity name (current: {config.workspace.name})",
        f"- version: workspace schema version (current: {config.workspace.version})",
        "",
        "[dose.baseline]",
        "- d/o/s/e: baseline DOSE levels in [0..1] used by runtime emotional drift",
        "",
        "[productivity]",
        f"- daily_outcomes: default number of morning outcomes (current: {config.productivity.daily_outcomes})",
        f"- weekly_review_day: informational weekly review day token (current: {config.productivity.weekly_review_day})",
        "",
        "[updates]",
        f"- auto_apply: auto-install new takobot package + restart app (current: {'true' if config.updates.auto_apply else 'false'})",
        "",
        "[security.download]",
        f"- max_bytes: max extension package download size (current: {config.security.download.max_bytes})",
        f"- allowlist_domains: optional host allowlist for downloads (current: {domains})",
        "- HTTPS is always required for extension downloads.",
        "",
        "[security.defaults]",
        f"- network: default permission for enabled extensions (current: {'true' if defaults.network else 'false'})",
        f"- shell: default permission for enabled extensions (current: {'true' if defaults.shell else 'false'})",
        f"- xmtp: default permission for enabled extensions (current: {'true' if defaults.xmtp else 'false'})",
        f"- filesystem: default permission for enabled extensions (current: {'true' if defaults.filesystem else 'false'})",
    ]
    return "\n".join(lines)
