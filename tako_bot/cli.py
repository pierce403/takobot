from __future__ import annotations

import argparse
import os
import random
import sys
import time
from datetime import date
from pathlib import Path

from . import __version__
from .daily import ensure_daily_log
from .ens import DEFAULT_ENS_RPC_URLS, resolve_recipient
from .git_safety import assert_not_tracked, panic_check_runtime_secrets
from .keys import apply_key_env_overrides, load_or_create_keys
from .operator import imprint_operator, load_operator
from .paths import daily_root, ensure_runtime_dirs, repo_root, runtime_paths
from .util import is_truthy
from .xmtp import default_message, hint_for_xmtp_error, send_dm_sync


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

    problems: list[str] = []

    try:
        panic_check_runtime_secrets(root, paths.root)
    except Exception as exc:  # noqa: BLE001
        problems.append(str(exc))

    if paths.keys_json.exists():
        try:
            assert_not_tracked(root, paths.keys_json)
        except Exception as exc:  # noqa: BLE001
            problems.append(str(exc))

    operator = load_operator(paths.operator_json)

    env = args.env or os.environ.get("XMTP_ENV", DEFAULT_ENV)

    print("tako doctor")
    print(f"- repo: {root}")
    print(f"- runtime: {paths.root} (ignored)")
    print(f"- daily: {daily_root()} (committed)")
    print(f"- env: {env}")
    print(f"- keys: {'present' if paths.keys_json.exists() else 'missing'}")
    if operator and isinstance(operator.get("operator_address"), str):
        print(f"- operator: {operator['operator_address']}")
    else:
        print("- operator: not imprinted")

    try:
        import xmtp  # noqa: F401
        print("- xmtp: import OK")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"xmtp import failed: {exc}")

    try:
        import web3  # noqa: F401
        print("- web3: import OK")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"web3 import failed: {exc}")

    if problems:
        print("\nProblems:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    return 0


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

    # Ensure today’s daily log exists (committed).
    ensure_daily_log(daily_root(), date.today())

    # Minimal onboarding ping to the operator (safe, non-destructive).
    try:
        send_dm_sync(
            operator_addr,
            f"tako online (env={env}). Reply 'help' for commands.\n\n(repo: {root.name})",
            env,
            paths.xmtp_db_dir,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"XMTP send failed: {exc}", file=sys.stderr)
        hint = hint_for_xmtp_error(exc)
        if hint:
            print(hint, file=sys.stderr)
        return 1

    print("Heartbeat started (sensors/tools disabled by default). Press Ctrl+C to stop.")

    first_tick = True
    try:
        while True:
            if first_tick:
                first_tick = False
                ensure_daily_log(daily_root(), date.today())
            if args.once:
                return 0
            interval = max(1.0, float(args.interval))
            time.sleep(interval + random.uniform(-0.2 * interval, 0.2 * interval))
    except KeyboardInterrupt:
        return 130


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
