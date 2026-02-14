from __future__ import annotations

from datetime import datetime, timezone


def is_truthy(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() not in {"", "0", "false", "no", "off"}


def parse_history_sync(value: str | None) -> tuple[bool, str | None]:
    if value is None:
        return False, None
    normalized = value.strip().lower()
    if normalized in {"", "none", "disable", "disabled", "off"}:
        return True, None
    return False, value


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()

