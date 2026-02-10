from __future__ import annotations

import asyncio
import argparse
import contextlib
import os
import random
import sys
import time
from datetime import date

from . import __version__
from .daily import ensure_daily_log
from .ens import DEFAULT_ENS_RPC_URLS, resolve_recipient
from .git_safety import assert_not_tracked, panic_check_runtime_secrets
from .keys import apply_key_env_overrides, load_or_create_keys
from .locks import instance_lock
from .operator import imprint_operator, load_operator, set_operator_inbox_id
from .paths import daily_root, ensure_runtime_dirs, repo_root, runtime_paths
from .util import is_truthy
from .xmtp import create_client, default_message, hint_for_xmtp_error, send_dm_sync


DEFAULT_ENV = "production"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tako", description="Tako — XMTP-native operator-imprinted agent")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="cmd", required=True)

    hi = sub.add_parser("hi", help="Send a one-off DM (backwards compatible with the old script).")
    hi.add_argument("--to", required=True, help="XMTP address or ENS name")
    hi.add_argument("--message", help="Custom message to send")
    hi.add_argument("--env", help="XMTP environment (overrides XMTP_ENV)")
    hi.add_argument("--ens-rpc-url", help="Ethereum RPC URL(s) for ENS resolution (comma-separated)")

    run = sub.add_parser("run", help="Run Tako daemon (heartbeat + operator control plane).")
    run.add_argument("--operator", help="Operator address or ENS name (required on first run)")
    run.add_argument("--env", help="XMTP environment (overrides XMTP_ENV)")
    run.add_argument("--interval", type=float, default=30.0, help="Heartbeat interval seconds (default: 30)")
    run.add_argument("--once", action="store_true", help="Run a single heartbeat tick and exit")

    doctor = sub.add_parser("doctor", help="Check environment, config, and safety preconditions.")
    doctor.add_argument("--env", help="XMTP environment (overrides XMTP_ENV)")

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
    apply_key_env_overrides(keys)

    env = args.env or os.environ.get("XMTP_ENV", DEFAULT_ENV)
    os.environ.setdefault("XMTP_ENV", env)

    ens_rpc_urls = _ens_rpc_urls_from_args(args.ens_rpc_url or os.environ.get("TAKO_ENS_RPC_URLS") or os.environ.get("TAKO_ENS_RPC_URL"))

    db_root = paths.xmtp_db_dir
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
        send_dm_sync(resolved, message, env, db_root)
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

    env = args.env or os.environ.get("XMTP_ENV", DEFAULT_ENV)
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
        f"- daily: {daily_root()} (committed)",
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
    apply_key_env_overrides(keys)

    env = args.env or os.environ.get("XMTP_ENV", DEFAULT_ENV)
    os.environ.setdefault("XMTP_ENV", env)

    operator_cfg = load_operator(paths.operator_json)
    operator_input = (args.operator or "").strip()
    if operator_cfg is None:
        if not operator_input:
            print("Operator not imprinted yet. Run: tako run --operator <addr|ens>", file=sys.stderr)
            return 2
        ens_rpc_urls = _ens_rpc_urls_from_args(
            os.environ.get("TAKO_ENS_RPC_URLS") or os.environ.get("TAKO_ENS_RPC_URL")
        )
        try:
            operator_addr = resolve_recipient(operator_input, ens_rpc_urls)
        except Exception as exc:  # noqa: BLE001
            print(f"Error resolving operator: {exc}", file=sys.stderr)
            return 2
        operator_cfg = imprint_operator(paths.operator_json, operator_addr)
        print(f"Imprinted operator: {operator_addr}")
    else:
        existing = operator_cfg.get("operator_address")
        if operator_input and isinstance(existing, str) and operator_input != existing:
            print(
                "Operator is already imprinted; refusing to change operator without an explicit re-imprint flow.",
                file=sys.stderr,
            )
            print(f"Existing operator: {existing}", file=sys.stderr)
            return 2

    operator_addr = operator_cfg.get("operator_address") if isinstance(operator_cfg, dict) else None
    if not isinstance(operator_addr, str) or not operator_addr:
        print("Invalid operator config.", file=sys.stderr)
        return 2

    try:
        with instance_lock(paths.locks_dir / "tako.lock"):
            return asyncio.run(_run_daemon(args, paths, operator_addr, env))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001
        print(str(exc), file=sys.stderr)
        return 2


async def _run_daemon(
    args: argparse.Namespace,
    paths,
    operator_addr: str,
    env: str,
) -> int:
    # Ensure today’s daily log exists (committed).
    ensure_daily_log(daily_root(), date.today())

    try:
        client = await create_client(env, paths.xmtp_db_dir)
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        print(f"XMTP client init failed: {exc}", file=sys.stderr)
        hint = hint_for_xmtp_error(exc)
        if hint:
            print(hint, file=sys.stderr)
        return 1

    operator_inbox_id: str | None = None
    if isinstance(load_operator(paths.operator_json), dict):
        value = load_operator(paths.operator_json).get("operator_inbox_id")  # type: ignore[union-attr]
        operator_inbox_id = value if isinstance(value, str) and value else None

    if operator_inbox_id is None:
        try:
            from xmtp.identifiers import Identifier, IdentifierKind

            identifier = Identifier(kind=IdentifierKind.ETHEREUM, value=operator_addr)
            operator_inbox_id = client.get_inbox_id_by_identifier(identifier)
            if operator_inbox_id:
                set_operator_inbox_id(paths.operator_json, operator_inbox_id)
        except Exception:
            operator_inbox_id = None

    # Onboarding ping to the operator (safe, non-destructive).
    try:
        dm = await client.conversations.new_dm(operator_addr)
        await dm.send(f"tako online (env={env}). Reply 'help' for commands.\n\n(repo: {repo_root().name})")
    except Exception as exc:  # noqa: BLE001
        print(f"XMTP send failed: {exc}", file=sys.stderr)
        hint = hint_for_xmtp_error(exc)
        if hint:
            print(hint, file=sys.stderr)
        return 1

    if args.once:
        return 0

    print("Daemon started. Press Ctrl+C to stop.")

    start = time.monotonic()
    heartbeat = asyncio.create_task(_heartbeat_loop(args))
    stream = client.conversations.stream_all_messages()

    try:
        async for item in stream:
            if isinstance(item, Exception):
                print(f"XMTP stream error: {item}", file=sys.stderr)
                continue

            sender = getattr(item, "sender_inbox_id", None)
            if not isinstance(sender, str):
                continue
            if sender == client.inbox_id:
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

            if operator_inbox_id and sender != operator_inbox_id:
                # Non-operator: only respond to obvious command attempts with a boundary.
                lowered = text.lower()
                if lowered.startswith(("help", "tako", "/")):
                    await convo.send("Operator-only: I can chat, but config/tools/permissions/routines require the operator.")
                continue

            cmd, rest = _parse_command(text)
            if cmd in {"help", "h", "?"}:
                await convo.send(_help_text())
                continue
            if cmd == "status":
                uptime = int(time.monotonic() - start)
                await convo.send(f"status: ok\nenv: {env}\nuptime_s: {uptime}\nversion: {__version__}")
                continue
            if cmd == "doctor":
                lines, problems = _doctor_report(repo_root(), paths, env)
                report = "\n".join(lines)
                if problems:
                    report += "\n\nProblems:\n" + "\n".join(f"- {p}" for p in problems)
                await convo.send(report)
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
    )


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
