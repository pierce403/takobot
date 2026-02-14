from __future__ import annotations

import asyncio
from importlib import metadata
import socket
from pathlib import Path


def default_message() -> str:
    hostname = socket.gethostname()
    return f"hi from {hostname} (tako)"


def hint_for_xmtp_error(error: Exception) -> str | None:
    message = str(error)
    if "grpc-status header missing" in message or "IdentityApi" in message:
        return (
            "Tip: check outbound HTTPS/HTTP2 access to "
            "grpc.production.xmtp.network:443 and "
            "message-history.production.ephemera.network."
        )
    if "file is not a database" in message or "sqlcipher" in message:
        return (
            "Tip: the local XMTP database appears corrupted or was created with a "
            "different encryption key. Remove .tako/xmtp-db or set "
            "a fresh runtime directory to recreate it."
        )
    return None


def probe_xmtp_import() -> tuple[bool, str]:
    package_version: str | None = None
    try:
        package_version = metadata.version("xmtp")
    except metadata.PackageNotFoundError:
        package_version = None
    except Exception:
        package_version = None

    try:
        import xmtp  # noqa: F401
    except ModuleNotFoundError as exc:
        missing_name = (exc.name or "").strip()
        if missing_name == "xmtp":
            if package_version:
                return False, f"package xmtp=={package_version} is installed, but import still failed: {exc}"
            return False, "package `xmtp` is not installed in this Python environment."
        if package_version:
            return False, f"xmtp=={package_version} is installed, but a subdependency is missing: {missing_name or exc}"
        return False, f"xmtp import failed: missing module {missing_name or exc}"
    except Exception as exc:  # noqa: BLE001
        if package_version:
            return False, f"xmtp=={package_version} is installed, but import failed: {exc}"
        return False, f"xmtp import failed: {exc}"

    if package_version:
        return True, f"import OK (xmtp=={package_version})"
    return True, "import OK"


async def create_client(env: str, db_root: Path, wallet_key: str, db_encryption_key: str) -> object:
    from xmtp import Client
    from xmtp.signers import create_signer
    from xmtp.types import ClientOptions

    signer = create_signer(wallet_key)

    def db_path_for(inbox_id: str) -> str:
        return str(db_root / f"xmtp-{env}-{inbox_id}.db3")

    # Contract: no user-facing env-var configuration. Defaults are intentionally fixed for now.
    api_url = None
    history_sync_url = None
    gateway_host = None
    disable_history_sync = True
    disable_device_sync = True

    options = ClientOptions(
        env=env,
        api_url=api_url,
        history_sync_url=history_sync_url,
        gateway_host=gateway_host,
        disable_history_sync=disable_history_sync,
        disable_device_sync=disable_device_sync,
        db_path=db_path_for,
        db_encryption_key=db_encryption_key,
    )
    return await Client.create(signer, options)


async def send_dm(
    recipient: str,
    message: str,
    env: str,
    db_root: Path,
    wallet_key: str,
    db_encryption_key: str,
) -> None:
    client = await create_client(env, db_root, wallet_key, db_encryption_key)
    dm = await client.conversations.new_dm(recipient)
    await dm.send(message)


def send_dm_sync(
    recipient: str,
    message: str,
    env: str,
    db_root: Path,
    wallet_key: str,
    db_encryption_key: str,
) -> None:
    asyncio.run(send_dm(recipient, message, env, db_root, wallet_key, db_encryption_key))
