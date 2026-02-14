from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


PROVIDER_PRIORITY = ("codex", "claude", "gemini")
CODEX_AGENTIC_EXEC_ARGS = [
    "--skip-git-repo-check",
    "--dangerously-bypass-approvals-and-sandbox",
]

StreamEventHook = Callable[[str, str], None]


@dataclass(frozen=True)
class InferenceProviderStatus:
    provider: str
    cli_name: str
    cli_path: str | None
    cli_installed: bool
    auth_kind: str
    key_env_var: str | None
    key_source: str | None
    key_present: bool
    ready: bool
    note: str = ""


@dataclass
class InferenceRuntime:
    statuses: dict[str, InferenceProviderStatus]
    selected_provider: str | None
    selected_auth_kind: str
    selected_key_env_var: str | None
    selected_key_source: str | None
    _api_keys: dict[str, str]

    @property
    def ready(self) -> bool:
        if not self.selected_provider:
            return False
        status = self.statuses.get(self.selected_provider)
        return bool(status and status.ready)

    def selected_env_overrides(self) -> dict[str, str]:
        if not self.selected_provider:
            return {}
        return self.env_overrides_for(self.selected_provider)

    def env_overrides_for(self, provider: str) -> dict[str, str]:
        if provider not in self._api_keys:
            return {}
        status = self.statuses.get(provider)
        if not status or not status.key_env_var:
            return {}
        return {status.key_env_var: self._api_keys[provider]}


def discover_inference_runtime() -> InferenceRuntime:
    home = Path.home()
    env = os.environ
    statuses: dict[str, InferenceProviderStatus] = {}
    api_keys: dict[str, str] = {}

    codex_status, codex_key = _detect_codex(home, env)
    statuses["codex"] = codex_status
    if codex_key:
        api_keys["codex"] = codex_key

    claude_status, claude_key = _detect_claude(home, env)
    statuses["claude"] = claude_status
    if claude_key:
        api_keys["claude"] = claude_key

    gemini_status, gemini_key = _detect_gemini(home, env)
    statuses["gemini"] = gemini_status
    if gemini_key:
        api_keys["gemini"] = gemini_key

    requested_provider = os.environ.get("TAKO_INFERENCE_PROVIDER", "").strip().lower()
    selected_provider = None
    if requested_provider in statuses and statuses[requested_provider].ready:
        selected_provider = requested_provider
    for provider in PROVIDER_PRIORITY:
        if selected_provider:
            break
        status = statuses.get(provider)
        if status and status.ready:
            selected_provider = provider
            break

    selected_status = statuses.get(selected_provider or "")
    return InferenceRuntime(
        statuses=statuses,
        selected_provider=selected_provider,
        selected_auth_kind=selected_status.auth_kind if selected_status else "none",
        selected_key_env_var=selected_status.key_env_var if selected_status else None,
        selected_key_source=selected_status.key_source if selected_status else None,
        _api_keys=api_keys,
    )


def persist_inference_runtime(path: Path, runtime: InferenceRuntime) -> None:
    payload = {
        "updated_at": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
        "selected_provider": runtime.selected_provider or "none",
        "selected_auth_kind": runtime.selected_auth_kind,
        "selected_key_env_var": runtime.selected_key_env_var or "",
        "selected_key_source": runtime.selected_key_source or "",
        "providers": {
            provider: {
                "cli_name": status.cli_name,
                "cli_path": status.cli_path or "",
                "cli_installed": status.cli_installed,
                "auth_kind": status.auth_kind,
                "key_env_var": status.key_env_var or "",
                "key_source": status.key_source or "",
                "key_present": status.key_present,
                "ready": status.ready,
                "note": status.note,
            }
            for provider, status in sorted(runtime.statuses.items())
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def run_inference_prompt(runtime: InferenceRuntime, prompt: str, *, timeout_s: float = 70.0) -> str:
    provider = runtime.selected_provider
    if not provider:
        raise RuntimeError("no inference provider selected")
    status = runtime.statuses.get(provider)
    if not status or not status.ready:
        raise RuntimeError("selected inference provider is not ready")

    return _run_with_provider(runtime, provider, prompt, timeout_s=timeout_s)


def run_inference_prompt_with_fallback(
    runtime: InferenceRuntime,
    prompt: str,
    *,
    timeout_s: float = 70.0,
) -> tuple[str, str]:
    order: list[str] = []
    if runtime.selected_provider:
        status = runtime.statuses.get(runtime.selected_provider)
        if status and status.ready:
            order.append(runtime.selected_provider)
    for provider in PROVIDER_PRIORITY:
        status = runtime.statuses.get(provider)
        if not status or not status.ready:
            continue
        if provider in order:
            continue
        order.append(provider)

    if not order:
        raise RuntimeError("no ready inference providers available")

    failures: list[str] = []
    for provider in order:
        try:
            text = _run_with_provider(runtime, provider, prompt, timeout_s=timeout_s)
            return provider, text
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{provider}: {_summarize_error_text(str(exc))}")

    detail = "; ".join(failures) if failures else "all provider attempts failed"
    raise RuntimeError(f"inference provider fallback exhausted: {detail}")


async def stream_inference_prompt_with_fallback(
    runtime: InferenceRuntime,
    prompt: str,
    *,
    timeout_s: float = 70.0,
    on_event: StreamEventHook | None = None,
) -> tuple[str, str]:
    order: list[str] = []
    if runtime.selected_provider:
        status = runtime.statuses.get(runtime.selected_provider)
        if status and status.ready:
            order.append(runtime.selected_provider)
    for provider in PROVIDER_PRIORITY:
        status = runtime.statuses.get(provider)
        if not status or not status.ready:
            continue
        if provider in order:
            continue
        order.append(provider)

    if not order:
        raise RuntimeError("no ready inference providers available")

    failures: list[str] = []
    for provider in order:
        if on_event:
            on_event("provider", provider)
        try:
            text = await _stream_with_provider(runtime, provider, prompt, timeout_s=timeout_s, on_event=on_event)
            return provider, text
        except Exception as exc:  # noqa: BLE001
            failures.append(f"{provider}: {_summarize_error_text(str(exc))}")
            if on_event:
                on_event("status", f"{provider} failed: {_summarize_error_text(str(exc))}")

    detail = "; ".join(failures) if failures else "all provider attempts failed"
    raise RuntimeError(f"inference provider fallback exhausted: {detail}")


def format_runtime_lines(runtime: InferenceRuntime) -> list[str]:
    selected = runtime.selected_provider or "none"
    lines = [
        f"inference selected: {selected}",
        f"inference ready: {'yes' if runtime.ready else 'no'}",
    ]
    if runtime.selected_provider:
        lines.append(f"inference auth: {runtime.selected_auth_kind}")
        if runtime.selected_key_source:
            lines.append(f"inference key source: {runtime.selected_key_source}")

    for provider in PROVIDER_PRIORITY:
        status = runtime.statuses.get(provider)
        if not status:
            continue
        lines.append(
            f"{provider}: cli={'yes' if status.cli_installed else 'no'} "
            f"auth={status.auth_kind} ready={'yes' if status.ready else 'no'} "
            f"source={status.key_source or 'none'}"
        )
    return lines


def _detect_codex(home: Path, env: os._Environ[str]) -> tuple[InferenceProviderStatus, str | None]:
    cli_name = "codex"
    cli_path = shutil.which(cli_name)
    cli_installed = cli_path is not None
    auth_path = home / ".codex" / "auth.json"

    env_key = _env_non_empty(env, "OPENAI_API_KEY")
    if env_key:
        return (
            InferenceProviderStatus(
                provider="codex",
                cli_name=cli_name,
                cli_path=cli_path,
                cli_installed=cli_installed,
                auth_kind="api_key",
                key_env_var="OPENAI_API_KEY",
                key_source="env:OPENAI_API_KEY",
                key_present=True,
                ready=cli_installed,
            ),
            env_key,
        )

    auth_doc = _read_json(auth_path)
    file_key = ""
    if isinstance(auth_doc, dict):
        raw_file_key = auth_doc.get("OPENAI_API_KEY")
        if isinstance(raw_file_key, str):
            file_key = raw_file_key.strip()
        tokens = auth_doc.get("tokens")
        token_ready = isinstance(tokens, dict) and isinstance(tokens.get("refresh_token"), str) and bool(
            tokens.get("refresh_token", "").strip()
        )
        if file_key:
            return (
                InferenceProviderStatus(
                    provider="codex",
                    cli_name=cli_name,
                    cli_path=cli_path,
                    cli_installed=cli_installed,
                    auth_kind="api_key",
                    key_env_var="OPENAI_API_KEY",
                    key_source=f"file:{_tilde_path(auth_path)}#OPENAI_API_KEY",
                    key_present=True,
                    ready=cli_installed,
                ),
                file_key,
            )
        if token_ready:
            return (
                InferenceProviderStatus(
                    provider="codex",
                    cli_name=cli_name,
                    cli_path=cli_path,
                    cli_installed=cli_installed,
                    auth_kind="oauth",
                    key_env_var=None,
                    key_source=f"file:{_tilde_path(auth_path)}#tokens.refresh_token",
                    key_present=True,
                    ready=cli_installed,
                    note="CLI-authenticated session tokens detected.",
                ),
                None,
            )

    return (
        InferenceProviderStatus(
            provider="codex",
            cli_name=cli_name,
            cli_path=cli_path,
            cli_installed=cli_installed,
            auth_kind="none",
            key_env_var="OPENAI_API_KEY",
            key_source=None,
            key_present=False,
            ready=False,
        ),
        None,
    )


def _detect_claude(home: Path, env: os._Environ[str]) -> tuple[InferenceProviderStatus, str | None]:
    cli_name = "claude"
    cli_path = shutil.which(cli_name)
    cli_installed = cli_path is not None

    for env_var in ("ANTHROPIC_API_KEY", "CLAUDE_API_KEY"):
        env_key = _env_non_empty(env, env_var)
        if env_key:
            return (
                InferenceProviderStatus(
                    provider="claude",
                    cli_name=cli_name,
                    cli_path=cli_path,
                    cli_installed=cli_installed,
                    auth_kind="api_key",
                    key_env_var="ANTHROPIC_API_KEY",
                    key_source=f"env:{env_var}",
                    key_present=True,
                    ready=cli_installed,
                ),
                env_key,
            )

    candidates = [
        home / ".claude" / "credentials.json",
        home / ".claude" / ".credentials.json",
        home / ".config" / "claude" / "credentials.json",
        home / ".config" / "claude" / "config.json",
        home / ".claude.json",
    ]
    for path in candidates:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue

        key = _find_first_key(payload, {"ANTHROPIC_API_KEY", "anthropicApiKey", "apiKey", "api_key"})
        if key:
            return (
                InferenceProviderStatus(
                    provider="claude",
                    cli_name=cli_name,
                    cli_path=cli_path,
                    cli_installed=cli_installed,
                    auth_kind="api_key",
                    key_env_var="ANTHROPIC_API_KEY",
                    key_source=f"file:{_tilde_path(path)}",
                    key_present=True,
                    ready=cli_installed,
                ),
                key,
            )

        token = _find_first_key(payload, {"refresh_token", "access_token"})
        if token:
            return (
                InferenceProviderStatus(
                    provider="claude",
                    cli_name=cli_name,
                    cli_path=cli_path,
                    cli_installed=cli_installed,
                    auth_kind="oauth",
                    key_env_var=None,
                    key_source=f"file:{_tilde_path(path)}",
                    key_present=True,
                    ready=cli_installed,
                    note="CLI-authenticated session token detected.",
                ),
                None,
            )

    return (
        InferenceProviderStatus(
            provider="claude",
            cli_name=cli_name,
            cli_path=cli_path,
            cli_installed=cli_installed,
            auth_kind="none",
            key_env_var="ANTHROPIC_API_KEY",
            key_source=None,
            key_present=False,
            ready=False,
        ),
        None,
    )


def _detect_gemini(home: Path, env: os._Environ[str]) -> tuple[InferenceProviderStatus, str | None]:
    cli_name = "gemini"
    cli_path = shutil.which(cli_name)
    cli_installed = cli_path is not None

    for env_var in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        env_key = _env_non_empty(env, env_var)
        if env_key:
            return (
                InferenceProviderStatus(
                    provider="gemini",
                    cli_name=cli_name,
                    cli_path=cli_path,
                    cli_installed=cli_installed,
                    auth_kind="api_key",
                    key_env_var=env_var,
                    key_source=f"env:{env_var}",
                    key_present=True,
                    ready=cli_installed,
                ),
                env_key,
            )

    key_candidates = [
        home / ".gemini" / "settings.json",
        home / ".gemini" / "config.json",
        home / ".config" / "gemini" / "settings.json",
        home / ".config" / "gemini" / "config.json",
    ]
    for path in key_candidates:
        payload = _read_json(path)
        if not isinstance(payload, dict):
            continue
        key = _find_first_key(payload, {"GEMINI_API_KEY", "GOOGLE_API_KEY", "apiKey", "api_key"})
        if key:
            env_name = "GEMINI_API_KEY"
            return (
                InferenceProviderStatus(
                    provider="gemini",
                    cli_name=cli_name,
                    cli_path=cli_path,
                    cli_installed=cli_installed,
                    auth_kind="api_key",
                    key_env_var=env_name,
                    key_source=f"file:{_tilde_path(path)}",
                    key_present=True,
                    ready=cli_installed,
                ),
                key,
            )

    oauth_path = home / ".gemini" / "oauth_creds.json"
    payload = _read_json(oauth_path)
    token = ""
    if isinstance(payload, dict):
        token = _find_first_key(payload, {"refresh_token", "access_token"})
    if token:
        return (
            InferenceProviderStatus(
                provider="gemini",
                cli_name=cli_name,
                cli_path=cli_path,
                cli_installed=cli_installed,
                auth_kind="oauth",
                key_env_var=None,
                key_source=f"file:{_tilde_path(oauth_path)}",
                key_present=True,
                ready=cli_installed,
                note="CLI OAuth credentials detected.",
            ),
            None,
        )

    return (
        InferenceProviderStatus(
            provider="gemini",
            cli_name=cli_name,
            cli_path=cli_path,
            cli_installed=cli_installed,
            auth_kind="none",
            key_env_var="GEMINI_API_KEY",
            key_source=None,
            key_present=False,
            ready=False,
        ),
        None,
    )


def _run_codex(prompt: str, *, env: dict[str, str], timeout_s: float) -> str:
    with tempfile.NamedTemporaryFile(prefix="tako-codex-", suffix=".txt", delete=False) as handle:
        output_path = Path(handle.name)
    cmd = [
        "codex",
        "exec",
        *CODEX_AGENTIC_EXEC_ARGS,
        "--output-last-message",
        str(output_path),
        prompt,
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_s,
        )
        message = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        if message:
            return message
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit={proc.returncode}"
        raise RuntimeError(f"codex inference failed: {detail}")
    finally:
        with contextlib.suppress(Exception):
            output_path.unlink(missing_ok=True)


def _run_claude(prompt: str, *, env: dict[str, str], timeout_s: float) -> str:
    help_text = _safe_help_text("claude")
    if "--print" in help_text:
        cmd = ["claude", "--print", prompt]
    elif "--prompt" in help_text or " -p," in help_text:
        cmd = ["claude", "-p", prompt]
    else:
        cmd = ["claude", prompt]

    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout_s,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    detail = proc.stderr.strip() or proc.stdout.strip() or f"exit={proc.returncode}"
    raise RuntimeError(f"claude inference failed: {detail}")


def _run_gemini(prompt: str, *, env: dict[str, str], timeout_s: float) -> str:
    cmd = ["gemini", "--output-format", "text", prompt]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout_s,
    )
    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()
    detail = proc.stderr.strip() or proc.stdout.strip() or f"exit={proc.returncode}"
    raise RuntimeError(f"gemini inference failed: {detail}")


def _safe_help_text(command: str) -> str:
    try:
        proc = subprocess.run(
            [command, "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=6.0,
        )
    except Exception:
        return ""
    return f"{proc.stdout}\n{proc.stderr}".strip()


def _read_json(path: Path) -> dict[str, Any] | list[Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _find_first_key(payload: Any, candidates: set[str]) -> str:
    if isinstance(payload, dict):
        for key, value in payload.items():
            if key in candidates and isinstance(value, str) and value.strip():
                return value.strip()
        for value in payload.values():
            found = _find_first_key(value, candidates)
            if found:
                return found
        return ""
    if isinstance(payload, list):
        for item in payload:
            found = _find_first_key(item, candidates)
            if found:
                return found
        return ""
    return ""


def _env_non_empty(env: os._Environ[str], key: str) -> str:
    value = env.get(key, "").strip()
    return value if value else ""


def _tilde_path(path: Path) -> str:
    home = Path.home()
    try:
        return f"~/{path.relative_to(home)}"
    except Exception:
        return str(path)


def _run_with_provider(runtime: InferenceRuntime, provider: str, prompt: str, *, timeout_s: float) -> str:
    env = os.environ.copy()
    env.update(runtime.env_overrides_for(provider))
    if provider == "codex":
        return _run_codex(prompt, env=env, timeout_s=timeout_s)
    if provider == "claude":
        return _run_claude(prompt, env=env, timeout_s=timeout_s)
    if provider == "gemini":
        return _run_gemini(prompt, env=env, timeout_s=timeout_s)
    raise RuntimeError(f"unsupported inference provider: {provider}")


async def _stream_with_provider(
    runtime: InferenceRuntime,
    provider: str,
    prompt: str,
    *,
    timeout_s: float,
    on_event: StreamEventHook | None,
) -> str:
    env = os.environ.copy()
    env.update(runtime.env_overrides_for(provider))

    if provider == "gemini":
        return await _stream_gemini(prompt, env=env, timeout_s=timeout_s, on_event=on_event)
    if provider == "codex":
        return await _stream_codex(prompt, env=env, timeout_s=timeout_s, on_event=on_event)
    if provider == "claude":
        text = await asyncio.to_thread(_run_claude, prompt, env=env, timeout_s=timeout_s)
        await _simulate_stream(text, on_event=on_event)
        return text

    raise RuntimeError(f"unsupported inference provider: {provider}")


async def _simulate_stream(text: str, *, on_event: StreamEventHook | None) -> None:
    if not on_event:
        return
    if not text:
        return
    chunk_size = 24
    delay_s = 0.01
    for idx in range(0, len(text), chunk_size):
        on_event("delta", text[idx : idx + chunk_size])
        await asyncio.sleep(delay_s)


async def _stream_gemini(
    prompt: str,
    *,
    env: dict[str, str],
    timeout_s: float,
    on_event: StreamEventHook | None,
) -> str:
    cmd = ["gemini", "--output-format", "stream-json", prompt]
    assistant_text = ""

    def handle_stdout_line(line: str) -> None:
        nonlocal assistant_text
        stripped = line.strip()
        if not stripped:
            return
        if not stripped.startswith("{"):
            if on_event:
                on_event("status", stripped)
            return
        try:
            payload = json.loads(stripped)
        except Exception:
            if on_event:
                on_event("status", stripped)
            return
        if not isinstance(payload, dict):
            return
        if payload.get("type") != "message":
            return
        if payload.get("role") != "assistant":
            return
        content = payload.get("content")
        if not isinstance(content, str) or not content:
            return

        is_delta = payload.get("delta") is True
        if is_delta:
            assistant_text += content
            if on_event:
                on_event("delta", content)
            return

        if content.startswith(assistant_text):
            delta = content[len(assistant_text) :]
            assistant_text = content
            if delta and on_event:
                on_event("delta", delta)
            return

        assistant_text = content
        if on_event:
            on_event("delta", content)

    stderr_lines: list[str] = []

    def handle_stderr_line(line: str) -> None:
        stripped = line.strip()
        if stripped:
            stderr_lines.append(stripped)
            if on_event:
                on_event("status", stripped)

    await _run_streaming_process(cmd, env=env, timeout_s=timeout_s, on_stdout_line=handle_stdout_line, on_stderr_line=handle_stderr_line)

    if not assistant_text:
        detail = "; ".join(stderr_lines[-5:]) if stderr_lines else "no assistant output received"
        raise RuntimeError(f"gemini inference returned no assistant output: {detail}")
    return assistant_text


async def _stream_codex(
    prompt: str,
    *,
    env: dict[str, str],
    timeout_s: float,
    on_event: StreamEventHook | None,
) -> str:
    cmd = ["codex", "exec", *CODEX_AGENTIC_EXEC_ARGS, "--color", "never", "--json", prompt]
    final_messages: list[str] = []
    streamed_any_delta = False

    def handle_stdout_line(line: str) -> None:
        nonlocal streamed_any_delta
        stripped = line.strip()
        if not stripped:
            return
        if not stripped.startswith("{"):
            if on_event:
                on_event("status", stripped)
            return
        try:
            payload = json.loads(stripped)
        except Exception:
            if on_event:
                on_event("status", stripped)
            return
        if not isinstance(payload, dict):
            return

        event_type = payload.get("type")
        if isinstance(event_type, str) and event_type in {"thread.started", "turn.started"}:
            if on_event:
                on_event("status", event_type)
            return

        if event_type == "turn.completed":
            usage = payload.get("usage")
            if isinstance(usage, dict) and on_event:
                tokens = usage.get("output_tokens")
                if tokens is not None:
                    on_event("status", f"turn.completed output_tokens={tokens}")
            return

        if event_type == "item.completed":
            item = payload.get("item")
            if not isinstance(item, dict):
                return
            if item.get("type") != "agent_message":
                return
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                final_messages.append(text)
            return

        if event_type == "item.delta":
            item = payload.get("item")
            if not isinstance(item, dict):
                return
            if item.get("type") != "agent_message":
                return
            delta = item.get("delta") or item.get("text")
            if isinstance(delta, str) and delta:
                streamed_any_delta = True
                if on_event:
                    on_event("delta", delta)
            return

    stderr_lines: list[str] = []

    def handle_stderr_line(line: str) -> None:
        stripped = line.strip()
        if stripped:
            stderr_lines.append(stripped)
            if on_event:
                on_event("status", stripped)

    await _run_streaming_process(cmd, env=env, timeout_s=timeout_s, on_stdout_line=handle_stdout_line, on_stderr_line=handle_stderr_line)

    combined = "\n\n".join(msg.strip() for msg in final_messages if msg.strip())
    if not combined:
        detail = "; ".join(stderr_lines[-5:]) if stderr_lines else "no agent_message item received"
        raise RuntimeError(f"codex inference returned no agent_message output: {detail}")

    if not streamed_any_delta:
        await _simulate_stream(combined, on_event=on_event)
    return combined


async def _run_streaming_process(
    cmd: list[str],
    *,
    env: dict[str, str],
    timeout_s: float,
    on_stdout_line: Callable[[str], None],
    on_stderr_line: Callable[[str], None],
) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    assert proc.stdout is not None
    assert proc.stderr is not None

    async def pump(stream: asyncio.StreamReader, handler: Callable[[str], None]) -> None:
        while True:
            raw = await stream.readline()
            if not raw:
                return
            handler(raw.decode("utf-8", errors="replace").rstrip("\n"))

    stdout_task = asyncio.create_task(pump(proc.stdout, on_stdout_line))
    stderr_task = asyncio.create_task(pump(proc.stderr, on_stderr_line))

    try:
        await asyncio.wait_for(asyncio.gather(stdout_task, stderr_task, proc.wait()), timeout=timeout_s)
    except asyncio.TimeoutError as exc:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        raise RuntimeError(f"inference subprocess timed out after {timeout_s:.0f}s") from exc
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()

    if proc.returncode != 0:
        raise RuntimeError(f"inference subprocess failed: exit={proc.returncode}")


def _summarize_error_text(text: str) -> str:
    value = " ".join(text.split())
    if len(value) <= 220:
        return value
    return f"{value[:217]}..."
