from __future__ import annotations

from datetime import date
from pathlib import Path


def daily_path(daily_root: Path, day: date) -> Path:
    return daily_root / f"{day.isoformat()}.md"


def ensure_daily_log(daily_root: Path, day: date) -> Path:
    daily_root.mkdir(parents=True, exist_ok=True)
    path = daily_path(daily_root, day)
    if path.exists():
        return path
    content = (
        f"# Daily Log — {day.isoformat()}\n\n"
        "No secrets. No private keys. No tokens. Summaries only.\n\n"
        "## Outcomes (3 for today)\n\n"
        "- [ ] \n"
        "- [ ] \n"
        "- [ ] \n\n"
        "## Intent\n\n"
        "- \n\n"
        "## Notes\n\n"
        "- \n\n"
        "## Decisions\n\n"
        "- \n\n"
        "## Promote to MEMORY.md (if durable)\n\n"
        "- [ ] Promote long-lived decisions into repo-root `MEMORY.md`.\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def append_daily_note(daily_root: Path, day: date, note: str) -> Path:
    path = ensure_daily_log(daily_root, day)
    cleaned = " ".join(note.strip().split())
    if not cleaned:
        return path
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n- ")
        handle.write(cleaned)
        handle.write("\n")
    return path
