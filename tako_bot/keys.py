from __future__ import annotations

import json
import os
import secrets
from pathlib import Path
from typing import Any


def generate_private_key() -> str:
    return "0x" + secrets.token_hex(32)


def generate_db_key() -> str:
    return "0x" + secrets.token_hex(32)


def _chmod_600(path: Path) -> None:
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, dict):
        raise RuntimeError(f"Invalid JSON object in {path}")
    return data


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")
    _chmod_600(path)


def load_or_create_keys(keys_path: Path, legacy_config_path: Path | None = None) -> dict[str, str]:
    if keys_path.exists():
        data = _load_json(keys_path)
        wallet_key = data.get("wallet_key")
        db_key = data.get("db_encryption_key")
        if not isinstance(wallet_key, str) or not wallet_key:
            raise RuntimeError(f"Missing wallet_key in {keys_path}")
        if not isinstance(db_key, str) or not db_key:
            raise RuntimeError(f"Missing db_encryption_key in {keys_path}")
        return {"wallet_key": wallet_key, "db_encryption_key": db_key}

    if legacy_config_path and legacy_config_path.exists():
        legacy = _load_json(legacy_config_path)
        wallet_key = legacy.get("wallet_key")
        db_key = legacy.get("db_encryption_key")
        if isinstance(wallet_key, str) and wallet_key and isinstance(db_key, str) and db_key:
            _write_json(keys_path, {"wallet_key": wallet_key, "db_encryption_key": db_key})
            return {"wallet_key": wallet_key, "db_encryption_key": db_key}

    wallet_key = generate_private_key()
    db_key = generate_db_key()
    _write_json(keys_path, {"wallet_key": wallet_key, "db_encryption_key": db_key})
    return {"wallet_key": wallet_key, "db_encryption_key": db_key}


def apply_key_env_overrides(keys: dict[str, str]) -> dict[str, str]:
    wallet_key = os.environ.get("XMTP_WALLET_KEY") or keys["wallet_key"]
    db_key = os.environ.get("XMTP_DB_ENCRYPTION_KEY") or keys["db_encryption_key"]
    os.environ.setdefault("XMTP_WALLET_KEY", wallet_key)
    os.environ.setdefault("XMTP_DB_ENCRYPTION_KEY", db_key)
    return {"wallet_key": wallet_key, "db_encryption_key": db_key}

