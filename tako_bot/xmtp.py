from __future__ import annotations

import asyncio
import os
import socket
from pathlib import Path

from .util import is_truthy, parse_history_sync


def default_message() -> str:
    hostname = socket.gethostname()
    return f"hi from {hostname} (tako)"


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


async def send_dm(recipient: str, message: str, env: str, db_root: Path) -> None:
    from xmtp import Client
    from xmtp.signers import create_signer
    from xmtp.types import ClientOptions

    signer = create_signer(os.environ["XMTP_WALLET_KEY"])

    def db_path_for(inbox_id: str) -> str:
        return str(db_root / f"xmtp-{env}-{inbox_id}.db3")

    api_url = os.environ.get("XMTP_API_URL")
    history_sync_url = os.environ.get("XMTP_HISTORY_SYNC_URL")
    gateway_host = os.environ.get("XMTP_GATEWAY_HOST")
    disable_history_sync_from_url, normalized_history_sync_url = parse_history_sync(history_sync_url)
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


def send_dm_sync(recipient: str, message: str, env: str, db_root: Path) -> None:
    asyncio.run(send_dm(recipient, message, env, db_root))
