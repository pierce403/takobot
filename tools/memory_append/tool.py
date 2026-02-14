from __future__ import annotations

from datetime import date

from takobot.daily import ensure_daily_log
from takobot.paths import daily_root

TOOL_MANIFEST = {
    "name": "memory_append",
    "description": "Append a note to today’s memory daily log (no secrets).",
    "permissions": ["write_repo"],
    "entrypoint": "run",
}


def run(input: dict, ctx: dict) -> dict:
    note = input.get("note", "")
    if not isinstance(note, str) or not note.strip():
        return {"ok": False, "error": "Missing input.note (string)."}

    path = ensure_daily_log(daily_root(), date.today())
    with path.open("a", encoding="utf-8") as handle:
        handle.write("\n- ")
        handle.write(note.strip().replace("\n", " ").strip())
        handle.write("\n")

    return {"ok": True, "daily_log": str(path)}
