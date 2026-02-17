from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable

from .paths import repo_root


DEFAULT_SOUL_NAME = "Tako"
DEFAULT_SOUL_ROLE = "Help the operator think clearly, decide wisely, and act safely while staying incredibly curious about the world."
DEFAULT_SOUL_MISSION = DEFAULT_SOUL_ROLE
MISSION_OBJECTIVES_HEADER = "## Mission Objectives"
MISSION_OBJECTIVES_PLACEHOLDER = "No explicit mission objectives yet."


def soul_path(path: Path | None = None) -> Path:
    if path is not None:
        return path
    return repo_root() / "SOUL.md"


def load_soul_excerpt(*, path: Path | None = None, max_chars: int = 1800) -> str:
    target = soul_path(path)
    if not target.exists():
        return "SOUL.md is missing."
    try:
        text = target.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return f"SOUL.md read failed: {exc}"

    lines = [line.rstrip() for line in text.splitlines()]
    if not lines:
        return "SOUL.md is empty."

    joined = "\n".join(lines).strip()
    if not joined:
        return "SOUL.md is empty."

    limit = max(200, int(max_chars))
    if len(joined) <= limit:
        return joined
    return joined[: limit - 3].rstrip() + "..."


def _sanitize(value: str) -> str:
    cleaned = " ".join(value.strip().split())
    return cleaned


def _strip_objective_prefix(value: str) -> str:
    stripped = value.strip()
    stripped = re.sub(r"^(?:[-*]\s+|\d+[.)]\s+)", "", stripped)
    return stripped


def parse_mission_objectives_text(text: str) -> list[str]:
    raw = text.replace("\r", "\n")
    candidates: list[str] = []
    for line in raw.split("\n"):
        chunk = line.strip()
        if not chunk:
            continue
        parts = [part.strip() for part in chunk.split(";") if part.strip()]
        for part in parts:
            cleaned = _sanitize(_strip_objective_prefix(part))
            if cleaned:
                candidates.append(cleaned)
    if not candidates:
        single = _sanitize(_strip_objective_prefix(raw))
        if single:
            candidates = [single]
    seen: set[str] = set()
    normalized: list[str] = []
    for item in candidates:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(item)
    return normalized


def _normalize_mission_objectives(objectives: Iterable[str]) -> list[str]:
    merged = parse_mission_objectives_text("\n".join(str(item) for item in objectives))
    return merged or [MISSION_OBJECTIVES_PLACEHOLDER]


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


def read_mission_objectives(path: Path | None = None) -> list[str]:
    target = soul_path(path)
    if not target.exists():
        return []

    lines = target.read_text(encoding="utf-8").splitlines()
    in_section = False
    objectives: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped == MISSION_OBJECTIVES_HEADER:
            in_section = True
            continue
        if in_section and stripped.startswith("## "):
            break
        if not in_section or not stripped:
            continue
        if stripped.startswith("- ") or stripped.startswith("* "):
            item = _sanitize(_strip_objective_prefix(stripped))
            if item:
                objectives.append(item)
            continue
        if re.match(r"^\d+[.)]\s+", stripped):
            item = _sanitize(_strip_objective_prefix(stripped))
            if item:
                objectives.append(item)
            continue
        if objectives:
            objectives[-1] = _sanitize(f"{objectives[-1]} {stripped}")
    filtered = [item for item in objectives if item and item != MISSION_OBJECTIVES_PLACEHOLDER]
    seen: set[str] = set()
    unique: list[str] = []
    for item in filtered:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


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


def update_mission_objectives(objectives: Iterable[str], path: Path | None = None) -> list[str]:
    target = soul_path(path)
    normalized = _normalize_mission_objectives(objectives)

    if not target.exists():
        content = (
            "# SOUL.md — Identity & Boundaries (Not Memory)\n\n"
            "## Identity\n\n"
            f"- Name: {DEFAULT_SOUL_NAME}\n"
            f"- Role: {DEFAULT_SOUL_ROLE}\n\n"
            f"{MISSION_OBJECTIVES_HEADER}\n\n"
            + "\n".join(f"- {item}" for item in normalized)
            + "\n"
        )
        target.write_text(content, encoding="utf-8")
        return [] if normalized == [MISSION_OBJECTIVES_PLACEHOLDER] else normalized

    lines = target.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    in_identity = False
    in_mission = False
    saw_identity = False
    saw_mission = False
    inserted_after_identity = False

    def _append_mission_section() -> None:
        if out and out[-1] != "":
            out.append("")
        out.append(MISSION_OBJECTIVES_HEADER)
        out.append("")
        out.extend(f"- {item}" for item in normalized)
        out.append("")

    for line in lines:
        stripped = line.strip()
        if stripped == "## Identity":
            saw_identity = True
            in_identity = True
            out.append(line)
            continue

        if in_identity and stripped.startswith("## "):
            if not saw_mission and not inserted_after_identity:
                _append_mission_section()
                inserted_after_identity = True
            in_identity = False

        if stripped == MISSION_OBJECTIVES_HEADER:
            saw_mission = True
            in_mission = True
            _append_mission_section()
            continue

        if in_mission:
            if stripped.startswith("## "):
                in_mission = False
                out.append(line)
            continue

        out.append(line)

    if not saw_mission:
        if not inserted_after_identity and saw_identity:
            _append_mission_section()
        elif not saw_identity:
            if out and out[-1] != "":
                out.append("")
            out.extend(
                [
                    "## Identity",
                    "",
                    f"- Name: {DEFAULT_SOUL_NAME}",
                    f"- Role: {DEFAULT_SOUL_ROLE}",
                    "",
                ]
            )
            _append_mission_section()
        elif out and out[-1] != "":
            out.append("")
            _append_mission_section()

    target.write_text("\n".join(out).rstrip() + "\n", encoding="utf-8")
    return [] if normalized == [MISSION_OBJECTIVES_PLACEHOLDER] else normalized
