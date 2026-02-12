from __future__ import annotations

from datetime import date
from pathlib import Path


PROMOTIONS_HEADING = "## Promotions"


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def ensure_promotions_section(path: Path) -> None:
    lines = _read_lines(path)
    if any(line.strip() == PROMOTIONS_HEADING for line in lines):
        return
    lines.append("")
    lines.append(PROMOTIONS_HEADING)
    lines.append("")
    lines.append("- ")
    _write_lines(path, lines)


def promote(path: Path, *, day: date, note: str) -> None:
    cleaned = " ".join(note.strip().split())
    if not cleaned:
        raise ValueError("promotion note is empty")

    ensure_promotions_section(path)
    lines = _read_lines(path)
    heading_idx = None
    for idx, line in enumerate(lines):
        if line.strip() == PROMOTIONS_HEADING:
            heading_idx = idx
            break
    if heading_idx is None:
        raise RuntimeError("promotions section missing")

    insert_at = len(lines)
    for idx in range(heading_idx + 1, len(lines)):
        if lines[idx].startswith("## ") and idx > heading_idx:
            insert_at = idx
            break
    bullet = f"- {day.isoformat()}: {cleaned}"
    new_lines = lines[:insert_at] + [bullet] + lines[insert_at:]
    _write_lines(path, new_lines)

