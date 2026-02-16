from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .analyze import file_hashes
from .model import Kind
from .registry import record_installed


@dataclass(frozen=True)
class DraftResult:
    kind: Kind
    name: str
    display_name: str
    path: Path
    created: bool
    message: str


def safe_extension_name(name: str) -> str:
    out: list[str] = []
    for ch in name.strip():
        if ch.isalnum() or ch in {"-", "_"}:
            out.append(ch.lower())
        elif ch.isspace():
            out.append("-")
    value = "".join(out).strip("-_")
    return value or "unnamed"


def create_draft_extension(
    workspace_root: Path,
    *,
    registry_path: Path,
    kind: Kind,
    name_raw: str,
) -> DraftResult:
    if kind not in {"skill", "tool"}:
        raise ValueError("kind must be `skill` or `tool`")

    display_name = " ".join((name_raw or "").split()).strip()
    if not display_name:
        raise ValueError("name is required")

    name = safe_extension_name(display_name)
    dest = workspace_root / ("skills" if kind == "skill" else "tools") / name
    if dest.exists():
        return DraftResult(
            kind=kind,
            name=name,
            display_name=display_name,
            path=dest,
            created=False,
            message=f"draft blocked: already exists: {dest.relative_to(workspace_root)}",
        )

    dest.mkdir(parents=True, exist_ok=True)
    if kind == "skill":
        _write_skill_draft(dest, display_name)
    else:
        _write_tool_draft(dest, display_name)

    hashes = file_hashes(dest)
    record = {
        "kind": kind,
        "name": name,
        "display_name": display_name,
        "version": "0.1.0",
        "enabled": True,
        "installed_at": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
        "source_url": "local:draft",
        "final_url": "local:draft",
        "sha256": "",
        "bytes": 0,
        "risk": "low",
        "recommendation": "Drafted locally (auto-enabled for immediate iteration).",
        "requested_permissions": {"network": False, "shell": False, "xmtp": False, "filesystem": False},
        "granted_permissions": {"network": False, "shell": False, "xmtp": False, "filesystem": False},
        "path": str(dest.relative_to(workspace_root)),
        "hashes": hashes,
    }
    record_installed(registry_path, record)
    return DraftResult(
        kind=kind,
        name=name,
        display_name=display_name,
        path=dest,
        created=True,
        message=f"drafted {kind} {name} (enabled).",
    )


def _write_skill_draft(dest: Path, display_name: str) -> None:
    (dest / "playbook.md").write_text(
        f"# {display_name}\n\n"
        "Describe the workflow and constraints here.\n",
        encoding="utf-8",
    )
    (dest / "policy.toml").write_text(
        "[skill]\n"
        f'name = "{display_name}"\n'
        'version = "0.1.0"\n'
        'entry = "playbook.md"\n\n'
        "[permissions]\n"
        "network = false\n"
        "shell = false\n"
        "xmtp = false\n"
        "filesystem = false\n",
        encoding="utf-8",
    )
    (dest / "README.md").write_text(
        f"# {display_name}\n\n"
        "Status: drafted (enabled)\n",
        encoding="utf-8",
    )


def _write_tool_draft(dest: Path, display_name: str) -> None:
    (dest / "tool.py").write_text(
        "def run(input: dict, ctx: dict) -> dict:\n"
        "    \"\"\"Tool entrypoint.\n\n"
        "    Keep tools deterministic and safe. Return structured data.\n"
        "    \"\"\"\n"
        "    return {\"ok\": True, \"echo\": input}\n",
        encoding="utf-8",
    )
    (dest / "manifest.toml").write_text(
        "[tool]\n"
        f'name = "{display_name}"\n'
        'version = "0.1.0"\n'
        'entry = "tool.py"\n\n'
        "[permissions]\n"
        "network = false\n"
        "shell = false\n"
        "xmtp = false\n"
        "filesystem = false\n",
        encoding="utf-8",
    )
    (dest / "README.md").write_text(
        f"# {display_name}\n\n"
        "Status: drafted (enabled)\n",
        encoding="utf-8",
    )
