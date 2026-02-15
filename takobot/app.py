from __future__ import annotations

import argparse
import asyncio
from collections import deque
import contextlib
import importlib.util
import json
import os
import platform
import random
import re
import secrets
import shutil
import socket
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from textual import events
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Footer, Input, Static, TextArea

from . import __version__
from .cli import DEFAULT_ENV, RuntimeHooks, _doctor_report, _run_daemon
from .conversation import ConversationStore
from .config import TakoConfig, explain_tako_toml, load_tako_toml, set_updates_auto_apply, set_workspace_name
from .daily import append_daily_note, ensure_daily_log
from . import dose
from .ens import DEFAULT_ENS_RPC_URLS, resolve_recipient
from .git_safety import assert_not_tracked, auto_commit_pending, ensure_local_git_identity, panic_check_runtime_secrets
from .inference import (
    CONFIGURABLE_API_KEY_VARS,
    SUPPORTED_PROVIDER_PREFERENCES,
    InferenceRuntime,
    clear_inference_api_key,
    discover_inference_runtime,
    format_inference_auth_inventory,
    format_runtime_lines,
    persist_inference_runtime,
    run_inference_prompt_with_fallback,
    set_inference_api_key,
    set_inference_ollama_host,
    set_inference_ollama_model,
    set_inference_preferred_provider,
    stream_inference_prompt_with_fallback,
)
from .identity import build_identity_name_prompt, extract_name_from_model_output, looks_like_name_change_request
from .input_history import InputHistory
from .keys import derive_eth_address, load_or_create_keys
from .locks import instance_lock
from .operator import clear_operator, get_operator_inbox_id, imprint_operator, load_operator
from .pairing import clear_pending
from .paths import code_root, daily_root, ensure_code_dir, ensure_runtime_dirs, repo_root, runtime_paths
from .problem_tasks import ensure_problem_tasks
from .self_update import run_self_update
from .skillpacks import seed_openclaw_starter_skills
from .soul import DEFAULT_SOUL_NAME, DEFAULT_SOUL_ROLE, read_identity, update_identity
from .tool_ops import fetch_webpage, run_local_command
from .xmtp import create_client, hint_for_xmtp_error, probe_xmtp_import
from .productivity import open_loops as prod_open_loops
from .productivity import outcomes as prod_outcomes
from .productivity import promote as prod_promote
from .productivity import summarize as prod_summarize
from .productivity import tasks as prod_tasks
from .productivity import weekly_review as prod_weekly
from .extensions.analyze import ManifestError, analyze_quarantine
from .extensions.enable import permissions_ok as ext_permissions_ok
from .extensions.enable import verify_integrity as ext_verify_integrity
from .extensions.install import InstallError, install_from_quarantine
from .extensions.draft import create_draft_extension
from .extensions.model import PermissionSet as ExtPermissionSet
from .extensions.model import QuarantineProvenance
from .extensions.quarantine import QuarantineError, fetch_to_quarantine
from .extensions.registry import (
    drop_pending as ext_drop_pending,
    get_installed as ext_get_installed,
    get_pending as ext_get_pending,
    list_installed as ext_list_installed,
    list_pending as ext_list_pending,
    record_installed as ext_record_installed,
    record_pending as ext_record_pending,
    set_enabled as ext_set_enabled,
)


HEARTBEAT_JITTER = 0.2
EVENT_INGEST_INTERVAL_S = 0.8
LOCAL_CHAT_TIMEOUT_S = 75.0
LOCAL_CHAT_MAX_CHARS = 700
ACTIVITY_LOG_MAX = 80
TRANSCRIPT_LOG_MAX = 2000
STREAM_BOX_MAX_CHARS = 8000
STREAM_BOX_MAX_STATUS_LINES = 40
INPUT_HISTORY_MAX = 200
CHAT_CONTEXT_USER_TURNS = 12
CHAT_CONTEXT_MAX_CHARS = 8_000
SLASH_MENU_MAX_ITEMS = 12
UPDATE_CHECK_INITIAL_DELAY_S = 20.0
UPDATE_CHECK_INTERVAL_S = 6 * 60 * 60
THINKING_SPINNER_FRAMES = ("⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏")
SLASH_COMMAND_SPECS: tuple[tuple[str, str], ...] = (
    ("/help", "Show command reference"),
    ("/status", "Show runtime status"),
    ("/stats", "Show counters and metrics"),
    ("/health", "Show health summary"),
    ("/config", "Explain tako.toml settings"),
    ("/models", "Show pi and inference auth config"),
    ("/dose", "Show or tune DOSE levels"),
    ("/task", "Create a task"),
    ("/tasks", "List tasks"),
    ("/done", "Mark a task done"),
    ("/morning", "Set today's outcomes"),
    ("/outcomes", "Show or update outcomes"),
    ("/compress", "Write daily summary"),
    ("/weekly", "Run weekly review"),
    ("/promote", "Promote note into MEMORY.md"),
    ("/inference", "Inference provider controls"),
    ("/doctor", "Run diagnostics"),
    ("/pair", "Start XMTP pairing"),
    ("/setup", "Run identity/routines onboarding"),
    ("/update", "Apply update or run check"),
    ("/upgrade", "Alias for /update"),
    ("/web", "Fetch webpage"),
    ("/run", "Run shell command in code/"),
    ("/install", "Install skill or tool"),
    ("/review", "Review pending installs"),
    ("/enable", "Enable extension"),
    ("/draft", "Draft extension scaffold"),
    ("/extensions", "List extensions"),
    ("/copy", "Copy transcript or last line"),
    ("/activity", "Show recent activity"),
    ("/safe", "Toggle safe mode"),
    ("/stop", "Alias safe on"),
    ("/resume", "Alias safe off"),
    ("/quit", "Quit app"),
)
LOCAL_COMMAND_COMPLETIONS: tuple[str, ...] = (
    "activity",
    "compress",
    "config",
    "copy",
    "doctor",
    "done",
    "dose",
    "draft",
    "enable",
    "exit",
    "extensions",
    "h",
    "health",
    "help",
    "inference",
    "install",
    "models",
    "morning",
    "outcomes",
    "pair",
    "profile",
    "promote",
    "quit",
    "reimprint",
    "resume",
    "review",
    "run",
    "safe",
    "setup",
    "stats",
    "status",
    "stop",
    "task",
    "tasks",
    "toml",
    "update",
    "upgrade",
    "web",
    "weekly",
)

SEVERITY_ORDER = {
    "info": 0,
    "warn": 1,
    "error": 2,
    "critical": 3,
}

ANSI_CSI_RE = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")
ANSI_OSC_RE = re.compile(r"\x1B\][^\x07\x1B]*(?:\x07|\x1B\\)")
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")


class SessionState(str, Enum):
    BOOTING = "BOOTING"
    ONBOARDING_IDENTITY = "ONBOARDING_IDENTITY"
    ONBOARDING_ROUTINES = "ONBOARDING_ROUTINES"
    ASK_XMTP_HANDLE = "ASK_XMTP_HANDLE"
    PAIRING_OUTBOUND = "PAIRING_OUTBOUND"
    PAIRED = "PAIRED"
    RUNNING = "RUNNING"


FIRST_INTERACTIVE_INFERENCE_STATES = {
    SessionState.ASK_XMTP_HANDLE,
    SessionState.PAIRING_OUTBOUND,
    SessionState.ONBOARDING_IDENTITY,
    SessionState.ONBOARDING_ROUTINES,
    SessionState.PAIRED,
    SessionState.RUNNING,
}


class TakoTerminalApp(App[None]):
    CSS = """
    Screen {
        layout: vertical;
    }

    #status-bar {
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

    #panel-octo {
        height: 12;
        border: solid $primary;
        margin: 0 0 1 0;
        padding: 0 1;
    }

    .panel {
        height: 1fr;
        border: solid $primary;
        margin: 0 0 1 0;
        padding: 0 1;
    }

    #input-box {
        margin: 0;
        border: solid $border-blurred;
    }

    #input-box:focus {
        border: solid $border;
    }

    #slash-menu {
        height: auto;
        max-height: 8;
        border: solid $secondary;
        margin: 0 0 1 0;
        padding: 0 1;
    }

    #stream-box {
        height: 7;
        border: solid $secondary;
        margin: 1 0 0 0;
        padding: 0 1;
    }

    Footer {
        dock: none;
    }
    """

    BINDINGS = [
        ("ctrl+c", "request_quit", "Quit"),
        ("f2", "toggle_safe_mode", "Safe Mode"),
        ("ctrl+shift+c", "copy_transcript", "Copy Transcript"),
        ("ctrl+shift+l", "copy_last_line", "Copy Last Line"),
        ("ctrl+shift+v", "paste_input", "Paste"),
        ("ctrl+v", "paste_input", "Paste"),
        ("shift+insert", "paste_input", "Paste"),
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
        self.code_dir: Path | None = None
        self.wallet_key = ""
        self.db_encryption_key = ""
        self.address = ""
        self.config: TakoConfig = TakoConfig()
        self.config_warning = ""

        self.identity_name = DEFAULT_SOUL_NAME
        self.identity_role = DEFAULT_SOUL_ROLE
        self.routines = ""

        self.operator_inbox_id: str | None = None
        self.operator_address: str | None = None
        self.operator_paired = False

        self.identity_step = 0
        self.awaiting_xmtp_handle = False
        self.identity_onboarding_pending = False

        self.pairing_handle = ""
        self.pairing_resolved = ""
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
        self.update_check_task: asyncio.Task[None] | None = None

        self.lock_context = None
        self.lock_acquired = False
        self.shutdown_complete = False

        self.event_log_path: Path | None = None
        self.app_log_path: Path | None = None
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
        self.last_git_autocommit_error = ""
        self.inference_runtime: InferenceRuntime | None = None
        self.inference_state_path: Path | None = None
        self.inference_last_provider = "none"
        self.inference_last_error = ""
        self.inference_gate_open = False
        self.inference_gate_opened_state = "none"
        self.inference_gate_opened_at: float | None = None
        self.inference_gate_block_noted = False
        self.inference_ever_used = False
        self.last_update_check_at: float | None = None
        self.last_update_check_signature = ""
        self.auto_updates_enabled = True
        self.last_auto_update_error = ""
        self.operator_requests_sent: set[str] = set()

        self.dose: dose.DoseState | None = None
        self.dose_path: Path | None = None
        self.dose_label = "unknown"
        self.dose_last_emitted_label = "unknown"

        self.open_loops_path: Path | None = None
        self.open_loops_summary: dict[str, Any] = {"count": 0, "oldest_age_s": 0.0, "top": []}
        self.open_tasks_count = 0
        self.signal_loops: deque[prod_open_loops.OpenLoop] = deque(maxlen=25)

        self.extensions_registry_path: Path | None = None
        self.quarantine_root: Path | None = None

        self.prompt_mode: str | None = None
        self.prompt_step = 0
        self.prompt_values: list[str] = []
        self.input_history = InputHistory(max_items=INPUT_HISTORY_MAX)
        self.conversations: ConversationStore | None = None

        self.activity_entries: deque[str] = deque(maxlen=ACTIVITY_LOG_MAX)
        self.transcript_lines: deque[str] = deque(maxlen=TRANSCRIPT_LOG_MAX)
        self.stream_provider = "none"
        self.stream_status_lines: list[str] = []
        self.stream_reply = ""
        self.stream_active = False
        self.stream_focus = ""
        self.stream_started_at: float | None = None
        self.stream_last_render_at = 0.0
        self._applying_tab_completion = False
        self.command_completion_seed = ""
        self.command_completion_matches: list[str] = []
        self.command_completion_index = -1

        self.status_bar: Static
        self.transcript: TextArea
        self.stream_box: TextArea
        self.input_box: Input
        self.slash_menu: Static
        self.octo_panel: Static
        self.tasks_panel: Static
        self.memory_panel: Static
        self.sensors_panel: Static
        self.activity_panel: Static

    def compose(self) -> ComposeResult:
        yield Static("", id="status-bar")
        with Horizontal(id="main"):
            yield TextArea(
                "",
                id="transcript",
                read_only=True,
                show_cursor=False,
                highlight_cursor_line=False,
                show_line_numbers=False,
                language=None,
            )
            with Vertical(id="sidebar"):
                yield Static("", id="panel-octo")
                yield Static("", id="panel-tasks", classes="panel")
                yield Static("", id="panel-memory", classes="panel")
                yield Static("", id="panel-sensors", classes="panel")
                yield Static("", id="panel-activity", classes="panel")
        yield TextArea(
            "",
            id="stream-box",
            read_only=True,
            show_cursor=False,
            highlight_cursor_line=False,
            show_line_numbers=False,
            placeholder="bubble stream: inference + tools will appear here while I'm working",
        )
        yield Input(id="input-box", placeholder="Type here. During onboarding, answer the current question.")
        yield Static("", id="slash-menu")
        yield Footer()

    def on_mount(self) -> None:
        self.status_bar = self.query_one("#status-bar", Static)
        self.transcript = self.query_one("#transcript", TextArea)
        self.stream_box = self.query_one("#stream-box", TextArea)
        self.input_box = self.query_one("#input-box", Input)
        self.slash_menu = self.query_one("#slash-menu", Static)
        self.octo_panel = self.query_one("#panel-octo", Static)
        self.tasks_panel = self.query_one("#panel-tasks", Static)
        self.memory_panel = self.query_one("#panel-memory", Static)
        self.sensors_panel = self.query_one("#panel-sensors", Static)
        self.activity_panel = self.query_one("#panel-activity", Static)
        self.slash_menu.display = False
        self._ensure_input_focus()
        self.set_interval(0.5, self._refresh_status)
        self._refresh_panels()
        self.boot_task = asyncio.create_task(self._boot())

    def on_resize(self, _: events.Resize) -> None:
        self.call_after_refresh(self._ensure_input_focus)

    def on_input_blurred(self, _: Input.Blurred) -> None:
        if self.input_box.disabled:
            return
        self.call_after_refresh(self._ensure_input_focus)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "input-box":
            return
        if not self._applying_tab_completion:
            self._reset_tab_completion_state()
        self._update_slash_menu(event.value)

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

    def action_copy_transcript(self) -> None:
        if not self.transcript_lines:
            self._write_system("clipboard: transcript is empty.")
            return
        payload = "\n".join(self.transcript_lines)
        self._copy_payload_to_clipboard(payload, summary=f"transcript ({len(self.transcript_lines)} lines)")
        self._add_activity("clipboard", "copied full transcript")

    def action_copy_last_line(self) -> None:
        if not self.transcript_lines:
            self._write_system("clipboard: no transcript lines yet.")
            return
        payload = self.transcript_lines[-1]
        self._copy_payload_to_clipboard(payload, summary="last transcript line")
        self._add_activity("clipboard", "copied last line")

    def action_paste_input(self) -> None:
        if self.input_box.disabled:
            return
        self._ensure_input_focus()
        pasted_text, backend = _paste_from_system_clipboard()
        if pasted_text:
            cleaned = _clean_paste_text(pasted_text)
            if cleaned:
                self.input_box.insert_text_at_cursor(cleaned)
                self._add_activity("clipboard", f"pasted from {backend}")
                return

        local_clipboard = self.clipboard or ""
        cleaned = _clean_paste_text(local_clipboard)
        if cleaned:
            self.input_box.insert_text_at_cursor(cleaned)
            self._add_activity("clipboard", "pasted local clipboard")
            return

        self._write_system("clipboard: no paste payload detected. try terminal paste or install `wl-paste`/`xclip`.")

    def _copy_payload_to_clipboard(self, payload: str, *, summary: str) -> None:
        self.copy_to_clipboard(payload)
        backend = _copy_to_system_clipboard(payload)
        fallback_path = _persist_clipboard_payload(self.paths.state_dir if self.paths is not None else None, payload)
        if backend:
            self._write_system(f"clipboard: copied {summary} via {backend}.")
            return
        if fallback_path:
            self._write_system(
                f"clipboard: sent {summary} via terminal OSC52; fallback saved to {fallback_path}."
            )
            return
        self._write_system(f"clipboard: sent {summary} via terminal OSC52.")

    def on_paste(self, event: events.Paste) -> None:
        if self.input_box.disabled or self.input_box.has_focus is False:
            return
        cleaned = _clean_paste_text(event.text)
        if cleaned == event.text:
            return
        event.stop()
        self.input_box.insert_text_at_cursor(cleaned)
        self._add_activity("clipboard", "sanitized pasted text")

    def on_key(self, event: events.Key) -> None:
        if event.key not in {"up", "down", "tab"}:
            return
        if self.input_box.disabled or self.input_box.has_focus is False:
            return

        if event.key == "tab":
            event.stop()
            self._apply_tab_completion()
            return

        if event.key == "up":
            replacement = self.input_history.navigate_up(self.input_box.value)
        else:
            replacement = self.input_history.navigate_down()
        if replacement is None:
            return

        event.stop()
        self.input_box.value = replacement
        self.input_box.cursor_position = len(replacement)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        raw_value = event.value
        text = _sanitize(event.value)
        if not text:
            if raw_value and _contains_terminal_control(raw_value):
                self._write_system("ignored terminal control-sequence noise; input focus restored.")
            self._ensure_input_focus()
            return
        self._hide_slash_menu()
        self._reset_tab_completion_state()
        self.input_history.add(text)
        event.input.value = ""

        self._write_user(text)
        self._set_indicator("thinking")
        try:
            await self._route_input(text)
        finally:
            if self.indicator == "thinking":
                self._set_indicator("idle")
            self._ensure_input_focus()

    async def _boot(self) -> None:
        self._set_state(SessionState.BOOTING)
        self.mode = "boot"
        self.runtime_mode = "offline"
        self._set_indicator("acting")
        self._write_tako("waking up... tiny octopus stretch complete.")
        self._add_activity("startup", "boot sequence started")

        try:
            self.paths = ensure_runtime_dirs(runtime_paths())
            self.app_log_path = self.paths.logs_dir / "app.log"
            self.conversations = ConversationStore(self.paths.state_dir)
            root = repo_root()
            self.code_dir = ensure_code_dir(root)
            self._add_activity("workspace", f"code dir ready: {self.code_dir}")

            cfg, warn = load_tako_toml(root / "tako.toml")
            self.config = cfg
            self.auto_updates_enabled = bool(cfg.updates.auto_apply)
            self.config_warning = warn
            if warn:
                self._write_system(warn)
                self._add_activity("config", f"warning: {warn}")
                self._record_event(
                    "config.load.warning",
                    warn,
                    severity="warn",
                    source="config",
                )
                self._request_operator_configuration(
                    key="config.tako_toml",
                    reason="could you please fix `tako.toml` so I can load workspace settings cleanly?",
                    next_steps=[
                        "run `doctor` to inspect current environment/config status",
                        "fix TOML syntax in `tako.toml`, then restart `takobot`",
                    ],
                )
            else:
                self._add_activity("config", "tako.toml loaded")
            self._add_activity("update", f"auto-updates {'on' if self.auto_updates_enabled else 'off'}")

            self.dose_path = self.paths.state_dir / "dose.json"
            try:
                self.dose = dose.load_or_create(
                    self.dose_path,
                    baseline=(
                        self.config.dose_baseline.d,
                        self.config.dose_baseline.o,
                        self.config.dose_baseline.s,
                        self.config.dose_baseline.e,
                    ),
                )
                # Catch up for downtime (capped inside tick).
                now = time.time()
                dt = now - float(self.dose.last_updated_ts)
                if dt > 0.0:
                    self.dose.tick(now, dt)
                    dose.save(self.dose_path, self.dose)
                self.dose_label = self.dose.label()
                self.dose_last_emitted_label = self.dose_label
                self._add_activity("dose", f"initialized (label={self.dose_label})")
                self._record_event(
                    "dose.started",
                    "DOSE engine initialized.",
                    source="dose",
                    metadata={"path": str(self.dose_path), "label": self.dose_label},
                )
            except Exception as exc:  # noqa: BLE001
                self.dose = dose.default_state()
                self.dose_label = self.dose.label()
                self.dose_last_emitted_label = self.dose_label
                self._write_system(f"dose init warning: {_summarize_error(exc)}")

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

            self.open_loops_path = self.paths.state_dir / "open_loops.json"
            self._refresh_open_loops(save=True)

            self.extensions_registry_path = self.paths.state_dir / "extensions.json"
            self.quarantine_root = self.paths.root / "quarantine"
            self.quarantine_root.mkdir(parents=True, exist_ok=True)
            seeded = seed_openclaw_starter_skills(root, registry_path=self.extensions_registry_path)
            if seeded.created_skills or seeded.registered_skills:
                self._add_activity(
                    "skills",
                    (
                        "starter skills synced "
                        f"(created={len(seeded.created_skills)} registered={len(seeded.registered_skills)})"
                    ),
                )
                append_daily_note(
                    daily_root(),
                    date.today(),
                    (
                        "OpenClaw starter skills synced: "
                        f"created={len(seeded.created_skills)} "
                        f"registered={len(seeded.registered_skills)}"
                    ),
                )

            self.identity_name, self.identity_role = read_identity()
            config_path = root / "tako.toml"
            configured_name = _sanitize_for_display(str(self.config.workspace.name or "")).strip()
            if configured_name.lower() in {"tako-workspace", "takobot-workspace"}:
                configured_name = ""
            if configured_name and configured_name != self.identity_name:
                previous_name = self.identity_name
                self.identity_name = configured_name
                self.identity_name, self.identity_role = update_identity(self.identity_name, self.identity_role)
                append_daily_note(
                    daily_root(),
                    date.today(),
                    f"Identity name synced from tako.toml: {previous_name} -> {self.identity_name}",
                )
                self._add_activity("identity", f"name synced from config ({self.identity_name})")
            elif self.identity_name:
                ok, _summary = set_workspace_name(config_path, self.identity_name)
                if ok:
                    refreshed_cfg, _warn2 = load_tako_toml(config_path)
                    self.config = refreshed_cfg
                    self._add_activity("config", "workspace.name synced from identity")
            self.instance_kind = (
                "established"
                if keys_preexisting or operator_preexisting or xmtp_db_preexisting or state_preexisting
                else "brand-new"
            )

            self._initialize_inference_runtime()
            await self._initialize_reasoning_runtime()
            await self._run_startup_health_check(
                keys_preexisting=keys_preexisting,
                operator_preexisting=operator_preexisting,
                xmtp_db_preexisting=xmtp_db_preexisting,
                state_preexisting=state_preexisting,
            )

            self._write_tako(f"all set! my XMTP address is {self.address}.")
            self._add_activity("xmtp", f"wallet address ready: {self.address[:12]}...")

            operator_cfg = load_operator(self.paths.operator_json)
            self.operator_inbox_id = get_operator_inbox_id(operator_cfg)
            if operator_cfg and isinstance(operator_cfg.get("operator_address"), str):
                self.operator_address = operator_cfg.get("operator_address")

            if self.operator_inbox_id:
                self.operator_paired = True
                self.mode = "paired"
                self._set_state(SessionState.PAIRED)
                self._write_tako("operator imprint found. XMTP is already my control current for config changes.")
                self._add_activity("xmtp", "operator imprint detected; starting runtime")
                await self._start_xmtp_runtime()
                self._set_state(SessionState.RUNNING)
                self._write_tako("terminal is now your local cockpit. chat works here too. type `help`.")
                if self._today_outcomes_blank():
                    self._write_tako("tiny morning bubble: type `morning` to set 3 outcomes that make today a win.")
                return

            self.operator_paired = False
            self.mode = "onboarding"
            self._set_state(SessionState.ASK_XMTP_HANDLE)
            self.awaiting_xmtp_handle = False
            self._write_tako(
                "first tentacle task, ASAP: let's set up your XMTP control channel. "
                "do you have an XMTP handle? (yes/no)\n"
                "we'll do identity/goals after inference currents are awake."
            )
            if self._today_outcomes_blank():
                self._write_tako("also: type `morning` any time to set 3 outcomes for today.")
        except Exception as exc:  # noqa: BLE001
            self._error_card(
                "startup blocked",
                str(exc),
                [
                    "Check repo safety constraints (.tako secrets must not be tracked).",
                    "Resolve the issue, then restart `takobot`.",
                ],
            )
            self.input_box.disabled = True
        finally:
            self._set_indicator("idle")

    def _today_outcomes_blank(self) -> bool:
        try:
            daily_path = ensure_daily_log(daily_root(), date.today())
            prod_outcomes.ensure_outcomes_section(daily_path)
            outcomes = prod_outcomes.get_outcomes(daily_path)
            return not any(item.text.strip() for item in outcomes)
        except Exception:
            return False

    def _request_operator_configuration(self, *, key: str, reason: str, next_steps: list[str]) -> None:
        token = key.strip().lower()
        if token in self.operator_requests_sent:
            return
        self.operator_requests_sent.add(token)
        lines = [f"operator request: {reason}"]
        for step in next_steps:
            lines.append(f"- {step}")
        message = "\n".join(lines)
        self._write_tako(message)
        self._add_activity("operator", f"request: {reason}")
        self._record_event(
            "operator.request.configuration",
            reason,
            source="operator",
            metadata={"request_key": token, "next_steps": list(next_steps)},
        )

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
        await self._start_periodic_update_checks()

        self._write_system("Type1 tide scanner online. Consuming event log and triaging signals.")
        self._add_activity("reasoning", "Type1/Type2 loops online")
        self._record_event(
            "reasoning.engine.started",
            "Type1/Type2 reasoning loops started.",
            source="startup",
            metadata={"event_log": str(self.event_log_path)},
        )

    def _initialize_inference_runtime(self) -> None:
        if self.paths is None:
            return

        try:
            runtime = discover_inference_runtime()
            self.inference_runtime = runtime
            self.inference_last_error = ""
            self.inference_last_provider = runtime.selected_provider or "none"
            self.inference_state_path = self.paths.state_dir / "inference.json"
            persist_inference_runtime(self.inference_state_path, runtime)

            selected = runtime.selected_provider or "none"
            ready = "yes" if runtime.ready else "no"
            source = runtime.selected_key_source or "none"
            self._write_system(f"inference bridge: provider={selected} ready={ready} source={source}")
            self._add_activity("inference", f"discovered provider={selected} ready={ready}")
            self._record_event(
                "inference.runtime.detected",
                f"Inference discovery complete. selected={selected}; ready={ready}; source={source}",
                source="startup",
                metadata={
                    "selected_provider": selected,
                    "ready": ready,
                    "key_source": source,
                    "state_file": str(self.inference_state_path),
                },
            )
        except Exception as exc:  # noqa: BLE001
            self.inference_runtime = None
            self.inference_last_error = _summarize_error(exc)
            self.inference_last_provider = "none"
            self._write_system(f"inference discovery warning: {self.inference_last_error}")
            self._add_activity("inference", f"discovery warning: {self.inference_last_error}")
            self._record_event(
                "inference.runtime.error",
                f"Inference discovery failed: {exc}",
                severity="warn",
                source="startup",
            )

    def _maybe_open_inference_gate_for_turn(self, text: str) -> None:
        if self.inference_gate_open:
            return
        if not text.strip():
            return
        if self.state not in FIRST_INTERACTIVE_INFERENCE_STATES:
            return

        self.inference_gate_open = True
        self.inference_gate_opened_state = self.state.value
        self.inference_gate_opened_at = time.monotonic()
        self.inference_gate_block_noted = False
        self._write_system(
            f"inference gate opened on first interactive turn (state={self.inference_gate_opened_state})."
        )
        self._add_activity("inference", f"gate opened in state={self.inference_gate_opened_state}")
        self._record_event(
            "inference.gate.opened",
            "Inference gate opened after first interactive user turn.",
            source="session",
            metadata={"state": self.inference_gate_opened_state},
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
        xmtp_import_ok, xmtp_import_status = probe_xmtp_import()
        web3_import_ok = importlib.util.find_spec("web3") is not None
        textual_import_ok = importlib.util.find_spec("textual") is not None
        git_identity_ok, git_identity_detail, git_identity_auto_configured = ensure_local_git_identity(
            repo_root(),
            identity_name=self.identity_name,
        )
        if git_identity_ok and git_identity_auto_configured:
            self._add_activity("git", f"identity auto-configured ({git_identity_detail})")
            self._record_event(
                "git.identity.autoconfigured",
                f"Git identity auto-configured: {git_identity_detail}",
                source="runtime",
            )

        self.health_summary = {
            "instance_kind": self.instance_kind,
            "lock": "ok" if self.lock_acquired else "missing",
            "workspace_writable": _yes_no(os.access(repo_root(), os.W_OK)),
            "runtime_writable": _yes_no(os.access(self.paths.root, os.W_OK)),
            "disk_free_mb": str(disk_free_mb),
            "keys_preexisting": _yes_no(keys_preexisting),
            "operator_preexisting": _yes_no(operator_preexisting),
            "xmtp_db_preexisting": _yes_no(xmtp_db_preexisting),
            "state_preexisting": _yes_no(state_preexisting),
            "xmtp_import": _yes_no(xmtp_import_ok),
            "xmtp_import_status": xmtp_import_status,
            "web3_import": _yes_no(web3_import_ok),
            "textual_import": _yes_no(textual_import_ok),
            "git_identity_configured": _yes_no(git_identity_ok),
            "git_identity_status": git_identity_detail,
            "git_identity_auto_configured": _yes_no(git_identity_auto_configured),
            "dns_xmtp": _yes_no(dns_xmtp_ok),
            "python": platform.python_version(),
        }
        if self.inference_runtime is not None:
            self.health_summary["inference_selected"] = self.inference_runtime.selected_provider or "none"
            self.health_summary["inference_ready"] = _yes_no(self.inference_runtime.ready)
            self.health_summary["inference_key_source"] = self.inference_runtime.selected_key_source or "none"
            self.health_summary["inference_gate"] = "open" if self.inference_gate_open else "closed"
            self.health_summary["inference_start_mode"] = "first_interactive_turn"
            for provider, status in sorted(self.inference_runtime.statuses.items()):
                self.health_summary[f"inference_{provider}_cli"] = _yes_no(status.cli_installed)
                self.health_summary[f"inference_{provider}_ready"] = _yes_no(status.ready)
                self.health_summary[f"inference_{provider}_auth"] = status.auth_kind

        issues: list[tuple[str, str]] = []
        if not self.lock_acquired:
            issues.append(("critical", "Instance lock is not held."))
        if not os.access(repo_root(), os.W_OK):
            issues.append(("error", "Workspace directory is not writable."))
        if disk_free_mb < 256:
            issues.append(("warn", f"Low disk space under .tako: {disk_free_mb} MB free."))
        if not xmtp_import_ok:
            issues.append(("warn", f"xmtp import unavailable; {xmtp_import_status}"))
        if not git_identity_ok:
            issues.append(("warn", f"git identity unavailable; {git_identity_detail}"))
        if not dns_xmtp_ok:
            issues.append(("warn", "DNS lookup for XMTP host failed; outbound XMTP connectivity may be unavailable."))
        if self.inference_runtime is None:
            issues.append(("warn", "Inference runtime discovery was not initialized."))
        elif not self.inference_runtime.ready:
            issues.append(("warn", "No ready inference provider found (pi/ollama/codex/claude/gemini)."))
            for hint in _inference_setup_hints(self.inference_runtime):
                issues.append(("info", f"inference hint: {hint}"))
        elif not self.inference_gate_open:
            issues.append(("info", "Inference execution is gated until the first interactive turn."))

        health_line = (
            f"health check: {self.instance_kind} instance | "
            f"lock={self.health_summary['lock']} | "
            f"disk_free_mb={disk_free_mb} | "
            f"xmtp_import={self.health_summary['xmtp_import']} | "
            f"dns_xmtp={self.health_summary['dns_xmtp']} | "
            f"inference={self.health_summary.get('inference_selected', 'none')}/"
            f"{self.health_summary.get('inference_ready', 'no')} | "
            f"inference_gate={self.health_summary.get('inference_gate', 'closed')}"
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
            if severity == "info":
                self._write_system(f"health hint: {message}")
                self._record_event("health.check.hint", message, severity="info", source="health")
                continue
            self._write_system(f"health issue [{severity}]: {message}")
            self._record_event("health.check.issue", message, severity=severity, source="health")

        issue_problems = [message for severity, message in issues if severity in {"warn", "error", "critical"}]
        if issue_problems:
            records = ensure_problem_tasks(repo_root(), issue_problems, source="startup-health")
            created = [record for record in records if record.created]
            if created:
                self._add_activity("tasks", f"problem tasks created: {', '.join(record.task_id for record in created[:3])}")
            elif records:
                self._add_activity("tasks", "problem tasks already open")

        if not git_identity_ok:
            self._request_operator_configuration(
                key="git.identity",
                reason="I couldn't auto-configure git identity for clean commit attribution; could you please configure `user.name` and `user.email` manually?",
                next_steps=[
                    "run `git config --global user.name \"Your Name\"`",
                    "run `git config --global user.email \"you@example.com\"`",
                    "or set repo-local values: `git config user.name \"Your Name\"` + `git config user.email \"you@example.com\"`",
                ],
            )
        if not xmtp_import_ok:
            self._request_operator_configuration(
                key="deps.xmtp",
                reason="could you please install XMTP support so pairing/runtime messaging can run?",
                next_steps=[
                    "run `.venv/bin/pip install --upgrade takobot xmtp`",
                    "restart `takobot` and run `doctor`",
                ],
            )

    def _record_event(
        self,
        event_type: str,
        message: str,
        *,
        severity: str = "info",
        source: str = "system",
        metadata: dict[str, Any] | None = None,
    ) -> None:
        safe_message = _sanitize_for_display(message)
        event = {
            "id": _new_event_id(),
            "ts": _utc_now_iso(),
            "type": event_type,
            "severity": severity.lower(),
            "source": source,
            "message": safe_message,
            "metadata": metadata or {},
        }

        if self.dose is not None:
            try:
                self.dose.apply_event(
                    str(event.get("type", "")),
                    str(event.get("severity", "info")),
                    str(event.get("source", "system")),
                    str(event.get("message", "")),
                    event.get("metadata") if isinstance(event.get("metadata"), dict) else {},
                )
                self.dose_label = self.dose.label()
            except Exception as exc:  # noqa: BLE001
                self._write_system(f"dose update warning: {_summarize_error(exc)}")

        self._maybe_capture_signal_loop(event)

        if self.event_log_path is None:
            self.pending_events.append(event)
        else:
            self._append_event_to_log(event)

        self._enqueue_type1_event(event)

    def _maybe_capture_signal_loop(self, event: dict[str, Any]) -> None:
        severity = str(event.get("severity", "info")).lower()
        if severity not in {"warn", "error", "critical"}:
            return
        source = str(event.get("source", "")).lower()
        if source in {"type1", "type2", "dose"}:
            return
        event_type = str(event.get("type", "")).lower()
        if event_type.startswith(("heartbeat.", "inference.chat.", "xmtp.inbound.message", "productivity.")):
            return

        capture_prefixes = (
            "health.check.issue",
            "runtime.",
            "pairing.outbound.send_failed",
            "pairing.outbound.resolve_failed",
            "inference.runtime.error",
            "inference.error",
            "ui.error_card",
        )
        if not event_type.startswith(capture_prefixes):
            return

        title = f"{event.get('type', 'signal')}: {event.get('message', '')}"
        now = time.time()
        self.signal_loops.appendleft(
            prod_open_loops.OpenLoop(
                id=f"signal:{event.get('id', '')}",
                kind="signal",
                title=_summarize_text(_sanitize_for_display(str(title))),
                created_ts=now,
                updated_ts=now,
                source=source or "system",
            )
        )

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
        model_used = "heuristic"
        if self.inference_runtime is not None and self.inference_runtime.ready and self.inference_gate_open:
            self._add_activity("inference", f"Type2[{depth}] -> requesting model reasoning")
            prompt = _build_type2_prompt(event=event, depth=depth, reason=reason, fallback=recommendation)
            try:
                self._record_event(
                    "inference.request",
                    "Type2 requested inference from discovery-selected provider set.",
                    source="inference",
                    metadata={
                        "selected_provider": self.inference_runtime.selected_provider or "none",
                        "depth": depth,
                        "event_type": event_type,
                    },
                )
                provider, model_output = await asyncio.to_thread(
                    run_inference_prompt_with_fallback,
                    self.inference_runtime,
                    prompt,
                    timeout_s=_type2_inference_timeout(depth),
                )
                cleaned = _sanitize_for_display(model_output).strip()
                if cleaned:
                    recommendation = _summarize_text(cleaned)
                    model_used = provider
                    self.inference_ever_used = True
                    self.inference_last_provider = provider
                    self.inference_last_error = ""
                    self._add_activity("inference", f"Type2[{depth}] used provider={provider}")
            except Exception as exc:  # noqa: BLE001
                self.inference_last_error = _summarize_error(exc)
                self._write_system(
                    f"inference warning: {self.inference_last_error}. falling back to heuristics."
                )
                self._add_activity("inference", f"Type2 fallback due to error: {self.inference_last_error}")
                self._record_event(
                    "inference.error",
                    f"Inference provider chain failed: {exc}",
                    severity="warn",
                    source="inference",
                    metadata={
                        "selected_provider": self.inference_runtime.selected_provider or "none",
                        "depth": depth,
                        "event_type": event_type,
                    },
                )
        elif self.inference_runtime is not None and self.inference_runtime.ready and not self.inference_gate_open:
            model_used = "heuristic:gate-closed"
            if not self.inference_gate_block_noted:
                self.inference_gate_block_noted = True
                self._write_system(
                    "inference gate is closed until the first interactive turn; Type2 is using heuristics for now."
                )
                self._add_activity("inference", "Type2 blocked: gate is closed")
                self._record_event(
                    "inference.gate.blocked",
                    "Inference call skipped because gate is closed before first interactive turn.",
                    source="inference",
                    metadata={"event_type": event_type, "depth": depth},
                )
        self.type2_escalations += 1
        self.type2_last = f"{event_type}:{depth}:{model_used}"
        self._write_system(f"Type2[{depth}] ({model_used}): {recommendation}")
        append_daily_note(
            daily_root(),
            date.today(),
            f"Type2 escalation ({depth}) on {event_type} via {model_used}: {reason}. Recommendation: {recommendation}",
        )
        self._record_event(
            "type2.result",
            recommendation,
            source="type2",
            metadata={"event_type": event_type, "depth": depth, "reason": reason, "model_used": model_used},
        )

    def _assess_event_for_type2(self, event: dict[str, Any]) -> tuple[bool, str, str]:
        source = str(event.get("source", "")).lower()
        if source in {"type1", "type2"}:
            return False, "light", "already processed by cognition loop"

        severity = str(event.get("severity", "info")).lower()
        event_type = str(event.get("type", "")).lower()
        message = str(event.get("message", "")).lower()

        stability = None
        if self.dose is not None:
            stability = (float(self.dose.s) + float(self.dose.e)) / 2.0
        cautious = stability is not None and stability < 0.45
        calm = stability is not None and stability > 0.75

        if severity in {"critical", "error"}:
            depth = _depth_for_severity(severity)
            return True, depth, f"severity={severity}"

        if "another tako instance" in message or "instance lock" in message:
            return True, "deep", "duplicate-instance risk"

        if event_type.startswith("health.check.issue"):
            if severity == "warn" and calm:
                return False, "light", "startup health issue (tolerated)"
            reason = "startup health issue"
            if severity == "warn" and cautious:
                reason += " (cautious)"
            return True, "medium", reason

        if event_type.startswith("runtime.") and severity == "warn":
            if event_type.startswith("runtime.crash") or "crash" in message:
                return True, "medium", "runtime crash"
            if "unstable" in message:
                return True, "medium", "runtime instability"
            if event_type.startswith("runtime.polling") or "polling fallback" in message or "switching to polling" in message:
                if calm:
                    return False, "light", "runtime polling tolerated"
                return True, "medium", "runtime polling fallback"
            if cautious and (event_type.startswith("runtime.reconnect") or "reconnecting" in message or "retrying" in message):
                return True, "light", "runtime reconnect churn (cautious)"

        if event_type.startswith("runtime.polling") and severity == "info" and cautious:
            return True, "light", "runtime polling (cautious)"

        return False, "light", "type1 handled"

    async def _route_input(self, text: str) -> None:
        if self.state == SessionState.BOOTING:
            self._write_tako("still booting. give me a moment.")
            return

        if self.prompt_mode is not None:
            await self._handle_prompt_input(text)
            return

        self._maybe_open_inference_gate_for_turn(text)

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
        await self._maybe_start_delayed_identity_onboarding()

    async def _handle_prompt_input(self, text: str) -> None:
        mode = self.prompt_mode
        if mode == "morning_outcomes":
            lowered = text.strip().lower()
            if lowered in {"skip", "later", "cancel", "stop"}:
                self.prompt_mode = None
                self.prompt_step = 0
                self.prompt_values = []
                self._write_tako("okie. whenever you're ready: type `morning` to set today's 3 outcomes.")
                self._refresh_open_loops(save=True)
                return

            # Allow sending multiple outcomes in one message.
            parts = [part.strip() for part in re.split(r"[;\n]+", text) if part.strip()]
            if not parts:
                self._write_tako("tiny bubble: send an outcome (or `skip`).")
                return
            self.prompt_values.extend(parts)
            self.prompt_values = self.prompt_values[:3]
            self.prompt_step = len(self.prompt_values)

            if self.paths is None:
                self._write_tako("can't write outcomes yet: runtime paths missing.")
                return

            if self.prompt_step >= 3:
                daily_path = ensure_daily_log(daily_root(), date.today())
                prod_outcomes.set_outcomes(daily_path, self.prompt_values)
                append_daily_note(
                    daily_root(),
                    date.today(),
                    "Set 3 outcomes for today via `morning`.",
                )
                self._record_event(
                    "outcomes.set",
                    "Daily outcomes set.",
                    source="terminal",
                    metadata={"count": 3},
                )
                self._add_activity("outcomes", "set 3 outcomes")
                self._write_tako("splashy. outcomes set. you can check them with `outcomes` and mark done with `outcomes done 1`.")
                self.prompt_mode = None
                self.prompt_step = 0
                self.prompt_values = []
                self._refresh_open_loops(save=True)
                return

            next_idx = self.prompt_step + 1
            self._write_tako(f"cute. outcome {next_idx}? (or send multiple separated by `;`)")
            self._refresh_open_loops(save=True)
            return

        # Unknown prompt mode: clear it defensively.
        self.prompt_mode = None
        self.prompt_step = 0
        self.prompt_values = []

    async def _handle_identity_onboarding(self, text: str) -> None:
        lowered = text.strip().lower()
        if lowered in {"skip", "later"}:
            self._write_tako("copy that. whenever you want, just tell me what to call myself and what my purpose is.")
            self.identity_onboarding_pending = False
            self._set_state(SessionState.RUNNING)
            return

        if self.identity_step == 0:
            if lowered in {"keep", "same", "default"}:
                self._write_tako(f"okay, I'll keep `{self.identity_name}` for now.")
                self.identity_step = 1
                self._write_tako("cute. and what should my purpose be? one sentence is perfect.")
                return

            parsed_name = await self._infer_identity_name(text)
            if not parsed_name:
                self._write_tako(
                    "tiny clarification bubble: inference couldn't isolate a confident name yet. "
                    "you can retry with just the name, like `SILLYTAKO`."
                )
                return

            self.identity_name = parsed_name
            self.identity_step = 1
            self._write_tako(f"adorable. `{self.identity_name}` it is. and what should my purpose be? one sentence is perfect.")
            return

        self.identity_role = text or self.identity_role
        self.identity_name, self.identity_role = update_identity(self.identity_name, self.identity_role)
        ok_name, summary_name = set_workspace_name(repo_root() / "tako.toml", self.identity_name)
        if not ok_name:
            self._write_system(f"name sync warning: {summary_name}")
        else:
            refreshed_cfg, _warn2 = load_tako_toml(repo_root() / "tako.toml")
            self.config = refreshed_cfg
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
        self._add_activity("identity", f"name/role updated ({self.identity_name})")
        self._write_tako(f"identity tucked away in my little shell: {self.identity_name} — {self.identity_role}")
        self._set_state(SessionState.ONBOARDING_ROUTINES)
        self._write_tako("last onboarding nibble: what should I watch or do daily? free-form note.")

    async def _handle_routines_onboarding(self, text: str) -> None:
        if text.strip().lower() in {"skip", "later"}:
            self.routines = "No explicit routines yet."
        else:
            self.routines = text or "No explicit routines yet."
        if self.paths is not None:
            routines_path = self.paths.state_dir / "routines.txt"
            routines_path.write_text(self.routines + "\n", encoding="utf-8")
        append_daily_note(daily_root(), date.today(), f"Routine note captured: {self.routines}")
        self._record_event("onboarding.routines.saved", "Routine preferences captured.", source="onboarding")
        self._add_activity("identity", "daily routines captured")
        await self._finalize_onboarding()

    async def _handle_xmtp_handle_prompt(self, text: str) -> None:
        lowered = text.strip().lower()
        if lowered in {"local", "local-only", "skip"}:
            self._record_event("pairing.user.local_only", "Operator chose local-only mode.", source="pairing")
            self._add_activity("pairing", "operator chose local-only mode")
            if self.mode == "onboarding":
                self._write_tako("no worries, captain. we'll keep paddling locally for now.")
                await self._enter_local_only_mode()
                self._schedule_identity_onboarding_after_awake()
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
            self._add_activity("pairing", "operator has XMTP handle")
            self._write_tako("splash it over: share the handle (.eth or 0x...).")
            return

        if self.mode == "onboarding":
            self._record_event("pairing.user.no_handle", "Operator has no XMTP handle yet.", source="pairing")
            self._write_tako("got it. we'll continue in local mode first, and you can pair later with `pair`.")
            await self._enter_local_only_mode()
            self._schedule_identity_onboarding_after_awake()
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
        self._add_activity("pairing", f"starting outbound pairing to {handle}")
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
            self._add_activity("pairing", f"resolve failed: {_summarize_error(exc)}")
            self._set_state(SessionState.ASK_XMTP_HANDLE)
            self.awaiting_xmtp_handle = True
            self._set_indicator("idle")
            return

        host = socket.gethostname()
        outbound_message = (
            f"Hi from Tako on {host}!\n\n"
            "Pairing is automatic in this setup; I assume you're ready to talk.\n"
            "Reply `help` and I'll answer."
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
            stressed = self.dose is not None and self.dose_label == "stressed"
            if stressed:
                next_steps = [
                    "Type `local-only` to keep working without XMTP pairing.",
                    "Type `retry` to attempt pairing again.",
                    "If the network feels wobbly: check DNS/egress, then try again later.",
                ]
            else:
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
            self._add_activity("pairing", f"DM failed: {_summarize_error(exc)}")
            await self._cleanup_pairing_resources()
            self._set_state(SessionState.PAIRING_OUTBOUND)
            self._set_indicator("idle")
            return

        self.pairing_client = client
        self.pairing_dm = dm
        self.pairing_resolved = resolved
        self.pairing_operator_inbox_id = operator_inbox_id
        self.pairing_completed = False

        self._write_tako(f"outbound pairing DM sent to {handle} ({resolved}). assuming the other side is ready.")
        self._add_activity("pairing", f"DM sent; auto-confirming {resolved}")
        self._record_event(
            "pairing.outbound.sent",
            "Outbound pairing DM sent.",
            source="pairing",
            metadata={"resolved": resolved},
        )
        await self._complete_pairing("outbound_assumed_ready_v1")
        self._set_indicator("idle")

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
                self._write_tako("roger that. we'll keep things local.")
                await self._enter_local_only_mode()
                self._schedule_identity_onboarding_after_awake()
                return
            await self._enter_local_only_mode()
            return

        self._write_tako("pairing is automatic now. commands: `retry`, `change`, `local-only`")

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
        self._add_activity("pairing", f"paired with {self.pairing_resolved}")

        await self._cleanup_pairing_resources()

        self._set_state(SessionState.PAIRED)
        self._write_tako("paired! XMTP is now primary control channel for identity/config/tools/routines.")
        self._record_event(
            "pairing.completed",
            "Operator pairing completed successfully.",
            source="pairing",
            metadata={"operator_address": self.pairing_resolved, "pairing_method": pairing_method},
        )
        await self._start_xmtp_runtime()
        self._set_state(SessionState.RUNNING)
        self._write_tako("all tentacles online. chat is open here too. type `help`.")
        self._schedule_identity_onboarding_after_awake()

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
        self._add_activity("runtime", "entered local-only mode")
        self._record_event("runtime.local_mode", "Running in local-only mode.", source="startup")

    async def _finalize_onboarding(self) -> None:
        if self.operator_paired:
            self.mode = "paired"
            self._record_event("onboarding.completed", "Onboarding completed with operator pairing.", source="onboarding")
            self._set_state(SessionState.RUNNING)
            self._write_tako("identity + routines updated. current stays strong.")
            return

        self.mode = "local-only"
        self._record_event("onboarding.completed", "Onboarding completed in local-only mode.", source="onboarding")
        self._set_state(SessionState.RUNNING)
        self._write_tako("identity + routines updated. local mode stays active.")

    def _begin_identity_onboarding(self) -> None:
        self.mode = "onboarding"
        self._set_state(SessionState.ONBOARDING_IDENTITY)
        self.identity_step = 0
        self.identity_onboarding_pending = False
        self._add_activity("identity", "interactive identity setup started")
        self._record_event("onboarding.identity.begin", "Identity prompt phase started.", source="onboarding")
        if self.identity_name.strip() == DEFAULT_SOUL_NAME:
            self._write_tako(
                "next tiny question: I'm still on my default name (`Tako`). "
                "what name would you like me to use? you can type just the name, or say "
                "`your name can be SILLYTAKO`."
            )
            return
        self._write_tako(
            f"next tiny question: should I keep `{self.identity_name}`, or do you want a new name? "
            "you can type just the name or `keep`."
        )

    def _schedule_identity_onboarding_after_awake(self) -> None:
        self.identity_onboarding_pending = True
        self._write_tako("once inference is awake, I'll ask about name/goals/routines.")
        self._add_activity("identity", "identity setup queued until inference is active")

    async def _maybe_start_delayed_identity_onboarding(self) -> None:
        if not self.identity_onboarding_pending:
            return
        if not self._inference_is_awake():
            return
        self.identity_onboarding_pending = False
        self._write_tako("inference is awake now. want to tune my identity and goals? let's do it.")
        self._begin_identity_onboarding()

    def _inference_is_awake(self) -> bool:
        return bool(
            self.inference_runtime is not None
            and self.inference_runtime.ready
            and self.inference_gate_open
            and self.inference_ever_used
        )

    async def _start_xmtp_runtime(self) -> None:
        if self.paths is None:
            self._write_tako("cannot start XMTP runtime: paths unavailable.")
            return
        if self.safe_mode:
            self.runtime_mode = "safe"
            self._write_tako("safe mode is enabled; XMTP runtime is paused.")
            return

        await self._stop_xmtp_runtime()

        hooks = RuntimeHooks(
            log=self._on_runtime_log,
            inbound_message=self._on_runtime_inbound,
            emit_console=False,
            log_file=self.paths.logs_dir / "runtime.log",
        )
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

    async def _start_periodic_update_checks(self) -> None:
        if self.update_check_task is not None:
            return
        self.update_check_task = asyncio.create_task(self._periodic_update_check_loop(), name="tako-update-check")
        self._record_event("update.check.loop.started", "Periodic update checks started.", source="update")

    async def _stop_periodic_update_checks(self) -> None:
        if self.update_check_task is None:
            return
        self.update_check_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.update_check_task
        self.update_check_task = None
        self._record_event("update.check.loop.stopped", "Periodic update checks stopped.", source="update")

    async def _periodic_update_check_loop(self) -> None:
        await asyncio.sleep(UPDATE_CHECK_INITIAL_DELAY_S)
        while True:
            await self._run_periodic_update_check()
            await asyncio.sleep(UPDATE_CHECK_INTERVAL_S)

    async def _run_periodic_update_check(self) -> None:
        try:
            result = await asyncio.to_thread(run_self_update, repo_root(), apply=False)
        except Exception as exc:  # noqa: BLE001
            summary = f"update check failed: {_summarize_error(exc)}"
            if summary == self.last_update_check_signature:
                return
            self.last_update_check_signature = summary
            self.last_update_check_at = time.monotonic()
            self._add_activity("update", summary)
            self._record_event("update.check.error", summary, severity="warn", source="update")
            return

        detail = result.details[0] if result.details else ""
        signature = f"{result.ok}|{result.summary}|{detail}"
        self.last_update_check_at = time.monotonic()
        update_available = result.ok and result.summary == "update available."
        if signature == self.last_update_check_signature and not (update_available and self.auto_updates_enabled):
            return
        self.last_update_check_signature = signature

        if update_available:
            append_daily_note(daily_root(), date.today(), f"Periodic update check: {result.summary}")
            if self.auto_updates_enabled:
                await self._apply_auto_update(detail)
                return

            message = "package update available. run `update` to apply."
            if detail:
                message = f"{message} ({detail})"
            self._write_system(message)
            self._add_activity("update", _summarize_text(message))
            self._record_event("update.check.available", message, source="update")
            return

        if not result.ok:
            self._add_activity("update", f"check warning: {result.summary}")
            self._record_event("update.check.error", result.summary, severity="warn", source="update")
            return

        self.last_auto_update_error = ""
        self._add_activity("update", f"check: {result.summary}")
        self._record_event("update.check.ok", result.summary, source="update")

    async def _apply_auto_update(self, detail: str) -> None:
        message = "package update available. auto-update is on; applying now."
        if detail:
            message = f"{message} ({detail})"
        self._write_system(message)
        self._add_activity("update", "auto-update applying")
        self._record_event("update.auto.apply.start", message, source="update", metadata={"detail": detail})

        try:
            result = await asyncio.to_thread(run_self_update, repo_root(), apply=True)
        except Exception as exc:  # noqa: BLE001
            summary = f"auto-update failed: {_summarize_error(exc)}"
            if summary != self.last_auto_update_error:
                self.last_auto_update_error = summary
                self._write_system(summary)
                self._add_activity("update", summary)
                self._record_event("update.auto.apply.error", summary, severity="warn", source="update")
            return

        lines = [result.summary, *result.details]
        self._write_system("\n".join(lines))
        self._add_activity("update", f"auto-apply: {result.summary}")
        self._record_event(
            "update.auto.apply.result",
            result.summary,
            severity="info" if result.ok else "warn",
            source="update",
            metadata={"changed": result.changed},
        )

        if not result.ok:
            summary = f"auto-update failed: {result.summary}"
            if summary != self.last_auto_update_error:
                self.last_auto_update_error = summary
                self._write_system(summary)
            return

        self.last_auto_update_error = ""
        if result.changed:
            append_daily_note(daily_root(), date.today(), "Auto-update applied; restarting terminal app.")
            await self._restart_after_auto_update()

    async def _restart_after_auto_update(self) -> None:
        self._write_system("auto-update applied. restarting takobot now.")
        self._add_activity("update", "restarting after auto-update")
        self._record_event("runtime.restart", "Restarting after auto-update.", source="update")
        await asyncio.sleep(0.2)
        argv_tail = [arg for arg in sys.argv[1:] if arg]
        if not argv_tail:
            argv_tail = ["app", "--interval", str(self.interval)]
        args = [sys.executable, "-m", "takobot", *argv_tail]
        try:
            os.execv(sys.executable, args)
        except OSError as exc:
            summary = f"auto-restart failed: {_summarize_error(exc)}"
            self._write_system(summary)
            self._record_event("runtime.restart.error", summary, severity="warn", source="update")

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
                now = time.time()
                if self.dose is not None:
                    try:
                        dt = now - float(self.dose.last_updated_ts)
                        self.dose.tick(now, dt)
                        self.dose_label = self.dose.label()
                    except Exception as exc:  # noqa: BLE001
                        self._write_system(f"dose tick warning: {_summarize_error(exc)}")
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
                label_changed = self.dose is not None and self.dose_label != self.dose_last_emitted_label
                if label_changed:
                    before = self.dose_last_emitted_label
                    after = self.dose_label
                    self.dose_last_emitted_label = after
                    self._add_activity("dose", f"mode {before} -> {after}")
                    self._record_event(
                        "dose.mode.changed",
                        f"DOSE mode changed: {before} -> {after}.",
                        source="dose",
                        metadata={"from": before, "to": after},
                    )
                    if "stressed" in {before, after}:
                        append_daily_note(
                            daily_root(),
                            date.today(),
                            f"DOSE mode changed: {before} -> {after}",
                        )

                if self.dose is not None and self.dose_path is not None:
                    should_save = label_changed or (self.heartbeat_ticks % 5 == 0)
                    if should_save:
                        try:
                            dose.save(self.dose_path, self.dose)
                        except Exception as exc:  # noqa: BLE001
                            self._write_system(f"dose save warning: {_summarize_error(exc)}")
                self._refresh_open_loops(save=True)
                await self._run_git_autocommit()
            await asyncio.sleep(
                self.interval
                + random.uniform(-HEARTBEAT_JITTER * self.interval, HEARTBEAT_JITTER * self.interval)
            )

    async def _run_git_autocommit(self) -> None:
        result = await asyncio.to_thread(
            auto_commit_pending,
            repo_root(),
            message="Heartbeat auto-commit: capture pending workspace changes",
            identity_name=self.identity_name,
        )
        if result.committed:
            commit_ref = result.commit or "unknown"
            self.last_git_autocommit_error = ""
            self._add_activity("git", f"auto-commit {commit_ref}")
            self._record_event(
                "git.auto_commit.created",
                f"Heartbeat auto-commit created ({commit_ref}).",
                source="runtime",
                metadata={"commit": result.commit},
            )
            return
        if not result.ok and result.summary != self.last_git_autocommit_error:
            self.last_git_autocommit_error = result.summary
            self._write_system(result.summary)
            self._record_event(
                "git.auto_commit.error",
                result.summary,
                severity="warn",
                source="runtime",
            )
        if not result.ok:
            records = ensure_problem_tasks(repo_root(), [result.summary], source="heartbeat-git")
            created = [record for record in records if record.created]
            if created:
                self._add_activity("tasks", f"problem task created: {created[0].task_id}")
        if not result.ok and _is_git_identity_error(result.summary):
            self._request_operator_configuration(
                key="git.identity",
                reason="I couldn't auto-configure git identity for heartbeat commits; could you please configure `user.name` and `user.email` manually?",
                next_steps=[
                    "run `git config --global user.name \"Your Name\"`",
                    "run `git config --global user.email \"you@example.com\"`",
                    "or set repo-local values: `git config user.name \"Your Name\"` + `git config user.email \"you@example.com\"`",
                ],
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
        if not _looks_like_local_command(text):
            if _looks_like_tako_toml_question(text):
                self._write_tako(explain_tako_toml(self.config, path=repo_root() / "tako.toml"))
                return
            if await self._maybe_handle_inline_name_change(text):
                return
            reply = await self._local_chat_reply(text)
            self._record_local_chat_turn(user_text=text, assistant_text=reply)
            self._write_tako(reply)
            return

        cmd, rest = _parse_command(text)
        if cmd == "":
            if text.strip().startswith("/"):
                self._write_tako("empty slash command. keep typing after `/` or use `/help`.")
                return
            self._write_tako("unknown local command. type `help`. plain text chat always works here.")
            return
        if cmd in {"help", "h", "?"}:
            self._write_tako(
                "local cockpit commands: help, status, stats, health, config, models, dose, task, tasks, done, morning, outcomes, compress, weekly, promote, inference, doctor, pair, setup, update, upgrade, web, run, install, review pending, enable, draft, extensions, reimprint, copy last, copy transcript, activity, safe on, safe off, stop, resume, quit\n"
                "inference controls: `inference refresh`, `inference auth`, `inference provider <...>`, `inference ollama model <name>`, `inference key list|set|clear`\n"
                "slash commands: type `/` to show available command shortcuts (`/models`, `/upgrade`, `/stats`, `/dose ...`)\n"
                "update controls: `update`/`upgrade`, `update check`, `update auto status`, `update auto on`, `update auto off`\n"
                "run command cwd: `code/` (git-ignored workspace for cloned repos)"
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
            update_check_age = (
                f"{int(time.monotonic() - self.last_update_check_at)}s ago"
                if self.last_update_check_at is not None
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
                f"inference_provider: {(self.inference_runtime.selected_provider if self.inference_runtime else 'none')}\n"
                f"inference_ready: {('yes' if self.inference_runtime and self.inference_runtime.ready else 'no')}\n"
                f"inference_gate: {('open' if self.inference_gate_open else 'closed')}\n"
                f"inference_gate_state: {self.inference_gate_opened_state}\n"
                f"auto_updates: {('on' if self.auto_updates_enabled else 'off')}\n"
                f"last_update_check: {update_check_age}\n"
                f"dose_label: {self.dose_label}\n"
                f"uptime_s: {uptime}\n"
                f"version: {__version__}\n"
                f"code_dir: {self.code_dir or code_root(repo_root())}\n"
                f"tako_address: {self.address}"
            )
            return

        if cmd == "stats":
            uptime = int(time.monotonic() - self.started_at)
            heartbeat_age = (
                f"{int(time.monotonic() - self.last_heartbeat_at)}s ago"
                if self.last_heartbeat_at is not None
                else "n/a"
            )
            update_check_age = (
                f"{int(time.monotonic() - self.last_update_check_at)}s ago"
                if self.last_update_check_at is not None
                else "n/a"
            )
            loops_count = int(self.open_loops_summary.get("count") or 0)
            inference_provider = self.inference_runtime.selected_provider if self.inference_runtime else "none"
            inference_ready = "yes" if self.inference_runtime and self.inference_runtime.ready else "no"
            lines = [
                "stats:",
                f"version: {__version__}",
                f"uptime_s: {uptime}",
                f"heartbeat_ticks: {self.heartbeat_ticks}",
                f"last_heartbeat: {heartbeat_age}",
                f"events_written: {self.event_total_written}",
                f"events_ingested: {self.event_total_ingested}",
                f"type1_processed: {self.type1_processed}",
                f"type2_escalations: {self.type2_escalations}",
                f"open_tasks: {self.open_tasks_count}",
                f"open_loops: {loops_count}",
                f"inference_provider: {inference_provider}",
                f"inference_ready: {inference_ready}",
                f"last_update_check: {update_check_age}",
                f"auto_updates: {'on' if self.auto_updates_enabled else 'off'}",
                f"operator_paired: {'yes' if self.operator_paired else 'no'}",
            ]
            if self.dose is None:
                lines.append("dose: not ready")
            else:
                lines.append(
                    f"dose: D={self.dose.d:.2f} O={self.dose.o:.2f} S={self.dose.s:.2f} E={self.dose.e:.2f} ({self.dose_label})"
                )
            self._write_tako("\n".join(lines))
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

        if cmd in {"config", "toml"}:
            self._write_tako(explain_tako_toml(self.config, path=repo_root() / "tako.toml"))
            return

        if cmd == "models":
            if self.inference_runtime is None:
                self._initialize_inference_runtime()
            if self.inference_runtime is None:
                self._write_tako("models unavailable: inference runtime is not initialized.")
                return
            pi_status = self.inference_runtime.statuses.get("pi")
            lines = [
                "models (pi + inference):",
                f"selected provider: {self.inference_runtime.selected_provider or 'none'}",
                f"inference ready: {'yes' if self.inference_runtime.ready else 'no'}",
            ]
            if pi_status is None:
                lines.append("pi: unavailable")
            else:
                lines.extend(
                    [
                        f"pi cli installed: {'yes' if pi_status.cli_installed else 'no'}",
                        f"pi ready: {'yes' if pi_status.ready else 'no'}",
                        f"pi auth kind: {pi_status.auth_kind}",
                        f"pi source: {pi_status.key_source or 'none'}",
                    ]
                )
                if pi_status.note:
                    lines.append(f"pi note: {pi_status.note}")
            lines.append("")
            lines.extend(format_inference_auth_inventory())
            self._write_tako("\n".join(lines))
            return

        if cmd == "dose":
            action = rest.strip().lower()
            if self.dose is None:
                self._write_tako("dose engine isn't awake yet. give me a moment.")
                return
            if action in {"help", "?"}:
                self._write_tako(
                    "usage: `dose` (show), `dose calm`, `dose explore`, "
                    "`dose <d|o|s|e|dopamine|oxytocin|serotonin|endorphins> <0..1>`"
                )
                return
            if action in {"calm", "explore"}:
                if self.operator_paired and not self.safe_mode:
                    self._write_tako(
                        "dose tuning is operator-only over XMTP when paired. "
                        "if you need an emergency local nudge, enable safe mode first (`safe on`)."
                    )
                    return
                event_type = "dose.operator.calm" if action == "calm" else "dose.operator.explore"
                self._record_event(
                    event_type,
                    f"Operator requested DOSE `{action}` nudge.",
                    source="terminal",
                    metadata={"action": action},
                )
                self._add_activity("dose", f"operator nudge: {action}")
                if self.dose_path is not None:
                    with contextlib.suppress(Exception):
                        dose.save(self.dose_path, self.dose)
                self._write_tako(f"okie! current dose: D={self.dose.d:.2f} O={self.dose.o:.2f} S={self.dose.s:.2f} E={self.dose.e:.2f} ({self.dose_label})")
                return
            set_target = _parse_dose_set_request(action)
            if set_target is not None:
                if self.operator_paired and not self.safe_mode:
                    self._write_tako(
                        "dose tuning is operator-only over XMTP when paired. "
                        "if you need an emergency local nudge, enable safe mode first (`safe on`)."
                    )
                    return
                channel, value = set_target
                setattr(self.dose, channel, value)
                self.dose.clamp()
                self.dose.last_updated_ts = time.time()
                self.dose_label = self.dose.label()
                self.dose_last_emitted_label = self.dose_label
                if self.dose_path is not None:
                    with contextlib.suppress(Exception):
                        dose.save(self.dose_path, self.dose)
                label = _dose_channel_label(channel)
                level = _format_level(value)
                self._record_event(
                    "dose.operator.set",
                    f"Operator set {label} level to {level}.",
                    source="terminal",
                    metadata={"channel": channel, "value": level},
                )
                self._add_activity("dose", f"{label} set to {level}")
                self._write_tako(f"{label} levels set to {level}.")
                return
            if action not in {"", "show", "status"}:
                self._write_tako(
                    "usage: `dose` (show), `dose calm`, `dose explore`, "
                    "`dose <d|o|s|e|dopamine|oxytocin|serotonin|endorphins> <0..1>`"
                )
                return
            bias = self.dose.behavior_bias()
            self._write_tako(
                "dose status:\n"
                f"D={self.dose.d:.2f} O={self.dose.o:.2f} S={self.dose.s:.2f} E={self.dose.e:.2f}\n"
                f"label={self.dose_label}\n"
                f"bias: verbosity={bias['verbosity']:.2f} confirm={bias['confirm_level']:.2f} explore={bias['explore_bias']:.2f} patience={bias['patience']:.2f}"
            )
            return

        if cmd == "task":
            spec = rest.strip()
            if not spec:
                self._write_tako("usage: `task <title>` (optionally: `| project=... | area=... | due=YYYY-MM-DD`)")
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
                    self._write_tako("tiny bubble: `due` must be YYYY-MM-DD.")
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
                self._write_tako(f"task create failed: {_summarize_error(exc)}")
                return

            append_daily_note(daily_root(), date.today(), f"Created task {task.id}: {task.title}")
            self._record_event(
                "productivity.task.created",
                f"Task created: {task.id}",
                source="terminal",
                metadata={"id": task.id, "title": task.title, "project": project or "", "area": area or ""},
            )
            self._add_activity("tasks", f"created {task.id}")
            self._refresh_open_loops(save=True)
            self._write_tako(f"task created: {task.id}\n{task.title}\nfile: {task.path.relative_to(repo_root())}")
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
                    self._write_tako("usage: `tasks due YYYY-MM-DD`")
                    return
            elif raw:
                # Support `tasks project=... | area=... | due=...`
                parts = [part.strip() for part in raw.split("|") if part.strip()]
                for part in parts:
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
                        try:
                            due_before = datetime.strptime(value, "%Y-%m-%d").date()
                        except Exception:
                            self._write_tako("tiny bubble: `due` must be YYYY-MM-DD.")
                            return
                    elif key == "status":
                        status = value.strip().lower() or status

            filtered = prod_tasks.filter_tasks(all_tasks, status=status, project=project, area=area, due_on_or_before=due_before)
            open_count = sum(1 for task in all_tasks if task.is_open)
            done_count = sum(1 for task in all_tasks if task.is_done)
            lines = [f"tasks: open={open_count} done={done_count}"]
            if project:
                lines.append(f"filter project={project}")
            if area:
                lines.append(f"filter area={area}")
            if due_before:
                lines.append(f"filter due<= {due_before.isoformat()}")
            if not filtered:
                lines.append("(none)")
                self._write_tako("\n".join(lines))
                return
            lines.append("")
            for task in filtered[:25]:
                lines.append("- " + prod_tasks.format_task_line(task))
            if len(filtered) > 25:
                lines.append(f"... and {len(filtered) - 25} more")

            # DOSE-biased focus hint (light touch).
            if self.dose is not None:
                hint = _dose_productivity_hint(self.dose)
                if hint:
                    lines.append("")
                    lines.append("dose hint: " + hint)

            self._write_tako("\n".join(lines))
            return

        if cmd == "done":
            task_id = rest.strip()
            if not task_id:
                self._write_tako("usage: `done <task-id>`")
                return
            task = prod_tasks.mark_done(repo_root(), task_id)
            if task is None:
                self._write_tako(f"unknown task id: {task_id}")
                return
            append_daily_note(daily_root(), date.today(), f"Completed task {task.id}: {task.title}")
            self._record_event(
                "productivity.task.done",
                f"Task completed: {task.id}",
                source="terminal",
                metadata={"id": task.id, "title": task.title},
            )
            self._add_activity("tasks", f"done {task.id}")
            self._refresh_open_loops(save=True)
            self._write_tako(f"done: {task.id} ({task.title})")
            return

        if cmd == "morning":
            self.prompt_mode = "morning_outcomes"
            self.prompt_step = 0
            self.prompt_values = []
            self._add_activity("outcomes", "morning prompt started")
            self._write_tako("morning tide! what are the 3 outcomes that make today a win?\noutcome 1? (or `skip`)")
            self._refresh_open_loops(save=True)
            return

        if cmd == "outcomes":
            action = rest.strip().lower()
            daily_path = ensure_daily_log(daily_root(), date.today())
            prod_outcomes.ensure_outcomes_section(daily_path)
            if action in {"set", "morning"}:
                self.prompt_mode = "morning_outcomes"
                self.prompt_step = 0
                self.prompt_values = []
                self._add_activity("outcomes", "prompt started via outcomes set")
                self._write_tako("okie. outcome 1? (or `skip`)")
                return
            if action.startswith("done ") or action.startswith("undo "):
                verb, _, tail = action.partition(" ")
                try:
                    idx = int(tail.strip())
                except Exception:
                    self._write_tako("usage: `outcomes done 1` (or `outcomes undo 1`)")
                    return
                try:
                    updated = prod_outcomes.mark_outcome(daily_path, idx, done=(verb == "done"))
                except Exception as exc:  # noqa: BLE001
                    self._write_tako(f"outcomes update failed: {_summarize_error(exc)}")
                    return
                done_count, total = prod_outcomes.outcomes_completion(updated)
                append_daily_note(
                    daily_root(),
                    date.today(),
                    f"Outcome {idx} marked {'done' if verb == 'done' else 'not done'} ({done_count}/{total}).",
                )
                event_type = "outcome.completed" if verb == "done" else "outcome.reopened"
                self._record_event(
                    event_type,
                    f"Outcome {idx} marked {verb}.",
                    source="terminal",
                    metadata={"index": idx},
                )
                self._add_activity("outcomes", f"{verb} {idx}")
                self._refresh_open_loops(save=True)
                self._write_tako(f"outcomes: {done_count}/{total} done")
                return

            outcomes = prod_outcomes.get_outcomes(daily_path)
            done_count, total = prod_outcomes.outcomes_completion(outcomes)
            lines = [f"outcomes ({done_count}/{total} done):"]
            if not outcomes:
                lines.append("(none)")
                self._write_tako("\n".join(lines))
                return
            for idx, item in enumerate(outcomes, start=1):
                if not item.text.strip():
                    continue
                box = "x" if item.done else " "
                lines.append(f"- {idx}. [{box}] {item.text}")
            lines.append("")
            lines.append("commands: `morning` to set, `outcomes done 1`, `outcomes undo 1`")
            self._write_tako("\n".join(lines))
            return

        if cmd == "compress":
            if self.paths is None:
                self._write_tako("compress unavailable: runtime paths missing.")
                return
            day = date.today()
            daily_path = ensure_daily_log(daily_root(), day)
            root = repo_root()
            tasks = prod_tasks.list_tasks(root)
            prod_outcomes.ensure_outcomes_section(daily_path)
            outcomes = prod_outcomes.get_outcomes(daily_path)

            infer = None
            if self.inference_runtime is not None and self.inference_runtime.ready and self.inference_gate_open:
                def _infer(prompt: str, timeout_s: float) -> tuple[str, str]:
                    return run_inference_prompt_with_fallback(self.inference_runtime, prompt, timeout_s=timeout_s)
                infer = _infer

            self._add_activity("inference", "compress daily log (Type2)")
            previous_indicator = self.indicator
            self._set_indicator("acting")
            try:
                result = await asyncio.to_thread(
                    prod_summarize.compress_daily_log,
                    daily_path,
                    day=day,
                    tasks=tasks,
                    outcomes=outcomes,
                    infer=infer,
                )
            finally:
                if self.indicator == "acting":
                    self._set_indicator(previous_indicator if previous_indicator != "acting" else "idle")

            append_daily_note(daily_root(), day, f"Compressed summary updated (provider={result.provider}).")
            self._record_event(
                "daily.compress.completed",
                "Daily log compressed summary updated.",
                source="terminal",
                metadata={"provider": result.provider},
            )
            self._add_activity("daily", f"compressed summary ({result.provider})")
            self._write_tako(f"compressed summary updated (provider={result.provider}).")
            return

        if cmd in {"weekly", "review"}:
            action = rest.strip().lower()
            if cmd == "review" and action == "pending":
                if self.extensions_registry_path is None:
                    self._write_tako("review pending unavailable: runtime paths missing.")
                    return
                pending = ext_list_pending(self.extensions_registry_path)
                if not pending:
                    self._write_tako("pending installs: none")
                    return
                lines = ["pending installs:"]
                for item in pending[:12]:
                    lines.append(
                        f"- {item.get('id')} {item.get('kind')} {item.get('name')} risk={item.get('risk')} url={item.get('final_url') or item.get('source_url')}"
                    )
                if len(pending) > 12:
                    lines.append(f"- ... (+{len(pending) - 12} more)")
                self._write_tako("\n".join(lines))
                return

            if cmd == "review" and action not in {"weekly", "week", ""}:
                self._write_tako("usage: `weekly` or `review weekly` or `review pending`")
                return
            root = repo_root()
            today = date.today()
            review = prod_weekly.build_weekly_review(root, today=today)

            infer = None
            if self.inference_runtime is not None and self.inference_runtime.ready and self.inference_gate_open:
                def _infer(prompt: str, timeout_s: float) -> tuple[str, str]:
                    return run_inference_prompt_with_fallback(self.inference_runtime, prompt, timeout_s=timeout_s)
                infer = _infer
            report, provider, err = prod_weekly.weekly_review_with_inference(review, infer=infer)

            append_daily_note(daily_root(), today, "Weekly review run.")
            self._record_event(
                "review.weekly.completed",
                "Weekly review completed.",
                source="terminal",
                metadata={"provider": provider, "error": err},
            )
            self._add_activity("review", f"weekly ({provider})")
            self._write_tako(report)
            return

        if cmd == "promote":
            note = rest.strip()
            if not note:
                self._write_tako("usage: `promote <durable note to add to MEMORY.md>`")
                return
            try:
                prod_promote.promote(repo_root() / "MEMORY.md", day=date.today(), note=note)
            except Exception as exc:  # noqa: BLE001
                self._write_tako(f"promote failed: {_summarize_error(exc)}")
                return
            append_daily_note(daily_root(), date.today(), "Promoted a durable note into MEMORY.md.")
            self._record_event(
                "memory.promote",
                "Operator promoted a note into MEMORY.md.",
                source="terminal",
            )
            self._add_activity("memory", "promotion added")
            self._write_tako("inked into MEMORY.md.")
            return

        if cmd == "inference":
            action_raw = rest.strip()
            action = action_raw.lower()
            if action in {"help", "?"}:
                supported = ", ".join(SUPPORTED_PROVIDER_PREFERENCES)
                keys = ", ".join(CONFIGURABLE_API_KEY_VARS)
                self._write_tako(
                    "inference commands:\n"
                    "- inference\n"
                    "- inference refresh\n"
                    "- inference auth\n"
                    "- inference provider <auto|pi|ollama|codex|claude|gemini>\n"
                    "- inference ollama model <name> (or empty to clear)\n"
                    "- inference ollama host <url> (or empty to clear)\n"
                    "- inference key list\n"
                    "- inference key set <ENV_VAR> <value>\n"
                    "- inference key clear <ENV_VAR>\n"
                    f"supported providers: {supported}\n"
                    f"supported key names: {keys}"
                )
                return

            if action in {"refresh", "rescan", "scan", "reload"}:
                self._initialize_inference_runtime()
                self._write_tako("inference scan refreshed.")
                return

            if action in {"auth", "tokens"}:
                self._write_tako("\n".join(format_inference_auth_inventory()))
                return

            if action.startswith("provider "):
                target = action_raw.split(maxsplit=1)[1] if len(action_raw.split(maxsplit=1)) == 2 else "auto"
                ok, summary = set_inference_preferred_provider(target)
                if ok:
                    self._initialize_inference_runtime()
                self._write_tako(summary)
                return

            if action.startswith("ollama model"):
                model = ""
                parts = action_raw.split(maxsplit=2)
                if len(parts) == 3:
                    model = parts[2]
                ok, summary = set_inference_ollama_model(model)
                if ok:
                    self._initialize_inference_runtime()
                self._write_tako(summary)
                return

            if action.startswith("ollama host"):
                host = ""
                parts = action_raw.split(maxsplit=2)
                if len(parts) == 3:
                    host = parts[2]
                ok, summary = set_inference_ollama_host(host)
                if ok:
                    self._initialize_inference_runtime()
                self._write_tako(summary)
                return

            if action.startswith("key "):
                parts = action_raw.split(maxsplit=3)
                if len(parts) >= 2 and parts[1].lower() == "list":
                    self._write_tako("\n".join(format_inference_auth_inventory()))
                    return
                if len(parts) == 4 and parts[1].lower() == "set":
                    env_var = parts[2]
                    key_value = parts[3]
                    ok, summary = set_inference_api_key(env_var, key_value)
                    if ok:
                        self._initialize_inference_runtime()
                    self._write_tako(summary)
                    return
                if len(parts) >= 3 and parts[1].lower() == "clear":
                    env_var = parts[2]
                    ok, summary = clear_inference_api_key(env_var)
                    if ok:
                        self._initialize_inference_runtime()
                    self._write_tako(summary)
                    return
                self._write_tako("usage: `inference key list|set <ENV_VAR> <value>|clear <ENV_VAR>`")
                return

            if self.inference_runtime is None:
                self._write_tako("inference runtime is not initialized.")
                return
            lines = ["inference status:"]
            lines.append(f"inference gate: {'open' if self.inference_gate_open else 'closed'}")
            lines.append(f"inference gate opened state: {self.inference_gate_opened_state}")
            lines.extend(format_runtime_lines(self.inference_runtime))
            for hint in _inference_setup_hints(self.inference_runtime):
                lines.append(f"hint: {hint}")
            if self.inference_last_error:
                lines.append(f"last error: {self.inference_last_error}")
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
                task_records = ensure_problem_tasks(repo_root(), problems, source="doctor")
                if task_records:
                    created = [record for record in task_records if record.created]
                    if created:
                        self._write_tako("Problem tasks created:\n" + "\n".join(f"- {record.task_id}: {record.title}" for record in created))
                    else:
                        self._write_tako("Problem tasks already open:\n" + "\n".join(f"- {record.task_id}: {record.title}" for record in task_records))
            return

        if cmd == "pair":
            if self.operator_paired:
                self._write_tako("already paired. if you need to clear the operator channel: `reimprint CONFIRM`.")
                return
            self._set_state(SessionState.ASK_XMTP_HANDLE)
            self.awaiting_xmtp_handle = True
            self._write_tako("share your XMTP handle to start outbound pairing, or `local-only`.")
            return

        if cmd in {"setup", "profile"}:
            self._begin_identity_onboarding()
            return

        if cmd == "reimprint":
            if self.paths is None:
                self._write_tako("reimprint unavailable: runtime paths missing.")
                return

            if rest.strip().lower() != "confirm":
                self._write_tako(
                    "reimprint is a big ink cloud: it clears the current operator channel.\n\n"
                    "if you're sure, type: `reimprint CONFIRM`"
                )
                return

            clear_operator(self.paths.operator_json)
            clear_pending(self.paths.state_dir / "pairing.json")
            append_daily_note(daily_root(), date.today(), "Operator cleared imprint locally (reimprint CONFIRM).")
            self._record_event(
                "operator.reimprint.cleared",
                "Operator imprint cleared from terminal app.",
                source="terminal",
            )
            self._add_activity("operator", "operator imprint cleared via terminal")

            self.operator_paired = False
            self.operator_inbox_id = None
            self.operator_address = None
            await self._stop_xmtp_runtime()
            self.mode = "local-only"
            self.runtime_mode = "local"
            self._write_tako("whoosh. operator imprint cleared. when you're ready, type `pair` to set a new XMTP control channel.")
            return

        if cmd in {"update", "upgrade"}:
            action = rest.strip().lower()
            if action in {"help", "?"}:
                self._write_tako(
                    "usage:\n"
                    "- `update` or `upgrade` (apply update)\n"
                    "- `update check` (check only)\n"
                    "- `update auto status`\n"
                    "- `update auto on`\n"
                    "- `update auto off`"
                )
                return

            parts = [part for part in action.split() if part]
            if parts and parts[0] == "auto":
                choice = parts[1] if len(parts) > 1 else "status"
                if choice in {"status", "state"}:
                    self._write_tako(f"auto-updates are currently {'on' if self.auto_updates_enabled else 'off'}.")
                    return
                if choice not in {"on", "off"}:
                    self._write_tako("usage: `update auto status|on|off`")
                    return

                enabled = choice == "on"
                config_path = repo_root() / "tako.toml"
                ok, summary = await asyncio.to_thread(set_updates_auto_apply, config_path, enabled)
                if not ok:
                    self._write_tako(f"failed to persist update setting: {summary}")
                    self._record_event("update.auto.config.error", summary, severity="warn", source="terminal")
                    return

                self.auto_updates_enabled = enabled
                self._add_activity("update", f"auto-updates {'on' if enabled else 'off'}")
                self._record_event(
                    "update.auto.config.changed",
                    f"Auto-updates set to {'on' if enabled else 'off'}.",
                    source="terminal",
                    metadata={"enabled": enabled},
                )
                append_daily_note(
                    daily_root(),
                    date.today(),
                    f"Auto-updates set to {'on' if enabled else 'off'} from terminal.",
                )
                self._write_tako(f"auto-updates {'enabled' if enabled else 'disabled'}.\n{summary}")
                return

            apply_update = action not in {"check", "status", "dry-run", "dryrun"}
            self._add_activity("update", f"requested local update apply={_yes_no(apply_update)}")
            self._record_event(
                "runtime.self_update.requested",
                "Local self-update requested from terminal.",
                source="terminal",
                metadata={"apply": apply_update},
            )
            try:
                result = await asyncio.to_thread(run_self_update, repo_root(), apply=apply_update)
            except Exception as exc:  # noqa: BLE001
                summary = _summarize_error(exc)
                self._write_tako(f"self-update failed: {summary}")
                self._add_activity("update", f"failed: {summary}")
                self._record_event(
                    "runtime.self_update.error",
                    f"Local self-update failed: {exc}",
                    severity="warn",
                    source="terminal",
                )
                return

            lines = [result.summary, *result.details]
            if result.changed:
                if apply_update:
                    lines.append("update applied. restarting now.")
                else:
                    lines.append("restart Tako to load updated code.")
            self._write_tako("\n".join(lines))
            self._add_activity("update", result.summary)
            append_daily_note(daily_root(), date.today(), f"Local self-update command: {result.summary}")
            self._record_event(
                "runtime.self_update.result",
                result.summary,
                severity="info" if result.ok else "warn",
                source="terminal",
                metadata={"changed": result.changed, "apply": apply_update},
            )
            if apply_update and result.ok and result.changed:
                await self._restart_after_auto_update()
            return

        if cmd == "extensions":
            if self.extensions_registry_path is None:
                self._write_tako("extensions unavailable: runtime paths missing.")
                return
            tail = rest.strip().lower()
            kind = None
            if tail in {"skill", "skills"}:
                kind = "skill"
            elif tail in {"tool", "tools"}:
                kind = "tool"
            installed = ext_list_installed(self.extensions_registry_path, kind=kind)
            if not installed:
                self._write_tako("extensions: none installed yet.")
                return
            lines = ["extensions:"]
            for item in installed[:18]:
                lines.append(
                    f"- {item.get('kind')} {item.get('name')} enabled={_yes_no(bool(item.get('enabled')))} risk={item.get('risk')}"
                )
            if len(installed) > 18:
                lines.append(f"- ... (+{len(installed) - 18} more)")
            self._write_tako("\n".join(lines))
            return

        if cmd == "install":
            if self.paths is None or self.extensions_registry_path is None or self.quarantine_root is None:
                self._write_tako("install unavailable: runtime paths missing.")
                return

            parts = rest.strip().split()
            if not parts:
                self._write_tako(
                    "usage:\n"
                    "- `install skill <url>`\n"
                    "- `install tool <url>`\n"
                    "- `install accept <quarantine_id> [enable]`\n"
                    "- `install reject <quarantine_id>`"
                )
                return

            action = parts[0].strip().lower()
            if action in {"skill", "tool"}:
                if len(parts) < 2:
                    self._write_tako(f"usage: `install {action} <url>`")
                    return
                url = rest.strip().split(maxsplit=1)[1]
                kind = "skill" if action == "skill" else "tool"
                defaults = self.config.security.default_permissions
                policy_defaults = ExtPermissionSet(
                    network=defaults.network,
                    shell=defaults.shell,
                    xmtp=defaults.xmtp,
                    filesystem=defaults.filesystem,
                )

                self._add_activity("ext:quarantine", f"fetching {kind} from {url}")
                previous_indicator = self.indicator
                self._set_indicator("acting")
                try:
                    qdir, provenance = await asyncio.to_thread(
                        fetch_to_quarantine,
                        url,
                        quarantine_root=self.quarantine_root,
                        max_bytes=int(self.config.security.download.max_bytes),
                        allowlist_domains=list(self.config.security.download.allowlist_domains),
                    )
                    qid = qdir.name
                    report = await asyncio.to_thread(
                        analyze_quarantine,
                        quarantine_id=qid,
                        qdir=qdir,
                        kind=kind,
                        provenance=provenance,
                        policy_defaults=policy_defaults,
                    )
                except (QuarantineError, ManifestError) as exc:
                    summary = _summarize_error(exc)
                    self._write_tako(f"install failed: {summary}")
                    self._add_activity("ext:quarantine", f"failed: {summary}")
                    return
                finally:
                    if self.indicator == "acting":
                        self._set_indicator(previous_indicator if previous_indicator != "acting" else "idle")

                ext_record_pending(self.extensions_registry_path, report, qdir=qdir)
                append_daily_note(
                    daily_root(),
                    date.today(),
                    f"Quarantined {kind} install: {provenance.final_url} (id={qid}, sha256={provenance.sha256[:12]}..., risk={report.risk})",
                )
                self._record_event(
                    "extensions.install.pending",
                    f"Extension install pending: {kind} {report.manifest.name}",
                    source="terminal",
                    metadata={"kind": kind, "id": qid, "name": report.manifest.name, "risk": report.risk},
                )
                self._add_activity("ext:install", f"pending {kind} {report.manifest.name} ({qid}) risk={report.risk}")

                perms = report.manifest.requested_permissions.to_dict()
                lines = [
                    f"install pending: {qid}",
                    f"kind: {kind}",
                    f"name: {report.manifest.name}",
                    f"version: {report.manifest.version}",
                    f"risk: {report.risk}",
                    f"requested_permissions: {perms}",
                    f"source: {provenance.final_url}",
                    f"sha256: {provenance.sha256}",
                    f"recommendation: {report.recommendation}",
                ]
                if report.risky_hits:
                    lines.append("risky_hits:")
                    for hit in report.risky_hits[:8]:
                        lines.append(f"- {hit.path}: {hit.pattern}")
                    if len(report.risky_hits) > 8:
                        lines.append(f"- ... (+{len(report.risky_hits) - 8} more)")
                lines.append("next: `install accept <id>` (disabled), `install accept <id> enable`, or `install reject <id>`.")
                self._write_tako("\n".join(lines))
                return

            if action in {"accept", "approve"}:
                if len(parts) < 2:
                    self._write_tako("usage: `install accept <quarantine_id> [enable]`")
                    return
                qid = parts[1].strip()
                want_enable = len(parts) >= 3 and parts[2].strip().lower() in {"enable", "enabled", "on", "true", "1"}
                pending = ext_get_pending(self.extensions_registry_path, qid)
                if pending is None:
                    self._write_tako(f"unknown quarantine id: {qid} (try `review pending`)")
                    return

                qdir = Path(str(pending.get("quarantine_dir") or "")).expanduser()
                if not qdir.exists():
                    self._write_tako(f"quarantine directory missing: {qdir}")
                    return
                kind = str(pending.get("kind") or "").strip().lower()
                if kind not in {"skill", "tool"}:
                    self._write_tako(f"invalid pending kind for {qid}: {kind}")
                    return

                prov = QuarantineProvenance(
                    source_url=str(pending.get("source_url") or ""),
                    fetched_at=QuarantineProvenance.now_iso(),
                    final_url=str(pending.get("final_url") or pending.get("source_url") or ""),
                    content_type="",
                    sha256=str(pending.get("sha256") or ""),
                    bytes=int(pending.get("bytes") or 0),
                )
                defaults = self.config.security.default_permissions
                policy_defaults = ExtPermissionSet(
                    network=defaults.network,
                    shell=defaults.shell,
                    xmtp=defaults.xmtp,
                    filesystem=defaults.filesystem,
                )

                try:
                    report = await asyncio.to_thread(
                        analyze_quarantine,
                        quarantine_id=qid,
                        qdir=qdir,
                        kind=kind,
                        provenance=prov,
                        policy_defaults=policy_defaults,
                    )
                    installed = await asyncio.to_thread(
                        install_from_quarantine,
                        report=report,
                        workspace_root=repo_root(),
                    )
                except (ManifestError, InstallError) as exc:
                    summary = _summarize_error(exc)
                    self._write_tako(f"install accept failed: {summary}")
                    self._add_activity("ext:install", f"accept failed: {summary}")
                    return

                ext_record_installed(self.extensions_registry_path, installed.record)
                ext_drop_pending(self.extensions_registry_path, qid)
                append_daily_note(
                    daily_root(),
                    date.today(),
                    f"Installed {kind} `{installed.name}` from quarantine {qid} (disabled, sha256={installed.record.get('sha256','')[:12]}...).",
                )
                self._record_event(
                    "extensions.install.installed",
                    f"Extension installed: {kind} {installed.name}",
                    source="terminal",
                    metadata={"kind": kind, "id": qid, "name": installed.name},
                )
                self._add_activity("ext:install", f"installed {kind} {installed.name} enabled=no")
                self._write_tako(
                    f"installed {kind} into {installed.dest_dir.relative_to(repo_root())} (disabled).\n"
                    f"next: `enable {kind} {installed.name}`"
                )
                # Helpful nudge: suggest committing workspace changes if git is available.
                try:
                    status = await asyncio.to_thread(run_local_command, "git status --porcelain")
                    if status.ok and status.output.strip() and status.output.strip() != "(no output)":
                        self._write_tako(
                            "git changes detected:\n"
                            f"{status.output}\n\n"
                            f"suggestion: `git add -A && git commit -m \"Install {kind} {installed.name}\"`"
                        )
                except Exception:
                    pass

                if want_enable:
                    await self._handle_running_input(f"enable {kind} {installed.name}")
                return

            if action == "reject":
                if len(parts) < 2:
                    self._write_tako("usage: `install reject <quarantine_id>`")
                    return
                qid = parts[1].strip()
                pending = ext_get_pending(self.extensions_registry_path, qid)
                if pending is not None:
                    qdir = Path(str(pending.get("quarantine_dir") or ""))
                    with contextlib.suppress(Exception):
                        shutil.rmtree(qdir)
                    ext_drop_pending(self.extensions_registry_path, qid)
                self._add_activity("ext:install", f"rejected {qid}")
                append_daily_note(daily_root(), date.today(), f"Rejected extension install {qid}.")
                self._write_tako(f"rejected {qid}.")
                return

            self._write_tako(
                "usage:\n"
                "- `install skill <url>`\n"
                "- `install tool <url>`\n"
                "- `install accept <quarantine_id> [enable]`\n"
                "- `install reject <quarantine_id>`"
            )
            return

        if cmd == "enable":
            if self.extensions_registry_path is None:
                self._write_tako("enable unavailable: runtime paths missing.")
                return
            parts = rest.strip().split(maxsplit=1)
            if len(parts) < 2:
                self._write_tako("usage: `enable skill <name>` or `enable tool <name>`")
                return
            kind = parts[0].strip().lower()
            name = parts[1].strip()
            if kind not in {"skill", "tool"} or not name:
                self._write_tako("usage: `enable skill <name>` or `enable tool <name>`")
                return

            record = ext_get_installed(self.extensions_registry_path, kind=kind, name=name)
            if record is None:
                self._write_tako(f"not installed: {kind} {name}")
                return

            ok, err = ext_verify_integrity(record, workspace_root=repo_root())
            if not ok:
                self._write_tako(f"enable blocked: {err}")
                self._add_activity("ext:enable", f"blocked {kind} {name}: {err}")
                return

            defaults = self.config.security.default_permissions
            policy_defaults = ExtPermissionSet(
                network=defaults.network,
                shell=defaults.shell,
                xmtp=defaults.xmtp,
                filesystem=defaults.filesystem,
            )
            ok, err = ext_permissions_ok(record, policy_defaults=policy_defaults)
            if not ok:
                self._write_tako(f"enable blocked: {err}")
                self._add_activity("ext:enable", f"blocked {kind} {name}: {err}")
                return

            ext_set_enabled(self.extensions_registry_path, kind=kind, name=name, enabled=True)
            append_daily_note(daily_root(), date.today(), f"Enabled {kind} `{name}`.")
            self._record_event(
                "extensions.enabled",
                f"Extension enabled: {kind} {name}",
                source="terminal",
                metadata={"kind": kind, "name": name},
            )
            self._add_activity("ext:enable", f"enabled {kind} {name}")
            self._write_tako(f"enabled {kind} {name}.")
            return

        if cmd == "draft":
            if self.extensions_registry_path is None:
                self._write_tako("draft unavailable: runtime paths missing.")
                return
            parts = rest.strip().split(maxsplit=1)
            if len(parts) < 2:
                self._write_tako("usage: `draft skill <name>` or `draft tool <name>`")
                return
            kind = parts[0].strip().lower()
            name_raw = parts[1].strip()
            if kind not in {"skill", "tool"} or not name_raw:
                self._write_tako("usage: `draft skill <name>` or `draft tool <name>`")
                return
            root = repo_root()
            result = await asyncio.to_thread(
                create_draft_extension,
                root,
                registry_path=self.extensions_registry_path,
                kind=kind,
                name_raw=name_raw,
            )
            if not result.created:
                self._write_tako(result.message)
                return

            append_daily_note(daily_root(), date.today(), f"Drafted {kind} `{result.name}` (disabled).")
            self._record_event(
                "extensions.drafted",
                f"Extension drafted: {kind} {result.name}",
                source="terminal",
                metadata={"kind": kind, "name": result.name},
            )
            self._add_activity("ext:draft", f"drafted {kind} {result.name} (disabled)")
            self._write_tako(result.message)
            return

        if cmd == "web":
            target = rest.strip()
            if not target:
                self._write_tako("usage: `web <https://...>`")
                return
            self._add_activity("tool:web", f"fetching {target}")
            previous_indicator = self.indicator
            self._set_indicator("acting")
            try:
                result = await asyncio.to_thread(fetch_webpage, target)
            finally:
                if self.indicator == "acting":
                    self._set_indicator(previous_indicator if previous_indicator != "acting" else "idle")
            if not result.ok:
                self._add_activity("tool:web", f"failed: {result.error}")
                self._write_tako(f"web fetch failed: {result.error}")
                return
            title_line = f"title: {result.title}\n" if result.title else ""
            append_daily_note(daily_root(), date.today(), f"Local web fetch: {result.url}")
            self._write_tako(f"web: {result.url}\n{title_line}{result.text}")
            self._add_activity("tool:web", f"fetched {result.url}")
            return

        if cmd == "run":
            command = rest.strip()
            if not command:
                self._write_tako("usage: `run <shell command>`")
                return
            workdir = self.code_dir or ensure_code_dir(repo_root())
            self._add_activity("tool:run", f"executing `{command}`")
            previous_indicator = self.indicator
            self._set_indicator("acting")
            try:
                result = await asyncio.to_thread(run_local_command, command, cwd=workdir)
            finally:
                if self.indicator == "acting":
                    self._set_indicator(previous_indicator if previous_indicator != "acting" else "idle")
            if result.error:
                self._add_activity("tool:run", f"failed: {result.error}")
                self._write_tako(f"run failed: {result.error}")
                return
            self._write_tako(
                f"run: {result.command}\n"
                f"cwd: {workdir}\n"
                f"exit_code: {result.exit_code}\n"
                f"{result.output}"
            )
            self._add_activity("tool:run", f"finished exit={result.exit_code}")
            return

        if cmd == "copy":
            target = rest.strip().lower()
            if target == "last":
                self.action_copy_last_line()
                return
            if target == "transcript":
                self.action_copy_transcript()
                return
            self._write_tako("usage: `copy last` or `copy transcript`.")
            return

        if cmd == "activity":
            self._write_tako(_activity_text(list(self.activity_entries)))
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

        self._write_tako("unknown local command. type `help`. plain text chat always works here.")

    def _stream_clear(self) -> None:
        self.stream_active = False
        self.stream_provider = "none"
        self.stream_status_lines = []
        self.stream_reply = ""
        self.stream_focus = ""
        self.stream_started_at = None
        self.stream_last_render_at = 0.0
        if hasattr(self, "stream_box"):
            self.stream_box.load_text("")

    def _stream_begin(self, *, focus: str = "") -> None:
        self.stream_active = True
        self.stream_provider = "starting"
        self.stream_status_lines = []
        self.stream_reply = ""
        self.stream_focus = _stream_focus_summary(focus)
        self.stream_started_at = time.monotonic()
        self.stream_last_render_at = 0.0
        self._stream_render(force=True)

    def _on_inference_stream_event(self, kind: str, payload: str) -> None:
        if kind == "provider":
            self.stream_provider = payload.strip() or self.stream_provider
            self._stream_render(force=True)
            return

        if kind == "status":
            line = _sanitize_for_display(payload).strip()
            if not line:
                return
            self.stream_status_lines.append(line)
            if len(self.stream_status_lines) > STREAM_BOX_MAX_STATUS_LINES:
                self.stream_status_lines = self.stream_status_lines[-STREAM_BOX_MAX_STATUS_LINES :]
            self._stream_render()
            return

        if kind == "delta":
            delta = _sanitize_for_display(payload)
            if not delta:
                return
            self.stream_reply += delta
            if len(self.stream_reply) > STREAM_BOX_MAX_CHARS:
                self.stream_reply = self.stream_reply[-STREAM_BOX_MAX_CHARS :]
            self._stream_render()
            return

    def _stream_render(self, *, force: bool = False) -> None:
        now = time.monotonic()
        if not force and (now - self.stream_last_render_at) < 0.05:
            return
        self.stream_last_render_at = now

        elapsed_s = 0
        if self.stream_started_at is not None:
            elapsed_s = int(max(0.0, time.monotonic() - self.stream_started_at))
        header = (
            f"bubble stream: provider={self.stream_provider} | mind={self._thinking_visual()} | elapsed={elapsed_s}s\n"
        )
        focus = f"focus: {self.stream_focus}\n" if self.stream_focus else ""
        status = ""
        if self.stream_status_lines:
            status = "\n".join(self.stream_status_lines) + "\n\n"
        elif self.stream_active and elapsed_s >= 3:
            status = "thinking about the current request...\n\n"

        caret = "|" if self.stream_active else ""
        body = self.stream_reply + caret

        self.stream_box.load_text(header + focus + status + body)
        self.stream_box.scroll_end(animate=False)

    async def _local_chat_reply(self, text: str) -> str:
        if self.operator_paired:
            fallback = (
                "chat current is open here and over XMTP. "
                "config/tools/permissions/routines changes remain operator-only on XMTP."
            )
        else:
            fallback = "chat current is open. type `pair` when you want to establish XMTP operator control."

        if self.inference_runtime is None or not self.inference_runtime.ready:
            return fallback

        history = ""
        if self.conversations is not None:
            history = self.conversations.format_prompt_context(
                "terminal:main",
                user_turn_limit=CHAT_CONTEXT_USER_TURNS,
                max_chars=CHAT_CONTEXT_MAX_CHARS,
                user_label="User",
                assistant_label="Takobot",
            )

        prompt = _build_terminal_chat_prompt(
            text=text,
            mode=self.mode,
            state=self.state.value,
            operator_paired=self.operator_paired,
            history=history,
        )
        self._add_activity("inference", "terminal chat inference requested")
        self._stream_begin(focus=text)

        try:
            provider, reply = await stream_inference_prompt_with_fallback(
                self.inference_runtime,
                prompt,
                timeout_s=LOCAL_CHAT_TIMEOUT_S,
                on_event=self._on_inference_stream_event,
            )
        except Exception as exc:  # noqa: BLE001
            self.inference_last_error = _summarize_error(exc)
            self._record_event(
                "inference.chat.error",
                f"Terminal chat inference failed: {exc}",
                severity="warn",
                source="inference",
            )
            self._add_activity("inference", f"chat inference fallback: {self.inference_last_error}")
            self._stream_clear()
            return fallback
        finally:
            self.stream_active = False
            self._stream_render(force=True)

        cleaned = _clean_chat_reply(reply)
        if not cleaned:
            return fallback
        self.inference_ever_used = True
        self.inference_last_provider = provider
        self.inference_last_error = ""
        self._add_activity("inference", f"terminal chat used provider={provider}")
        self._record_event(
            "inference.chat.reply",
            "Terminal chat reply generated.",
            source="inference",
            metadata={"provider": provider},
        )
        return cleaned

    def _record_local_chat_turn(self, *, user_text: str, assistant_text: str) -> None:
        if self.conversations is None:
            return
        try:
            self.conversations.append_user_assistant("terminal:main", user_text, assistant_text)
        except Exception as exc:  # noqa: BLE001
            self._add_activity("memory", f"conversation save warning: {_summarize_error(exc)}")

    async def _infer_identity_name(self, text: str) -> str:
        if self.inference_runtime is None or not self.inference_runtime.ready:
            self._add_activity("identity", "name extraction blocked: inference unavailable")
            return ""

        prompt = build_identity_name_prompt(text=text, current_name=self.identity_name)
        self._add_activity("inference", "identity name extraction requested")
        try:
            provider, output = await asyncio.to_thread(
                run_inference_prompt_with_fallback,
                self.inference_runtime,
                prompt,
                timeout_s=45.0,
            )
        except Exception as exc:  # noqa: BLE001
            self.inference_last_error = _summarize_error(exc)
            self._add_activity("inference", f"identity name extraction failed: {self.inference_last_error}")
            self._record_event(
                "inference.identity_name.error",
                f"Identity name extraction failed: {exc}",
                severity="warn",
                source="inference",
            )
            return ""

        self.inference_ever_used = True
        self.inference_last_provider = provider
        self.inference_last_error = ""
        name = extract_name_from_model_output(_sanitize_for_display(output))
        if name:
            self._add_activity("inference", f"identity name extracted via provider={provider}")
        else:
            self._add_activity("inference", f"identity name extraction returned empty via provider={provider}")
        self._record_event(
            "inference.identity_name.result",
            "Identity name extraction completed.",
            source="inference",
            metadata={"provider": provider, "has_name": _yes_no(bool(name))},
        )
        return name

    async def _maybe_handle_inline_name_change(self, text: str) -> bool:
        if not looks_like_name_change_request(text):
            return False
        if self.paths is None:
            return False
        if self.inference_runtime is None or not self.inference_runtime.ready:
            self._write_tako("I can do that once inference is awake. try again in a moment, little captain.")
            return True

        previous = self.identity_name
        parsed_name = await self._infer_identity_name(text)
        if not parsed_name:
            self._write_tako("tiny clarification bubble: I couldn't isolate the name. try like: `call yourself SILLYTAKO`.")
            return True
        if parsed_name == previous:
            self._write_tako(f"already swimming under the name `{parsed_name}`.")
            return True

        self.identity_name = parsed_name
        self.identity_name, self.identity_role = update_identity(self.identity_name, self.identity_role)
        ok_name, summary_name = set_workspace_name(repo_root() / "tako.toml", self.identity_name)
        if not ok_name:
            self._write_system(f"name sync warning: {summary_name}")
        else:
            refreshed_cfg, _warn2 = load_tako_toml(repo_root() / "tako.toml")
            self.config = refreshed_cfg
        append_daily_note(
            daily_root(),
            date.today(),
            f"Identity updated in terminal chat: name {previous} -> {self.identity_name}",
        )
        self._record_event(
            "identity.name.updated",
            f"Identity name updated from {previous} to {self.identity_name}.",
            source="terminal",
            metadata={"old": previous, "new": self.identity_name},
        )
        self._add_activity("identity", f"name updated {previous} -> {self.identity_name}")
        self._write_tako(f"ink dried. I'll go by `{self.identity_name}` now.")
        return True

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
        if level in {"warn", "error"}:
            self._add_activity("runtime", f"{level}: {_summarize_text(message)}")
        elif message.startswith(("status:", "pairing:", "inbox_id:")):
            self._add_activity("runtime", _summarize_text(message))
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
        safe_text = _mask_sensitive_inference_command(text)
        self._write_system(f"xmtp<{short_sender}>: {safe_text}")
        self._add_activity("xmtp", f"inbound from {short_sender}")
        self._record_event(
            "xmtp.inbound.message",
            "Inbound XMTP message received.",
            source="xmtp",
            metadata={"sender_inbox_id": sender_inbox_id, "preview": _summarize_text(safe_text)},
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
        await self._stop_periodic_update_checks()
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

    def _thinking_phase(self) -> str:
        if self.stream_active:
            return "responding"
        if self.indicator.startswith("type2:"):
            depth = self.indicator.split(":", 1)[1] or "medium"
            return f"type2-{depth}"
        if self.indicator in {"thinking", "acting"}:
            return self.indicator
        return "idle"

    def _thinking_visual(self) -> str:
        phase = self._thinking_phase()
        if phase == "idle":
            return "idle"
        frame = THINKING_SPINNER_FRAMES[int(time.monotonic() * 8) % len(THINKING_SPINNER_FRAMES)]
        return f"{frame} {phase}"

    def _ensure_input_focus(self) -> None:
        input_box = getattr(self, "input_box", None)
        if input_box is None or input_box.disabled:
            return
        with contextlib.suppress(Exception):
            input_box.focus()

    def _hide_slash_menu(self) -> None:
        if not hasattr(self, "slash_menu"):
            return
        self.slash_menu.display = False
        self.slash_menu.update("")

    def _reset_tab_completion_state(self) -> None:
        self.command_completion_seed = ""
        self.command_completion_matches = []
        self.command_completion_index = -1

    def _apply_tab_completion(self) -> None:
        context = _command_completion_context(self.input_box.value)
        if context is None:
            return
        base, token, slash = context
        matches = _command_completion_matches(token, slash=slash)
        if not matches:
            return

        seed = f"{base}|{token}|{'slash' if slash else 'plain'}"
        index = 0
        if (
            seed == self.command_completion_seed
            and matches == self.command_completion_matches
            and 0 <= self.command_completion_index < len(matches)
        ):
            current = token.strip().lower()
            if current == matches[self.command_completion_index]:
                index = (self.command_completion_index + 1) % len(matches)
        elif token.strip().lower() in matches:
            current_index = matches.index(token.strip().lower())
            index = (current_index + 1) % len(matches)

        completed = f"{base}{matches[index]} "
        self.command_completion_seed = seed
        self.command_completion_matches = matches
        self.command_completion_index = index

        self._applying_tab_completion = True
        self.input_box.value = completed
        self.input_box.cursor_position = len(completed)
        self._applying_tab_completion = False
        self._update_slash_menu(completed)

    def _update_slash_menu(self, raw_text: str) -> None:
        if not hasattr(self, "slash_menu"):
            return
        value = raw_text.strip()
        if not value.startswith("/"):
            self._hide_slash_menu()
            return
        token = value[1:]
        if " " in token:
            self._hide_slash_menu()
            return
        matches = _slash_command_matches(token, limit=SLASH_MENU_MAX_ITEMS)
        if not matches:
            self._hide_slash_menu()
            return
        lines = ["Slash commands"]
        for command, summary in matches:
            lines.append(f"- {command}  {summary}")
        self.slash_menu.update("\n".join(lines))
        self.slash_menu.display = True

    def _refresh_status(self) -> None:
        uptime_s = int(time.monotonic() - self.started_at)
        safe = "on" if self.safe_mode else "off"
        updates = "on" if self.auto_updates_enabled else "off"
        thinking = self._thinking_visual()
        self.status_bar.update(
            f"state={self.state.value} | mode={self.mode} | runtime={self.runtime_mode} | "
            f"dose={self.dose_label} | indicator={self.indicator} | mind={thinking} | safe={safe} | updates={updates} | uptime={uptime_s}s"
        )
        self._refresh_panels()

    def _refresh_open_loops(self, *, save: bool) -> None:
        if self.paths is None:
            return

        root = repo_root()
        tasks = prod_tasks.list_tasks(root)
        self.open_tasks_count = sum(1 for task in tasks if task.is_open)

        daily_path = ensure_daily_log(daily_root(), date.today())
        with contextlib.suppress(Exception):
            prod_outcomes.ensure_outcomes_section(daily_path)
        outcomes = []
        with contextlib.suppress(Exception):
            outcomes = prod_outcomes.get_outcomes(daily_path)

        session = {
            "state": self.state.value,
            "operator_paired": self.operator_paired,
            "awaiting_xmtp_handle": self.awaiting_xmtp_handle,
            "safe_mode": self.safe_mode,
            "inference_ready": bool(self.inference_runtime is not None and self.inference_runtime.ready),
        }
        loops = prod_open_loops.compute_open_loops(tasks=tasks, outcomes=outcomes, session=session)
        loops.extend(list(self.signal_loops))
        self.open_loops_summary = prod_open_loops.summarize_open_loops(loops)

        if save and self.open_loops_path is not None:
            with contextlib.suppress(Exception):
                prod_open_loops.save_open_loops(self.open_loops_path, loops)

    def _refresh_panels(self) -> None:
        pair_next = "establish XMTP pairing" if not self.operator_paired else "process operator commands via XMTP"
        heartbeat_age = (
            f"{int(time.monotonic() - self.last_heartbeat_at)}s"
            if self.last_heartbeat_at is not None
            else "n/a"
        )
        update_check_age = (
            f"{int(time.monotonic() - self.last_update_check_at)}s"
            if self.last_update_check_at is not None
            else "n/a"
        )
        loops_count = int(self.open_loops_summary.get("count") or 0)
        loops_age_s = float(self.open_loops_summary.get("oldest_age_s") or 0.0)
        loops_age = f"{int(loops_age_s // 3600)}h" if loops_age_s >= 3600 else f"{int(loops_age_s)}s"
        thinking = self._thinking_visual()
        tasks = (
            "Tasks\n"
            f"- state: {self.state.value}\n"
            f"- instance: {self.instance_kind}\n"
            f"- next: {pair_next}\n"
            f"- runtime: {self.runtime_mode}\n"
            f"- mind: {thinking}\n"
            f"- safe mode: {'on' if self.safe_mode else 'off'}\n"
            f"- auto updates: {'on' if self.auto_updates_enabled else 'off'}\n"
            f"- inference gate: {'open' if self.inference_gate_open else 'closed'}\n"
            f"- open tasks: {self.open_tasks_count}\n"
            f"- open loops: {loops_count} (oldest {loops_age})\n"
            f"- heartbeat ticks: {self.heartbeat_ticks}\n"
            f"- last heartbeat: {heartbeat_age}\n"
            f"- last update check: {update_check_age}"
        )
        self.tasks_panel.update(tasks)
        level = _octopus_level(
            heartbeat_ticks=self.heartbeat_ticks,
            type2_escalations=self.type2_escalations,
            operator_paired=self.operator_paired,
        )
        frame = int((time.monotonic() - self.started_at) * 2.0)
        self.octo_panel.update(
            _octopus_panel_text(
                level,
                frame,
                version=__version__,
                dose_state=self.dose,
                dose_label=self.dose_label,
                thinking=thinking,
            )
        )

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
        inference_provider = self.inference_runtime.selected_provider if self.inference_runtime else "none"
        inference_ready = "yes" if self.inference_runtime and self.inference_runtime.ready else "no"
        inference_source = self.inference_runtime.selected_key_source if self.inference_runtime else None
        if self.dose is None:
            dose_line = "- dose: not ready"
        else:
            dose_line = (
                f"- dose: D={self.dose.d:.2f} O={self.dose.o:.2f} S={self.dose.s:.2f} "
                f"E={self.dose.e:.2f} (label={self.dose_label})"
            )
        sensors = (
            "Sensors\n"
            f"- xmtp ingress: {'active' if self.operator_paired and not self.safe_mode else 'inactive'}\n"
            f"- mind: {thinking}\n"
            f"- auto updates: {'on' if self.auto_updates_enabled else 'off'}\n"
            f"- type1 processed: {self.type1_processed}\n"
            f"- type2 escalations: {self.type2_escalations}\n"
            f"- type2 last: {self.type2_last}\n"
            f"{dose_line}\n"
            f"- inference: {inference_provider} (ready={inference_ready})\n"
            f"- inference gate: {'open' if self.inference_gate_open else 'closed'}\n"
            f"- inference source: {inference_source or 'none'}\n"
            f"- operator: {operator}\n"
            f"- events written: {self.event_total_written} / ingested: {self.event_total_ingested}"
        )
        self.sensors_panel.update(sensors)
        self.activity_panel.update(_activity_text(list(self.activity_entries)))

    def _write_tako(self, text: str) -> None:
        safe = _sanitize_for_display(text)
        line = f"Tako: {safe}"
        self._append_transcript_line(line)
        self._append_app_log("tako", safe)

    def _write_user(self, text: str) -> None:
        safe = _sanitize_for_display(text)
        line = f"You: {safe}"
        self._append_transcript_line(line)
        self._append_app_log("user", safe)

    def _write_system(self, text: str) -> None:
        safe = _sanitize_for_display(text)
        line = f"System: {safe}"
        self._append_transcript_line(line)
        self._append_app_log("system", safe)

    def _append_transcript_line(self, line: str) -> None:
        self.transcript_lines.append(line)
        payload = "\n".join(self.transcript_lines)
        self.transcript.load_text(payload)
        self.transcript.scroll_end(animate=False)

    def _append_app_log(self, channel: str, message: str) -> None:
        if self.app_log_path is None:
            return
        stamp = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
        safe_channel = channel.strip().lower() or "system"
        safe_message = " ".join(message.split())
        with contextlib.suppress(Exception):
            self.app_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.app_log_path.open("a", encoding="utf-8") as handle:
                handle.write(f"{stamp} [{safe_channel}] {safe_message}\n")

    def _add_activity(self, kind: str, detail: str) -> None:
        stamp = datetime.now().strftime("%H:%M:%S")
        entry = f"{stamp} {kind}: {_summarize_text(_sanitize_for_display(detail))}"
        self.activity_entries.appendleft(entry)
        self._refresh_panels()

    def _error_card(self, summary: str, detail: str, next_steps: list[str]) -> None:
        self._write_system(f"ERROR: {summary}: {_summarize_text(detail)}")
        self._write_system("Next steps:")
        for step in next_steps:
            self._write_system(f"- {step}")
        severity = "critical" if summary == "startup blocked" else "error"
        with contextlib.suppress(Exception):
            append_daily_note(
                daily_root(),
                date.today(),
                f"Error card: {summary}: {_summarize_text(_sanitize_for_display(detail))}",
            )
        self._record_event(
            "ui.error_card",
            f"{summary}: {_summarize_text(detail)}",
            severity=severity,
            source="ui",
            metadata={"summary": summary},
        )


def run_terminal_app(*, interval: float = 30.0) -> int:
    app = TakoTerminalApp(interval=interval)
    # Keep terminal-native text selection/copy behavior (right-click/context-menu) by
    # disabling mouse reporting in app mode.
    app.run(mouse=False)
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


def _strip_terminal_controls(value: str) -> str:
    cleaned = ANSI_CSI_RE.sub("", value)
    cleaned = ANSI_OSC_RE.sub("", cleaned)
    cleaned = cleaned.replace("\r", "")
    cleaned = CONTROL_CHARS_RE.sub("", cleaned)
    return cleaned


def _sanitize_for_display(value: str) -> str:
    return _strip_terminal_controls(value)


def _contains_terminal_control(value: str) -> bool:
    return _strip_terminal_controls(value) != value


def _sanitize(value: str) -> str:
    cleaned = _strip_terminal_controls(value)
    return " ".join(cleaned.strip().split())


def _clean_paste_text(value: str) -> str:
    cleaned = _strip_terminal_controls(value).replace("\r", "\n")
    lines = [line.strip() for line in cleaned.split("\n")]
    parts = [line for line in lines if line]
    return " ".join(parts)


def _copy_to_system_clipboard(value: str) -> str | None:
    candidates = [
        ("pbcopy",),
        ("wl-copy",),
        ("xclip", "-selection", "clipboard"),
        ("xsel", "--clipboard", "--input"),
        ("clip.exe",),
    ]
    for command in candidates:
        executable = command[0]
        if shutil.which(executable) is None:
            continue
        try:
            subprocess.run(
                command,
                input=value,
                text=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=2,
            )
        except Exception:
            continue
        return executable
    return None


def _paste_from_system_clipboard() -> tuple[str | None, str | None]:
    candidates = [
        ("pbpaste",),
        ("wl-paste", "-n"),
        ("xclip", "-selection", "clipboard", "-out"),
        ("xsel", "--clipboard", "--output"),
        ("powershell.exe", "-NoProfile", "-Command", "Get-Clipboard"),
    ]
    for command in candidates:
        executable = command[0]
        if shutil.which(executable) is None:
            continue
        try:
            completed = subprocess.run(
                command,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=2,
            )
        except Exception:
            continue
        if not completed.stdout:
            continue
        return completed.stdout, executable
    return None, None


def _persist_clipboard_payload(state_dir: Path | None, value: str) -> Path | None:
    if state_dir is None:
        return None
    target = state_dir / "clipboard.txt"
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value, encoding="utf-8")
    except Exception:
        return None
    return target


def _parse_yes_no(value: str) -> bool | None:
    normalized = value.strip().lower()
    if normalized in {"y", "yes", "true", "1", "ok", "sure"}:
        return True
    if normalized in {"n", "no", "false", "0", "nope"}:
        return False
    return None


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


def _mask_sensitive_inference_command(text: str) -> str:
    cmd, rest = _parse_command(text)
    if cmd != "inference":
        return text
    parts = rest.strip().split(maxsplit=3)
    if len(parts) == 4 and parts[0].lower() == "key" and parts[1].lower() == "set":
        return f"inference key set {parts[2]} ********"
    return text


def _slash_command_matches(query: str, *, limit: int = SLASH_MENU_MAX_ITEMS) -> list[tuple[str, str]]:
    needle = query.strip().lower()
    results: list[tuple[str, str]] = []
    for command, summary in SLASH_COMMAND_SPECS:
        key = command[1:].lower()
        if needle and not key.startswith(needle):
            continue
        results.append((command, summary))
    return results[: max(1, int(limit))]


def _command_completion_context(value: str) -> tuple[str, str, bool] | None:
    raw = value.rstrip("\n")
    if not raw.strip():
        return None
    leading = raw[: len(raw) - len(raw.lstrip())]
    rest = raw[len(leading) :]
    prefix = ""
    lowered = rest.lower()
    if lowered.startswith("takobot "):
        prefix = rest[:8]
        rest = rest[8:]
    elif lowered.startswith("tako "):
        prefix = rest[:5]
        rest = rest[5:]
    slash = rest.startswith("/")
    if slash:
        rest = rest[1:]
    if any(ch.isspace() for ch in rest):
        return None
    if not slash and not rest:
        return None
    base = f"{leading}{prefix}{'/' if slash else ''}"
    return base, rest.strip().lower(), slash


def _command_completion_matches(query: str, *, slash: bool) -> list[str]:
    needle = query.strip().lower()
    if slash:
        candidates = [command[1:].lower() for command, _summary in SLASH_COMMAND_SPECS]
    else:
        candidates = list(LOCAL_COMMAND_COMPLETIONS)
    if not needle:
        return sorted(candidates)
    return sorted(candidate for candidate in candidates if candidate.startswith(needle))


def _parse_dose_set_request(action: str) -> tuple[str, float] | None:
    parts = action.strip().split()
    if len(parts) != 2:
        return None
    channel = _normalize_dose_channel(parts[0])
    if channel is None:
        return None
    try:
        value = float(parts[1])
    except Exception:
        return None
    value = max(0.0, min(1.0, value))
    return channel, value


def _normalize_dose_channel(token: str) -> str | None:
    value = token.strip().lower()
    aliases = {
        "d": "d",
        "dop": "d",
        "dopamine": "d",
        "o": "d",
        "ox": "o",
        "oxy": "o",
        "oxytocin": "o",
        "s": "s",
        "ser": "s",
        "serotonin": "s",
        "e": "e",
        "endo": "e",
        "endorphin": "e",
        "endorphins": "e",
    }
    return aliases.get(value)


def _dose_channel_label(channel: str) -> str:
    names = {
        "d": "dopamine",
        "o": "oxytocin",
        "s": "serotonin",
        "e": "endorphins",
    }
    return names.get(channel, "dose")


def _format_level(value: float) -> str:
    return f"{max(0.0, min(1.0, value)):.2f}".rstrip("0").rstrip(".")


def _looks_like_local_command(text: str) -> bool:
    value = text.strip()
    if not value:
        return False
    lowered = value.lower()
    if lowered.startswith("takobot ") or lowered.startswith("tako ") or value.startswith("/"):
        return True

    cmd, rest = _parse_command(value)
    tail = rest.strip().lower()
    if cmd in {"help", "h", "?", "status", "stats", "health", "doctor", "config", "toml", "models", "pair", "setup", "profile", "stop", "resume", "quit", "exit", "activity"}:
        return tail == ""
    if cmd == "dose":
        return tail in {"", "show", "status", "calm", "explore", "help", "?"} or _parse_dose_set_request(tail) is not None
    if cmd == "morning":
        return tail == ""
    if cmd == "task":
        return True
    if cmd == "tasks":
        return True
    if cmd == "done":
        return tail != ""
    if cmd == "outcomes":
        return True
    if cmd == "compress":
        return tail in {"", "today"}
    if cmd == "weekly":
        return tail == ""
    if cmd == "review":
        return tail in {"weekly", "week", "pending"}
    if cmd == "promote":
        return True
    if cmd == "inference":
        return True
    if cmd == "update":
        return tail in {"", "check", "status", "dry-run", "dryrun", "help", "?"}
    if cmd == "upgrade":
        return tail in {"", "check", "status", "dry-run", "dryrun", "help", "?"}
    if cmd == "reimprint":
        return True
    if cmd in {"web", "run"}:
        return tail != ""
    if cmd == "copy":
        return tail in {"last", "transcript"}
    if cmd == "safe":
        return tail in {"", "on", "off", "enable", "enabled", "disable", "disabled", "true", "false", "1", "0"}
    if cmd == "install":
        return True
    if cmd == "enable":
        return tail != ""
    if cmd == "draft":
        return tail != ""
    if cmd == "extensions":
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


def _build_terminal_chat_prompt(*, text: str, mode: str, state: str, operator_paired: bool, history: str) -> str:
    paired = "yes" if operator_paired else "no"
    history_block = f"{history}\n" if history else "(none)\n"
    return (
        "You are Tako, a super cute octopus assistant with pragmatic engineering judgment.\n"
        "Reply with plain text only (no markdown), maximum 4 short lines.\n"
        "Be incredibly curious about the world: ask sharp follow-up questions and suggest quick research when uncertain.\n"
        "Terminal chat is always available.\n"
        "Hard boundary: identity/config/tools/permissions/routines remain operator-only over XMTP when paired.\n"
        f"session_mode={mode}\n"
        f"session_state={state}\n"
        f"operator_paired={paired}\n"
        "recent_conversation=\n"
        f"{history_block}"
        f"user_message={text}\n"
    )


def _clean_chat_reply(text: str) -> str:
    value = _sanitize_for_display(" ".join(text.strip().split()))
    if not value:
        return ""
    if len(value) > LOCAL_CHAT_MAX_CHARS:
        return value[: LOCAL_CHAT_MAX_CHARS - 3] + "..."
    return value


def _inference_setup_hints(runtime: InferenceRuntime) -> list[str]:
    hints: list[str] = []

    pi = runtime.statuses.get("pi")
    if pi and not pi.ready:
        if not pi.cli_installed:
            hints.append("pi runtime missing; run bootstrap/setup to install workspace-local pi tooling.")
        else:
            hints.append("run `inference auth` to inspect pi oauth tokens, or set API keys via `inference key set ...`.")

    ollama = runtime.statuses.get("ollama")
    if ollama and not ollama.ready:
        if not ollama.cli_installed:
            hints.append("install Ollama and pull a model (or use another provider).")
        else:
            hints.append("set `inference ollama model <name>` (or `OLLAMA_MODEL`) so ollama can answer prompts.")

    codex = runtime.statuses.get("codex")
    if codex and not codex.ready:
        if not codex.cli_installed:
            hints.append("install Codex CLI (`npm i -g @openai/codex`) or add `codex` to PATH.")
        else:
            hints.append("run `codex login` or set `OPENAI_API_KEY`.")

    claude = runtime.statuses.get("claude")
    if claude and not claude.ready:
        if not claude.cli_installed:
            hints.append("install Claude CLI and add `claude` to PATH.")
        else:
            hints.append("set `ANTHROPIC_API_KEY` (or `CLAUDE_API_KEY`) for Claude inference.")

    gemini = runtime.statuses.get("gemini")
    if gemini and not gemini.ready:
        if not gemini.cli_installed:
            hints.append("install Gemini CLI and add `gemini` to PATH.")
        else:
            hints.append("run `gemini` and complete auth, or set `GEMINI_API_KEY` / `GOOGLE_API_KEY`.")

    return hints


def _build_type2_prompt(*, event: dict[str, Any], depth: str, reason: str, fallback: str) -> str:
    event_type = str(event.get("type", "unknown"))
    severity = str(event.get("severity", "info"))
    source = str(event.get("source", "system"))
    message = str(event.get("message", ""))
    metadata = event.get("metadata")
    metadata_json = json.dumps(metadata, ensure_ascii=True, sort_keys=True) if isinstance(metadata, dict) else "{}"

    return (
        "You are Tako Type2 reasoning.\n"
        "Given an operational event, produce exactly one concise safe recommendation line.\n"
        "Priorities: safety, reversibility, operator control boundary, and immediate next action.\n"
        "No markdown, no bullets, <= 180 characters.\n"
        f"depth={depth}\n"
        f"reason={reason}\n"
        f"event.type={event_type}\n"
        f"event.severity={severity}\n"
        f"event.source={source}\n"
        f"event.message={message}\n"
        f"event.metadata={metadata_json}\n"
        f"fallback={fallback}\n"
    )


def _type2_inference_timeout(depth: str) -> float:
    if depth == "deep":
        return 120.0
    if depth == "medium":
        return 85.0
    return 60.0


def _summarize_error(error: Exception) -> str:
    return _summarize_text(str(error) or error.__class__.__name__)


def _summarize_text(text: str) -> str:
    value = " ".join(text.split())
    if len(value) <= 220:
        return value
    return f"{value[:217]}..."


def _stream_focus_summary(text: str) -> str:
    value = " ".join(_sanitize_for_display(text).split())
    if not value:
        return ""
    if len(value) <= 120:
        return value
    return f"{value[:117]}..."


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


def _is_git_identity_error(text: str) -> bool:
    lowered = text.lower()
    return "user.name" in lowered or "user.email" in lowered or "author identity unknown" in lowered


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
        return "XMTP dependency is missing. Install `takobot` (or `xmtp`) into `.venv`, then retry pairing/runtime startup."
    if "user.name" in text or "user.email" in text or "author identity unknown" in text:
        return "Git identity setup failed. Takobot auto-configures repo-local identity from workspace name; if this persists, set `git config user.name ...` and `git config user.email ...`."
    if "dns lookup for xmtp" in text:
        return "Check network/DNS egress for XMTP hosts, then retry pairing or runtime startup."
    if "runtime crashed" in text or "runtime.crash" in kind:
        return "Enable safe mode, inspect `doctor` output, then restart XMTP runtime."
    if kind.startswith("health.check.issue"):
        return "Resolve reported health issue before proceeding with risky actions."
    return "Review the event details, then choose a safe next action or pause in safe mode."


def _activity_text(entries: list[str]) -> str:
    if not entries:
        return "Activity\n- idle"
    lines = ["Activity"]
    for entry in entries[:10]:
        lines.append(f"- {entry}")
    return "\n".join(lines)


def _dose_productivity_hint(state: dose.DoseState) -> str:
    # Light-touch hint for operator planning. This should never override policy or force actions.
    if state.label() == "stressed":
        return "stressed tide: reduce churn, pick 1 tiny next action, and consider a summary pass (`compress`)."
    if state.e < 0.42:
        return "low E: keep tasks small, prefer quick wins + summaries over big context switches."
    if state.s >= 0.78:
        return "high S: great for cleanup, maintenance, and finishing open loops."
    if state.d >= 0.78:
        return "high D: good time for exploration, drafting, and new threads."
    if state.o >= 0.78:
        return "high O: good time for check-ins, alignment, and writing down intent."
    return ""


def _octopus_level(*, heartbeat_ticks: int, type2_escalations: int, operator_paired: bool) -> int:
    score = (heartbeat_ticks // 20) + type2_escalations + (2 if operator_paired else 0)
    if score >= 18:
        return 4
    if score >= 10:
        return 3
    if score >= 4:
        return 2
    if score >= 1:
        return 1
    return 0


def _octopus_panel_text(
    level: int,
    frame: int,
    *,
    version: str,
    dose_state: dose.DoseState | None,
    dose_label: str,
    thinking: str,
) -> str:
    art = _octopus_art(level, frame)
    mood = "zzz" if frame % 12 == 0 else "~"
    if dose_state is None:
        dose_line = "D○○○○ O○○○○ S○○○○ E○○○○ pending"
    else:
        dose_line = (
            f"D{_dose_meter(dose_state.d)} "
            f"O{_dose_meter(dose_state.o)} "
            f"S{_dose_meter(dose_state.s)} "
            f"E{_dose_meter(dose_state.e)} "
            f"{dose_label}"
        )
    return f"Takobot v{version} | L{level} {mood}\nMind {thinking}\n{dose_line}\n{art}"


def _dose_meter(value: float, *, width: int = 4) -> str:
    clamped = max(0.0, min(1.0, float(value)))
    filled = int(round(clamped * width))
    filled = max(0, min(width, filled))
    return ("●" * filled) + ("○" * (width - filled))


def _octopus_art(level: int, frame: int) -> str:
    phase = frame % 4
    blink = frame % 12 == 0
    eyes = "- -" if blink else ("O O" if level >= 4 else "o o")
    beak = "><" if level >= 2 else "^"

    band = ".-~~~~-." if level >= 3 else ".-\"\"\"-."

    bubble_offsets = [5, 3, 7, 4]
    bubble_chars = ["o", "o", ("O" if level >= 4 else "o"), "o"]
    bubble = " " * bubble_offsets[phase] + bubble_chars[phase]
    crown = "  ^-^" if level >= 4 else ""

    tentacles = [
        ("_/~~\\__/~~\\_", "/__/~~\\__/~~\\__\\", "\\__\\__/~~\\__/__/_"),
        ("_/~~\\_/~~\\__", "/__/~~\\__/~~\\__\\", "\\__\\__/~~\\__/__/_"),
        ("__/~~\\__/~~\\_", "/__/~~\\_/~~\\__\\", "\\__\\__/~~\\__/__/_"),
        ("_/~~\\__/~~\\__", "/__/~~\\__/~~\\__\\", "\\__\\__/~~\\__/__/_"),
    ]
    t1, t2, t3 = tentacles[phase]

    lines = [
        f"{bubble}{crown}".rstrip(),
        band,
        f"/  {eyes}  \\",
        f"|    {beak}    |",
        r"|  \____/  |",
        r"\________/",
        t1,
        t2,
        t3,
    ]

    drift = [0, 1, 2, 1][phase]
    prefix = " " * (2 + drift)
    return "\n".join(prefix + line for line in lines)


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
