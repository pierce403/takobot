from __future__ import annotations

from pathlib import Path
import tomllib

from .paths import repo_root


def load_skills_frontmatter_excerpt(*, root: Path | None = None, max_chars: int = 1400) -> str:
    return _load_root_doc_excerpt(root=root, filename="SKILLS.md", max_chars=max_chars)


def load_tools_frontmatter_excerpt(*, root: Path | None = None, max_chars: int = 1400) -> str:
    return _load_root_doc_excerpt(root=root, filename="TOOLS.md", max_chars=max_chars)


def build_skills_inventory_excerpt(
    *,
    root: Path | None = None,
    max_items: int = 20,
    max_chars: int = 1600,
) -> str:
    target_root = root or repo_root()
    skills_root = target_root / "skills"
    if not skills_root.exists():
        return "skills/ directory is missing."

    entries: list[str] = []
    for item in sorted(skills_root.iterdir()):
        if not item.is_dir() or item.name.startswith("."):
            continue
        slug = item.name
        summary = _skill_summary(item)
        entries.append(f"- {slug}: {summary}")
        if len(entries) >= max(1, int(max_items)):
            break

    if not entries:
        return "No installed skills detected under skills/."

    return _truncate("\n".join(entries), max_chars=max_chars)


def build_tools_inventory_excerpt(
    *,
    root: Path | None = None,
    max_items: int = 20,
    max_chars: int = 1600,
) -> str:
    target_root = root or repo_root()
    tools_root = target_root / "tools"
    if not tools_root.exists():
        return "tools/ directory is missing."

    entries: list[str] = []
    for item in sorted(tools_root.iterdir()):
        if not item.is_dir() or item.name.startswith("."):
            continue
        slug = item.name
        summary = _tool_summary(item)
        entries.append(f"- {slug}: {summary}")
        if len(entries) >= max(1, int(max_items)):
            break

    if not entries:
        return "No installed tools detected under tools/."

    return _truncate("\n".join(entries), max_chars=max_chars)


def _load_root_doc_excerpt(*, root: Path | None, filename: str, max_chars: int) -> str:
    target_root = root or repo_root()
    path = target_root / filename
    if not path.exists():
        return f"{filename} is missing."
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return f"{filename} read failed: {exc}"
    return _truncate(_normalize_multiline(text), max_chars=max_chars)


def _skill_summary(skill_dir: Path) -> str:
    playbook = skill_dir / "playbook.md"
    if playbook.exists():
        purpose = _section_body(playbook, "## Purpose")
        if purpose:
            return purpose
    readme = skill_dir / "README.md"
    if readme.exists():
        first = _first_content_line(readme)
        if first:
            return first
    return "installed skill"


def _tool_summary(tool_dir: Path) -> str:
    manifest = tool_dir / "manifest.toml"
    if manifest.exists():
        try:
            payload = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if isinstance(payload, dict):
            tool_section = payload.get("tool")
            if isinstance(tool_section, dict):
                description = _clean_inline(str(tool_section.get("description") or ""))
                if description:
                    return description
    readme = tool_dir / "README.md"
    if readme.exists():
        first = _first_content_line(readme)
        if first:
            return first
    return "installed tool"


def _first_content_line(path: Path) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            continue
        return _clean_inline(line)
    return ""


def _section_body(path: Path, heading: str) -> str:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except Exception:
        return ""
    capture = False
    body: list[str] = []
    for raw in lines:
        line = raw.rstrip()
        stripped = line.strip()
        if stripped == heading:
            capture = True
            continue
        if capture and stripped.startswith("## "):
            break
        if capture and stripped:
            body.append(stripped)
    return _clean_inline(" ".join(body))


def _clean_inline(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _normalize_multiline(text: str) -> str:
    lines = [line.rstrip() for line in (text or "").splitlines()]
    joined = "\n".join(lines).strip()
    if not joined:
        return "(empty)"
    return joined


def _truncate(text: str, *, max_chars: int) -> str:
    limit = max(200, int(max_chars))
    normalized = _normalize_multiline(text)
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3].rstrip() + "..."
