from __future__ import annotations

import argparse
import asyncio
import contextlib
import random
import secrets
import socket
import time
from datetime import date
from enum import Enum

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
        self.boot_task: asyncio.Task[None] | None = None

        self.lock_context = None
        self.lock_acquired = False
        self.shutdown_complete = False

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
        self._write_tako(f"identity tucked away in my little shell: {self.identity_name} — {self.identity_role}")
        self._set_state(SessionState.ONBOARDING_ROUTINES)
        self._write_tako("last onboarding nibble: what should I watch or do daily? free-form note.")

    async def _handle_routines_onboarding(self, text: str) -> None:
        self.routines = text or "No explicit routines yet."
        if self.paths is not None:
            routines_path = self.paths.state_dir / "routines.txt"
            routines_path.write_text(self.routines + "\n", encoding="utf-8")
        append_daily_note(daily_root(), date.today(), f"Routine note captured: {self.routines}")
        await self._finalize_onboarding()

    async def _handle_xmtp_handle_prompt(self, text: str) -> None:
        lowered = text.strip().lower()
        if lowered in {"local", "local-only", "skip"}:
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
            self._write_tako("splash it over: share the handle (.eth or 0x...).")
            return

        if self.mode == "onboarding":
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
        self._set_state(SessionState.RUNNING)
        await self._stop_xmtp_runtime()
        await self._start_local_heartbeat()
        self._write_tako("continuing in terminal-managed local mode. use `pair` any time to add XMTP operator control.")

    async def _finalize_onboarding(self) -> None:
        if self.operator_paired:
            self.mode = "paired"
            self._set_state(SessionState.PAIRED)
            self._write_tako("onboarding complete. spinning up XMTP runtime currents.")
            await self._start_xmtp_runtime()
            self._set_state(SessionState.RUNNING)
            self._write_tako("all tentacles online. terminal remains your local cockpit. type `help`.")
            return

        await self._enter_local_only_mode()

    def _begin_identity_onboarding(self) -> None:
        self.mode = "onboarding"
        self._set_state(SessionState.ONBOARDING_IDENTITY)
        self.identity_step = 0
        self._write_tako("next tiny question: what should I be called?")

    async def _start_xmtp_runtime(self) -> None:
        if self.paths is None:
            self._write_tako("cannot start XMTP runtime: paths unavailable.")
            return
        if self.safe_mode:
            self.runtime_mode = "safe"
            self._write_tako("safe mode is enabled; XMTP runtime is paused.")
            return

        await self._stop_local_heartbeat()
        await self._stop_xmtp_runtime()

        hooks = RuntimeHooks(log=self._on_runtime_log, inbound_message=self._on_runtime_inbound, emit_console=False)
        args = argparse.Namespace(interval=self.interval, once=False)
        self.runtime_mode = "stream"
        self.runtime_task = asyncio.create_task(
            self._run_runtime_task(args, hooks),
            name="tako-xmtp-runtime",
        )

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

    async def _stop_xmtp_runtime(self) -> None:
        if self.runtime_task is None:
            return
        self.runtime_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.runtime_task
        self.runtime_task = None
        self.runtime_mode = "offline"

    async def _start_local_heartbeat(self) -> None:
        if self.local_heartbeat_task is not None:
            return
        self.local_heartbeat_task = asyncio.create_task(self._local_heartbeat_loop(), name="tako-local-heartbeat")

    async def _stop_local_heartbeat(self) -> None:
        if self.local_heartbeat_task is None:
            return
        self.local_heartbeat_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self.local_heartbeat_task
        self.local_heartbeat_task = None

    async def _local_heartbeat_loop(self) -> None:
        self.runtime_mode = "local-heartbeat"
        while True:
            ensure_daily_log(daily_root(), date.today())
            await asyncio.sleep(self.interval + random.uniform(-0.2 * self.interval, 0.2 * self.interval))

    async def _enable_safe_mode(self) -> None:
        self.safe_mode = True
        self.mode = "safe"
        await self._stop_local_heartbeat()
        await self._stop_xmtp_runtime()
        self.runtime_mode = "safe"
        self._write_tako("safe mode enabled. tucked into a little shell for now.")

    async def _disable_safe_mode(self) -> None:
        self.safe_mode = False
        self._write_tako("safe mode disabled. paddling again.")
        if self.operator_paired:
            self.mode = "paired"
            await self._start_xmtp_runtime()
        else:
            self.mode = "local-only"
            await self._start_local_heartbeat()

    async def _handle_running_input(self, text: str) -> None:
        cmd, rest = _parse_command(text)
        if cmd in {"help", "h", "?"}:
            self._write_tako(
                "local cockpit commands: help, status, doctor, pair, safe on, safe off, stop, resume, quit"
            )
            return

        if cmd == "status":
            uptime = int(time.monotonic() - self.started_at)
            paired = "yes" if self.operator_paired else "no"
            safe = "on" if self.safe_mode else "off"
            self._write_tako(
                "status: ok\n"
                f"paired: {paired}\n"
                f"mode: {self.mode}\n"
                f"runtime_mode: {self.runtime_mode}\n"
                f"safe_mode: {safe}\n"
                f"uptime_s: {uptime}\n"
                f"version: {__version__}\n"
                f"tako_address: {self.address}"
            )
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
            self.runtime_mode = "local-heartbeat"

        if level in {"warn", "error"} or message.startswith(("status:", "pairing:", "inbox_id:")):
            self._write_system(f"runtime[{level}]: {message}")

    def _on_runtime_inbound(self, sender_inbox_id: str, text: str) -> None:
        short_sender = sender_inbox_id[:10]
        self._write_system(f"xmtp<{short_sender}>: {text}")

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
        tasks = (
            "Tasks\n"
            f"- state: {self.state.value}\n"
            f"- next: {pair_next}\n"
            f"- runtime: {self.runtime_mode}\n"
            f"- safe mode: {'on' if self.safe_mode else 'off'}"
        )
        self.tasks_panel.update(tasks)

        memory = (
            "Memory\n"
            f"- name: {self.identity_name}\n"
            f"- role: {self.identity_role}\n"
            f"- daily log: memory/dailies/{date.today().isoformat()}.md\n"
            f"- routines: {self.routines or 'not captured yet'}"
        )
        self.memory_panel.update(memory)

        operator = self.operator_address or "not paired"
        sensors = (
            "Sensors\n"
            f"- xmtp ingress: {'active' if self.operator_paired and not self.safe_mode else 'inactive'}\n"
            "- task sensor: disabled\n"
            "- memory sensor: disabled\n"
            f"- operator: {operator}"
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
