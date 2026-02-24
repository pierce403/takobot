from __future__ import annotations

import argparse
import asyncio
import contextlib
import secrets
import socket
import sys
from datetime import date
from typing import TextIO

from .daily import append_daily_note, ensure_daily_log
from .ens import DEFAULT_ENS_RPC_URLS, resolve_recipient
from .git_safety import assert_not_tracked, panic_check_runtime_secrets
from .keys import derive_eth_address, load_or_create_keys
from .operator import get_operator_inbox_id, imprint_operator, load_operator
from .pairing import clear_pending
from .paths import daily_root, ensure_runtime_dirs, repo_root, runtime_paths
from .xmtp import create_client, hint_for_xmtp_error


DEFAULT_ENV = "production"
PAIRING_CODE_ATTEMPTS = 5
PAIRING_CODE_LENGTH = 8
PAIRING_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


class TerminalIO:
    def __init__(self, reader: TextIO, writer: TextIO) -> None:
        self.reader = reader
        self.writer = writer

    @classmethod
    def open(cls) -> TerminalIO | None:
        try:
            reader = open("/dev/tty", "r", encoding="utf-8")
            writer = open("/dev/tty", "w", encoding="utf-8")
        except OSError:
            return None
        return cls(reader, writer)

    def close(self) -> None:
        with contextlib.suppress(Exception):
            self.reader.close()
        with contextlib.suppress(Exception):
            self.writer.close()

    def say(self, text: str) -> None:
        self.writer.write(f"{text}\n")
        self.writer.flush()

    def prompt(self, label: str, default: str | None = None) -> str:
        if default:
            self.writer.write(f"{label} [{default}]: ")
        else:
            self.writer.write(f"{label}: ")
        self.writer.flush()
        line = self.reader.readline()
        value = line.strip()
        if not value and default is not None:
            return default
        return value


def _sanitize(value: str) -> str:
    return " ".join(value.strip().split())


def _new_pairing_code() -> str:
    raw = "".join(secrets.choice(PAIRING_CODE_ALPHABET) for _ in range(PAIRING_CODE_LENGTH))
    return f"{raw[:4]}-{raw[4:]}"


async def _resolve_operator_inbox_id(client, address: str, dm) -> str | None:
    peer_inbox_id = getattr(dm, "peer_inbox_id", None)
    if isinstance(peer_inbox_id, str) and peer_inbox_id.strip():
        return peer_inbox_id

    try:
        resolver = getattr(client, "resolve_inbox_id_for_address", None)
        if not callable(resolver):
            return None
        maybe_inbox = resolver(address)
        inbox_id = await maybe_inbox if asyncio.iscoroutine(maybe_inbox) else maybe_inbox
    except Exception:
        return None
    if isinstance(inbox_id, str) and inbox_id.strip():
        return inbox_id
    return None


async def _run_terminal_pairing(
    tty: TerminalIO,
    *,
    paths,
    wallet_key: str,
    db_encryption_key: str,
) -> bool:
    tty.say("Tako: I'm waking up. First, let's establish the secure operator channel.")
    tty.say("Tako: Share your XMTP handle (ENS like name.eth or a 0x address).")

    operator_handle = ""
    while not operator_handle:
        operator_handle = _sanitize(tty.prompt("Operator handle"))
        if not operator_handle:
            tty.say("Tako: I need a valid handle to send the pairing message.")

    try:
        resolved = resolve_recipient(operator_handle, list(DEFAULT_ENS_RPC_URLS))
    except Exception as exc:  # noqa: BLE001
        tty.say(f"Tako: I couldn't resolve that handle: {exc}")
        return False

    pairing_code = _new_pairing_code()
    host = socket.gethostname()
    outbound_message = (
        f"Hello, I'm Tako on {host}.\n\n"
        "Terminal bootstrap is in progress.\n"
        "To confirm you control this inbox, copy this code back into the terminal:\n\n"
        f"{pairing_code}"
    )

    try:
        client = await create_client(DEFAULT_ENV, paths.xmtp_db_dir, wallet_key, db_encryption_key)
    except Exception as exc:  # noqa: BLE001
        tty.say(f"Tako: XMTP client setup failed: {exc}")
        hint = hint_for_xmtp_error(exc)
        if hint:
            tty.say(hint)
        return False

    try:
        dm = await client.conversations.new_dm(resolved)
        await dm.send(outbound_message)
    except Exception as exc:  # noqa: BLE001
        tty.say(f"Tako: I couldn't send the outbound pairing DM: {exc}")
        hint = hint_for_xmtp_error(exc)
        if hint:
            tty.say(hint)
        return False

    operator_inbox_id = await _resolve_operator_inbox_id(client, resolved, dm)
    if not operator_inbox_id:
        tty.say("Tako: DM sent, but I couldn't resolve the operator inbox id for imprinting.")
        tty.say("Tako: Verify that handle is XMTP-enabled, then retry `.venv/bin/tako`.")
        return False

    tty.say(f"Tako: Outbound DM sent to {operator_handle} ({resolved}).")
    tty.say("Tako: Copy the code from XMTP and paste it here.")

    expected = pairing_code.upper()
    for attempt in range(1, PAIRING_CODE_ATTEMPTS + 1):
        entered = tty.prompt(f"Pairing code {attempt}/{PAIRING_CODE_ATTEMPTS}")
        if entered.strip().upper() == expected:
            imprint_operator(
                paths.operator_json,
                operator_inbox_id=operator_inbox_id,
                operator_address=resolved,
                pairing_method="terminal_outbound_challenge_v1",
            )
            clear_pending(paths.state_dir / "pairing.json")
            append_daily_note(daily_root(), date.today(), "Operator paired via terminal outbound DM challenge.")
            with contextlib.suppress(Exception):
                await dm.send("Paired. You are now the operator. Reply `help` for commands.")
            return True
        tty.say("Tako: That code doesn't match. Please copy the exact code from the DM.")

    tty.say("Tako: Pairing was not confirmed. Re-run `.venv/bin/tako` to try again.")
    return False


def run_bootstrap(args: argparse.Namespace) -> int:
    paths = ensure_runtime_dirs(runtime_paths())
    root = repo_root()

    panic_check_runtime_secrets(root, paths.root)
    assert_not_tracked(root, paths.keys_json)

    keys = load_or_create_keys(paths.keys_json, legacy_config_path=paths.root / "config.json")
    wallet_key = keys["wallet_key"]
    db_encryption_key = keys["db_encryption_key"]
    address = derive_eth_address(wallet_key)

    tty = TerminalIO.open()
    if tty is None:
        print("bootstrap: interactive terminal required (no /dev/tty available).", file=sys.stderr)
        return 1

    try:
        ensure_daily_log(daily_root(), date.today())
        append_daily_note(daily_root(), date.today(), "Terminal bootstrap started.")
        tty.say("Tako: I'm waking up in terminal-first bootstrap mode.")
        tty.say(f"Tako: My XMTP address is {address}.")

        operator_cfg = load_operator(paths.operator_json)
        operator_inbox_id = get_operator_inbox_id(operator_cfg)
        if operator_inbox_id:
            tty.say("Tako: Operator imprint already exists. Skipping pairing.")
        else:
            paired = asyncio.run(
                _run_terminal_pairing(
                    tty,
                    paths=paths,
                    wallet_key=wallet_key,
                    db_encryption_key=db_encryption_key,
                )
            )
            if not paired:
                return 1

        tty.say("Tako: Paired. From now on, use XMTP to manage me.")
        tty.say("Tako: Terminal is now read-only logs. You can close it or leave it running.")
    except KeyboardInterrupt:
        return 130
    finally:
        tty.close()

    from .cli import cmd_run

    run_args = argparse.Namespace(interval=args.interval, once=args.once)
    return cmd_run(run_args)
