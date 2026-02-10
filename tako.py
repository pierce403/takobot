#!/usr/bin/env python3
"""Minimal XMTP client that says hi to a target address or ENS name."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import socket
import sys
from urllib.parse import quote
from urllib.request import Request, urlopen
from pathlib import Path
from typing import Any

from xmtp import Client
from xmtp.signers import create_signer
from xmtp.types import ClientOptions

DEFAULT_ENV = "production"
DEFAULT_ENS_RPC_URL = "https://ethereum.publicnode.com"
DEFAULT_ENS_RPC_URLS = [DEFAULT_ENS_RPC_URL, "https://eth.llamarpc.com"]


def repo_root() -> Path:
    return Path(__file__).resolve().parent


def config_path() -> Path:
    return repo_root() / ".tako" / "config.json"


def generate_private_key() -> str:
    return "0x" + secrets.token_hex(32)


def generate_db_key() -> str:
    return "0x" + secrets.token_hex(32)


def load_or_create_config(path: Path) -> dict[str, Any]:
    if path.exists():
        with path.open("r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data

    data = {
        "wallet_key": generate_private_key(),
        "db_encryption_key": generate_db_key(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, sort_keys=True, ensure_ascii=True)
        handle.write("\n")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return data


def require_value(config: dict[str, Any], key: str) -> str:
    value = config.get(key)
    if not value or not isinstance(value, str):
        raise RuntimeError(f"Missing {key} in config and environment")
    return value


def resolve_recipient(recipient: str, rpc_urls: list[str]) -> str:
    if recipient.startswith("0x"):
        return recipient
    if recipient.endswith(".eth"):
        from web3 import Web3

        def resolve_web3bio(name: str) -> str:
            endpoint = f"https://api.web3.bio/ns/{quote(name)}"
            request = Request(endpoint, headers={"Content-Type": "application/json"}, method="GET")
            with urlopen(request, timeout=10) as response:
                if response.status >= 400:
                    raise RuntimeError(
                        f"web3.bio returned {response.status} {response.reason}"
                    )
                data = response.read()
            results = json.loads(data.decode("utf-8"))
            address_value = results[0].get("address") if results else None
            address = address_value if isinstance(address_value, str) else None
            if not address:
                raise RuntimeError(f"web3.bio did not resolve {name}")
            return address

        last_error: Exception | None = None
        for rpc_url in rpc_urls:
            try:
                web3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
                if not web3.is_connected():
                    last_error = RuntimeError(f"Unable to reach ENS RPC at {rpc_url}")
                    continue
                address = web3.ens.address(recipient)
                if address:
                    return address
                last_error = RuntimeError(f"ENS name did not resolve: {recipient}")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
        try:
            return resolve_web3bio(recipient)
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                f"ENS resolution failed via {', '.join(rpc_urls)}: {last_error}; "
                f"web3.bio error: {exc}"
            ) from exc
    return recipient


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Tako XMTP hello bot")
    parser.add_argument("--to", required=True, help="XMTP address or ENS name")
    parser.add_argument(
        "--message",
        help="Custom message to send (defaults to a friendly hi)",
    )
    parser.add_argument(
        "--env",
        help="XMTP environment (overrides XMTP_ENV)",
    )
    parser.add_argument(
        "--ens-rpc-url",
        help="Ethereum RPC URL for ENS resolution",
    )
    return parser


def default_message() -> str:
    hostname = socket.gethostname()
    return f"hi from {hostname} (tako)"


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


def hint_for_xmtp_error(error: Exception) -> str | None:
    message = str(error)
    if "grpc-status header missing" in message or "IdentityApi" in message:
        return (
            "Tip: check outbound HTTPS/HTTP2 access to "
            "grpc.production.xmtp.network:443 and "
            "message-history.production.ephemera.network, "
            "or override XMTP_API_URL/XMTP_HISTORY_SYNC_URL."
        )
    if "file is not a database" in message or "sqlcipher" in message:
        return (
            "Tip: the local XMTP database appears corrupted or was created with a "
            "different encryption key. Remove .tako/xmtp-db or set "
            "TAKO_RESET_DB=1 to recreate it."
        )
    return None


async def send_hi(recipient: str, message: str, env: str, db_root: Path) -> None:
    signer = create_signer(os.environ["XMTP_WALLET_KEY"])

    def db_path_for(inbox_id: str) -> str:
        return str(db_root / f"xmtp-{env}-{inbox_id}.db3")

    api_url = os.environ.get("XMTP_API_URL")
    history_sync_url = os.environ.get("XMTP_HISTORY_SYNC_URL")
    gateway_host = os.environ.get("XMTP_GATEWAY_HOST")
    disable_history_sync_from_url, normalized_history_sync_url = parse_history_sync(
        history_sync_url
    )
    disable_history_sync = is_truthy(os.environ.get("XMTP_DISABLE_HISTORY_SYNC"))
    disable_history_sync = disable_history_sync or disable_history_sync_from_url
    if disable_history_sync:
        normalized_history_sync_url = None
    disable_device_sync = True
    if "XMTP_DISABLE_DEVICE_SYNC" in os.environ:
        disable_device_sync = is_truthy(os.environ.get("XMTP_DISABLE_DEVICE_SYNC"))
    elif "TAKO_ENABLE_DEVICE_SYNC" in os.environ:
        disable_device_sync = not is_truthy(os.environ.get("TAKO_ENABLE_DEVICE_SYNC"))

    options = ClientOptions(
        env=env,
        api_url=api_url,
        history_sync_url=normalized_history_sync_url,
        gateway_host=gateway_host,
        disable_history_sync=disable_history_sync,
        disable_device_sync=disable_device_sync,
        db_path=db_path_for,
        db_encryption_key=os.environ.get("XMTP_DB_ENCRYPTION_KEY"),
    )
    client = await Client.create(signer, options)
    dm = await client.conversations.new_dm(recipient)
    await dm.send(message)


def run() -> int:
    args = build_parser().parse_args()

    cfg_path = config_path()
    config = load_or_create_config(cfg_path)

    wallet_key = os.environ.get("XMTP_WALLET_KEY") or require_value(
        config, "wallet_key"
    )
    db_key = os.environ.get("XMTP_DB_ENCRYPTION_KEY") or require_value(
        config, "db_encryption_key"
    )

    os.environ.setdefault("XMTP_WALLET_KEY", wallet_key)
    os.environ.setdefault("XMTP_DB_ENCRYPTION_KEY", db_key)

    env = args.env or os.environ.get("XMTP_ENV", DEFAULT_ENV)
    os.environ.setdefault("XMTP_ENV", env)

    ens_rpc_urls: list[str] = []
    if args.ens_rpc_url:
        ens_rpc_urls = [value.strip() for value in args.ens_rpc_url.split(",") if value.strip()]
    elif os.environ.get("TAKO_ENS_RPC_URLS"):
        ens_rpc_urls = [
            value.strip()
            for value in os.environ["TAKO_ENS_RPC_URLS"].split(",")
            if value.strip()
        ]
    elif os.environ.get("TAKO_ENS_RPC_URL"):
        ens_rpc_urls = [os.environ["TAKO_ENS_RPC_URL"].strip()]
    else:
        ens_rpc_urls = list(DEFAULT_ENS_RPC_URLS)

    db_root = repo_root() / ".tako" / "xmtp-db"
    if is_truthy(os.environ.get("TAKO_RESET_DB")) and db_root.exists():
        for item in db_root.iterdir():
            if item.is_dir():
                for child in item.iterdir():
                    child.unlink(missing_ok=True)
                item.rmdir()
            else:
                item.unlink(missing_ok=True)
    db_root.mkdir(parents=True, exist_ok=True)

    try:
        resolved = resolve_recipient(args.to, ens_rpc_urls)
    except Exception as exc:  # noqa: BLE001
        print(f"Error resolving recipient: {exc}", file=sys.stderr)
        return 1

    message = args.message or default_message()

    try:
        asyncio.run(send_hi(resolved, message, env, db_root))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(f"XMTP send failed: {exc}", file=sys.stderr)
        hint = hint_for_xmtp_error(exc)
        if hint:
            print(hint, file=sys.stderr)
        return 1

    if resolved != args.to:
        print(f"Sent to {args.to} (resolved {resolved})")
    else:
        print(f"Sent to {args.to}")
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
