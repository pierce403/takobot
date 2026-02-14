from __future__ import annotations

import asyncio
import argparse
import contextlib
from collections import deque
from dataclasses import dataclass
import random
import re
import sys
import time
from datetime import date, datetime, timezone
from typing import Callable

from . import __version__
from .daily import append_daily_note, ensure_daily_log
from .ens import DEFAULT_ENS_RPC_URLS, resolve_recipient
from .git_safety import assert_not_tracked, panic_check_runtime_secrets
from .inference import InferenceRuntime, discover_inference_runtime, format_runtime_lines, run_inference_prompt_with_fallback
from .keys import derive_eth_address, load_or_create_keys
from .locks import instance_lock
from .operator import clear_operator, get_operator_inbox_id, load_operator
from .pairing import clear_pending
from .paths import daily_root, ensure_runtime_dirs, repo_root, runtime_paths
from .self_update import run_self_update
from .soul import read_identity, update_identity
from .tool_ops import fetch_webpage, run_local_command
from .xmtp import create_client, default_message, hint_for_xmtp_error, send_dm_sync
from .identity import build_identity_name_prompt, extract_name_from_model_output, looks_like_name_change_request
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
        f"- workspace: {root}",
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
    except ModuleNotFoundError as exc:
        if exc.name == "xmtp":
            problems.append('xmtp import failed: missing dependency. Install with: pip install "takobot[xmtp]"')
        else:
            problems.append(f"xmtp import failed: {exc}")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"xmtp import failed: {exc}")

    try:
        import web3  # noqa: F401

        lines.append("- web3: import OK")
    except Exception as exc:  # noqa: BLE001
        problems.append(f"web3 import failed: {exc}")

    inference_runtime = discover_inference_runtime()
    lines.extend(f"- {line}" for line in format_runtime_lines(inference_runtime))

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
    inference_runtime = discover_inference_runtime()
    _emit_runtime_log(
        f"inference: selected={inference_runtime.selected_provider or 'none'} "
        f"ready={'yes' if inference_runtime.ready else 'no'}",
        hooks=hooks,
    )

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
                        await _handle_incoming_message(
                            item,
                            client,
                            paths,
                            address,
                            env,
                            start,
                            inference_runtime,
                            hooks=hooks,
                        )
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
                        await _handle_incoming_message(
                            item,
                            client,
                            paths,
                            address,
                            env,
                            start,
                            inference_runtime,
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
    inference_runtime: InferenceRuntime,
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
                "Pairing is terminal-first: run `.venv/bin/tako` in the workspace (or bootstrap with `setup.sh`), "
                "enter your XMTP handle, and I'll send an outbound DM and imprint the operator channel."
            )
        else:
            reply = await _chat_reply(
                text,
                inference_runtime,
                is_operator=False,
                operator_paired=False,
                hooks=hooks,
            )
            await convo.send(reply)
        return

    if sender_inbox_id != operator_inbox_id:
        if _looks_like_command(text):
            await convo.send("Operator-only: config/tools/permissions/routines require the operator.")
        else:
            reply = await _chat_reply(
                text,
                inference_runtime,
                is_operator=False,
                operator_paired=True,
                hooks=hooks,
            )
            await convo.send(reply)
        return

    if not _looks_like_command(text):
        if await _maybe_handle_operator_identity_update(text, inference_runtime, paths, convo, hooks=hooks):
            return
        reply = await _chat_reply(
            text,
            inference_runtime,
            is_operator=True,
            operator_paired=True,
            hooks=hooks,
        )
        await convo.send(reply)
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
                return run_inference_prompt_with_fallback(inference_runtime, prompt, timeout_s=timeout_s)
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
                return run_inference_prompt_with_fallback(inference_runtime, prompt, timeout_s=timeout_s)
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
        if result.changed:
            report_lines.append("Restart Tako to load updated code.")
            append_daily_note(daily_root(), date.today(), "Operator applied self-update over XMTP.")
        elif apply_update:
            append_daily_note(daily_root(), date.today(), f"Operator ran self-update: {result.summary}")
        await convo.send("\n".join(report_lines))
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
        result = await asyncio.to_thread(run_local_command, command)
        append_daily_note(
            daily_root(),
            date.today(),
            f"Operator ran local command via XMTP: `{command}` (exit={result.exit_code})",
        )
        if not result.ok and result.error:
            await convo.send(f"command failed before execution: {result.error}")
            return
        await convo.send(
            f"run: {result.command}\n"
            f"exit_code: {result.exit_code}\n"
            f"{result.output}"
        )
        return
    if cmd == "reimprint":
        if rest.strip().lower() != "confirm":
            await convo.send(
                "Re-imprint is operator-only and destructive.\n\n"
                "Reply: `reimprint CONFIRM` to clear the current operator. "
                "Then re-run terminal onboarding (`.venv/bin/tako`) to pair again."
            )
            return
        clear_operator(paths.operator_json)
        clear_pending(paths.state_dir / "pairing.json")
        append_daily_note(daily_root(), date.today(), "Operator cleared imprint (reimprint CONFIRM).")
        await convo.send("Operator imprint cleared. Run `.venv/bin/tako` in the local terminal to pair a new operator.")
        return

    await convo.send("Unknown command. Reply 'help'. For normal chat, send plain text.")


async def _maybe_handle_operator_identity_update(
    text: str,
    inference_runtime: InferenceRuntime,
    paths,
    convo,
    *,
    hooks: RuntimeHooks | None,
) -> bool:
    if not looks_like_name_change_request(text):
        return False
    if not inference_runtime.ready:
        await convo.send("I can rename myself once inference is awake. (inference is unavailable right now.)")
        return True

    current_name, current_role = read_identity()
    prompt = build_identity_name_prompt(text=text, current_name=current_name)
    try:
        _, output = await asyncio.to_thread(
            run_inference_prompt_with_fallback,
            inference_runtime,
            prompt,
            timeout_s=45.0,
        )
    except Exception as exc:  # noqa: BLE001
        _emit_runtime_log(f"identity name extraction failed: {_summarize_stream_error(exc)}", level="warn", hooks=hooks)
        await convo.send("little ink blot: I couldn't extract a clean name right now. try again in a moment.")
        return True

    parsed = extract_name_from_model_output(output)
    if not parsed:
        await convo.send("tiny clarification bubble: I couldn't isolate the name. try: `call yourself SILLYTAKO`.")
        return True
    if parsed == current_name:
        await convo.send(f"already swimming under `{parsed}`.")
        return True

    update_identity(parsed, current_role)
    append_daily_note(daily_root(), date.today(), f"Operator renamed via XMTP: {current_name} -> {parsed}")
    await convo.send(f"ink dried. I'll go by `{parsed}` now.")
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


async def _heartbeat_loop(args: argparse.Namespace) -> None:
    first_tick = True
    while True:
        if first_tick:
            first_tick = False
            ensure_daily_log(daily_root(), date.today())
        interval = max(1.0, float(args.interval))
        await asyncio.sleep(interval + random.uniform(-0.2 * interval, 0.2 * interval))


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
        "- task <title> (optional: | project=... | area=... | due=YYYY-MM-DD)\n"
        "- tasks (or `tasks project <name>` / `tasks area <name>` / `tasks due YYYY-MM-DD`)\n"
        "- done <task-id>\n"
        "- outcomes (or `outcomes set a ; b ; c`, `outcomes done 1`, `outcomes undo 1`)\n"
        "- morning a ; b ; c\n"
        "- compress\n"
        "- weekly (or `review weekly`)\n"
        "- promote <durable note>\n"
        "- update (or `update check`)\n"
        "- web <https://...>\n"
        "- run <shell command>\n"
        "- reimprint (operator-only)\n"
        "- plain text chat (inference-backed when available)\n"
    )


def _looks_like_command(text: str) -> bool:
    value = text.strip()
    if not value:
        return False
    lowered = value.lower()
    if lowered.startswith("tako ") or value.startswith("/"):
        return True
    cmd, rest = _parse_command(value)
    tail = rest.strip()
    tail_lower = tail.lower()
    if cmd in {"help", "h", "?", "status", "doctor"}:
        return tail == ""
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
    if cmd == "update":
        return tail_lower in {"", "check", "status", "dry-run", "dryrun", "help", "?"}
    if cmd in {"web", "run"}:
        return tail != ""
    if cmd == "reimprint":
        return True
    return False


async def _chat_reply(
    text: str,
    inference_runtime: InferenceRuntime,
    *,
    is_operator: bool,
    operator_paired: bool,
    hooks: RuntimeHooks | None,
) -> str:
    fallback = _fallback_chat_reply(is_operator=is_operator, operator_paired=operator_paired)
    if not inference_runtime.ready:
        return fallback

    prompt = _chat_prompt(text, is_operator=is_operator, operator_paired=operator_paired)
    try:
        provider, reply = await asyncio.to_thread(
            run_inference_prompt_with_fallback,
            inference_runtime,
            prompt,
            timeout_s=CHAT_INFERENCE_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001
        _emit_runtime_log(f"inference chat fallback: {_summarize_stream_error(exc)}", level="warn", hooks=hooks)
        return fallback

    cleaned = _clean_chat_reply(reply)
    if not cleaned:
        return fallback
    _emit_runtime_log(f"inference chat provider: {provider}", hooks=hooks)
    return cleaned


def _chat_prompt(text: str, *, is_operator: bool, operator_paired: bool) -> str:
    role = "operator" if is_operator else "non-operator"
    paired = "yes" if operator_paired else "no"
    return (
        "You are Tako, a cute but practical octopus assistant.\n"
        "Reply with plain text only (no markdown), max 4 short lines.\n"
        "You can chat broadly and help think through tasks.\n"
        "Hard boundary: only the operator may change identity/config/tools/permissions/routines.\n"
        "If user asks for restricted changes and they are non-operator, say operator-only clearly.\n"
        f"sender_role={role}\n"
        f"operator_paired={paired}\n"
        f"user_message={text}\n"
    )


def _fallback_chat_reply(*, is_operator: bool, operator_paired: bool) -> str:
    if is_operator:
        return "I can chat here. Commands: help, status, doctor, update, web, run, reimprint. Inference is unavailable right now, so I'm replying in fallback mode."
    if operator_paired:
        return "Happy to chat. Operator-only boundary still applies for identity/config/tools/permissions/routines."
    return "Happy to chat. This instance is not paired yet; run `.venv/bin/tako` locally to set the operator channel."


def _clean_chat_reply(text: str) -> str:
    value = " ".join(text.strip().split())
    if not value:
        return ""
    if len(value) > CHAT_REPLY_MAX_CHARS:
        return value[: CHAT_REPLY_MAX_CHARS - 3] + "..."
    return value


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
