from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import json
import os
import platform
import random
import secrets
import shutil
import socket
import time
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Input, RichLog, Static

from . import __version__
from .cli import DEFAULT_ENV, RuntimeHooks, _doctor_report, _run_daemon
from .daily import append_daily_note, ensure_daily_log
from .ens import DEFAULT_ENS_RPC_URLS, resolve_recipient
from .git_safety import assert_not_tracked, panic_check_runtime_secrets
from .keys import derive_eth_address, load_or_create_keys
from .locks import instance_lock
from .operator import get_operator_inbox_id, imprint_operator, load_operator
from .pairing import clear_pending
from .paths import daily_root, ensure_runtime_dirs, repo_root, runtime_paths
from .soul import DEFAULT_SOUL_NAME, DEFAULT_SOUL_ROLE, read_identity, update_identity
from .xmtp import create_client, hint_for_xmtp_error


PAIRING_CODE_ATTEMPTS = 5
PAIRING_CODE_LENGTH = 8
PAIRING_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
HEARTBEAT_JITTER = 0.2
EVENT_INGEST_INTERVAL_S = 0.8

SEVERITY_ORDER = {
    "info": 0,
    "warn": 1,
    "error": 2,
    "critical": 3,
}


class SessionState(str, Enum):
    BOOTING = "BOOTING"
    ONBOARDING_IDENTITY = "ONBOARDING_IDENTITY"
    ONBOARDING_ROUTINES = "ONBOARDING_ROUTINES"
    ASK_XMTP_HANDLE = "ASK_XMTP_HANDLE"
    PAIRING_OUTBOUND = "PAIRING_OUTBOUND"
    PAIRED = "PAIRED"
    RUNNING = "RUNNING"


class TakoTerminalApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #status-bar {
        dock: top;
        height: 1;
        padding: 0 1;
        background: $boost;
        color: $text;
    }

    #main {
        height: 1fr;
    }

    #transcript {
        width: 2fr;
        border: solid $accent;
        padding: 0 1;
    }

    #sidebar {
        width: 1fr;
        border: solid $secondary;
        padding: 0 1;
    }

    .panel {
        height: 1fr;
        border: solid $primary;
        margin: 0 0 1 0;
        padding: 0 1;
    }

    #input-box {
        dock: bottom;
        margin: 1 0 0 0;
    }
    """

    BINDINGS = [
        ("ctrl+c", "request_quit", "Quit"),
        ("f2", "toggle_safe_mode", "Safe Mode"),
    ]

    def __init__(self, *, interval: float = 30.0) -> None:
        super().__init__()
        self.interval = max(1.0, float(interval))
        self.started_at = time.monotonic()

        self.state = SessionState.BOOTING
        self.mode = "boot"
        self.indicator = "idle"
        self.runtime_mode = "offline"
        self.safe_mode = False

        self.paths = None
        self.wallet_key = ""
        self.db_encryption_key = ""
        self.address = ""

        self.identity_name = DEFAULT_SOUL_NAME
        self.identity_role = DEFAULT_SOUL_ROLE
        self.routines = ""

        self.operator_inbox_id: str | None = None
        self.operator_address: str | None = None
        self.operator_paired = False

        self.identity_step = 0
        self.awaiting_xmtp_handle = False

        self.pairing_handle = ""
        self.pairing_resolved = ""
        self.pairing_code = ""
        self.pairing_code_attempts = 0
        self.pairing_completed = False
        self.pairing_operator_inbox_id = ""
        self.pairing_client = None
        self.pairing_dm = None
        self.pairing_watch_task: asyncio.Task[None] | None = None

        self.runtime_task: asyncio.Task[None] | None = None
        self.local_heartbeat_task: asyncio.Task[None] | None = None
        self.event_ingest_task: asyncio.Task[None] | None = None
        self.type1_task: asyncio.Task[None] | None = None
        self.type2_task: asyncio.Task[None] | None = None
        self.boot_task: asyncio.Task[None] | None = None

        self.lock_context = None
        self.lock_acquired = False
        self.shutdown_complete = False

        self.event_log_path: Path | None = None
        self.event_cursor = 0
        self.pending_events: list[dict[str, Any]] = []
        self.seen_event_ids: set[str] = set()
        self.type1_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.type2_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()

        self.instance_kind = "unknown"
        self.health_summary: dict[str, str] = {}
        self.heartbeat_ticks = 0
        self.last_heartbeat_at: float | None = None
        self.type1_processed = 0
        self.type2_escalations = 0
        self.type2_last = "none"
        self.event_total_written = 0
        self.event_total_ingested = 0

        self.status_bar: Static
        self.transcript: RichLog
        self.input_box: Input
        self.tasks_panel: Static
        self.memory_panel: Static
        self.sensors_panel: Static

    def compose(self) -> ComposeResult:
        yield Static("", id="status-bar")
        with Horizontal(id="main"):
            yield RichLog(id="transcript", wrap=True, highlight=False, markup=False, auto_scroll=True)
            with Vertical(id="sidebar"):
                yield Static("", id="panel-tasks", classes="panel")
                yield Static("", id="panel-memory", classes="panel")
                yield Static("", id="panel-sensors", classes="panel")
        yield Input(id="input-box", placeholder="Type here. During onboarding, answer the current question.")
        yield Footer()

    def on_mount(self) -> None:
        self.status_bar = self.query_one("#status-bar", Static)
        self.transcript = self.query_one("#transcript", RichLog)
        self.input_box = self.query_one("#input-box", Input)
        self.tasks_panel = self.query_one("#panel-tasks", Static)
        self.memory_panel = self.query_one("#panel-memory", Static)
        self.sensors_panel = self.query_one("#panel-sensors", Static)
        self.input_box.focus()
        self.set_interval(0.5, self._refresh_status)
        self._refresh_panels()
        self.boot_task = asyncio.create_task(self._boot())

    async def on_unmount(self) -> None:
        await self._shutdown_background_tasks()

    async def action_request_quit(self) -> None:
        await self._shutdown_background_tasks()
        self.exit()

    async def action_toggle_safe_mode(self) -> None:
        if self.safe_mode:
            await self._disable_safe_mode()
            return
        await self._enable_safe_mode()

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = _sanitize(event.value)
        event.input.value = ""
        if not text:
            return

        self._write_user(text)
        self._set_indicator("thinking")
        try:
            await self._route_input(text)
        finally:
            if self.indicator == "thinking":
                self._set_indicator("idle")

    async def _boot(self) -> None:
        self._set_state(SessionState.BOOTING)
        self.mode = "boot"
        self.runtime_mode = "offline"
        self._set_indicator("acting")
        self._write_tako("waking up... tiny octopus stretch complete.")

        try:
            self.paths = ensure_runtime_dirs(runtime_paths())
            root = repo_root()

            keys_preexisting = self.paths.keys_json.exists()
            operator_preexisting = self.paths.operator_json.exists()
            xmtp_db_preexisting = any(self.paths.xmtp_db_dir.glob("*.db3"))
            state_preexisting = _dir_has_entries(self.paths.state_dir)

            panic_check_runtime_secrets(root, self.paths.root)
            assert_not_tracked(root, self.paths.keys_json)

            self.lock_context = instance_lock(self.paths.locks_dir / "tako.lock")
            self.lock_context.__enter__()
            self.lock_acquired = True

            keys = load_or_create_keys(self.paths.keys_json, legacy_config_path=self.paths.root / "config.json")
            self.wallet_key = keys["wallet_key"]
            self.db_encryption_key = keys["db_encryption_key"]
            self.address = derive_eth_address(self.wallet_key)

            ensure_daily_log(daily_root(), date.today())
            append_daily_note(daily_root(), date.today(), "Interactive terminal app session started.")

            self.identity_name, self.identity_role = read_identity()
            self.instance_kind = (
                "established"
                if keys_preexisting or operator_preexisting or xmtp_db_preexisting or state_preexisting
                else "brand-new"
            )

            await self._initialize_reasoning_runtime()
            await self._run_startup_health_check(
                keys_preexisting=keys_preexisting,
                operator_preexisting=operator_preexisting,
                xmtp_db_preexisting=xmtp_db_preexisting,
                state_preexisting=state_preexisting,
            )

            self._write_tako(f"all set! my XMTP address is {self.address}.")

            operator_cfg = load_operator(self.paths.operator_json)
            self.operator_inbox_id = get_operator_inbox_id(operator_cfg)
            if operator_cfg and isinstance(operator_cfg.get("operator_address"), str):
                self.operator_address = operator_cfg.get("operator_address")

            if self.operator_inbox_id:
                self.operator_paired = True
                self.mode = "paired"
                self._set_state(SessionState.PAIRED)
                self._write_tako("operator imprint found. XMTP is already my control current for config changes.")
                await self._start_xmtp_runtime()
                self._set_state(SessionState.RUNNING)
                self._write_tako("terminal is now your local cockpit (status/logs/read-only queries). type `help`.")
                return

            self.operator_paired = False
            self.mode = "onboarding"
            self._set_state(SessionState.ASK_XMTP_HANDLE)
            self.awaiting_xmtp_handle = False
            self._write_tako(
                "first tentacle task, ASAP: let's set up your XMTP control channel. "
                "do you have an XMTP handle? (yes/no)"
            )
        except Exception as exc:  # noqa: BLE001
            self._error_card(
                "startup blocked",
                str(exc),
                [
                    "Check repo safety constraints (.tako secrets must not be tracked).",
                    "Resolve the issue, then restart `tako`.",
                ],
            )
            self.input_box.disabled = True
        finally:
            self._set_indicator("idle")

    async def _initialize_reasoning_runtime(self) -> None:
        if self.paths is None:
            return

        if self.event_log_path is None:
            self.event_log_path = self.paths.state_dir / "events.jsonl"
            self.event_log_path.parent.mkdir(parents=True, exist_ok=True)
            self.event_log_path.touch(exist_ok=True)
            self.event_cursor = 0

        await self._flush_pending_events()

        if self.event_ingest_task is None:
            self.event_ingest_task = asyncio.create_task(self._event_ingest_loop(), name="tako-event-ingest")
        if self.type1_task is None:
            self.type1_task = asyncio.create_task(self._type1_loop(), name="tako-type1")
        if self.type2_task is None:
            self.type2_task = asyncio.create_task(self._type2_loop(), name="tako-type2")
        await self._start_local_heartbeat()

        self._write_system("Type1 tide scanner online. Consuming event log and triaging signals.")
        self._record_event(
            "reasoning.engine.started",
            "Type1/Type2 reasoning loops started.",
            source="startup",
            metadata={"event_log": str(self.event_log_path)},
        )

    async def _run_startup_health_check(
        self,
        *,
        keys_preexisting: bool,
        operator_preexisting: bool,
        xmtp_db_preexisting: bool,
        state_preexisting: bool,
    ) -> None:
        if self.paths is None:
            return

        disk = shutil.disk_usage(self.paths.root)
        disk_free_mb = int(disk.free / (1024 * 1024))
        dns_xmtp_ok = _dns_lookup_ok("grpc.production.xmtp.network")
        xmtp_import_ok = importlib.util.find_spec("xmtp") is not None
        web3_import_ok = importlib.util.find_spec("web3") is not None
        textual_import_ok = importlib.util.find_spec("textual") is not None

        self.health_summary = {
            "instance_kind": self.instance_kind,
            "lock": "ok" if self.lock_acquired else "missing",
            "repo_writable": _yes_no(os.access(repo_root(), os.W_OK)),
            "runtime_writable": _yes_no(os.access(self.paths.root, os.W_OK)),
            "disk_free_mb": str(disk_free_mb),
            "keys_preexisting": _yes_no(keys_preexisting),
            "operator_preexisting": _yes_no(operator_preexisting),
            "xmtp_db_preexisting": _yes_no(xmtp_db_preexisting),
            "state_preexisting": _yes_no(state_preexisting),
            "xmtp_import": _yes_no(xmtp_import_ok),
            "web3_import": _yes_no(web3_import_ok),
            "textual_import": _yes_no(textual_import_ok),
            "dns_xmtp": _yes_no(dns_xmtp_ok),
            "python": platform.python_version(),
        }

        issues: list[tuple[str, str]] = []
        if not self.lock_acquired:
            issues.append(("critical", "Instance lock is not held."))
        if not os.access(repo_root(), os.W_OK):
            issues.append(("error", "Repo directory is not writable."))
        if disk_free_mb < 256:
            issues.append(("warn", f"Low disk space under .tako: {disk_free_mb} MB free."))
        if not xmtp_import_ok:
            issues.append(("warn", "xmtp import unavailable; XMTP runtime/pairing may fail until dependencies are installed."))
        if not dns_xmtp_ok:
            issues.append(("warn", "DNS lookup for XMTP host failed; outbound XMTP connectivity may be unavailable."))

        health_line = (
            f"health check: {self.instance_kind} instance | "
            f"lock={self.health_summary['lock']} | "
            f"disk_free_mb={disk_free_mb} | "
            f"xmtp_import={self.health_summary['xmtp_import']} | "
            f"dns_xmtp={self.health_summary['dns_xmtp']}"
        )
        self._write_system(health_line)
        self._record_event(
            "health.check.summary",
            health_line,
            severity="warn" if issues else "info",
            source="health",
            metadata=self.health_summary,
        )

        for severity, message in issues:
            self._write_system(f"health issue [{severity}]: {message}")
            self._record_event("health.check.issue", message, severity=severity, source="health")

    def _record_event(
        self,
        event_type: str,
        message: str,
        *,
        severity: str = "info",
        source: str = "system",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        event = {
            "id": _new_event_id(),
            "ts": _utc_now_iso(),
            "type": event_type,
            "severity": severity.lower(),
            "source": source,
            "message": message,
            "metadata": metadata or {},
        }
        if self.event_log_path is None:
            self.pending_events.append(event)
        else:
            self._append_event_to_log(event)

        self._enqueue_type1_event(event)

    async def _flush_pending_events(self) -> None:
        if self.event_log_path is None or not self.pending_events:
            return
        pending = list(self.pending_events)
        self.pending_events.clear()
        for event in pending:
            self._append_event_to_log(event)

    def _append_event_to_log(self, event: dict[str, Any]) -> None:
        if self.event_log_path is None:
            return
        try:
            with self.event_log_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(event, sort_keys=True, ensure_ascii=True))
                handle.write("\n")
            self.event_total_written += 1
        except Exception as exc:  # noqa: BLE001
            self._write_system(f"event-log write warning: {_summarize_error(exc)}")

    def _enqueue_type1_event(self, event: dict[str, Any]) -> None:
        event_id = str(event.get("id") or "")
        if event_id and event_id in self.seen_event_ids:
            return
        if event_id:
            self.seen_event_ids.add(event_id)
        self.event_total_ingested += 1
        with contextlib.suppress(asyncio.QueueFull):
            self.type1_queue.put_nowait(event)

    async def _event_ingest_loop(self) -> None:
        while True:
            await asyncio.sleep(EVENT_INGEST_INTERVAL_S)
            if self.event_log_path is None:
                continue
            try:
                with self.event_log_path.open("r", encoding="utf-8") as handle:
                    handle.seek(self.event_cursor)
                    while True:
                        line = handle.readline()
                        if not line:
                            break
                        self.event_cursor = handle.tell()
                        payload = line.strip()
                        if not payload:
                            continue
                        try:
                            event = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(event, dict):
                            continue
                        if "id" not in event:
                            event["id"] = _line_event_id(payload)
                        self._enqueue_type1_event(event)
            except FileNotFoundError:
                continue
            except Exception as exc:  # noqa: BLE001
                self._write_system(f"event-log ingest warning: {_summarize_error(exc)}")

    async def _type1_loop(self) -> None:
        while True:
            event = await self.type1_queue.get()
            self.type1_processed += 1

            serious, depth, reason = self._assess_event_for_type2(event)
            if not serious:
                continue

            event_type = str(event.get("type", "unknown"))
            self._write_system(f"Type1: serious event `{event_type}` detected -> launching Type2 ({depth}).")
            self._record_event(
                "type1.escalation",
                f"Escalated event {event_type} to Type2 ({depth}): {reason}",
                severity="warn",
                source="type1",
                metadata={"event_type": event_type, "depth": depth, "reason": reason},
            )
            await self.type2_queue.put({"event": event, "depth": depth, "reason": reason})

    async def _type2_loop(self) -> None:
        while True:
            payload = await self.type2_queue.get()
            event = payload.get("event")
            depth = str(payload.get("depth", "medium"))
            reason = str(payload.get("reason", "serious signal"))
            if not isinstance(event, dict):
                continue
            await self._run_type2_thinking(event, depth=depth, reason=reason)

    async def _run_type2_thinking(self, event: dict[str, Any], *, depth: str, reason: str) -> None:
        sleep_s = {"light": 0.15, "medium": 0.4, "deep": 0.9}.get(depth, 0.4)
        previous_indicator = self.indicator
        self._set_indicator(f"type2:{depth}")
        try:
            await asyncio.sleep(sleep_s)
        finally:
            self._set_indicator(previous_indicator if previous_indicator.startswith("type2:") else "idle")

        event_type = str(event.get("type", "unknown"))
        message = str(event.get("message", ""))
        recommendation = _type2_recommendation(event_type, message)
        self.type2_escalations += 1
        self.type2_last = f"{event_type}:{depth}"
        self._write_system(f"Type2[{depth}]: {recommendation}")
        append_daily_note(
            daily_root(),
            date.today(),
            f"Type2 escalation ({depth}) on {event_type}: {reason}. Recommendation: {recommendation}",
        )
        self._record_event(
            "type2.result",
            recommendation,
            source="type2",
            metadata={"event_type": event_type, "depth": depth, "reason": reason},
        )

    def _assess_event_for_type2(self, event: dict[str, Any]) -> tuple[bool, str, str]:
        source = str(event.get("source", "")).lower()
        if source in {"type1", "type2"}:
            return False, "light", "already processed by cognition loop"

        severity = str(event.get("severity", "info")).lower()
        event_type = str(event.get("type", "")).lower()
        message = str(event.get("message", "")).lower()

        if severity in {"critical", "error"}:
            depth = _depth_for_severity(severity)
            return True, depth, f"severity={severity}"

        if "another tako instance" in message or "instance lock" in message:
            return True, "deep", "duplicate-instance risk"

        if event_type.startswith("health.check.issue"):
            return True, "medium", "startup health issue"

        if event_type.startswith("runtime.") and severity == "warn" and (
            "crash" in message or "unstable" in message or "polling fallback" in message
        ):
            return True, "medium", "runtime instability"

        return False, "light", "type1 handled"

    async def _route_input(self, text: str) -> None:
        if self.state == SessionState.BOOTING:
            self._write_tako("still booting. give me a moment.")
            return

        if self.state == SessionState.ONBOARDING_IDENTITY:
            await self._handle_identity_onboarding(text)
            return

        if self.state == SessionState.ONBOARDING_ROUTINES:
            await self._handle_routines_onboarding(text)
            return

        if self.state == SessionState.ASK_XMTP_HANDLE:
            await self._handle_xmtp_handle_prompt(text)
            return

        if self.state == SessionState.PAIRING_OUTBOUND:
            await self._handle_pairing_input(text)
            return

        await self._handle_running_input(text)

    async def _handle_identity_onboarding(self, text: str) -> None:
        if self.identity_step == 0:
            self.identity_name = text or self.identity_name
            self.identity_step = 1
            self._write_tako("cute. and what should my purpose be? one sentence is perfect.")
            return

        self.identity_role = text or self.identity_role
        self.identity_name, self.identity_role = update_identity(self.identity_name, self.identity_role)
        append_daily_note(
            daily_root(),
            date.today(),
            f"Identity set in terminal app: name={self.identity_name}; role={self.identity_role}",
        )
        self._record_event(
            "onboarding.identity.saved",
            "Identity values saved to SOUL.md.",
            source="onboarding",
            metadata={"name": self.identity_name},
        )
        self._write_tako(f"identity tucked away in my little shell: {self.identity_name} — {self.identity_role}")
        self._set_state(SessionState.ONBOARDING_ROUTINES)
        self._write_tako("last onboarding nibble: what should I watch or do daily? free-form note.")

    async def _handle_routines_onboarding(self, text: str) -> None:
        self.routines = text or "No explicit routines yet."
        if self.paths is not None:
            routines_path = self.paths.state_dir / "routines.txt"
            routines_path.write_text(self.routines + "\n", encoding="utf-8")
        append_daily_note(daily_root(), date.today(), f"Routine note captured: {self.routines}")
        self._record_event("onboarding.routines.saved", "Routine preferences captured.", source="onboarding")
        await self._finalize_onboarding()

    async def _handle_xmtp_handle_prompt(self, text: str) -> None:
        lowered = text.strip().lower()
        if lowered in {"local", "local-only", "skip"}:
            self._record_event("pairing.user.local_only", "Operator chose local-only mode.", source="pairing")
            if self.mode == "onboarding":
                self._write_tako("no worries, captain. we'll keep paddling locally for now.")
                self._begin_identity_onboarding()
                return
            await self._enter_local_only_mode()
            return

        if self.awaiting_xmtp_handle:
            await self._start_pairing(text)
            return

        yes_no = _parse_yes_no(text)
        if yes_no is None:
            self._write_tako("boop. please answer yes or no.")
            return

        if yes_no:
            self.awaiting_xmtp_handle = True
            self._record_event("pairing.user.has_handle", "Operator confirmed XMTP handle availability.", source="pairing")
            self._write_tako("splash it over: share the handle (.eth or 0x...).")
            return

        if self.mode == "onboarding":
            self._record_event("pairing.user.no_handle", "Operator has no XMTP handle yet.", source="pairing")
            self._write_tako("got it. we'll continue in local mode first, and you can pair later with `pair`.")
            self._begin_identity_onboarding()
            return

        await self._enter_local_only_mode()

    async def _start_pairing(self, handle: str) -> None:
        if self.paths is None:
            self._write_tako("uh-oh, my tide map is missing runtime paths. restart required.")
            return

        self.awaiting_xmtp_handle = False
        self.pairing_handle = handle
        self._set_state(SessionState.PAIRING_OUTBOUND)
        self._set_indicator("acting")
        self._record_event(
            "pairing.outbound.start",
            "Starting outbound pairing attempt.",
            source="pairing",
            metadata={"handle": handle},
        )

        try:
            resolved = resolve_recipient(handle, list(DEFAULT_ENS_RPC_URLS))
        except Exception as exc:  # noqa: BLE001
            self._error_card(
                "could not resolve XMTP handle",
                str(exc),
                [
                    "Check ENS/address spelling.",
                    "Share another handle or type `local-only`.",
                ],
            )
            self._record_event(
                "pairing.outbound.resolve_failed",
                f"Could not resolve pairing handle: {exc}",
                severity="warn",
                source="pairing",
                metadata={"handle": handle},
            )
            self._set_state(SessionState.ASK_XMTP_HANDLE)
            self.awaiting_xmtp_handle = True
            self._set_indicator("idle")
            return

        pairing_code = _new_pairing_code()
        host = socket.gethostname()
        outbound_message = (
            f"Hi from Tako on {host}!\n\n"
            "Tiny octopus pairing is in progress.\n"
            "Reply with this code on XMTP, or paste it back into terminal:\n\n"
            f"{pairing_code}"
        )

        try:
            client = await create_client(DEFAULT_ENV, self.paths.xmtp_db_dir, self.wallet_key, self.db_encryption_key)
            dm = await client.conversations.new_dm(resolved)
            await dm.send(outbound_message)
            operator_inbox_id = await _resolve_operator_inbox_id(client, resolved, dm)
            if not operator_inbox_id:
                raise RuntimeError("DM sent but operator inbox id could not be resolved.")
        except Exception as exc:  # noqa: BLE001
            hint = hint_for_xmtp_error(exc)
            next_steps = [
                "Type `retry` to attempt pairing again.",
                "Type `local-only` to continue without XMTP pairing.",
            ]
            if hint:
                next_steps.append(hint)
            self._error_card("pairing DM failed", str(exc), next_steps)
            self._record_event(
                "pairing.outbound.send_failed",
                f"Outbound pairing DM failed: {exc}",
                severity="error",
                source="pairing",
                metadata={"resolved": resolved},
            )
            await self._cleanup_pairing_resources()
            self._set_state(SessionState.PAIRING_OUTBOUND)
            self._set_indicator("idle")
            return

        self.pairing_client = client
        self.pairing_dm = dm
        self.pairing_resolved = resolved
        self.pairing_operator_inbox_id = operator_inbox_id
        self.pairing_code = pairing_code
        self.pairing_code_attempts = 0
        self.pairing_completed = False

        self._write_tako(f"outbound pairing DM sent to {handle} ({resolved}).")
        self._record_event(
            "pairing.outbound.sent",
            "Outbound pairing DM sent.",
            source="pairing",
            metadata={"resolved": resolved},
        )
        self._write_tako(
            "confirm by replying with the code on XMTP, or paste the code here with your human hands. "
            "commands: `retry`, `change`, `local-only`"
        )

        self.pairing_watch_task = asyncio.create_task(self._watch_for_pairing_reply())
        self._set_indicator("idle")

    async def _watch_for_pairing_reply(self) -> None:
        if not self.pairing_client or not self.pairing_operator_inbox_id or not self.pairing_code:
            return

        expected = _normalize_pairing_code(self.pairing_code)
        stream = self.pairing_client.conversations.stream_all_messages()
        try:
            async for item in stream:
                if self.pairing_completed:
                    break
                if isinstance(item, Exception):
                    continue
                sender_inbox_id = getattr(item, "sender_inbox_id", None)
                if sender_inbox_id != self.pairing_operator_inbox_id:
                    continue
                content = getattr(item, "content", None)
                if not isinstance(content, str):
                    continue
                if _normalize_pairing_code(content) == expected:
                    self._write_tako("yay! received matching pairing code over XMTP.")
                    self._record_event(
                        "pairing.confirmed.xmtp",
                        "Pairing code confirmed over XMTP reply.",
                        source="pairing",
                        metadata={"sender_inbox_id": sender_inbox_id},
                    )
                    await self._complete_pairing("xmtp_reply_v1")
                    break
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            self._write_system(f"pairing watcher warning: {_summarize_error(exc)}")
        finally:
            with contextlib.suppress(Exception):
                await stream.close()

    async def _handle_pairing_input(self, text: str) -> None:
        lowered = text.strip().lower()

        if lowered in {"retry", "resend"}:
            await self._cleanup_pairing_resources()
            await self._start_pairing(self.pairing_handle or self.pairing_resolved)
            return

        if lowered in {"change", "new"}:
            await self._cleanup_pairing_resources()
            self._set_state(SessionState.ASK_XMTP_HANDLE)
            self.awaiting_xmtp_handle = True
            self._write_tako("okay, new tide. share another XMTP handle.")
            return

        if lowered in {"local", "local-only", "skip"}:
            await self._cleanup_pairing_resources()
            if self.mode == "onboarding":
                self._write_tako("roger that. we'll keep things local and continue onboarding.")
                self._begin_identity_onboarding()
                return
            await self._enter_local_only_mode()
            return

        if not self.pairing_code:
            self._write_tako("pairing code is not active. type `retry` or `local-only`.")
            return

        expected = _normalize_pairing_code(self.pairing_code)
        entered = _normalize_pairing_code(text)
        if entered == expected:
            self._record_event("pairing.confirmed.terminal", "Pairing code confirmed in terminal.", source="pairing")
            await self._complete_pairing("terminal_copyback_v2")
            return

        self.pairing_code_attempts += 1
        remaining = PAIRING_CODE_ATTEMPTS - self.pairing_code_attempts
        if remaining > 0:
            self._write_tako(f"oops, code mismatch. try again ({remaining} attempts left), or type `local-only`.")
            return

        self._error_card(
            "pairing confirmation limit reached",
            "too many incorrect code attempts",
            [
                "Type `retry` to send a fresh DM/code.",
                "Type `change` to use a different handle.",
                "Type `local-only` to keep running without pairing.",
            ],
        )

    async def _complete_pairing(self, pairing_method: str) -> None:
        if self.pairing_completed or self.paths is None:
            return
        if not self.pairing_operator_inbox_id:
            self._write_tako("cannot finish pairing: missing operator inbox id.")
            return

        self.pairing_completed = True
        imprint_operator(
            self.paths.operator_json,
            operator_inbox_id=self.pairing_operator_inbox_id,
            operator_address=self.pairing_resolved,
            pairing_method=pairing_method,
        )
        clear_pending(self.paths.state_dir / "pairing.json")
        append_daily_note(daily_root(), date.today(), f"Operator paired via {pairing_method}.")

        if self.pairing_dm is not None:
            with contextlib.suppress(Exception):
                await self.pairing_dm.send("Paired! You are now the operator. Reply `help` for commands.")

        self.operator_paired = True
        self.operator_inbox_id = self.pairing_operator_inbox_id
        self.operator_address = self.pairing_resolved
        self.mode = "paired"

        await self._cleanup_pairing_resources()

        self._set_state(SessionState.PAIRED)
        self._write_tako("paired! XMTP is now primary control channel for identity/config/tools/routines.")
        self._record_event(
            "pairing.completed",
            "Operator pairing completed successfully.",
            source="pairing",
            metadata={"operator_address": self.pairing_resolved, "pairing_method": pairing_method},
        )
        self._begin_identity_onboarding()

    async def _cleanup_pairing_resources(self) -> None:
        current = asyncio.current_task()
        if self.pairing_watch_task is not None and self.pairing_watch_task is not current:
            self.pairing_watch_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.pairing_watch_task
        self.pairing_watch_task = None

        client = self.pairing_client
        self.pairing_client = None
        self.pairing_dm = None

        if client is not None:
            close_fn = getattr(client, "close", None)
            if callable(close_fn):
                with contextlib.suppress(Exception):
                    result = close_fn()
                    if asyncio.iscoroutine(result):
                        await result

    async def _enter_local_only_mode(self) -> None:
        self.mode = "local-only"
        self.operator_paired = False
        self.runtime_mode = "local"
        self._set_state(SessionState.RUNNING)
        await self._stop_xmtp_runtime()
        await self._start_local_heartbeat()
        self._write_tako("continuing in terminal-managed local mode. use `pair` any time to add XMTP operator control.")
        self._record_event("runtime.local_mode", "Running in local-only mode.", source="startup")

    async def _finalize_onboarding(self) -> None:
        if self.operator_paired:
            self.mode = "paired"
            self._set_state(SessionState.PAIRED)
            self._write_tako("onboarding complete. spinning up XMTP runtime currents.")
            self._record_event("onboarding.completed", "Onboarding completed with operator pairing.", source="onboarding")
            await self._start_xmtp_runtime()
            self._set_state(SessionState.RUNNING)
            self._write_tako("all tentacles online. terminal remains your local cockpit. type `help`.")
            return

        self._record_event("onboarding.completed", "Onboarding completed in local-only mode.", source="onboarding")
        await self._enter_local_only_mode()

    def _begin_identity_onboarding(self) -> None:
        self.mode = "onboarding"
        self._set_state(SessionState.ONBOARDING_IDENTITY)
        self.identity_step = 0
        self._record_event("onboarding.identity.begin", "Identity prompt phase started.", source="onboarding")
        self._write_tako("next tiny question: what should I be called?")

    async def _start_xmtp_runtime(self) -> None:
        if self.paths is None:
            self._write_tako("cannot start XMTP runtime: paths unavailable.")
            return
        if self.safe_mode:
            self.runtime_mode = "safe"
            self._write_tako("safe mode is enabled; XMTP runtime is paused.")
            return

        await self._stop_xmtp_runtime()

        hooks = RuntimeHooks(log=self._on_runtime_log, inbound_message=self._on_runtime_inbound, emit_console=False)
        args = argparse.Namespace(interval=self.interval, once=False)
        self.runtime_mode = "stream"
        self.runtime_task = asyncio.create_task(
            self._run_runtime_task(args, hooks),
            name="tako-xmtp-runtime",
        )
        self._record_event("runtime.xmtp.started", "XMTP runtime loop started.", source="runtime")

    async def _run_runtime_task(self, args: argparse.Namespace, hooks: RuntimeHooks) -> None:
        if self.paths is None:
            return
        try:
            code = await _run_daemon(
                args,
                self.paths,
                DEFAULT_ENV,
                self.wallet_key,
                self.db_encryption_key,
                self.address,
                hooks=hooks,
            )
            if code != 0:
                self._error_card(
                    "XMTP runtime exited",
                    f"daemon returned exit code {code}",
                    [
                        "Use `safe off` to retry runtime start.",
                        "Run `doctor` for local diagnostics.",
                    ],
                )
                self.runtime_mode = "offline"
                self._record_event(
                    "runtime.exit.nonzero",
                    f"XMTP runtime exited with code {code}.",
                    severity="error",
                    source="runtime",
                )
        except asyncio.CancelledError:
            self.runtime_mode = "offline"
            raise
        except Exception as exc:  # noqa: BLE001
            self.runtime_mode = "offline"
            self._error_card(
                "XMTP runtime crashed",
                _summarize_error(exc),
                [
                    "Use `safe on` then `safe off` to restart runtime.",
                    "Check network/XMTP connectivity and try again.",
                ],
            )
            self._record_event(
                "runtime.crash",
                f"XMTP runtime crashed: {exc}",
                severity="error",
                source="runtime",
            )

    async def _stop_xmtp_runtime(self) -> None:
        if self.runtime_task is None:
            return
        self.runtime_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.runtime_task
        self.runtime_task = None
        self.runtime_mode = "offline"
        self._record_event("runtime.xmtp.stopped", "XMTP runtime loop stopped.", source="runtime")

    async def _start_local_heartbeat(self) -> None:
        if self.local_heartbeat_task is not None:
            return
        self.local_heartbeat_task = asyncio.create_task(self._local_heartbeat_loop(), name="tako-local-heartbeat")
        self._record_event("heartbeat.loop.started", "Heartbeat loop started.", source="heartbeat")

    async def _stop_local_heartbeat(self) -> None:
        if self.local_heartbeat_task is None:
            return
        self.local_heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.local_heartbeat_task
        self.local_heartbeat_task = None
        self._record_event("heartbeat.loop.stopped", "Heartbeat loop stopped.", source="heartbeat")

    async def _local_heartbeat_loop(self) -> None:
        while True:
            if not self.safe_mode:
                ensure_daily_log(daily_root(), date.today())
                self.heartbeat_ticks += 1
                self.last_heartbeat_at = time.monotonic()
                self._record_event(
                    "heartbeat.tick",
                    "Heartbeat tick completed.",
                    source="heartbeat",
                    metadata={
                        "tick": self.heartbeat_ticks,
                        "mode": self.mode,
                        "runtime_mode": self.runtime_mode,
                    },
                )
            await asyncio.sleep(
                self.interval
                + random.uniform(-HEARTBEAT_JITTER * self.interval, HEARTBEAT_JITTER * self.interval)
            )

    async def _enable_safe_mode(self) -> None:
        self.safe_mode = True
        self.mode = "safe"
        await self._stop_local_heartbeat()
        await self._stop_xmtp_runtime()
        self.runtime_mode = "safe"
        self._write_tako("safe mode enabled. tucked into a little shell for now.")
        self._record_event("runtime.safe_mode", "Safe mode enabled.", source="operator")

    async def _disable_safe_mode(self) -> None:
        self.safe_mode = False
        self._write_tako("safe mode disabled. paddling again.")
        self._record_event("runtime.safe_mode", "Safe mode disabled.", source="operator")
        await self._start_local_heartbeat()
        if self.operator_paired:
            self.mode = "paired"
            await self._start_xmtp_runtime()
        else:
            self.mode = "local-only"

    async def _handle_running_input(self, text: str) -> None:
        cmd, rest = _parse_command(text)
        if cmd in {"help", "h", "?"}:
            self._write_tako(
                "local cockpit commands: help, status, health, doctor, pair, safe on, safe off, stop, resume, quit"
            )
            return

        if cmd == "status":
            uptime = int(time.monotonic() - self.started_at)
            paired = "yes" if self.operator_paired else "no"
            safe = "on" if self.safe_mode else "off"
            heartbeat_age = (
                f"{int(time.monotonic() - self.last_heartbeat_at)}s ago"
                if self.last_heartbeat_at is not None
                else "n/a"
            )
            self._write_tako(
                "status: ok\n"
                f"paired: {paired}\n"
                f"instance_kind: {self.instance_kind}\n"
                f"mode: {self.mode}\n"
                f"runtime_mode: {self.runtime_mode}\n"
                f"safe_mode: {safe}\n"
                f"heartbeat_ticks: {self.heartbeat_ticks}\n"
                f"last_heartbeat: {heartbeat_age}\n"
                f"type1_processed: {self.type1_processed}\n"
                f"type2_escalations: {self.type2_escalations}\n"
                f"uptime_s: {uptime}\n"
                f"version: {__version__}\n"
                f"tako_address: {self.address}"
            )
            return

        if cmd == "health":
            if not self.health_summary:
                self._write_tako("health summary is not available yet.")
                return
            lines = ["health summary:"]
            for key in sorted(self.health_summary):
                lines.append(f"{key}: {self.health_summary[key]}")
            self._write_tako("\n".join(lines))
            return

        if cmd == "doctor":
            if self.paths is None:
                self._write_tako("doctor unavailable: runtime paths missing.")
                return
            lines, problems = _doctor_report(repo_root(), self.paths, DEFAULT_ENV)
            self._write_tako("\n".join(lines))
            if problems:
                self._write_tako("Problems:\n" + "\n".join(f"- {p}" for p in problems))
            return

        if cmd == "pair":
            if self.operator_paired:
                self._write_tako("already paired. re-imprint is operator-only over XMTP (`reimprint CONFIRM`).")
                return
            self._set_state(SessionState.ASK_XMTP_HANDLE)
            self.awaiting_xmtp_handle = True
            self._write_tako("share your XMTP handle to start outbound pairing, or `local-only`.")
            return

        if cmd in {"safe", "stop", "resume"}:
            value = rest.strip().lower()
            if cmd == "stop" or (cmd == "safe" and value in {"", "on", "enable", "enabled", "true", "1"}):
                await self._enable_safe_mode()
                return
            if cmd == "resume" or (cmd == "safe" and value in {"off", "disable", "disabled", "false", "0"}):
                await self._disable_safe_mode()
                return
            self._write_tako("usage: `safe on` or `safe off`.")
            return

        if cmd in {"quit", "exit"}:
            await self.action_request_quit()
            return

        if self.operator_paired:
            self._write_tako(
                "operator changes are XMTP-only after pairing. terminal stays read-only for status/logs/safe-mode."
            )
            return

        self._write_tako("local mode active. type `pair` to establish XMTP operator channel.")

    def _on_runtime_log(self, level: str, message: str) -> None:
        lowered = message.lower()
        if "switching to polling" in lowered:
            self.runtime_mode = "poll"
        elif "retrying stream mode" in lowered or "daemon started" in lowered:
            self.runtime_mode = "stream"
        elif "status: unpaired" in lowered and not self.operator_paired:
            self.runtime_mode = "local"

        if level in {"warn", "error"} or message.startswith(("status:", "pairing:", "inbox_id:")):
            self._write_system(f"runtime[{level}]: {message}")
        severity = level if level in {"warn", "error"} else "info"
        event_type = "runtime.log"
        if "crash" in lowered:
            event_type = "runtime.crash"
        elif "polling" in lowered:
            event_type = "runtime.polling"
        elif "reconnecting" in lowered:
            event_type = "runtime.reconnect"
        self._record_event(event_type, message, severity=severity, source="runtime")

    def _on_runtime_inbound(self, sender_inbox_id: str, text: str) -> None:
        short_sender = sender_inbox_id[:10]
        self._write_system(f"xmtp<{short_sender}>: {text}")
        self._record_event(
            "xmtp.inbound.message",
            "Inbound XMTP message received.",
            source="xmtp",
            metadata={"sender_inbox_id": sender_inbox_id, "preview": _summarize_text(text)},
        )

    async def _shutdown_background_tasks(self) -> None:
        if self.shutdown_complete:
            return
        self.shutdown_complete = True

        if self.boot_task is not None and not self.boot_task.done():
            self.boot_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self.boot_task

        await self._cleanup_pairing_resources()
        await self._stop_xmtp_runtime()
        await self._stop_local_heartbeat()
        await _cancel_task(self.event_ingest_task)
        await _cancel_task(self.type1_task)
        await _cancel_task(self.type2_task)
        self.event_ingest_task = None
        self.type1_task = None
        self.type2_task = None

        if self.lock_context is not None and self.lock_acquired:
            with contextlib.suppress(Exception):
                self.lock_context.__exit__(None, None, None)
            self.lock_acquired = False
            self.lock_context = None

    def _set_state(self, state: SessionState) -> None:
        self.state = state
        self._refresh_panels()

    def _set_indicator(self, indicator: str) -> None:
        self.indicator = indicator

    def _refresh_status(self) -> None:
        uptime_s = int(time.monotonic() - self.started_at)
        safe = "on" if self.safe_mode else "off"
        self.status_bar.update(
            f"state={self.state.value} | mode={self.mode} | runtime={self.runtime_mode} | "
            f"indicator={self.indicator} | safe={safe} | uptime={uptime_s}s"
        )
        self._refresh_panels()

    def _refresh_panels(self) -> None:
        pair_next = "establish XMTP pairing" if not self.operator_paired else "process operator commands via XMTP"
        heartbeat_age = (
            f"{int(time.monotonic() - self.last_heartbeat_at)}s"
            if self.last_heartbeat_at is not None
            else "n/a"
        )
        tasks = (
            "Tasks\n"
            f"- state: {self.state.value}\n"
            f"- instance: {self.instance_kind}\n"
            f"- next: {pair_next}\n"
            f"- runtime: {self.runtime_mode}\n"
            f"- safe mode: {'on' if self.safe_mode else 'off'}\n"
            f"- heartbeat ticks: {self.heartbeat_ticks}\n"
            f"- last heartbeat: {heartbeat_age}"
        )
        self.tasks_panel.update(tasks)

        event_log_value = str(self.event_log_path) if self.event_log_path is not None else "not ready"
        memory = (
            "Memory\n"
            f"- name: {self.identity_name}\n"
            f"- role: {self.identity_role}\n"
            f"- daily log: memory/dailies/{date.today().isoformat()}.md\n"
            f"- routines: {self.routines or 'not captured yet'}\n"
            f"- event log: {event_log_value}"
        )
        self.memory_panel.update(memory)

        operator = self.operator_address or "not paired"
        sensors = (
            "Sensors\n"
            f"- xmtp ingress: {'active' if self.operator_paired and not self.safe_mode else 'inactive'}\n"
            f"- type1 processed: {self.type1_processed}\n"
            f"- type2 escalations: {self.type2_escalations}\n"
            f"- type2 last: {self.type2_last}\n"
            f"- operator: {operator}\n"
            f"- events written: {self.event_total_written} / ingested: {self.event_total_ingested}"
        )
        self.sensors_panel.update(sensors)

    def _write_tako(self, text: str) -> None:
        self.transcript.write(f"Tako: {text}")

    def _write_user(self, text: str) -> None:
        self.transcript.write(f"You: {text}")

    def _write_system(self, text: str) -> None:
        self.transcript.write(f"System: {text}")

    def _error_card(self, summary: str, detail: str, next_steps: list[str]) -> None:
        self._write_system(f"ERROR: {summary}: {_summarize_text(detail)}")
        self._write_system("Next steps:")
        for step in next_steps:
            self._write_system(f"- {step}")
        severity = "critical" if summary == "startup blocked" else "error"
        self._record_event(
            "ui.error_card",
            f"{summary}: {_summarize_text(detail)}",
            severity=severity,
            source="ui",
            metadata={"summary": summary},
        )


def run_terminal_app(*, interval: float = 30.0) -> int:
    app = TakoTerminalApp(interval=interval)
    app.run()
    return 0


async def _resolve_operator_inbox_id(client, address: str, dm) -> str | None:
    peer_inbox_id = getattr(dm, "peer_inbox_id", None)
    if isinstance(peer_inbox_id, str) and peer_inbox_id.strip():
        return peer_inbox_id

    try:
        from xmtp.identifiers import Identifier, IdentifierKind

        identifier = Identifier(kind=IdentifierKind.ETHEREUM, value=address)
        inbox_id = await client.get_inbox_id_by_identifier(identifier)
    except Exception:
        return None
    if isinstance(inbox_id, str) and inbox_id.strip():
        return inbox_id
    return None


def _new_pairing_code() -> str:
    raw = "".join(secrets.choice(PAIRING_CODE_ALPHABET) for _ in range(PAIRING_CODE_LENGTH))
    return f"{raw[:4]}-{raw[4:]}"


def _sanitize(value: str) -> str:
    return " ".join(value.strip().split())


def _parse_yes_no(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"y", "yes", "true", "1", "ok", "sure"}:
        return True
    if normalized in {"n", "no", "false", "0", "nope"}:
        return False
    return None


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


def _normalize_pairing_code(value: str) -> str:
    return "".join(char for char in value.upper() if char.isalnum())


def _summarize_error(error: Exception) -> str:
    return _summarize_text(str(error) or error.__class__.__name__)


def _summarize_text(text: str) -> str:
    value = " ".join(text.split())
    if len(value) <= 220:
        return value
    return f"{value[:217]}..."


def _utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def _new_event_id() -> str:
    stamp = int(time.time() * 1000)
    token = secrets.token_hex(4)
    return f"evt-{stamp}-{token}"


def _line_event_id(payload: str) -> str:
    token = secrets.token_hex(4)
    return f"line-{abs(hash(payload))}-{token}"


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


def _depth_for_severity(severity: str) -> str:
    rank = SEVERITY_ORDER.get(severity, 0)
    if rank >= 3:
        return "deep"
    if rank >= 2:
        return "medium"
    return "light"


def _type2_recommendation(event_type: str, message: str) -> str:
    text = message.lower()
    kind = event_type.lower()

    if "another tako instance" in text or "instance lock" in text:
        return "Another Tako instance may be active here. Stop the duplicate process before continuing."
    if "xmtp import unavailable" in text or "no module named 'xmtp'" in text:
        return "Install dependencies via `./tako.sh` and retry XMTP pairing/runtime startup."
    if "dns lookup for xmtp" in text:
        return "Check network/DNS egress for XMTP hosts, then retry pairing or runtime startup."
    if "runtime crashed" in text or "runtime.crash" in kind:
        return "Enable safe mode, inspect `doctor` output, then restart XMTP runtime."
    if kind.startswith("health.check.issue"):
        return "Resolve reported health issue before proceeding with risky actions."
    return "Review the event details, then choose a safe next action or pause in safe mode."


def _dns_lookup_ok(host: str) -> bool:
    with contextlib.suppress(Exception):
        socket.gethostbyname(host)
        return True
    return False


def _dir_has_entries(path: Path) -> bool:
    with contextlib.suppress(FileNotFoundError):
        return any(path.iterdir())
    return False


async def _cancel_task(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
