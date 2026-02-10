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
        "## Intent\n\n"
        "- \n\n"
        "## Notes\n\n"
        "- \n\n"
        "## Decisions\n\n"
        "- \n\n"
        "## Promote to MEMORY.md (if durable)\n\n"
        "- [ ] Promote long-lived decisions into `MEMORY.md`.\n"
    )
    path.write_text(content, encoding="utf-8")
    return path

