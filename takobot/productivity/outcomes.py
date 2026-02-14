from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path


OUTCOMES_HEADING_PREFIX = "## Outcomes"


@dataclass(frozen=True)
class Outcome:
    text: str
    done: bool


def _read_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def _write_lines(path: Path, lines: list[str]) -> None:
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _find_outcomes_block(lines: list[str]) -> tuple[int, int] | None:
    start = None
    for idx, line in enumerate(lines):
        if line.startswith(OUTCOMES_HEADING_PREFIX):
            start = idx
            break
    if start is None:
        return None
    end = len(lines)
    for idx in range(start + 1, len(lines)):
        if lines[idx].startswith("## "):
            end = idx
            break
    return start, end


def _default_block(outcomes: list[Outcome]) -> list[str]:
    block = ["## Outcomes (3 for today)", ""]
    for item in outcomes:
        box = "x" if item.done else " "
        block.append(f"- [{box}] {item.text}".rstrip())
    block.append("")
    return block


def _coerce_three(texts: list[str]) -> list[str]:
    cleaned = [" ".join(item.strip().split()) for item in texts if " ".join(item.strip().split())]
    cleaned = cleaned[:3]
    while len(cleaned) < 3:
        cleaned.append("")
    return cleaned


def ensure_outcomes_section(path: Path) -> None:
    lines = _read_lines(path)
    if _find_outcomes_block(lines) is not None:
        return

    insert_at = 0
    for idx, line in enumerate(lines):
        if line.startswith("# "):
            continue
        if line.strip() == "":
            insert_at = idx + 1
            break
    block = _default_block([Outcome("", False), Outcome("", False), Outcome("", False)])
    new_lines = lines[:insert_at] + [""] + block + lines[insert_at:]
    _write_lines(path, new_lines)


def get_outcomes(path: Path) -> list[Outcome]:
    lines = _read_lines(path)
    block = _find_outcomes_block(lines)
    if block is None:
        return []
    start, end = block
    items: list[Outcome] = []
    for line in lines[start + 1 : end]:
        stripped = line.strip()
        if not stripped.startswith("- ["):
            continue
        done = stripped.startswith("- [x]") or stripped.startswith("- [X]")
        text = stripped[5:].strip() if stripped.startswith("- [") else stripped
        items.append(Outcome(text=text, done=done))
    return items


def set_outcomes(path: Path, texts: list[str]) -> list[Outcome]:
    ensure_outcomes_section(path)
    lines = _read_lines(path)
    block = _find_outcomes_block(lines)
    if block is None:
        raise RuntimeError("outcomes block missing after ensure")
    start, end = block

    coerced = _coerce_three(texts)
    outcomes = [Outcome(text=item, done=False) for item in coerced]
    replacement = _default_block(outcomes)
    new_lines = lines[:start] + replacement + lines[end:]
    _write_lines(path, new_lines)
    return outcomes


def mark_outcome(path: Path, index_1: int, *, done: bool) -> list[Outcome]:
    ensure_outcomes_section(path)
    current = get_outcomes(path)
    if not current:
        current = [Outcome("", False), Outcome("", False), Outcome("", False)]
    idx = index_1 - 1
    if idx < 0 or idx >= len(current):
        raise ValueError("outcome index out of range")
    updated = list(current)
    updated[idx] = Outcome(text=updated[idx].text, done=done)
    ensure_outcomes_section(path)
    lines = _read_lines(path)
    block = _find_outcomes_block(lines)
    if block is None:
        raise RuntimeError("outcomes block missing")
    start, end = block
    replacement = _default_block(updated)
    new_lines = lines[:start] + replacement + lines[end:]
    _write_lines(path, new_lines)
    return updated


def outcomes_completion(outcomes: list[Outcome]) -> tuple[int, int]:
    total = len(outcomes)
    done = sum(1 for item in outcomes if item.done and item.text.strip())
    return done, total


def today_outcomes_path(daily_root: Path, day: date) -> Path:
    return daily_root / f"{day.isoformat()}.md"

