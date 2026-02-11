from __future__ import annotations

import asyncio
import argparse
import contextlib
from collections import deque
from dataclasses import dataclass
import random
import sys
import time
from datetime import date, datetime, timezone
from typing import Callable

from . import __version__
from .daily import append_daily_note, ensure_daily_log
from .ens import DEFAULT_ENS_RPC_URLS, resolve_recipient
from .git_safety import assert_not_tracked, panic_check_runtime_secrets
from .keys import derive_eth_address, load_or_create_keys
from .locks import instance_lock
from .operator import clear_operator, get_operator_inbox_id, load_operator
from .pairing import clear_pending
from .paths import daily_root, ensure_runtime_dirs, repo_root, runtime_paths
from .xmtp import create_client, default_message, hint_for_xmtp_error, send_dm_sync


DEFAULT_ENV = "production"
STREAM_RECONNECT_BASE_S = 1.5
STREAM_RECONNECT_MAX_S = 45.0
STREAM_ERROR_BURST_WINDOW_S = 18.0
STREAM_ERROR_BURST_THRESHOLD = 3
STREAM_HINT_COOLDOWN_S = 90.0
STREAM_POLL_INTERVAL_S = 3.0
STREAM_POLL_STABLE_CYCLES = 4
MESSAGE_HISTORY_PER_CONVERSATION = 80
SEEN_MESSAGE_CACHE_MAX = 4096


@dataclass(frozen=True)
class RuntimeHooks:
    log: Callable[[str, str], None] | None = None
    inbound_message: Callable[[str, str], None] | None = None
    emit_console: bool = True


def _emit_runtime_log(
    message: str,
    *,
    level: str = "info",
    stderr: bool = False,
    hooks: RuntimeHooks | None = None,
) -> None:
    if hooks and hooks.log:
        hooks.log(level, message)
    if hooks is None or hooks.emit_console:
        print(message, file=sys.stderr if stderr else sys.stdout)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tako", description="Tako — highly autonomous operator-imprinted agent")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    sub = parser.add_subparsers(dest="cmd", required=False)

    app = sub.add_parser("app", help="Start the interactive terminal app.")
    app.add_argument("--interval", type=float, default=30.0, help="(dev) Heartbeat interval seconds")

    hi = sub.add_parser("hi", help="(dev) Send a one-off DM.")
    hi.add_argument("--to", required=True, help="XMTP address or ENS name")
    hi.add_argument("--message", help="Custom message to send")

    run = sub.add_parser("run", help="Start Tako daemon (operator XMTP channel).")
    run.add_argument("--interval", type=float, default=30.0, help="(dev) Heartbeat interval seconds")
    run.add_argument("--once", action="store_true", help="(dev) Run a single tick and exit")

    bootstrap = sub.add_parser("bootstrap", help="Terminal-first onboarding + outbound pairing, then daemon.")
    bootstrap.add_argument("--interval", type=float, default=30.0, help="(dev) Heartbeat interval seconds")
    bootstrap.add_argument("--once", action="store_true", help="(dev) Run a single tick and exit")

    doctor = sub.add_parser("doctor", help="(dev) Check environment, config, and safety preconditions.")

    return parser


def _ens_rpc_urls_from_args(value: str | None) -> list[str]:
    if not value:
        return list(DEFAULT_ENS_RPC_URLS)
    urls = [item.strip() for item in value.split(",") if item.strip()]
    return urls or list(DEFAULT_ENS_RPC_URLS)


def cmd_app(args: argparse.Namespace) -> int:
    try:
        from .app import run_terminal_app
    except ModuleNotFoundError as exc:
        if exc.name == "textual":
            print(
                "Interactive app requires `textual`. Run `./tako.sh` so dependencies install via uv.",
                file=sys.stderr,
            )
            return 1
        raise

    return run_terminal_app(interval=max(1.0, float(args.interval)))


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


def cmd_bootstrap(args: argparse.Namespace) -> int:
    from .bootstrap_tty import run_bootstrap

    return run_bootstrap(args)


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
    operator_cfg = load_operator(paths.operator_json)
    operator_inbox_id = get_operator_inbox_id(operator_cfg)

    _emit_runtime_log(f"tako address: {address}")
    _emit_runtime_log("status: starting daemon")
    if operator_inbox_id:
        _emit_runtime_log("pairing: operator already imprinted")
    else:
        _emit_runtime_log("pairing: unpaired (launch `tako` for terminal onboarding)")

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
    hooks: RuntimeHooks | None = None,
) -> int:
    # Ensure today’s daily log exists (committed).
    ensure_daily_log(daily_root(), date.today())

    try:
        client = await create_client(env, paths.xmtp_db_dir, wallet_key, db_encryption_key)
    except asyncio.CancelledError:
        raise
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        _emit_runtime_log(f"XMTP client init failed: {exc}", level="error", stderr=True, hooks=hooks)
        hint = hint_for_xmtp_error(exc)
        if hint:
            _emit_runtime_log(hint, level="error", stderr=True, hooks=hooks)
        return 1

    operator_cfg = load_operator(paths.operator_json)
    operator_inbox_id = get_operator_inbox_id(operator_cfg)

    if operator_inbox_id:
        clear_pending(paths.state_dir / "pairing.json")
        _emit_runtime_log("status: paired", hooks=hooks)
    else:
        _emit_runtime_log("status: unpaired", hooks=hooks)
        _emit_runtime_log("pairing: launch `tako` for terminal-first pairing", hooks=hooks)

    _emit_runtime_log(f"inbox_id: {client.inbox_id}", hooks=hooks)
    if args.once:
        return 0

    _emit_runtime_log("Daemon started. Press Ctrl+C to stop.", hooks=hooks)

    start = time.monotonic()
    heartbeat = asyncio.create_task(_heartbeat_loop(args))
    reconnect_attempt = 0
    error_burst_count = 0
    last_error_at = 0.0
    poll_successes = 0
    mode = "stream"
    hint_last_printed: dict[str, float] = {}
    seen_message_ids: set[bytes] = set()
    seen_message_order: deque[bytes] = deque()

    with contextlib.suppress(Exception):
        await _prime_seen_messages(client, seen_message_ids, seen_message_order)

    try:
        while True:
            if mode == "poll":
                try:
                    items = await _poll_new_messages(client, seen_message_ids, seen_message_order)
                    for item in items:
                        await _handle_incoming_message(item, client, paths, address, env, start, hooks=hooks)
                    poll_successes += 1
                    reconnect_attempt = 0
                    if poll_successes >= STREAM_POLL_STABLE_CYCLES:
                        _emit_runtime_log(
                            "XMTP polling is stable; retrying stream mode.",
                            level="warn",
                            stderr=True,
                            hooks=hooks,
                        )
                        mode = "stream"
                        error_burst_count = 0
                        continue
                except asyncio.CancelledError:
                    raise
                except KeyboardInterrupt:
                    raise
                except Exception as exc:  # noqa: BLE001
                    now = time.monotonic()
                    summary = _summarize_stream_error(exc)
                    _emit_runtime_log(f"XMTP polling error: {summary}", level="error", stderr=True, hooks=hooks)
                    _maybe_print_xmtp_hint(exc, hint_last_printed, now, hooks=hooks)
                    poll_successes = 0

                await asyncio.sleep(STREAM_POLL_INTERVAL_S)
                continue

            stream = client.conversations.stream_all_messages()
            try:
                async for item in stream:
                    if isinstance(item, Exception):
                        now = time.monotonic()
                        if now - last_error_at > STREAM_ERROR_BURST_WINDOW_S:
                            error_burst_count = 0
                        error_burst_count += 1
                        last_error_at = now

                        summary = _summarize_stream_error(item)
                        _emit_runtime_log(f"XMTP stream warning: {summary}", level="warn", stderr=True, hooks=hooks)

                        _maybe_print_xmtp_hint(item, hint_last_printed, now, hooks=hooks)

                        if error_burst_count >= STREAM_ERROR_BURST_THRESHOLD:
                            _emit_runtime_log(
                                "XMTP stream unstable; switching to polling fallback.",
                                level="warn",
                                stderr=True,
                                hooks=hooks,
                            )
                            mode = "poll"
                            poll_successes = 0
                            break
                        continue

                    error_burst_count = 0
                    reconnect_attempt = 0
                    if _mark_message_seen(item, seen_message_ids, seen_message_order):
                        await _handle_incoming_message(item, client, paths, address, env, start, hooks=hooks)
            except asyncio.CancelledError:
                raise
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001
                now = time.monotonic()
                summary = _summarize_stream_error(exc)
                _emit_runtime_log(f"XMTP stream crashed: {summary}", level="error", stderr=True, hooks=hooks)
                _maybe_print_xmtp_hint(exc, hint_last_printed, now, hooks=hooks)
                mode = "poll"
                poll_successes = 0
            finally:
                with contextlib.suppress(Exception):
                    await stream.close()

            if mode == "poll":
                continue

            reconnect_delay = _stream_reconnect_delay(reconnect_attempt)
            reconnect_attempt += 1
            _emit_runtime_log(
                f"XMTP stream reconnecting in {reconnect_delay:.1f}s...",
                level="warn",
                stderr=True,
                hooks=hooks,
            )
            await asyncio.sleep(reconnect_delay)
    finally:
        heartbeat.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat

    return 0


async def _handle_incoming_message(
    item,
    client,
    paths,
    address: str,
    env: str,
    start: float,
    hooks: RuntimeHooks | None = None,
) -> None:
    sender_inbox_id = getattr(item, "sender_inbox_id", None)
    if not isinstance(sender_inbox_id, str):
        return
    if sender_inbox_id == client.inbox_id:
        return

    content = getattr(item, "content", None)
    if not isinstance(content, str):
        return
    text = content.strip()
    if not text:
        return
    if hooks and hooks.inbound_message:
        hooks.inbound_message(sender_inbox_id, text)

    convo_id = getattr(item, "conversation_id", None)
    if not isinstance(convo_id, (bytes, bytearray)):
        return

    convo = await client.conversations.get_conversation_by_id(bytes(convo_id))
    if convo is None:
        return

    operator_cfg = load_operator(paths.operator_json)
    operator_inbox_id = get_operator_inbox_id(operator_cfg)

    if operator_inbox_id is None:
        if _looks_like_command(text):
            await convo.send(
                "This Tako instance is not paired yet.\n\n"
                "Pairing is terminal-first now: run `tako` (or `./start.sh`) in the local repo, "
                "enter your XMTP handle, and confirm the outbound DM code there."
            )
        return

    if sender_inbox_id != operator_inbox_id:
        if _looks_like_command(text):
            await convo.send("Operator-only: config/tools/permissions/routines require the operator.")
        return

    cmd, rest = _parse_command(text)
    if cmd in {"help", "h", "?"}:
        await convo.send(_help_text())
        return
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
        return
    if cmd == "doctor":
        append_daily_note(daily_root(), date.today(), "Operator ran doctor.")
        lines, problems = _doctor_report(repo_root(), paths, env)
        report = "\n".join(lines)
        if problems:
            report += "\n\nProblems:\n" + "\n".join(f"- {p}" for p in problems)
        await convo.send(report)
        return
    if cmd == "reimprint":
        if rest.strip().lower() != "confirm":
            await convo.send(
                "Re-imprint is operator-only and destructive.\n\n"
                "Reply: `reimprint CONFIRM` to clear the current operator. "
                "Then re-run terminal onboarding (`tako` or `./start.sh`) to pair again."
            )
            return
        clear_operator(paths.operator_json)
        clear_pending(paths.state_dir / "pairing.json")
        append_daily_note(daily_root(), date.today(), "Operator cleared imprint (reimprint CONFIRM).")
        await convo.send("Operator imprint cleared. Run `tako` (or `./start.sh`) in the local terminal to pair a new operator.")
        return

    await convo.send("Unknown command. Reply 'help'.")


def _maybe_print_xmtp_hint(
    error: Exception,
    hint_last_printed: dict[str, float],
    now: float,
    hooks: RuntimeHooks | None = None,
) -> None:
    hint = hint_for_xmtp_error(error)
    if not hint:
        return
    last_hint_time = hint_last_printed.get(hint, 0.0)
    if now - last_hint_time > STREAM_HINT_COOLDOWN_S:
        hint_last_printed[hint] = now
        _emit_runtime_log(hint, level="warn", stderr=True, hooks=hooks)


def _message_id(item) -> bytes | None:
    value = getattr(item, "id", None)
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    return None


def _mark_message_seen(item, seen_ids: set[bytes], seen_order: deque[bytes]) -> bool:
    message_id = _message_id(item)
    if message_id is None:
        return True
    if message_id in seen_ids:
        return False

    seen_ids.add(message_id)
    seen_order.append(message_id)
    while len(seen_order) > SEEN_MESSAGE_CACHE_MAX:
        removed = seen_order.popleft()
        seen_ids.discard(removed)
    return True


def _fallback_history_options():
    from xmtp.bindings import NativeBindings

    return NativeBindings.FfiListMessagesOptions(
        sent_before_ns=None,
        sent_after_ns=None,
        limit=MESSAGE_HISTORY_PER_CONVERSATION,
        delivery_status=None,
        direction=NativeBindings.FfiDirection.DESCENDING,
        content_types=None,
        exclude_content_types=None,
        exclude_sender_inbox_ids=None,
        sort_by=NativeBindings.FfiSortBy.INSERTED_AT,
        inserted_after_ns=None,
        inserted_before_ns=None,
    )


async def _collect_history_messages(client) -> list[object]:
    options = _fallback_history_options()
    messages: list[object] = []

    with contextlib.suppress(Exception):
        await client.conversations.sync_all_conversations()

    conversations = await client.conversations.list()
    for convo in conversations:
        ffi_conversation = getattr(convo, "_ffi", None)
        if ffi_conversation is None:
            continue
        try:
            raw_messages = await ffi_conversation.find_messages(options)
        except Exception:
            continue

        for raw in raw_messages:
            try:
                decoded = client._decode_message(raw)
            except Exception:
                continue
            messages.append(decoded)

    messages.sort(
        key=lambda item: getattr(
            item,
            "sent_at",
            datetime.min.replace(tzinfo=timezone.utc),
        )
    )
    return messages


async def _prime_seen_messages(client, seen_ids: set[bytes], seen_order: deque[bytes]) -> None:
    history = await _collect_history_messages(client)
    for item in history:
        _mark_message_seen(item, seen_ids, seen_order)


async def _poll_new_messages(client, seen_ids: set[bytes], seen_order: deque[bytes]) -> list[object]:
    history = await _collect_history_messages(client)
    new_items: list[object] = []
    for item in history:
        if _mark_message_seen(item, seen_ids, seen_order):
            new_items.append(item)
    return new_items


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


def _summarize_stream_error(error: Exception) -> str:
    first_line = str(error).strip().splitlines()
    if not first_line:
        return error.__class__.__name__
    text = first_line[0].strip()
    if not text:
        return error.__class__.__name__
    if len(text) > 220:
        return f"{text[:217]}..."
    return text


def _stream_reconnect_delay(attempt: int) -> float:
    base = min(STREAM_RECONNECT_MAX_S, STREAM_RECONNECT_BASE_S * (2**max(0, attempt)))
    jitter = random.uniform(0.0, base * 0.2)
    return base + jitter


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    argv = list(argv) if argv is not None else list(sys.argv[1:])
    if not argv:
        argv = ["app"]
    args = parser.parse_args(argv)

    if args.cmd == "app":
        return cmd_app(args)
    if args.cmd == "hi":
        return cmd_hi(args)
    if args.cmd == "run":
        return cmd_run(args)
    if args.cmd == "bootstrap":
        return cmd_bootstrap(args)
    if args.cmd == "doctor":
        return cmd_doctor(args)

    parser.error(f"Unknown command: {args.cmd}")
    return 2
