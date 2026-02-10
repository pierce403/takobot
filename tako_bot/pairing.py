from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any


PAIRING_VERSION = 1


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _to_iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def _parse_iso(value: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _new_code() -> str:
    # Human-friendly: 6 digits.
    return f"{secrets.randbelow(1_000_000):06d}"


@dataclass(frozen=True)
class PendingPairing:
    requested_by_inbox_id: str
    code: str
    requested_at: datetime
    expires_at: datetime

    def is_expired(self, now: datetime | None = None) -> bool:
        now = now or _utcnow()
        return now >= self.expires_at

    def to_json(self) -> dict[str, Any]:
        return {
            "requested_by_inbox_id": self.requested_by_inbox_id,
            "code": self.code,
            "requested_at": _to_iso(self.requested_at),
            "expires_at": _to_iso(self.expires_at),
        }


def _load_json(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else None


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")


def load_pending(path: Path) -> PendingPairing | None:
    data = _load_json(path)
    if not data:
        return None
    if data.get("version") != PAIRING_VERSION:
        return None
    pending = data.get("pending")
    if not isinstance(pending, dict):
        return None

    requested_by_inbox_id = pending.get("requested_by_inbox_id")
    code = pending.get("code")
    requested_at = pending.get("requested_at")
    expires_at = pending.get("expires_at")
    if not all(isinstance(x, str) and x for x in [requested_by_inbox_id, code, requested_at, expires_at]):
        return None

    requested_dt = _parse_iso(requested_at)
    expires_dt = _parse_iso(expires_at)
    if requested_dt is None or expires_dt is None:
        return None

    pending_obj = PendingPairing(
        requested_by_inbox_id=requested_by_inbox_id,
        code=code,
        requested_at=requested_dt,
        expires_at=expires_dt,
    )
    if pending_obj.is_expired():
        clear_pending(path)
        return None
    return pending_obj


def issue_pairing_code(
    path: Path,
    *,
    requested_by_inbox_id: str,
    ttl_seconds: int = 300,
) -> PendingPairing:
    now = _utcnow()
    pending = PendingPairing(
        requested_by_inbox_id=requested_by_inbox_id,
        code=_new_code(),
        requested_at=now,
        expires_at=now + timedelta(seconds=ttl_seconds),
    )
    _write_json(
        path,
        {
            "version": PAIRING_VERSION,
            "pending": pending.to_json(),
        },
    )
    return pending


def clear_pending(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        _write_json(path, {"version": PAIRING_VERSION})


def verify_pairing_code(
    path: Path,
    *,
    requested_by_inbox_id: str,
    code: str,
) -> bool:
    pending = load_pending(path)
    if pending is None:
        return False
    if pending.requested_by_inbox_id != requested_by_inbox_id:
        return False
    if pending.is_expired():
        clear_pending(path)
        return False
    return pending.code == code.strip()

