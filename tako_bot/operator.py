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


def imprint_operator(path: Path, operator_address: str) -> dict[str, Any]:
    operator_address = operator_address.strip()
    if not operator_address:
        raise RuntimeError("Operator address is required.")
    data: dict[str, Any] = {
        "operator_address": operator_address,
        "paired_at": utc_now_iso(),
        "allowlisted_controller_commands": [
            "help",
            "status",
            "doctor",
        ],
    }
    save_operator(path, data)
    return data

