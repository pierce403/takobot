from __future__ import annotations

import asyncio
import argparse
import contextlib
import random
import sys
import time
from datetime import date

from . import __version__
from .daily import append_daily_note, ensure_daily_log
from .ens import DEFAULT_ENS_RPC_URLS, resolve_recipient
from .git_safety import assert_not_tracked, panic_check_runtime_secrets
from .keys import derive_eth_address, load_or_create_keys
from .locks import instance_lock
from .operator import clear_operator, get_operator_inbox_id, imprint_operator, load_operator
from .pairing import clear_pending, issue_pairing_code, load_pending, verify_pairing_code
from .paths import daily_root, ensure_runtime_dirs, repo_root, runtime_paths
from .xmtp import create_client, default_message, hint_for_xmtp_error, send_dm_sync


DEFAULT_ENV = "production"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tako", description="Tako — highly autonomous operator-imprinted agent")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="cmd", required=True)

    hi = sub.add_parser("hi", help="(dev) Send a one-off DM.")
    hi.add_argument("--to", required=True, help="XMTP address or ENS name")
    hi.add_argument("--message", help="Custom message to send")

    run = sub.add_parser("run", help="Start Tako daemon (pairing + operator channel).")
    run.add_argument("--interval", type=float, default=30.0, help="(dev) Heartbeat interval seconds")
    run.add_argument("--once", action="store_true", help="(dev) Run a single tick and exit")

    doctor = sub.add_parser("doctor", help="(dev) Check environment, config, and safety preconditions.")

    return parser


def _ens_rpc_urls_from_args(value: str | None) -> list[str]:
    if not value:
        return list(DEFAULT_ENS_RPC_URLS)
    urls = [item.strip() for item in value.split(",") if item.strip()]
    return urls or list(DEFAULT_ENS_RPC_URLS)


def cmd_hi(args: argparse.Namespace) -> int:
    paths = ensure_runtime_dirs(runtime_paths())

    # Keys live under .tako/ and must never be tracked.
    panic_check_runtime_secrets(repo_root(), paths.root)
    assert_not_tracked(repo_root(), paths.keys_json)

    keys = load_or_create_keys(paths.keys_json, legacy_config_path=paths.root / "config.json")
    wallet_key = keys["wallet_key"]
    db_encryption_key = keys["db_encryption_key"]

    env = DEFAULT_ENV

    ens_rpc_urls = _ens_rpc_urls_from_args(None)

    db_root = paths.xmtp_db_dir
    db_root.mkdir(parents=True, exist_ok=True)

    try:
        resolved = resolve_recipient(args.to, ens_rpc_urls)
    except Exception as exc:  # noqa: BLE001
        print(f"Error resolving recipient: {exc}", file=sys.stderr)
        return 1

    message = args.message or default_message()

    try:
        send_dm_sync(resolved, message, env, db_root, wallet_key, db_encryption_key)
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


def cmd_doctor(args: argparse.Namespace) -> int:
    paths = ensure_runtime_dirs(runtime_paths())
    root = repo_root()

    env = DEFAULT_ENV
    lines, problems = _doctor_report(root, paths, env)
    print("\n".join(lines))
    if problems:
        print("\nProblems:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    return 0


def _doctor_report(root, paths, env: str) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    operator = load_operator(paths.operator_json)

    try:
        panic_check_runtime_secrets(root, paths.root)
    except Exception as exc:  # noqa: BLE001
        problems.append(str(exc))

    if paths.keys_json.exists():
        try:
            assert_not_tracked(root, paths.keys_json)
        except Exception as exc:  # noqa: BLE001
            problems.append(str(exc))

    lines = [
        "tako doctor",
        f"- repo: {root}",
        f"- runtime: {paths.root} (ignored)",
        f"- memory dailies: {daily_root()} (committed)",
        f"- env: {env}",
        f"- keys: {'present' if paths.keys_json.exists() else 'missing'}",
    ]

    if operator and isinstance(operator.get("operator_address"), str):
        lines.append(f"- operator: {operator['operator_address']}")
    else:
        lines.append("- operator: not imprinted")

    try:
        import xmtp  # noqa: F401

        lines.append("- xmtp: import OK")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"xmtp import failed: {exc}")

    try:
        import web3  # noqa: F401

        lines.append("- web3: import OK")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"web3 import failed: {exc}")

    return lines, problems


def cmd_run(args: argparse.Namespace) -> int:
    paths = ensure_runtime_dirs(runtime_paths())

    root = repo_root()
    panic_check_runtime_secrets(root, paths.root)
    assert_not_tracked(root, paths.keys_json)

    keys = load_or_create_keys(paths.keys_json, legacy_config_path=paths.root / "config.json")
    wallet_key = keys["wallet_key"]
    db_encryption_key = keys["db_encryption_key"]

    env = DEFAULT_ENV

    address = derive_eth_address(wallet_key)
    print(f"tako address: {address}")
    print("status: starting daemon")
    print("pairing: DM this address on XMTP to pair as operator")

    try:
        with instance_lock(paths.locks_dir / "tako.lock"):
            return asyncio.run(_run_daemon(args, paths, env, wallet_key, db_encryption_key, address))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 2


async def _run_daemon(
    args: argparse.Namespace,
    paths,
    env: str,
    wallet_key: str,
    db_encryption_key: str,
    address: str,
) -> int:
    # Ensure today’s daily log exists (committed).
    ensure_daily_log(daily_root(), date.today())

    try:
        client = await create_client(env, paths.xmtp_db_dir, wallet_key, db_encryption_key)
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"XMTP client init failed: {exc}", file=sys.stderr)
        hint = hint_for_xmtp_error(exc)
        if hint:
            print(hint, file=sys.stderr)
        return 1

    operator_cfg = load_operator(paths.operator_json)
    operator_inbox_id = get_operator_inbox_id(operator_cfg)

    if operator_inbox_id:
        clear_pending(paths.state_dir / "pairing.json")
        print("status: paired")
    else:
        print("status: unpaired")

    print(f"inbox_id: {client.inbox_id}")
    if args.once:
        return 0

    print("Daemon started. Press Ctrl+C to stop.")

    start = time.monotonic()
    heartbeat = asyncio.create_task(_heartbeat_loop(args))
    pairing_path = paths.state_dir / "pairing.json"
    stream = client.conversations.stream_all_messages()

    try:
        async for item in stream:
            if isinstance(item, Exception):
                print(f"XMTP stream error: {item}", file=sys.stderr)
                continue

            sender_inbox_id = getattr(item, "sender_inbox_id", None)
            if not isinstance(sender_inbox_id, str):
                continue
            if sender_inbox_id == client.inbox_id:
                continue

            content = getattr(item, "content", None)
            if not isinstance(content, str):
                continue
            text = content.strip()
            if not text:
                continue

            convo_id = getattr(item, "conversation_id", None)
            if not isinstance(convo_id, (bytes, bytearray)):
                continue

            convo = await client.conversations.get_conversation_by_id(bytes(convo_id))
            if convo is None:
                continue

            operator_cfg = load_operator(paths.operator_json)
            operator_inbox_id = get_operator_inbox_id(operator_cfg)

            if operator_inbox_id is None:
                pending = load_pending(pairing_path)
                if pending and pending.requested_by_inbox_id != sender_inbox_id:
                    await convo.send("This Tako instance is currently pairing with someone else. Try again later.")
                    continue

                cmd, rest = _parse_command(text)
                if cmd == "pair" and pending and pending.requested_by_inbox_id == sender_inbox_id:
                    if verify_pairing_code(pairing_path, requested_by_inbox_id=sender_inbox_id, code=rest):
                        imprint_operator(
                            paths.operator_json,
                            operator_inbox_id=sender_inbox_id,
                            operator_address=None,
                        )
                        clear_pending(pairing_path)
                        append_daily_note(daily_root(), date.today(), "Operator paired via XMTP challenge.")
                        await convo.send("Paired. You are now the operator.\n\nReply 'help' for commands.")
                    else:
                        await convo.send("Pairing code incorrect or expired. Reply with `pair <code>` from my last message.")
                    continue

                if pending is None:
                    pending = issue_pairing_code(pairing_path, requested_by_inbox_id=sender_inbox_id)
                    append_daily_note(daily_root(), date.today(), "Pairing challenge issued (pending).")

                mins = max(1, int((pending.expires_at - pending.requested_at).total_seconds() / 60))
                await convo.send(
                    "This Tako instance is unpaired.\n\n"
                    f"To become the operator, reply: `pair {pending.code}` (expires in ~{mins} min).\n\n"
                    f"tako address: {address}"
                )
                continue

            if sender_inbox_id != operator_inbox_id:
                if _looks_like_command(text):
                    await convo.send("Operator-only: config/tools/permissions/routines require the operator.")
                continue

            cmd, rest = _parse_command(text)
            if cmd in {"help", "h", "?"}:
                await convo.send(_help_text())
                continue
            if cmd == "status":
                uptime = int(time.monotonic() - start)
                await convo.send(
                    "status: ok\n"
                    f"paired: yes\n"
                    f"env: {env}\n"
                    f"uptime_s: {uptime}\n"
                    f"version: {__version__}\n"
                    f"tako_address: {address}"
                )
                continue
            if cmd == "doctor":
                append_daily_note(daily_root(), date.today(), "Operator ran doctor.")
                lines, problems = _doctor_report(repo_root(), paths, env)
                report = "\n".join(lines)
                if problems:
                    report += "\n\nProblems:\n" + "\n".join(f"- {p}" for p in problems)
                await convo.send(report)
                continue
            if cmd == "reimprint":
                if rest.strip().lower() != "confirm":
                    await convo.send(
                        "Re-imprint is operator-only and destructive.\n\n"
                        "Reply: `reimprint CONFIRM` to clear the current operator and reopen pairing."
                    )
                    continue
                clear_operator(paths.operator_json)
                clear_pending(pairing_path)
                append_daily_note(daily_root(), date.today(), "Operator cleared imprint (reimprint CONFIRM).")
                await convo.send("Operator imprint cleared. The next DM will start pairing.")
                continue

            await convo.send("Unknown command. Reply 'help'.")
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        with contextlib.suppress(Exception):
            await stream.close()

    return 0


async def _heartbeat_loop(args: argparse.Namespace) -> None:
    first_tick = True
    while True:
        if first_tick:
            first_tick = False
            ensure_daily_log(daily_root(), date.today())
        interval = max(1.0, float(args.interval))
        await asyncio.sleep(interval + random.uniform(-0.2 * interval, 0.2 * interval))


def _parse_command(text: str) -> tuple[str, str]:
    value = text.strip()
    if value.lower().startswith("tako "):
        value = value[5:].lstrip()
    if value.startswith("/"):
        value = value[1:].lstrip()
    if not value:
        return "", ""
    parts = value.split(maxsplit=1)
    cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    return cmd, rest


def _help_text() -> str:
    return (
        "tako commands:\n"
        "- help\n"
        "- status\n"
        "- doctor\n"
        "- reimprint (operator-only)\n"
    )


def _looks_like_command(text: str) -> bool:
    value = text.strip().lower()
    return value.startswith(("help", "status", "doctor", "tako", "/"))


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.cmd == "hi":
        return cmd_hi(args)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "doctor":
        return cmd_doctor(args)

    parser.error(f"Unknown command: {args.cmd}")
    return 2
