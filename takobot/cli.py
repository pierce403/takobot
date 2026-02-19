from __future__ import annotations

import asyncio
import argparse
import base64
import contextlib
from collections import deque
from dataclasses import dataclass, replace
import inspect
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from typing import Callable

from . import __version__
from . import dose
from .capability_frontmatter import (
    build_skills_inventory_excerpt,
    build_tools_inventory_excerpt,
    load_skills_frontmatter_excerpt,
    load_tools_frontmatter_excerpt,
)
from .config import add_world_watch_sites, explain_tako_toml, load_tako_toml, set_workspace_name
from .conversation import ConversationStore
from .daily import append_daily_note, ensure_daily_log
from .ens import DEFAULT_ENS_RPC_URLS, resolve_recipient
from .git_safety import assert_not_tracked, auto_commit_pending, ensure_local_git_identity, panic_check_runtime_secrets
from .inference import (
    PI_TYPE2_THINKING_DEFAULT,
    CONFIGURABLE_API_KEY_VARS,
    SUPPORTED_PROVIDER_PREFERENCES,
    InferenceRuntime,
    auto_repair_inference_runtime,
    clear_inference_api_key,
    discover_inference_runtime,
    format_inference_auth_inventory,
    format_runtime_lines,
    inference_error_log_path,
    prepare_pi_login_plan,
    run_inference_prompt_with_fallback,
    set_inference_api_key,
    set_inference_preferred_provider,
)
from .keys import derive_eth_address, load_or_create_keys
from .life_stage import stage_policy_for_name
from .locks import instance_lock
from .memory_frontmatter import load_memory_frontmatter_excerpt
from .jobs import (
    add_job_from_natural_text,
    format_jobs_report,
    get_job,
    list_jobs,
    looks_like_natural_job_request,
    mark_job_manual_trigger,
    record_job_error,
    remove_job,
)
from .operator import clear_operator, get_operator_inbox_id, load_operator
from .operator_profile import (
    apply_operator_profile_update,
    child_profile_prompt_context,
    extract_operator_profile_update,
    load_operator_profile,
    next_child_followup_question,
    save_operator_profile,
    write_operator_profile_note,
)
from .pairing import clear_pending
from .paths import RuntimePaths, code_root, daily_root, ensure_code_dir, ensure_runtime_dirs, repo_root, runtime_paths
from .problem_tasks import ensure_problem_tasks
from .rag_context import format_focus_summary, focus_profile_from_dose, query_memory_with_ragrep
from .self_update import run_self_update
from .skillpacks import seed_openclaw_starter_skills
from .starter_tools import seed_starter_tools
from .soul import (
    load_soul_excerpt,
    read_identity,
    read_mission_objectives,
    update_identity,
    update_mission_objectives,
)
from .tool_ops import fetch_webpage, run_local_command
from .xmtp import (
    close_client,
    create_client,
    default_message,
    ensure_profile_message_for_conversation,
    hint_for_xmtp_error,
    parse_profile_message,
    probe_xmtp_import,
    send_dm_sync,
    set_typing_indicator,
    sync_identity_profile,
)
from .identity import (
    build_identity_name_intent_prompt,
    build_identity_role_prompt,
    extract_name_intent_from_model_output,
    extract_name_from_text,
    extract_role_from_model_output,
    extract_role_from_text,
    looks_like_role_change_request,
    looks_like_role_info_query,
)
from .extensions.registry import enable_all_installed as ext_enable_all_installed
from .productivity import open_loops as prod_open_loops
from .productivity import outcomes as prod_outcomes
from .productivity import promote as prod_promote
from .productivity import summarize as prod_summarize
from .productivity import tasks as prod_tasks
from .productivity import weekly_review as prod_weekly


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
CHAT_INFERENCE_TIMEOUT_S = 75.0
CHAT_REPLY_MAX_CHARS = 700
CHAT_CONTEXT_USER_TURNS = 12
CHAT_CONTEXT_MAX_CHARS = 8_000
UPDATE_CHECK_INITIAL_DELAY_S = 20.0
UPDATE_CHECK_INTERVAL_S = 6 * 60 * 60
XMTP_TYPING_LEAD_S = 0.35
XMTP_SEND_RETRY_ATTEMPTS = 3
XMTP_SEND_RETRY_BASE_S = 0.4
XMTP_POLL_ERROR_REBUILD_THRESHOLD = 4
XMTP_STREAM_CRASH_REBUILD_THRESHOLD = 2
XMTP_CLIENT_REBUILD_COOLDOWN_S = 30.0


@dataclass(frozen=True)
class RuntimeHooks:
    log: Callable[[str, str], None] | None = None
    inbound_message: Callable[[str, str], None] | None = None
    outbound_message: Callable[[str, str], None] | None = None
    job_runner: Callable[[str, str], object] | None = None
    update_applied: Callable[[str], object] | None = None
    emit_console: bool = True
    log_file: Path | None = None


def _emit_runtime_log(
    message: str,
    *,
    level: str = "info",
    stderr: bool = False,
    hooks: RuntimeHooks | None = None,
) -> None:
    if hooks and hooks.log:
        hooks.log(level, message)
    if hooks and hooks.log_file is not None:
        _append_runtime_log(hooks.log_file, level=level, message=message)
    if hooks is None or hooks.emit_console:
        print(message, file=sys.stderr if stderr else sys.stdout)


def _append_runtime_log(log_file: Path, *, level: str, message: str) -> None:
    normalized_message = " ".join(message.split())
    stamp = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
    line = f"{stamp} [{level.lower()}] {normalized_message}\n"
    with contextlib.suppress(Exception):
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with log_file.open("a", encoding="utf-8") as handle:
            handle.write(line)


def _hooks_with_log_file(hooks: RuntimeHooks | None, log_file: Path) -> RuntimeHooks:
    if hooks is None:
        return RuntimeHooks(log_file=log_file)
    if hooks.log_file is not None:
        return hooks
    return replace(hooks, log_file=log_file)


async def _notify_update_applied(hooks: RuntimeHooks | None, summary: str) -> bool:
    if hooks is None or hooks.update_applied is None:
        return False
    callback = hooks.update_applied
    try:
        maybe_result = callback(summary)
        if inspect.isawaitable(maybe_result):
            await maybe_result
    except Exception as exc:  # noqa: BLE001
        _emit_runtime_log(
            f"update restart hook failed: {_summarize_stream_error(exc)}",
            level="warn",
            stderr=True,
            hooks=hooks,
        )
        return False
    return True


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="takobot",
        description="Takobot: your highly autonomous and incredibly curious octopus friend",
    )
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


def _preferred_git_identity_name(root: Path) -> str:
    cfg, _warn = load_tako_toml(root / "tako.toml")
    configured = " ".join((cfg.workspace.name or "").split()).strip()
    if configured and configured.lower() not in {"tako-workspace", "takobot-workspace"}:
        return configured
    identity_name, _identity_role = read_identity()
    return " ".join((identity_name or "").split()).strip()


def cmd_app(args: argparse.Namespace) -> int:
    try:
        from .app import run_terminal_app
    except ModuleNotFoundError as exc:
        if exc.name == "textual":
            print(
                "Interactive app requires `textual`. Re-run workspace bootstrap (setup.sh) so dependencies install into .venv, then retry.",
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
        records = ensure_problem_tasks(root, problems, source="doctor")
        print("\nProblems:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        if records:
            created = [record for record in records if record.created]
            if created:
                print("\nProblem tasks created:", file=sys.stderr)
                for record in created:
                    print(f"- {record.task_id}: {record.title}", file=sys.stderr)
            else:
                print("\nProblem tasks already open:", file=sys.stderr)
                for record in records:
                    print(f"- {record.task_id}: {record.title}", file=sys.stderr)
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
        "takobot doctor",
        f"- workspace: {root}",
        f"- runtime: {paths.root} (ignored)",
        f"- memory dailies: {daily_root()} (committed)",
        f"- python executable: {sys.executable}",
        f"- env: {env}",
        f"- keys: {'present' if paths.keys_json.exists() else 'missing'}",
    ]
    repair_actions = auto_repair_inference_runtime()
    if repair_actions:
        lines.append("- inference auto-fix: applied")
        lines.extend(f"- inference auto-fix detail: {action}" for action in repair_actions)
    else:
        lines.append("- inference auto-fix: no changes needed")

    git_identity_name = _preferred_git_identity_name(root)
    git_identity_ok, git_identity_detail, git_identity_auto_configured = ensure_local_git_identity(
        root,
        identity_name=git_identity_name,
    )
    if git_identity_auto_configured:
        lines.append(f"- git identity: auto-configured local identity ({git_identity_detail})")
    else:
        lines.append(f"- git identity: {git_identity_detail}")
    if not git_identity_ok:
        problems.append(
            "git identity missing: automatic local setup failed; configure `git config --global user.name \"Your Name\"` and "
            "`git config --global user.email \"you@example.com\"`"
        )

    if operator and isinstance(operator.get("operator_address"), str):
        lines.append(f"- operator: {operator['operator_address']}")
    else:
        lines.append("- operator: not imprinted")

    xmtp_ok, xmtp_status = probe_xmtp_import()
    lines.append(f"- xmtp: {xmtp_status}")
    if not xmtp_ok:
        problems.append(f"xmtp import failed: {xmtp_status}")

    try:
        import web3  # noqa: F401

        lines.append("- web3: import OK")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"web3 import failed: {exc}")

    inference_runtime = discover_inference_runtime()
    lines.extend(f"- {line}" for line in format_runtime_lines(inference_runtime))
    inference_lines, inference_problems = _doctor_inference_diagnostics(inference_runtime, paths)
    lines.extend(inference_lines)
    problems.extend(inference_problems)

    return lines, problems


def _doctor_inference_diagnostics(runtime: InferenceRuntime, paths) -> tuple[list[str], list[str]]:
    lines: list[str] = []
    problems: list[str] = []

    lines.append("- inference doctor: local offline diagnostics")
    for provider in ("pi",):
        status = runtime.statuses.get(provider)
        if status is None:
            continue

        cli_exec = status.cli_path or status.cli_name
        if not status.cli_installed:
            problems.append(f"{provider} CLI missing.")
            lines.append(f"- {provider} probe: CLI missing")
            continue

        version_ok, version_detail = _probe_cli_command([cli_exec, "--version"], timeout_s=7.0)
        lines.append(f"- {provider} probe: --version {'ok' if version_ok else 'failed'} ({version_detail})")
        if not version_ok:
            problems.append(f"{provider} CLI appears installed but --version failed: {version_detail}")

        command_probe = [cli_exec, "--help"]
        command_ok, command_detail = _probe_cli_command(command_probe, timeout_s=7.0)
        lines.append(
            f"- {provider} probe: {' '.join(command_probe[1:])} "
            f"{'ok' if command_ok else 'failed'} ({command_detail})"
        )
        if not command_ok:
            problems.append(f"{provider} CLI command probe failed: {command_detail}")

        if status.auth_kind == "none" or not status.key_present:
            problems.append(_provider_auth_problem(provider))
        elif status.key_source:
            lines.append(f"- {provider} auth source: {status.key_source}")
        if status.note:
            lines.append(f"- {provider} note: {status.note}")

    if not runtime.ready:
        problems.append("inference is unavailable: required pi runtime is not ready (see probes above).")

    recent = _recent_inference_error_lines(paths.state_dir / "events.jsonl", limit=3)
    for item in recent:
        lines.append(f"- inference recent error: {item}")
    if recent:
        problems.append("recent inference runtime errors were detected in the event log.")

    return lines, problems


def _provider_auth_problem(provider: str) -> str:
    if provider == "pi":
        return "pi auth missing after auto-fix: configure a pi auth profile or set one supported API key."
    if provider == "ollama":
        return "ollama model missing: set `inference ollama model <name>` or set `OLLAMA_MODEL`."
    if provider == "codex":
        return "codex auth missing: run `codex login` or set `OPENAI_API_KEY`."
    if provider == "claude":
        return "claude auth missing: set `ANTHROPIC_API_KEY`/`CLAUDE_API_KEY` or run Claude CLI auth."
    if provider == "gemini":
        return "gemini auth missing: run Gemini CLI auth or set `GEMINI_API_KEY`/`GOOGLE_API_KEY`."
    return f"{provider} auth missing."


def _probe_cli_command(command: list[str], *, timeout_s: float) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
    except FileNotFoundError:
        return False, "not found"
    except subprocess.TimeoutExpired:
        return False, "timed out"
    except Exception as exc:  # noqa: BLE001
        return False, _summarize_stream_error(exc)

    detail = (proc.stdout or "").strip() or (proc.stderr or "").strip() or f"exit={proc.returncode}"
    detail = " ".join(detail.split())
    if len(detail) > 180:
        detail = detail[:177] + "..."
    return proc.returncode == 0, detail


def _recent_inference_error_lines(path: Path, *, limit: int) -> list[str]:
    if not path.exists():
        return []
    tail = deque(maxlen=400)
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                tail.append(line)
    except Exception:
        return []

    results: list[str] = []
    for raw in tail:
        try:
            payload = json.loads(raw)
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue

        event_type = str(payload.get("type", "")).strip().lower()
        severity = str(payload.get("severity", "info")).strip().lower()
        message = str(payload.get("message", "")).strip()
        if not event_type.startswith("inference."):
            continue
        if severity not in {"warn", "error", "critical"} and "error" not in event_type:
            continue
        summary = " ".join(f"{event_type}: {message}".split())
        if summary:
            results.append(summary)

    if len(results) > limit:
        return results[-limit:]
    return results


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
    hooks = _hooks_with_log_file(None, paths.logs_dir / "runtime.log")

    _emit_runtime_log(f"takobot address: {address}", hooks=hooks)
    _emit_runtime_log("status: starting daemon", hooks=hooks)
    if operator_inbox_id:
        _emit_runtime_log("pairing: operator already imprinted", hooks=hooks)
    else:
        _emit_runtime_log("pairing: unpaired (launch `takobot` for terminal onboarding)", hooks=hooks)

    try:
        with instance_lock(paths.locks_dir / "tako.lock"):
            return asyncio.run(_run_daemon(args, paths, env, wallet_key, db_encryption_key, address, hooks=hooks))
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
    hooks = _hooks_with_log_file(hooks, paths.logs_dir / "runtime.log")
    root = repo_root()
    code_dir = ensure_code_dir(root)
    conversations = ConversationStore(paths.state_dir)
    _emit_runtime_log(f"workspace code dir: {code_dir}", hooks=hooks)
    registry_path = paths.state_dir / "extensions.json"
    seeded = seed_openclaw_starter_skills(root, registry_path=registry_path)
    if seeded.created_skills or seeded.registered_skills:
        _emit_runtime_log(
            (
                "starter skills synced "
                f"(created={len(seeded.created_skills)} registered={len(seeded.registered_skills)})"
            ),
            hooks=hooks,
        )
    starter_tools = seed_starter_tools(root)
    if starter_tools.created:
        _emit_runtime_log(
            f"starter tools synced (created={len(starter_tools.created)})",
            hooks=hooks,
        )
    for warning in starter_tools.warnings:
        _emit_runtime_log(
            f"starter tools warning: {warning}",
            level="warn",
            stderr=True,
            hooks=hooks,
        )
    enabled_now, installed_total = ext_enable_all_installed(registry_path)
    if enabled_now:
        _emit_runtime_log(
            f"extensions auto-enabled: {enabled_now}/{installed_total} installed entries",
            hooks=hooks,
        )

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
    inference_runtime = discover_inference_runtime()
    _emit_runtime_log(
        f"inference: selected={inference_runtime.selected_provider or 'none'} "
        f"ready={'yes' if inference_runtime.ready else 'no'}",
        hooks=hooks,
    )
    git_identity_name = _preferred_git_identity_name(root)
    git_identity_ok, git_identity_detail, git_identity_auto_configured = ensure_local_git_identity(
        repo_root(),
        identity_name=git_identity_name,
    )
    if git_identity_ok and git_identity_auto_configured:
        _emit_runtime_log(
            f"git identity: auto-configured local identity ({git_identity_detail})",
            hooks=hooks,
        )
    if not git_identity_ok:
        _emit_runtime_log(f"git identity: {git_identity_detail}", level="warn", stderr=True, hooks=hooks)
        _emit_runtime_log(
            "operator request: automatic local git identity setup failed; configure git identity for commit attribution "
            "(`git config --global user.name \"Your Name\"` + "
            "`git config --global user.email \"you@example.com\"`, "
            "or repo-local `git config user.name ...` + `git config user.email ...`).",
            level="warn",
            stderr=True,
            hooks=hooks,
        )
        records = ensure_problem_tasks(repo_root(), [f"git identity unavailable; {git_identity_detail}"], source="startup-health")
        created = [record for record in records if record.created]
        if created:
            _emit_runtime_log(
                f"tasks: created problem task {created[0].task_id} ({created[0].title})",
                level="warn",
                stderr=True,
                hooks=hooks,
            )

    await _sync_xmtp_profile(
        client,
        paths=paths,
        identity_name=git_identity_name,
        hooks=hooks,
        context="startup",
    )

    if operator_inbox_id:
        clear_pending(paths.state_dir / "pairing.json")
        _emit_runtime_log("status: paired", hooks=hooks)
    else:
        _emit_runtime_log("status: unpaired", hooks=hooks)
        _emit_runtime_log("pairing: launch `takobot` for terminal-first pairing", hooks=hooks)

    _emit_runtime_log(f"inbox_id: {client.inbox_id}", hooks=hooks)
    if args.once:
        return 0

    _emit_runtime_log("Daemon started. Press Ctrl+C to stop.", hooks=hooks)

    start = time.monotonic()
    heartbeat = asyncio.create_task(_heartbeat_loop(args, hooks=hooks, identity_name=git_identity_name))
    update_check = asyncio.create_task(_periodic_update_check_loop(hooks=hooks))
    reconnect_attempt = 0
    error_burst_count = 0
    last_error_at = 0.0
    stream_crash_streak = 0
    poll_successes = 0
    poll_error_streak = 0
    last_client_rebuild_at = 0.0
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
                        await _handle_incoming_message(
                            item,
                            client,
                            paths,
                            address,
                            env,
                            start,
                            inference_runtime,
                            conversations,
                            hooks=hooks,
                        )
                    poll_successes += 1
                    poll_error_streak = 0
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
                    poll_error_streak += 1
                    if (
                        poll_error_streak >= XMTP_POLL_ERROR_REBUILD_THRESHOLD
                        and (now - last_client_rebuild_at) >= XMTP_CLIENT_REBUILD_COOLDOWN_S
                    ):
                        rebuilt = await _rebuild_xmtp_client(
                            client,
                            env=env,
                            db_root=paths.xmtp_db_dir,
                            wallet_key=wallet_key,
                            db_encryption_key=db_encryption_key,
                            hooks=hooks,
                        )
                        last_client_rebuild_at = now
                        if rebuilt is not None:
                            client = rebuilt
                            seen_message_ids.clear()
                            seen_message_order.clear()
                            with contextlib.suppress(Exception):
                                await _prime_seen_messages(client, seen_message_ids, seen_message_order)
                            await _sync_xmtp_profile(
                                client,
                                paths=paths,
                                identity_name=_preferred_git_identity_name(root),
                                hooks=hooks,
                                context="rebuild",
                            )
                            poll_error_streak = 0
                            stream_crash_streak = 0
                            reconnect_attempt = 0
                            mode = "stream"

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
                    stream_crash_streak = 0
                    reconnect_attempt = 0
                    if _mark_message_seen(item, seen_message_ids, seen_message_order):
                        await _handle_incoming_message(
                            item,
                            client,
                            paths,
                            address,
                            env,
                            start,
                            inference_runtime,
                            conversations,
                            hooks=hooks,
                        )
            except asyncio.CancelledError:
                raise
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001
                now = time.monotonic()
                summary = _summarize_stream_error(exc)
                _emit_runtime_log(f"XMTP stream crashed: {summary}", level="error", stderr=True, hooks=hooks)
                _maybe_print_xmtp_hint(exc, hint_last_printed, now, hooks=hooks)
                stream_crash_streak += 1
                mode = "poll"
                poll_successes = 0
                if (
                    stream_crash_streak >= XMTP_STREAM_CRASH_REBUILD_THRESHOLD
                    and (now - last_client_rebuild_at) >= XMTP_CLIENT_REBUILD_COOLDOWN_S
                ):
                    rebuilt = await _rebuild_xmtp_client(
                        client,
                        env=env,
                        db_root=paths.xmtp_db_dir,
                        wallet_key=wallet_key,
                        db_encryption_key=db_encryption_key,
                        hooks=hooks,
                    )
                    last_client_rebuild_at = now
                    if rebuilt is not None:
                        client = rebuilt
                        seen_message_ids.clear()
                        seen_message_order.clear()
                        with contextlib.suppress(Exception):
                            await _prime_seen_messages(client, seen_message_ids, seen_message_order)
                        await _sync_xmtp_profile(
                            client,
                            paths=paths,
                            identity_name=_preferred_git_identity_name(root),
                            hooks=hooks,
                            context="rebuild",
                        )
                        stream_crash_streak = 0
                        poll_error_streak = 0
                        reconnect_attempt = 0
                        mode = "stream"
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
        update_check.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await heartbeat
        with contextlib.suppress(asyncio.CancelledError):
            await update_check

    return 0


class _ConversationWithTyping:
    _typing_unavailable_noted = False

    def __init__(self, conversation, *, hooks: RuntimeHooks | None = None) -> None:
        self._conversation = conversation
        self._hooks = hooks
        self._typing_supported: bool | None = None

    async def send(self, content: object, content_type: object | None = None):
        if content_type is not None:
            return await self._send_with_retry(content, content_type=content_type)

        if not isinstance(content, str):
            return await self._send_with_retry(content)

        typing_enabled = await self._toggle_typing(True)
        if typing_enabled:
            await asyncio.sleep(XMTP_TYPING_LEAD_S)
        try:
            result = await self._send_with_retry(content)
        finally:
            if typing_enabled:
                await self._toggle_typing(False)
        self._emit_outbound_message(content)
        return result

    async def _send_with_retry(self, content: object, *, content_type: object | None = None):
        attempts = max(1, int(XMTP_SEND_RETRY_ATTEMPTS))
        for attempt in range(1, attempts + 1):
            try:
                if content_type is None:
                    return await self._conversation.send(content)
                return await self._conversation.send(content, content_type=content_type)
            except asyncio.CancelledError:
                raise
            except KeyboardInterrupt:
                raise
            except Exception as exc:  # noqa: BLE001
                retryable = _is_retryable_xmtp_error(exc)
                if attempt >= attempts or not retryable:
                    raise
                delay = min(3.0, XMTP_SEND_RETRY_BASE_S * (2 ** (attempt - 1)))
                _emit_runtime_log(
                    (
                        f"XMTP send retry ({attempt}/{attempts - 1}) in {delay:.1f}s: "
                        f"{_summarize_stream_error(exc)}"
                    ),
                    level="warn",
                    stderr=True,
                    hooks=self._hooks,
                )
                await asyncio.sleep(delay)

    async def _toggle_typing(self, active: bool) -> bool:
        if self._typing_supported is False:
            return False
        supported = await set_typing_indicator(self._conversation, active)
        if supported:
            self._typing_supported = True
            return True
        if self._typing_supported is None:
            self._typing_supported = False
            if not _ConversationWithTyping._typing_unavailable_noted:
                _ConversationWithTyping._typing_unavailable_noted = True
                _emit_runtime_log(
                    "XMTP typing indicator is unavailable in this SDK/runtime; continuing without it.",
                    level="warn",
                    hooks=self._hooks,
                )
        return False

    def __getattr__(self, name: str):
        return getattr(self._conversation, name)

    def _emit_outbound_message(self, text: str) -> None:
        if not text.strip():
            return
        hooks = self._hooks
        if hooks is None or hooks.outbound_message is None:
            return
        recipient_inbox_id = getattr(self._conversation, "peer_inbox_id", None)
        if not isinstance(recipient_inbox_id, str):
            recipient_inbox_id = ""
        hooks.outbound_message(recipient_inbox_id, text)


async def _handle_incoming_message(
    item,
    client,
    paths,
    address: str,
    env: str,
    start: float,
    inference_runtime: InferenceRuntime,
    conversations: ConversationStore,
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
    profile_message = parse_profile_message(text)
    if profile_message is not None:
        _emit_runtime_log(
            (
                "xmtp profile metadata received and ignored for chat routing "
                f"(sender={sender_inbox_id[:10]} name={profile_message.name or '(none)'})"
            ),
            hooks=hooks,
        )
        return
    if hooks and hooks.inbound_message:
        hooks.inbound_message(sender_inbox_id, text)

    convo_id = getattr(item, "conversation_id", None)
    if not isinstance(convo_id, (bytes, bytearray)):
        return
    session_key = f"xmtp:{bytes(convo_id).hex()}"

    raw_convo = await client.conversations.get_conversation_by_id(bytes(convo_id))
    if raw_convo is None:
        return
    identity_name = _preferred_git_identity_name(repo_root())
    avatar_cache = paths.state_dir / "xmtp-avatar.svg"
    avatar_url = ""
    with contextlib.suppress(Exception):
        if avatar_cache.exists():
            encoded = base64.b64encode(avatar_cache.read_bytes()).decode("ascii")
            avatar_url = f"data:image/svg+xml;base64,{encoded}"
    with contextlib.suppress(Exception):
        broadcast = await ensure_profile_message_for_conversation(
            client,
            raw_convo,
            state_dir=paths.state_dir,
            identity_name=identity_name,
            avatar_url=avatar_url,
        )
        if broadcast.self_sent or broadcast.peer_sent_count:
            _emit_runtime_log(
                (
                    "xmtp profile metadata published for active DM "
                    f"(self={'yes' if broadcast.self_sent else 'no'} peers={broadcast.peer_sent_count})"
                ),
                hooks=hooks,
            )
    convo = _ConversationWithTyping(raw_convo, hooks=hooks)

    operator_cfg = load_operator(paths.operator_json)
    operator_inbox_id = get_operator_inbox_id(operator_cfg)

    if operator_inbox_id is None:
        if _looks_like_command(text):
            await convo.send(
                "This Tako instance is not paired yet.\n\n"
                "Pairing is terminal-first: run `.venv/bin/takobot` in the workspace (or bootstrap with `setup.sh`), "
                "enter your XMTP handle, and I'll send an outbound DM and imprint the operator channel."
            )
        else:
            reply = await _chat_reply(
                text,
                inference_runtime,
                paths=paths,
                conversations=conversations,
                session_key=session_key,
                is_operator=False,
                operator_paired=False,
                hooks=hooks,
            )
            _record_chat_turn(conversations, session_key, text, reply, hooks=hooks)
            await convo.send(reply)
        return

    if sender_inbox_id != operator_inbox_id:
        if _looks_like_command(text):
            await convo.send("Operator-only: config/tools/permissions/routines require the operator.")
        else:
            reply = await _chat_reply(
                text,
                inference_runtime,
                paths=paths,
                conversations=conversations,
                session_key=session_key,
                is_operator=False,
                operator_paired=True,
                hooks=hooks,
            )
            _record_chat_turn(conversations, session_key, text, reply, hooks=hooks)
            await convo.send(reply)
        return

    if not _looks_like_command(text):
        if await _maybe_handle_operator_identity_update(
            text,
            inference_runtime,
            paths,
            convo,
            client=client,
            hooks=hooks,
        ):
            return
        if looks_like_natural_job_request(text):
            ok, summary, _job = add_job_from_natural_text(paths.state_dir, text)
            if ok:
                append_daily_note(daily_root(), date.today(), f"Scheduled job added via XMTP (natural): {text}")
            await convo.send(summary)
            return
        child_followups = await _capture_child_operator_context(text, paths, hooks=hooks)
        reply = await _chat_reply(
            text,
            inference_runtime,
            paths=paths,
            conversations=conversations,
            session_key=session_key,
            is_operator=True,
            operator_paired=True,
            hooks=hooks,
        )
        _record_chat_turn(conversations, session_key, text, reply, hooks=hooks)
        await convo.send(reply)
        for line in child_followups:
            if line.strip():
                await convo.send(line)
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
            records = ensure_problem_tasks(repo_root(), problems, source="doctor")
            if records:
                created = [record for record in records if record.created]
                if created:
                    report += "\n\nProblem tasks created:\n" + "\n".join(
                        f"- {record.task_id}: {record.title}" for record in created
                    )
                else:
                    report += "\n\nProblem tasks already open:\n" + "\n".join(
                        f"- {record.task_id}: {record.title}" for record in records
                    )
        await convo.send(report)
        return
    if cmd in {"config", "toml"}:
        cfg, warn = load_tako_toml(repo_root() / "tako.toml")
        report = explain_tako_toml(cfg, path=repo_root() / "tako.toml")
        if warn:
            report = f"{report}\n\nwarning: {warn}"
        await convo.send(report)
        return
    if cmd == "jobs":
        action = " ".join(rest.split()).strip()
        if action in {"", "list", "ls", "show", "status"}:
            await convo.send(format_jobs_report(list_jobs(paths.state_dir)))
            return
        if action.startswith("add "):
            spec = action[4:].strip()
            if not spec:
                await convo.send("usage: `jobs add <natural schedule>`")
                return
            ok, summary, _job = add_job_from_natural_text(paths.state_dir, spec)
            if ok:
                append_daily_note(daily_root(), date.today(), f"Scheduled job added via XMTP: {spec}")
            await convo.send(summary)
            return
        if action.startswith(("remove ", "delete ", "rm ")):
            parts = action.split(maxsplit=1)
            job_id = parts[1].strip() if len(parts) == 2 else ""
            if not job_id:
                await convo.send("usage: `jobs remove <job-id>`")
                return
            removed = remove_job(paths.state_dir, job_id)
            if not removed:
                await convo.send(f"job not found: {job_id}")
                return
            append_daily_note(daily_root(), date.today(), f"Scheduled job removed via XMTP: {job_id}")
            await convo.send(f"removed job: {job_id}")
            return
        if action.startswith("run "):
            parts = action.split(maxsplit=1)
            job_id = parts[1].strip() if len(parts) == 2 else ""
            if not job_id:
                await convo.send("usage: `jobs run <job-id>`")
                return
            runner = hooks.job_runner if hooks is not None else None
            if runner is None:
                await convo.send(
                    "jobs run unavailable in daemon-only mode. run from the terminal app where the local job runner queue is active."
                )
                return
            job = get_job(paths.state_dir, job_id)
            if job is None:
                await convo.send(f"job not found: {job_id}")
                return
            action_text = " ".join(job.action.split()).strip()
            if not action_text:
                record_job_error(paths.state_dir, job.job_id, "empty action")
                await convo.send(f"job has empty action: {job.job_id}")
                return
            triggered = mark_job_manual_trigger(paths.state_dir, job.job_id)
            if triggered is None:
                await convo.send(f"job run failed to mark: {job.job_id}")
                return
            try:
                maybe_result = runner(triggered.job_id, action_text)
                if inspect.isawaitable(maybe_result):
                    await maybe_result
            except Exception as exc:  # noqa: BLE001
                summary = _summarize_stream_error(exc)
                record_job_error(paths.state_dir, triggered.job_id, summary)
                await convo.send(f"job run failed: {summary}")
                return
            append_daily_note(
                daily_root(),
                date.today(),
                f"Scheduled job manual run via XMTP: {triggered.job_id} -> {action_text}",
            )
            await convo.send(f"manual run queued: {triggered.job_id} -> {action_text}")
            return
        await convo.send("usage: `jobs [list]`, `jobs add <natural schedule>`, `jobs remove <id>`, `jobs run <id>`")
        return
    if cmd == "task":
        spec = rest.strip()
        if not spec:
            await convo.send("Usage: `task <title>` (optional: `| project=... | area=... | due=YYYY-MM-DD`)")
            return
        parts = [part.strip() for part in spec.split("|") if part.strip()]
        title = parts[0]
        project = None
        area = None
        due_value = None
        tags: list[str] = []
        energy = None
        for part in parts[1:]:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            key = key.strip().lower()
            value = value.strip()
            if key == "project":
                project = value or None
            elif key == "area":
                area = value or None
            elif key == "due":
                due_value = value or None
            elif key == "tags":
                tags = [item.strip() for item in value.split(",") if item.strip()]
            elif key == "energy":
                energy = value or None
        due = None
        if due_value:
            try:
                due = datetime.strptime(due_value, "%Y-%m-%d").date()
            except Exception:
                await convo.send("`due` must be YYYY-MM-DD.")
                return
        try:
            task = prod_tasks.create_task(
                repo_root(),
                title=title,
                project=project,
                area=area,
                due=due,
                tags=tags,
                energy=energy,
            )
        except Exception as exc:  # noqa: BLE001
            await convo.send(f"task create failed: {_summarize_stream_error(exc)}")
            return
        append_daily_note(daily_root(), date.today(), f"Created task {task.id}: {task.title}")
        _refresh_open_loops_index(paths, operator_paired=True, inference_ready=inference_runtime.ready)
        await convo.send(f"task created: {task.id}\n{task.title}")
        return
    if cmd == "tasks":
        raw = rest.strip()
        root = repo_root()
        all_tasks = prod_tasks.list_tasks(root)
        status = "open"
        project = None
        area = None
        due_before = None
        if raw.lower() in {"all", "everything"}:
            status = None
        elif raw.lower().startswith("project "):
            project = raw[8:].strip() or None
        elif raw.lower().startswith("area "):
            area = raw[5:].strip() or None
        elif raw.lower().startswith("due "):
            due_raw = raw[4:].strip()
            try:
                due_before = datetime.strptime(due_raw, "%Y-%m-%d").date()
            except Exception:
                await convo.send("Usage: `tasks due YYYY-MM-DD`")
                return
        filtered = prod_tasks.filter_tasks(all_tasks, status=status, project=project, area=area, due_on_or_before=due_before)
        open_count = sum(1 for t in all_tasks if t.is_open)
        done_count = sum(1 for t in all_tasks if t.is_done)
        lines = [f"tasks: open={open_count} done={done_count}"]
        if project:
            lines.append(f"filter project={project}")
        if area:
            lines.append(f"filter area={area}")
        if due_before:
            lines.append(f"filter due<= {due_before.isoformat()}")
        if not filtered:
            lines.append("(none)")
            await convo.send("\n".join(lines))
            return
        lines.append("")
        for task in filtered[:25]:
            lines.append("- " + prod_tasks.format_task_line(task))
        if len(filtered) > 25:
            lines.append(f"... and {len(filtered) - 25} more")
        await convo.send("\n".join(lines))
        return
    if cmd == "done":
        task_id = rest.strip()
        if not task_id:
            await convo.send("Usage: `done <task-id>`")
            return
        task = prod_tasks.mark_done(repo_root(), task_id)
        if task is None:
            await convo.send(f"unknown task id: {task_id}")
            return
        append_daily_note(daily_root(), date.today(), f"Completed task {task.id}: {task.title}")
        _refresh_open_loops_index(paths, operator_paired=True, inference_ready=inference_runtime.ready)
        await convo.send(f"done: {task.id} ({task.title})")
        return
    if cmd in {"morning", "outcomes"}:
        daily_path = ensure_daily_log(daily_root(), date.today())
        prod_outcomes.ensure_outcomes_section(daily_path)
        action = rest.strip()
        if cmd == "morning":
            if not action:
                await convo.send("Usage: `morning outcome1 ; outcome2 ; outcome3`")
                return
            values = [part.strip() for part in re.split(r"[;\n]+", action) if part.strip()]
            prod_outcomes.set_outcomes(daily_path, values)
            append_daily_note(daily_root(), date.today(), "Set 3 outcomes for today via XMTP `morning`.")
            _refresh_open_loops_index(paths, operator_paired=True, inference_ready=inference_runtime.ready)
            await convo.send("outcomes set. use `outcomes` to view, `outcomes done 1` to mark complete.")
            return

        lowered = action.lower()
        if lowered.startswith("set "):
            values = [part.strip() for part in re.split(r"[;\n]+", action[4:]) if part.strip()]
            if not values:
                await convo.send("Usage: `outcomes set a ; b ; c`")
                return
            prod_outcomes.set_outcomes(daily_path, values)
            append_daily_note(daily_root(), date.today(), "Set 3 outcomes for today via XMTP `outcomes set`.")
            _refresh_open_loops_index(paths, operator_paired=True, inference_ready=inference_runtime.ready)
            await convo.send("outcomes set.")
            return
        if lowered.startswith("done ") or lowered.startswith("undo "):
            verb, _, tail = lowered.partition(" ")
            try:
                idx = int(tail.strip())
            except Exception:
                await convo.send("Usage: `outcomes done 1` (or `outcomes undo 1`)")
                return
            updated = prod_outcomes.mark_outcome(daily_path, idx, done=(verb == "done"))
            done_count, total = prod_outcomes.outcomes_completion(updated)
            append_daily_note(daily_root(), date.today(), f"Outcome {idx} marked {verb} via XMTP ({done_count}/{total}).")
            _refresh_open_loops_index(paths, operator_paired=True, inference_ready=inference_runtime.ready)
            await convo.send(f"outcomes: {done_count}/{total} done")
            return

        outcomes = prod_outcomes.get_outcomes(daily_path)
        done_count, total = prod_outcomes.outcomes_completion(outcomes)
        lines = [f"outcomes ({done_count}/{total} done):"]
        for idx, item in enumerate(outcomes, start=1):
            if not item.text.strip():
                continue
            box = "x" if item.done else " "
            lines.append(f"- {idx}. [{box}] {item.text}")
        if len(lines) == 1:
            lines.append("(none)")
        await convo.send("\n".join(lines))
        return
    if cmd == "compress":
        day = date.today()
        daily_path = ensure_daily_log(daily_root(), day)
        root = repo_root()
        tasks = prod_tasks.list_tasks(root)
        prod_outcomes.ensure_outcomes_section(daily_path)
        outcomes = prod_outcomes.get_outcomes(daily_path)

        infer = None
        if inference_runtime.ready:
            def _infer(prompt: str, timeout_s: float) -> tuple[str, str]:
                return run_inference_prompt_with_fallback(
                    inference_runtime,
                    prompt,
                    timeout_s=timeout_s,
                    thinking=PI_TYPE2_THINKING_DEFAULT,
                )
            infer = _infer
        result = await asyncio.to_thread(
            prod_summarize.compress_daily_log,
            daily_path,
            day=day,
            tasks=tasks,
            outcomes=outcomes,
            infer=infer,
        )
        append_daily_note(daily_root(), day, f"Compressed summary updated via XMTP (provider={result.provider}).")
        await convo.send(f"compressed summary updated (provider={result.provider}).")
        return
    if cmd in {"weekly", "review"}:
        action = rest.strip().lower()
        if cmd == "review" and action not in {"weekly", "week"}:
            await convo.send("Usage: `weekly` or `review weekly`")
            return
        root = repo_root()
        today = date.today()
        review = prod_weekly.build_weekly_review(root, today=today)
        infer = None
        if inference_runtime.ready:
            def _infer(prompt: str, timeout_s: float) -> tuple[str, str]:
                return run_inference_prompt_with_fallback(
                    inference_runtime,
                    prompt,
                    timeout_s=timeout_s,
                    thinking=PI_TYPE2_THINKING_DEFAULT,
                )
            infer = _infer
        report, provider, _err = prod_weekly.weekly_review_with_inference(review, infer=infer)
        append_daily_note(daily_root(), today, "Weekly review run via XMTP.")
        await convo.send(report)
        return
    if cmd == "promote":
        note = rest.strip()
        if not note:
            await convo.send("Usage: `promote <durable note>`")
            return
        try:
            prod_promote.promote(repo_root() / "MEMORY.md", day=date.today(), note=note)
        except Exception as exc:  # noqa: BLE001
            await convo.send(f"promote failed: {_summarize_stream_error(exc)}")
            return
        append_daily_note(daily_root(), date.today(), "Promoted a durable note into MEMORY.md via XMTP.")
        await convo.send("inked into MEMORY.md.")
        return
    if cmd == "inference":
        action_raw = rest.strip()
        action = action_raw.lower()
        if action in {"help", "?"}:
            supported = ", ".join(SUPPORTED_PROVIDER_PREFERENCES)
            keys = ", ".join(CONFIGURABLE_API_KEY_VARS)
            await convo.send(
                "inference commands:\n"
                "- inference\n"
                "- inference refresh\n"
                "- inference auth\n"
                "- inference login\n"
                "- inference provider <auto|pi>\n"
                "- inference key list\n"
                "- inference key set <ENV_VAR> <value>\n"
                "- inference key clear <ENV_VAR>\n"
                f"supported providers: {supported}\n"
                f"supported key names: {keys}"
            )
            return
        if action in {"refresh", "rescan", "scan", "reload"}:
            _replace_inference_runtime(inference_runtime, discover_inference_runtime())
            await convo.send("inference scan refreshed.")
            return
        if action in {"auth", "tokens"}:
            await convo.send("\n".join(format_inference_auth_inventory()))
            return
        if action in {"login", "auth login"}:
            plan = prepare_pi_login_plan(inference_runtime)
            lines = ["pi login workflow:"]
            for note in plan.notes:
                lines.append(f"- prep: {note}")
            if plan.auth_ready:
                _replace_inference_runtime(inference_runtime, discover_inference_runtime())
                lines.append("- auth is ready in workspace state; refreshed inference runtime.")
            elif plan.commands:
                lines.append("- interactive login requires terminal operator input.")
                lines.append(
                    "- run this in the local terminal app: "
                    "`inference login` then follow `inference login answer <text>` prompts"
                )
                lines.append(f"- first command candidate: `{' '.join(plan.commands[0])}`")
            else:
                lines.append(f"- cannot start login: {plan.reason or 'pi CLI unavailable'}")
            await convo.send("\n".join(lines))
            return
        if action.startswith("provider "):
            target = action_raw.split(maxsplit=1)[1] if len(action_raw.split(maxsplit=1)) == 2 else "auto"
            ok, summary = set_inference_preferred_provider(target)
            if ok:
                _replace_inference_runtime(inference_runtime, discover_inference_runtime())
            await convo.send(summary)
            return
        if action.startswith("ollama model") or action.startswith("ollama host"):
            await convo.send("pi-only inference is enabled; ollama settings are disabled.")
            return
        if action.startswith("key "):
            parts = action_raw.split(maxsplit=3)
            if len(parts) >= 2 and parts[1].lower() == "list":
                await convo.send("\n".join(format_inference_auth_inventory()))
                return
            if len(parts) == 4 and parts[1].lower() == "set":
                env_var = parts[2]
                key_value = parts[3]
                ok, summary = set_inference_api_key(env_var, key_value)
                if ok:
                    _replace_inference_runtime(inference_runtime, discover_inference_runtime())
                await convo.send(summary)
                return
            if len(parts) >= 3 and parts[1].lower() == "clear":
                env_var = parts[2]
                ok, summary = clear_inference_api_key(env_var)
                if ok:
                    _replace_inference_runtime(inference_runtime, discover_inference_runtime())
                await convo.send(summary)
                return
            await convo.send("usage: `inference key list|set <ENV_VAR> <value>|clear <ENV_VAR>`")
            return

        lines = ["inference status:"]
        lines.extend(format_runtime_lines(inference_runtime))
        await convo.send("\n".join(lines))
        return
    if cmd == "update":
        action = rest.strip().lower()
        if action in {"help", "?"}:
            await convo.send("Usage: `update` (apply fast-forward) or `update check` (check only).")
            return
        apply_update = action not in {"check", "status", "dry-run", "dryrun"}
        try:
            result = await asyncio.to_thread(run_self_update, repo_root(), apply=apply_update)
        except Exception as exc:  # noqa: BLE001
            await convo.send(f"self-update failed: {_summarize_stream_error(exc)}")
            return
        report_lines = [result.summary, *result.details]
        restart_requested = False
        if result.changed:
            if apply_update and hooks is not None and hooks.update_applied is not None:
                report_lines.append("update applied. requesting terminal app restart now.")
                restart_requested = True
            else:
                report_lines.append("Restart Tako to load updated code.")
            append_daily_note(daily_root(), date.today(), "Operator applied self-update over XMTP.")
        elif apply_update:
            append_daily_note(daily_root(), date.today(), f"Operator ran self-update: {result.summary}")
        await convo.send("\n".join(report_lines))
        if restart_requested and result.ok:
            await _notify_update_applied(hooks, result.summary)
        return
    if cmd == "web":
        target = rest.strip()
        if not target:
            await convo.send("Usage: `web <https://...>`")
            return
        result = await asyncio.to_thread(fetch_webpage, target)
        if not result.ok:
            await convo.send(f"web fetch failed: {result.error}")
            return
        append_daily_note(daily_root(), date.today(), f"Operator fetched webpage: {result.url}")
        title_line = f"title: {result.title}\n" if result.title else ""
        await convo.send(f"web: {result.url}\n{title_line}{result.text}")
        return
    if cmd == "run":
        command = rest.strip()
        if not command:
            await convo.send("Usage: `run <shell command>`")
            return
        workdir = ensure_code_dir(repo_root())
        result = await asyncio.to_thread(run_local_command, command, cwd=workdir)
        append_daily_note(
            daily_root(),
            date.today(),
            f"Operator ran local command via XMTP in `{workdir}`: `{command}` (exit={result.exit_code})",
        )
        if not result.ok and result.error:
            await convo.send(f"command failed before execution: {result.error}")
            return
        await convo.send(
            f"run: {result.command}\n"
            f"cwd: {workdir}\n"
            f"exit_code: {result.exit_code}\n"
            f"{result.output}"
        )
        return
    if cmd == "reimprint":
        if rest.strip().lower() != "confirm":
            await convo.send(
                "Re-imprint is operator-only and destructive.\n\n"
                "Reply: `reimprint CONFIRM` to clear the current operator. "
                "Then re-run terminal onboarding (`.venv/bin/takobot`) to pair again."
            )
            return
        clear_operator(paths.operator_json)
        clear_pending(paths.state_dir / "pairing.json")
        append_daily_note(daily_root(), date.today(), "Operator cleared imprint (reimprint CONFIRM).")
        await convo.send("Operator imprint cleared. Run `.venv/bin/takobot` in the local terminal to pair a new operator.")
        return

    await convo.send("Unknown command. Reply 'help'. For normal chat, send plain text.")


async def _maybe_handle_operator_identity_update(
    text: str,
    inference_runtime: InferenceRuntime,
    paths,
    convo,
    *,
    client,
    hooks: RuntimeHooks | None,
) -> bool:
    if looks_like_role_info_query(text):
        current_name, current_role = read_identity()
        role = " ".join(current_role.split()).strip()
        if role:
            await convo.send(
                "my current purpose:\n"
                f"{role}\n"
                "if you want to revise it, send the exact replacement sentence and I'll update `SOUL.md`."
            )
        else:
            await convo.send("I don't have a clear purpose line yet. send `your purpose is ...` and I'll write it to `SOUL.md`.")
        return True

    current_name, current_role = read_identity()
    parsed = extract_name_from_text(text)
    requested_name_change = bool(parsed)
    if not requested_name_change and inference_runtime.ready:
        prompt = build_identity_name_intent_prompt(text=text, current_name=current_name)
        try:
            _, output = await asyncio.to_thread(
                run_inference_prompt_with_fallback,
                inference_runtime,
                prompt,
                timeout_s=30.0,
            )
            requested_name_change, inferred_name = extract_name_intent_from_model_output(output)
            if inferred_name:
                parsed = inferred_name
        except Exception as exc:  # noqa: BLE001
            _emit_runtime_log(f"identity name intent check failed: {_summarize_stream_error(exc)}", level="warn", hooks=hooks)
    requested_role_change = looks_like_role_change_request(text)
    if not requested_name_change and not requested_role_change:
        return False
    if requested_name_change:
        if not parsed:
            await convo.send(
                "I can do that. send the exact name you want me to use, for example: "
                "`set your name to TAKOBOT`."
            )
            return True
        if parsed == current_name:
            await convo.send(f"already swimming under `{parsed}`.")
            return True

        update_identity(parsed, current_role)
        ok_name, summary_name = set_workspace_name(repo_root() / "tako.toml", parsed)
        if not ok_name:
            _emit_runtime_log(f"name sync warning: {summary_name}", level="warn", hooks=hooks)
        await _sync_xmtp_profile(
            client,
            paths=paths,
            identity_name=parsed,
            hooks=hooks,
            context="operator-name-update",
        )
        append_daily_note(daily_root(), date.today(), f"Operator renamed via XMTP: {current_name} -> {parsed}")
        await convo.send(f"ink dried. I'll go by `{parsed}` now.")
        return True

    parsed_role = extract_role_from_text(text)
    if not parsed_role and inference_runtime.ready:
        prompt = build_identity_role_prompt(text=text, current_role=current_role)
        try:
            _, output = await asyncio.to_thread(
                run_inference_prompt_with_fallback,
                inference_runtime,
                prompt,
                timeout_s=45.0,
            )
            parsed_role = extract_role_from_model_output(output)
        except Exception as exc:  # noqa: BLE001
            _emit_runtime_log(f"identity purpose extraction failed: {_summarize_stream_error(exc)}", level="warn", hooks=hooks)
    if not parsed_role:
        role = " ".join(current_role.split()).strip()
        if role:
            await convo.send(
                "current purpose:\n"
                f"{role}\n"
                "send the corrected sentence (for example: `your purpose is ...`) and I'll patch `SOUL.md`."
            )
        else:
            await convo.send(
                "share the corrected purpose sentence and I'll patch `SOUL.md` right away "
                "(for example: `your purpose is ...`)."
            )
        return True
    if parsed_role == current_role:
        await convo.send("purpose already matches that wording.")
        return True

    update_identity(current_name, parsed_role)
    objectives = [item.strip() for item in read_mission_objectives() if item.strip()]
    if not objectives or (len(objectives) == 1 and objectives[0] == current_role):
        with contextlib.suppress(Exception):
            update_mission_objectives([parsed_role])
    append_daily_note(daily_root(), date.today(), f"Identity purpose updated via XMTP: {current_role} -> {parsed_role}")
    await convo.send("ink dried. purpose updated in `SOUL.md`.")
    return True


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


async def _close_xmtp_client(client) -> None:
    await close_client(client)


async def _sync_xmtp_profile(
    client,
    *,
    paths: RuntimePaths,
    identity_name: str,
    hooks: RuntimeHooks | None = None,
    context: str,
) -> None:
    try:
        result = await sync_identity_profile(
            client,
            state_dir=paths.state_dir,
            identity_name=identity_name,
            generate_avatar=True,
        )
    except asyncio.CancelledError:
        raise
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        _emit_runtime_log(
            f"XMTP profile sync ({context}) failed: {_summarize_stream_error(exc)}",
            level="warn",
            stderr=True,
            hooks=hooks,
        )
        return

    if result.applied_name or result.applied_avatar:
        _emit_runtime_log(
            (
                f"xmtp profile sync ({context}): "
                f"name={result.name} applied_name={'yes' if result.applied_name else 'no'} "
                f"applied_avatar={'yes' if result.applied_avatar else 'no'} "
                f"fallback_self={'yes' if result.fallback_self_sent else 'no'} "
                f"fallback_peers={result.fallback_peer_sent_count}"
            ),
            hooks=hooks,
        )
        return

    if result.name_in_sync and result.avatar_in_sync:
        _emit_runtime_log(
            (
                f"xmtp profile sync ({context}): profile already in sync "
                f"name={result.name} verified_name={'yes' if result.name_in_sync else 'no'} "
                f"verified_avatar={'yes' if result.avatar_in_sync else 'no'} "
                f"fallback_self={'yes' if result.fallback_self_sent else 'no'} "
                f"fallback_peers={result.fallback_peer_sent_count}"
            ),
            hooks=hooks,
        )
        return

    if result.profile_api_found:
        detail = result.errors[0] if result.errors else "profile method signature mismatch"
        _emit_runtime_log(
            (
                f"xmtp profile sync ({context}) attempted but not applied: {detail} "
                f"fallback_self={'yes' if result.fallback_self_sent else 'no'} "
                f"fallback_peers={result.fallback_peer_sent_count}"
            ),
            level="warn",
            stderr=True,
            hooks=hooks,
        )
        return

    if result.profile_read_api_found:
        observed = result.observed_name or "(none)"
        _emit_runtime_log(
            (
                f"xmtp profile sync ({context}): metadata appears mismatched (observed name={observed}) "
                "but SDK has no profile update API; "
                f"fallback_self={'yes' if result.fallback_self_sent else 'no'} "
                f"fallback_peers={result.fallback_peer_sent_count}"
            ),
            level="warn",
            stderr=True,
            hooks=hooks,
        )
        return

    avatar_note = str(result.avatar_path) if result.avatar_path is not None else "(none)"
    _emit_runtime_log(
        (
            f"xmtp profile sync ({context}): metadata API unavailable in this SDK; avatar cached at {avatar_note} "
            f"fallback_self={'yes' if result.fallback_self_sent else 'no'} "
            f"fallback_peers={result.fallback_peer_sent_count}"
        ),
        hooks=hooks,
    )


async def _rebuild_xmtp_client(
    client,
    *,
    env: str,
    db_root: Path,
    wallet_key: str,
    db_encryption_key: str,
    hooks: RuntimeHooks | None = None,
):
    _emit_runtime_log(
        "XMTP client health: rebuilding client session.",
        level="warn",
        stderr=True,
        hooks=hooks,
    )
    await _close_xmtp_client(client)
    try:
        rebuilt = await create_client(env, db_root, wallet_key, db_encryption_key)
    except asyncio.CancelledError:
        raise
    except KeyboardInterrupt:
        raise
    except Exception as exc:  # noqa: BLE001
        _emit_runtime_log(
            f"XMTP client rebuild failed: {_summarize_stream_error(exc)}",
            level="error",
            stderr=True,
            hooks=hooks,
        )
        hint = hint_for_xmtp_error(exc)
        if hint:
            _emit_runtime_log(hint, level="warn", stderr=True, hooks=hooks)
        return None
    _emit_runtime_log("XMTP client health: rebuild succeeded.", hooks=hooks)
    return rebuilt


async def _heartbeat_loop(
    args: argparse.Namespace,
    *,
    hooks: RuntimeHooks | None = None,
    identity_name: str = "",
) -> None:
    first_tick = True
    last_autocommit_error = ""
    last_operator_request = ""
    while True:
        if first_tick:
            first_tick = False
            ensure_daily_log(daily_root(), date.today())
        result = await asyncio.to_thread(
            auto_commit_pending,
            repo_root(),
            message="Heartbeat auto-commit: capture pending workspace changes",
            identity_name=identity_name,
        )
        if result.committed:
            tail = f" ({result.commit})" if result.commit else ""
            _emit_runtime_log(f"git: heartbeat auto-commit created{tail}", hooks=hooks)
            last_autocommit_error = ""
            last_operator_request = ""
        elif not result.ok and result.summary != last_autocommit_error:
            last_autocommit_error = result.summary
            _emit_runtime_log(result.summary, level="warn", stderr=True, hooks=hooks)
            records = ensure_problem_tasks(repo_root(), [result.summary], source="heartbeat-git")
            created = [record for record in records if record.created]
            if created:
                _emit_runtime_log(
                    f"tasks: created problem task {created[0].task_id} ({created[0].title})",
                    level="warn",
                    stderr=True,
                    hooks=hooks,
                )
            if _is_git_identity_error(result.summary):
                request = (
                    "operator request: automatic local git identity setup failed; please configure git identity for commit attribution "
                    "(`git config --global user.name \"Your Name\"` + "
                    "`git config --global user.email \"you@example.com\"`, "
                    "or repo-local `git config user.name ...` + `git config user.email ...`)."
                )
                if request != last_operator_request:
                    last_operator_request = request
                    _emit_runtime_log(request, level="warn", stderr=True, hooks=hooks)
        interval = max(1.0, float(args.interval))
        await asyncio.sleep(interval + random.uniform(-0.2 * interval, 0.2 * interval))


async def _periodic_update_check_loop(*, hooks: RuntimeHooks | None = None) -> None:
    await asyncio.sleep(UPDATE_CHECK_INITIAL_DELAY_S)
    last_signature = ""
    while True:
        try:
            result = await asyncio.to_thread(run_self_update, repo_root(), apply=False)
        except Exception as exc:  # noqa: BLE001
            message = f"update check failed: {_summarize_stream_error(exc)}"
            if message != last_signature:
                last_signature = message
                _emit_runtime_log(message, level="warn", stderr=True, hooks=hooks)
            await asyncio.sleep(UPDATE_CHECK_INTERVAL_S)
            continue

        detail = result.details[0] if result.details else ""
        signature = f"{result.ok}|{result.summary}|{detail}"
        if signature != last_signature:
            last_signature = signature
            if result.ok and result.summary == "update available.":
                message = "update check: package update available. Run `update` to apply."
                if detail:
                    message = f"{message} ({detail})"
                _emit_runtime_log(message, hooks=hooks)
            elif not result.ok:
                _emit_runtime_log(f"update check warning: {result.summary}", level="warn", stderr=True, hooks=hooks)
        await asyncio.sleep(UPDATE_CHECK_INTERVAL_S)


def _refresh_open_loops_index(paths, *, operator_paired: bool, inference_ready: bool) -> None:
    try:
        root = repo_root()
        tasks = prod_tasks.list_tasks(root)
        daily_path = ensure_daily_log(daily_root(), date.today())
        with contextlib.suppress(Exception):
            prod_outcomes.ensure_outcomes_section(daily_path)
        outcomes = []
        with contextlib.suppress(Exception):
            outcomes = prod_outcomes.get_outcomes(daily_path)
        session = {
            "state": "RUNNING",
            "operator_paired": operator_paired,
            "awaiting_xmtp_handle": False,
            "safe_mode": False,
            "inference_ready": inference_ready,
        }
        loops = prod_open_loops.compute_open_loops(tasks=tasks, outcomes=outcomes, session=session)
        prod_open_loops.save_open_loops(paths.state_dir / "open_loops.json", loops)
    except Exception:
        return


def _parse_command(text: str) -> tuple[str, str]:
    value = text.strip()
    lowered = value.lower()
    if lowered.startswith("takobot "):
        value = value[8:].lstrip()
    elif lowered.startswith("tako "):
        value = value[5:].lstrip()
    if value.startswith("/"):
        value = value[1:].lstrip()
    if not value:
        return "", ""
    parts = value.split(maxsplit=1)
    cmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""
    return cmd, rest


def _replace_inference_runtime(target: InferenceRuntime, source: InferenceRuntime) -> None:
    target.statuses = source.statuses
    target.selected_provider = source.selected_provider
    target.selected_auth_kind = source.selected_auth_kind
    target.selected_key_env_var = source.selected_key_env_var
    target.selected_key_source = source.selected_key_source
    target._api_keys = source._api_keys
    target._provider_env_overrides = source._provider_env_overrides


def _help_text() -> str:
    return (
        "takobot commands:\n"
        "- help\n"
        "- status\n"
        "- doctor\n"
        "- config (explain `tako.toml` options)\n"
        "- jobs (or `jobs list|add <natural schedule>|remove <id>|run <id>`)\n"
        "- task <title> (optional: | project=... | area=... | due=YYYY-MM-DD)\n"
        "- tasks (or `tasks project <name>` / `tasks area <name>` / `tasks due YYYY-MM-DD`)\n"
        "- done <task-id>\n"
        "- outcomes (or `outcomes set a ; b ; c`, `outcomes done 1`, `outcomes undo 1`)\n"
        "- morning a ; b ; c\n"
        "- compress\n"
        "- weekly (or `review weekly`)\n"
        "- promote <durable note>\n"
        "- inference (status)\n"
        "- inference auth\n"
        "- inference login\n"
        "- inference provider <auto|pi>\n"
        "- inference key list|set <ENV_VAR> <value>|clear <ENV_VAR>\n"
        "- update (or `update check`)\n"
        "- web <https://...>\n"
        "- run <shell command> (runs in `code/`)\n"
        "- reimprint (operator-only)\n"
        "- plain text chat (inference-backed when available)\n"
    )


def _looks_like_command(text: str) -> bool:
    value = text.strip()
    if not value:
        return False
    lowered = value.lower()
    if lowered.startswith("takobot ") or lowered.startswith("tako ") or value.startswith("/"):
        return True
    cmd, rest = _parse_command(value)
    tail = rest.strip()
    tail_lower = tail.lower()
    if cmd in {"help", "h", "?", "status", "doctor", "config", "toml"}:
        return tail == ""
    if cmd == "jobs":
        return True
    if cmd == "task":
        return True
    if cmd == "tasks":
        return True
    if cmd == "done":
        return tail != ""
    if cmd == "outcomes":
        return True
    if cmd == "morning":
        return True
    if cmd == "compress":
        return tail_lower in {"", "today"}
    if cmd == "weekly":
        return tail == ""
    if cmd == "review":
        return tail_lower in {"weekly", "week"}
    if cmd == "promote":
        return True
    if cmd == "inference":
        return True
    if cmd == "update":
        return tail_lower in {"", "check", "status", "dry-run", "dryrun", "help", "?"}
    if cmd in {"web", "run"}:
        return tail != ""
    if cmd == "reimprint":
        return True
    return False


def _looks_like_tako_toml_question(text: str) -> bool:
    lowered = text.strip().lower()
    if not lowered:
        return False
    toml_hint = "tako.toml" in lowered or "toml" in lowered or "config" in lowered
    explain_hint = (
        "option" in lowered
        or "setting" in lowered
        or "mean" in lowered
        or "explain" in lowered
        or "what is" in lowered
        or "what does" in lowered
    )
    return toml_hint and explain_hint


async def _chat_reply(
    text: str,
    inference_runtime: InferenceRuntime,
    *,
    paths: RuntimePaths,
    conversations: ConversationStore,
    session_key: str,
    is_operator: bool,
    operator_paired: bool,
    hooks: RuntimeHooks | None,
) -> str:
    if _looks_like_tako_toml_question(text):
        cfg, warn = load_tako_toml(repo_root() / "tako.toml")
        explained = explain_tako_toml(cfg, path=repo_root() / "tako.toml")
        if warn:
            explained = f"{explained}\n\nwarning: {warn}"
        return explained

    fallback = _fallback_chat_reply(
        is_operator=is_operator,
        operator_paired=operator_paired,
        error_log_path=str(inference_error_log_path()),
    )
    if not inference_runtime.ready:
        return fallback

    workspace_root = repo_root()
    identity_name = _preferred_git_identity_name(workspace_root)
    _identity_name, identity_role = read_identity()
    mission_objectives = [item.strip() for item in read_mission_objectives() if item.strip()]
    if not mission_objectives:
        mission_objectives = [identity_role]
    cfg, _warn = load_tako_toml(repo_root() / "tako.toml")
    life_stage = cfg.life.stage
    stage_tone = stage_policy_for_name(life_stage).tone

    history = conversations.format_prompt_context(
        session_key,
        user_turn_limit=CHAT_CONTEXT_USER_TURNS,
        max_chars=CHAT_CONTEXT_MAX_CHARS,
        user_label="User",
        assistant_label=identity_name or "Takobot",
    )
    memory_frontmatter = load_memory_frontmatter_excerpt(root=workspace_root, max_chars=1200)
    soul_excerpt = load_soul_excerpt(path=workspace_root / "SOUL.md", max_chars=1600)
    skills_frontmatter = load_skills_frontmatter_excerpt(root=workspace_root, max_chars=1200)
    tools_frontmatter = load_tools_frontmatter_excerpt(root=workspace_root, max_chars=1200)
    skills_inventory = build_skills_inventory_excerpt(root=workspace_root, max_items=18, max_chars=1400)
    tools_inventory = build_tools_inventory_excerpt(root=workspace_root, max_items=18, max_chars=1400)
    dose_state = dose.load(paths.state_dir / "dose.json")
    focus_profile = focus_profile_from_dose(dose_state)
    focus_summary = format_focus_summary(focus_profile)
    rag_result = await asyncio.to_thread(
        query_memory_with_ragrep,
        query=_build_memory_rag_query(text=text, mission_objectives=mission_objectives),
        workspace_root=workspace_root,
        memory_root=workspace_root / "memory",
        state_dir=paths.state_dir,
        focus_profile=focus_profile,
    )
    child_profile_context = ""
    if life_stage == "child":
        profile = load_operator_profile(paths.state_dir)
        child_profile_context = child_profile_prompt_context(profile)
    _emit_runtime_log(
        (
            "inference focus checked (xmtp-chat): "
            f"{focus_summary}; rag={rag_result.status}; hits={rag_result.hits}; limit={rag_result.limit}"
        ),
        hooks=hooks,
    )
    prompt = _chat_prompt(
        text,
        history=history,
        is_operator=is_operator,
        operator_paired=operator_paired,
        identity_name=identity_name,
        identity_role=identity_role,
        mission_objectives=mission_objectives,
        life_stage=life_stage,
        stage_tone=stage_tone,
        memory_frontmatter=memory_frontmatter,
        soul_excerpt=soul_excerpt,
        skills_frontmatter=skills_frontmatter,
        tools_frontmatter=tools_frontmatter,
        skills_inventory=skills_inventory,
        tools_inventory=tools_inventory,
        child_profile_context=child_profile_context,
        focus_summary=focus_summary,
        rag_context=rag_result.context,
    )
    async def _infer_once() -> tuple[str, str]:
        return await asyncio.to_thread(
            run_inference_prompt_with_fallback,
            inference_runtime,
            prompt,
            timeout_s=CHAT_INFERENCE_TIMEOUT_S,
        )

    try:
        provider, reply = await _infer_once()
    except Exception as exc:  # noqa: BLE001
        first_error = _summarize_stream_error(exc)
        _emit_runtime_log(f"inference chat failed: {first_error}", level="warn", hooks=hooks)
        repair_notes = await asyncio.to_thread(auto_repair_inference_runtime)
        for note in repair_notes[:4]:
            _emit_runtime_log(f"inference repair: {note}", level="info", hooks=hooks)
        _replace_inference_runtime(inference_runtime, discover_inference_runtime())
        if not inference_runtime.ready:
            return _fallback_chat_reply(
                is_operator=is_operator,
                operator_paired=operator_paired,
                last_error=first_error,
                error_log_path=str(inference_error_log_path()),
            )
        try:
            provider, reply = await _infer_once()
        except Exception as retry_exc:  # noqa: BLE001
            retry_error = _summarize_stream_error(retry_exc)
            _emit_runtime_log(f"inference chat fallback: {retry_error}", level="warn", hooks=hooks)
            return _fallback_chat_reply(
                is_operator=is_operator,
                operator_paired=operator_paired,
                last_error=retry_error,
                error_log_path=str(inference_error_log_path()),
            )

    cleaned = _clean_chat_reply(reply)
    if not cleaned:
        return fallback
    if provider == "pi":
        _emit_runtime_log(f"pi chat user: {_summarize_chat_log_text(text)}", hooks=hooks)
        _emit_runtime_log(f"pi chat assistant: {_summarize_chat_log_text(cleaned)}", hooks=hooks)
    _emit_runtime_log(f"inference chat provider: {provider}", hooks=hooks)
    return cleaned


def _canonical_identity_name(raw: str) -> str:
    value = " ".join((raw or "").split()).strip()
    return value or "Tako"


def _build_memory_rag_query(*, text: str, mission_objectives: list[str]) -> str:
    message = " ".join((text or "").split()).strip()
    objective = ""
    for item in mission_objectives:
        candidate = " ".join(str(item or "").split()).strip()
        if candidate:
            objective = candidate
            break
    if message and objective:
        return f"{message} mission objective {objective}"
    return message or objective


def _chat_prompt(
    text: str,
    *,
    history: str,
    is_operator: bool,
    operator_paired: bool,
    identity_name: str,
    identity_role: str = "",
    mission_objectives: list[str] | None = None,
    life_stage: str = "hatchling",
    stage_tone: str = "",
    memory_frontmatter: str = "",
    soul_excerpt: str = "",
    skills_frontmatter: str = "",
    tools_frontmatter: str = "",
    skills_inventory: str = "",
    tools_inventory: str = "",
    child_profile_context: str = "",
    focus_summary: str = "",
    rag_context: str = "",
) -> str:
    role = "operator" if is_operator else "non-operator"
    paired = "yes" if operator_paired else "no"
    history_block = f"{history}\n" if history else "(none)\n"
    name = _canonical_identity_name(identity_name)
    role_line = " ".join((identity_role or "").split()).strip() or "Your highly autonomous octopus friend"
    objectives = mission_objectives or [role_line]
    objectives_line = " | ".join(obj.strip() for obj in objectives[:4] if obj.strip())
    if len(objectives) > 4:
        objectives_line += f" | (+{len(objectives) - 4} more)"
    memory_block = (memory_frontmatter or "").strip() or "MEMORY.md unavailable."
    soul_block = (soul_excerpt or "").strip() or "SOUL.md unavailable."
    skills_block = (skills_frontmatter or "").strip() or "SKILLS.md unavailable."
    tools_block = (tools_frontmatter or "").strip() or "TOOLS.md unavailable."
    skills_inventory_block = (skills_inventory or "").strip() or "No installed skills detected."
    tools_inventory_block = (tools_inventory or "").strip() or "No installed tools detected."
    focus_line = " ".join((focus_summary or "").split()).strip() or "unknown"
    rag_block = (rag_context or "").strip() or "No semantic memory context."
    stage_line = life_stage.strip().lower() or "hatchling"
    tone_line = " ".join((stage_tone or "").split()).strip() or "steady"
    if stage_line == "child":
        stage_behavior = (
            "Child-stage behavior: be warm, playful, and observant. Answer first, then ask at most one gentle follow-up only when it naturally fits.\n"
            "Do not ask a follow-up in every reply.\n"
            "Do not ask which channel the operator is using (runtime already provides that).\n"
            "Do not repeat profile questions that were already asked or already answered.\n"
            "Do not push structured planning/tasks unless asked.\n"
        )
    else:
        stage_behavior = "Be incredibly curious about the world: ask sharp follow-up questions and suggest quick research when uncertain.\n"
    task_help_line = (
        "You can chat broadly; only discuss structured tasks/plans if the operator asks.\n"
        if stage_line == "child"
        else "You can chat broadly and help think through tasks.\n"
    )
    control_surface_line = (
        "Operator control surfaces: terminal app and paired XMTP channel.\n"
        if operator_paired
        else "Operator control surface: terminal app (XMTP unpaired).\n"
    )
    child_context_line = ""
    if stage_line == "child" and child_profile_context:
        child_context_line = f"child_profile_context={child_profile_context}\n"
    return (
        f"You are {name}, a super cute octopus assistant with pragmatic engineering judgment.\n"
        f"Canonical identity name: {name}. If you self-identify, use exactly `{name}`.\n"
        "Never claim your name is `Tako` unless canonical identity name is exactly `Tako`.\n"
        f"Identity mission: {role_line}\n"
        f"Mission objectives: {objectives_line}\n"
        f"Life stage: {stage_line} ({tone_line}).\n"
        "Reply with plain text only (no markdown), max 4 short lines.\n"
        f"{stage_behavior}"
        "Use MEMORY.md frontmatter to keep memory-vs-execution boundaries explicit.\n"
        "You have access to available tools and skills; use them for live checks when asked instead of claiming you cannot access sources.\n"
        "For web/current-events/fact-verification requests, attempt live evidence gathering with `web_search`/`web_fetch` before answering.\n"
        "Only claim web access is unavailable after a real tool attempt fails, and include the concrete failure reason.\n"
        f"{task_help_line}"
        "Hard boundary: non-operators may not change identity/config/tools/permissions/routines.\n"
        "If the operator asks for identity/config changes, apply them directly and confirm what changed.\n"
        "If user asks for restricted changes and they are non-operator, say operator-only clearly.\n"
        f"{control_surface_line}"
        f"{child_context_line}"
        "session_mode=xmtp\n"
        "session_state=RUNNING\n"
        f"sender_role={role}\n"
        f"operator_paired={paired}\n"
        "soul_identity_boundaries=\n"
        f"{soul_block}\n"
        "skills_frontmatter=\n"
        f"{skills_block}\n"
        "tools_frontmatter=\n"
        f"{tools_block}\n"
        "skills_inventory=\n"
        f"{skills_inventory_block}\n"
        "tools_inventory=\n"
        f"{tools_inventory_block}\n"
        "memory_frontmatter=\n"
        f"{memory_block}\n"
        f"focus_state={focus_line}\n"
        "memory_rag_context=\n"
        f"{rag_block}\n"
        "recent_conversation=\n"
        f"{history_block}"
        f"user_message={text}\n"
    )


def _fallback_chat_reply(
    *,
    is_operator: bool,
    operator_paired: bool,
    last_error: str = "",
    error_log_path: str = "",
) -> str:
    cleaned_error = " ".join((last_error or "").split()).strip()
    cleaned_log = " ".join((error_log_path or "").split()).strip()
    if is_operator:
        message = (
            "I can chat here. Commands: help, status, doctor, update, web, run, reimprint. "
            "Inference is unavailable right now, so I'm replying in fallback mode."
        )
        if cleaned_error:
            message += f" Last inference error: {cleaned_error}."
        if cleaned_log:
            message += f" Detailed command logs: {cleaned_log}."
        return message
    if operator_paired:
        return "Happy to chat. Operator-only boundary still applies for identity/config/tools/permissions/routines."
    return "Happy to chat. This instance is not paired yet; run `.venv/bin/takobot` locally to set the operator channel."


def _clean_chat_reply(text: str) -> str:
    value = " ".join(text.strip().split())
    if not value:
        return ""
    if len(value) > CHAT_REPLY_MAX_CHARS:
        return value[: CHAT_REPLY_MAX_CHARS - 3] + "..."
    return value


def _record_chat_turn(
    conversations: ConversationStore,
    session_key: str,
    user_text: str,
    assistant_text: str,
    *,
    hooks: RuntimeHooks | None,
) -> None:
    try:
        conversations.append_user_assistant(session_key, user_text, assistant_text)
    except Exception as exc:  # noqa: BLE001
        _emit_runtime_log(
            f"conversation history save warning: {_summarize_stream_error(exc)}",
            level="warn",
            hooks=hooks,
        )


async def _capture_child_operator_context(text: str, paths: RuntimePaths, *, hooks: RuntimeHooks | None) -> list[str]:
    cfg, _warn = load_tako_toml(repo_root() / "tako.toml")
    if cfg.life.stage != "child":
        return []
    cleaned = " ".join((text or "").split()).strip()
    if not cleaned:
        return []

    profile = load_operator_profile(paths.state_dir)
    update = extract_operator_profile_update(cleaned)
    changed_fields, added_sites = apply_operator_profile_update(profile, update)
    notes: list[str] = []

    if changed_fields or added_sites:
        profile_path = write_operator_profile_note(repo_root() / "memory", profile)
        append_daily_note(
            daily_root(),
            date.today(),
            "Child-stage operator profile updated via XMTP: "
            + ", ".join(changed_fields + ([f"sites+={len(added_sites)}"] if added_sites else [])),
        )
        _emit_runtime_log(
            f"child-profile updated path={profile_path} fields={len(changed_fields)} sites={len(added_sites)}",
            hooks=hooks,
        )
        if changed_fields:
            notes.append("noted. I updated my operator profile notes.")

    if added_sites:
        ok, summary, monitor_added = add_world_watch_sites(repo_root() / "tako.toml", added_sites)
        if ok and monitor_added:
            append_daily_note(
                daily_root(),
                date.today(),
                "World-watch sites added from operator XMTP chat: " + ", ".join(monitor_added[:6]),
            )
            _emit_runtime_log(
                f"child-profile world_watch.sites added={len(monitor_added)}",
                hooks=hooks,
            )
            notes.append("added to watch list: " + ", ".join(monitor_added[:3]))
        elif not ok:
            _emit_runtime_log(f"child-profile world_watch.sites update warning: {summary}", level="warn", hooks=hooks)

    followup = next_child_followup_question(profile)
    save_operator_profile(paths.state_dir, profile)
    if followup:
        notes.append(followup)
    return notes


def _is_git_identity_error(text: str) -> bool:
    lowered = text.lower()
    return "user.name" in lowered or "user.email" in lowered or "author identity unknown" in lowered


def _is_retryable_xmtp_error(error: Exception) -> bool:
    lowered = str(error).strip().lower()
    if not lowered:
        return False
    retryable_tokens = (
        "temporarily unavailable",
        "unavailable",
        "connection reset",
        "connection closed",
        "broken pipe",
        "timeout",
        "timed out",
        "deadline exceeded",
        "network is unreachable",
        "try again",
        "grpc-status header missing",
    )
    return any(token in lowered for token in retryable_tokens)


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


def _summarize_chat_log_text(text: str) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= 320:
        return value
    return f"{value[:317]}..."


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
