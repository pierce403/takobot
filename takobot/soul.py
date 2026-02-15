from __future__ import annotations

from pathlib import Path

from .paths import repo_root


DEFAULT_SOUL_NAME = "Tako"
DEFAULT_SOUL_ROLE = "Help the operator think clearly, decide wisely, and act safely while staying incredibly curious about the world."
DEFAULT_SOUL_MISSION = DEFAULT_SOUL_ROLE


def soul_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    return repo_root() / "SOUL.md"


def _sanitize(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    return cleaned


def read_identity(path: Path | None = None) -> tuple[str, str]:
    target = soul_path(path)
    if not target.exists():
        return DEFAULT_SOUL_NAME, DEFAULT_SOUL_ROLE

    lines = target.read_text(encoding="utf-8").splitlines()
    in_identity = False
    name = ""
    role = ""

    for line in lines:
        stripped = line.strip()
        if stripped == "## Identity":
            in_identity = True
            continue
        if in_identity and stripped.startswith("## "):
            break
        if in_identity and stripped.startswith("- Name:"):
            name = stripped[len("- Name:") :].strip()
        if in_identity and stripped.startswith("- Role:"):
            role = stripped[len("- Role:") :].strip()
        if in_identity and stripped.startswith("- Mission:") and not role:
            role = stripped[len("- Mission:") :].strip()

    return (_sanitize(name) or DEFAULT_SOUL_NAME, _sanitize(role) or DEFAULT_SOUL_ROLE)


def read_identity_mission(path: Path | None = None) -> tuple[str, str]:
    return read_identity(path)


def update_identity(name: str, role: str, path: Path | None = None) -> tuple[str, str]:
    target = soul_path(path)
    current_name, current_role = read_identity(target)

    final_name = _sanitize(name) or current_name
    final_role = _sanitize(role) or current_role

    if not target.exists():
        content = (
            "# SOUL.md — Identity & Boundaries (Not Memory)\n\n"
            "## Identity\n\n"
            f"- Name: {final_name}\n"
            f"- Role: {final_role}\n"
        )
        target.write_text(content, encoding="utf-8")
        return final_name, final_role

    lines = target.read_text(encoding="utf-8").splitlines()

    out: list[str] = []
    in_identity = False
    saw_identity = False
    saw_name = False
    saw_role = False

    for line in lines:
        stripped = line.strip()
        if stripped == "## Identity":
            saw_identity = True
            in_identity = True
            saw_name = False
            saw_role = False
            out.append(line)
            continue

        if in_identity and stripped.startswith("## "):
            if not saw_name:
                out.append(f"- Name: {final_name}")
            if not saw_role:
                out.append(f"- Role: {final_role}")
            if out and out[-1] != "":
                out.append("")
            in_identity = False

        if in_identity and stripped.startswith("- Name:"):
            out.append(f"- Name: {final_name}")
            saw_name = True
            continue
        if in_identity and stripped.startswith("- Role:"):
            out.append(f"- Role: {final_role}")
            saw_role = True
            continue

        out.append(line)

    if in_identity:
        if not saw_name:
            out.append(f"- Name: {final_name}")
        if not saw_role:
            out.append(f"- Role: {final_role}")

    if not saw_identity:
        if out and out[-1] != "":
            out.append("")
        out.extend(
            [
                "## Identity",
                "",
                f"- Name: {final_name}",
                f"- Role: {final_role}",
            ]
        )

    target.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return final_name, final_role


def update_identity_mission(name: str, mission: str, path: Path | None = None) -> tuple[str, str]:
    return update_identity(name, mission, path)
