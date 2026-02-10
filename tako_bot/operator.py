from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .util import utc_now_iso


def load_operator(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else None


def save_operator(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")


def get_operator_inbox_id(data: dict[str, Any] | None) -> str | None:
    if not data:
        return None
    value = data.get("operator_inbox_id")
    return value if isinstance(value, str) and value.strip() else None


def imprint_operator(
    path: Path,
    *,
    operator_inbox_id: str,
    operator_address: str | None = None,
    pairing_method: str = "first_dm_challenge_v1",
) -> dict[str, Any]:
    operator_inbox_id = operator_inbox_id.strip()
    if not operator_inbox_id:
        raise RuntimeError("Operator inbox id is required.")
    data: dict[str, Any] = {
        "operator_address": operator_address,
        "operator_inbox_id": operator_inbox_id,
        "paired_at": utc_now_iso(),
        "pairing_method": pairing_method,
        "allowlisted_controller_commands": [
            "help",
            "status",
            "doctor",
            "reimprint",
        ],
    }
    save_operator(path, data)
    return data


def set_operator_inbox_id(path: Path, operator_inbox_id: str) -> None:
    operator_inbox_id = operator_inbox_id.strip()
    if not operator_inbox_id:
        return
    data = load_operator(path) or {}
    if not isinstance(data, dict):
        data = {}
    data["operator_inbox_id"] = operator_inbox_id
    save_operator(path, data)


def clear_operator(path: Path) -> None:
    path.unlink(missing_ok=True)
