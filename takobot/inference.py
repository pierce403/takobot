from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import shlex
import shutil
import subprocess
import tempfile
import traceback
from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .node_runtime import (
    NODE_RUNTIME_MIN_MAJOR,
    ensure_workspace_node_runtime,
    latest_node_bin_dir as _shared_latest_node_bin_dir,
    node_major_from_version as _shared_node_major_from_version,
    node_path_meets_min_major as _shared_node_path_meets_min_major,
    workspace_nvm_dir as _shared_workspace_nvm_dir,
)
from .paths import ensure_runtime_dirs, repo_root, runtime_paths


PROVIDER_PRIORITY = ("pi",)
SUPPORTED_PROVIDER_PREFERENCES = ("auto", *PROVIDER_PRIORITY)
CODEX_AGENTIC_EXEC_ARGS = [
    "--skip-git-repo-check",
    "--dangerously-bypass-approvals-and-sandbox",
]
INFERENCE_SETTINGS_FILENAME = "inference-settings.json"
PI_PACKAGE_VERSION = "0.52.12"
PI_MIN_NODE_MAJOR = NODE_RUNTIME_MIN_MAJOR
KNOWN_INFERENCE_PROVIDERS = ("pi", "ollama", "codex", "claude", "gemini")
PI_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "OPENROUTER_API_KEY",
    "XAI_API_KEY",
    "GROQ_API_KEY",
    "CEREBRAS_API_KEY",
    "MISTRAL_API_KEY",
    "AI_GATEWAY_API_KEY",
    "ZAI_API_KEY",
    "MINIMAX_API_KEY",
    "KIMI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "ALI_BAILIAN_API_KEY",
    "MIDDLEWARE_API_KEY",
    "AWS_BEARER_TOKEN_BEDROCK",
)
CONFIGURABLE_API_KEY_VARS = tuple(
    sorted(
        {
            *PI_KEY_ENV_VARS,
            "CLAUDE_API_KEY",
        }
    )
)
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"
PI_TYPE1_THINKING_DEFAULT = "minimal"
PI_TYPE2_THINKING_DEFAULT = "xhigh"
PI_PROMPT_MAX_LINE_CHARS = 320
PI_PROMPT_MAX_CHARS = 80_000
PI_PROMPT_TRUNCATION_MARKER = "\n[... prompt truncated for pi runtime safety ...]\n"
INFERENCE_LOG_MAX_COMMAND_CHARS = 1000
INFERENCE_LOG_MAX_ARG_CHARS = 180
_PI_HELP_TEXT_CACHE: dict[str, str] = {}
_INTERACTIVE_PROMPT_SIGNALS = (
    "press any key to continue",
    "press enter to continue",
    "press return to continue",
)
_PI_MANAGED_LEGACY_TOOL_NAMES = {"fd", "rg", "fd.exe", "rg.exe"}

StreamEventHook = Callable[[str, str], None]


@dataclass(frozen=True)
class InferenceSettings:
    preferred_provider: str = "auto"
    ollama_model: str = ""
    ollama_host: str = ""
    api_keys: dict[str, str] = field(default_factory=dict)


def load_inference_settings(path: Path | None = None) -> InferenceSettings:
    settings_path = path or inference_settings_path()
    if not settings_path.exists():
        return InferenceSettings()
    payload = _read_json(settings_path)
    if not isinstance(payload, dict):
        return InferenceSettings()

    preferred = str(payload.get("preferred_provider") or "").strip().lower()
    if preferred not in SUPPORTED_PROVIDER_PREFERENCES:
        preferred = "auto"
    ollama_model = " ".join(str(payload.get("ollama_model") or "").split()).strip()
    ollama_host = " ".join(str(payload.get("ollama_host") or "").split()).strip()

    raw_keys = payload.get("api_keys")
    api_keys: dict[str, str] = {}
    if isinstance(raw_keys, dict):
        for key, value in raw_keys.items():
            if not isinstance(key, str) or not isinstance(value, str):
                continue
            env_var = key.strip().upper()
            if env_var not in CONFIGURABLE_API_KEY_VARS:
                continue
            cleaned = value.strip()
            if cleaned:
                api_keys[env_var] = cleaned

    return InferenceSettings(
        preferred_provider=preferred or "auto",
        ollama_model=ollama_model,
        ollama_host=ollama_host,
        api_keys=api_keys,
    )


def save_inference_settings(settings: InferenceSettings, path: Path | None = None) -> tuple[bool, str]:
    settings_path = path or inference_settings_path()
    payload = {
        "preferred_provider": settings.preferred_provider,
        "ollama_model": settings.ollama_model,
        "ollama_host": settings.ollama_host,
        "api_keys": dict(sorted(settings.api_keys.items())),
    }
    try:
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with contextlib.suppress(Exception):
            os.chmod(settings_path, 0o600)
    except Exception as exc:  # noqa: BLE001
        return False, f"failed writing inference settings: {exc}"
    return True, f"inference settings saved: {settings_path}"


def inference_settings_path() -> Path:
    paths = ensure_runtime_dirs(runtime_paths())
    return paths.state_dir / INFERENCE_SETTINGS_FILENAME


def set_inference_preferred_provider(provider: str, path: Path | None = None) -> tuple[bool, str]:
    candidate = " ".join((provider or "").split()).strip().lower() or "auto"
    if candidate not in SUPPORTED_PROVIDER_PREFERENCES:
        supported = ", ".join(SUPPORTED_PROVIDER_PREFERENCES)
        return False, f"unsupported provider `{candidate}` (expected: {supported})"
    settings = load_inference_settings(path)
    updated = InferenceSettings(
        preferred_provider=candidate,
        ollama_model=settings.ollama_model,
        ollama_host=settings.ollama_host,
        api_keys=dict(settings.api_keys),
    )
    ok, message = save_inference_settings(updated, path=path)
    if not ok:
        return False, message
    return True, f"inference preferred provider set to `{candidate}`"


def set_inference_ollama_model(model: str, path: Path | None = None) -> tuple[bool, str]:
    cleaned = " ".join((model or "").split()).strip()
    settings = load_inference_settings(path)
    updated = InferenceSettings(
        preferred_provider=settings.preferred_provider,
        ollama_model=cleaned,
        ollama_host=settings.ollama_host,
        api_keys=dict(settings.api_keys),
    )
    ok, message = save_inference_settings(updated, path=path)
    if not ok:
        return False, message
    if cleaned:
        return True, f"ollama model set to `{cleaned}`"
    return True, "ollama model preference cleared (auto-detect will be used)"


def set_inference_ollama_host(host: str, path: Path | None = None) -> tuple[bool, str]:
    cleaned = " ".join((host or "").split()).strip()
    settings = load_inference_settings(path)
    updated = InferenceSettings(
        preferred_provider=settings.preferred_provider,
        ollama_model=settings.ollama_model,
        ollama_host=cleaned,
        api_keys=dict(settings.api_keys),
    )
    ok, message = save_inference_settings(updated, path=path)
    if not ok:
        return False, message
    if cleaned:
        return True, f"ollama host set to `{cleaned}`"
    return True, "ollama host preference cleared"


def set_inference_api_key(env_var: str, value: str, path: Path | None = None) -> tuple[bool, str]:
    key_name = (env_var or "").strip().upper()
    if key_name not in CONFIGURABLE_API_KEY_VARS:
        supported = ", ".join(CONFIGURABLE_API_KEY_VARS)
        return False, f"unsupported API key name `{key_name}` (supported: {supported})"
    cleaned = (value or "").strip()
    if not cleaned:
        return False, f"{key_name} value cannot be empty"

    settings = load_inference_settings(path)
    api_keys = dict(settings.api_keys)
    api_keys[key_name] = cleaned
    updated = InferenceSettings(
        preferred_provider=settings.preferred_provider,
        ollama_model=settings.ollama_model,
        ollama_host=settings.ollama_host,
        api_keys=api_keys,
    )
    ok, message = save_inference_settings(updated, path=path)
    if not ok:
        return False, message
    return True, f"inference API key saved for `{key_name}`"


def clear_inference_api_key(env_var: str, path: Path | None = None) -> tuple[bool, str]:
    key_name = (env_var or "").strip().upper()
    if key_name not in CONFIGURABLE_API_KEY_VARS:
        supported = ", ".join(CONFIGURABLE_API_KEY_VARS)
        return False, f"unsupported API key name `{key_name}` (supported: {supported})"
    settings = load_inference_settings(path)
    api_keys = dict(settings.api_keys)
    removed = api_keys.pop(key_name, None)
    updated = InferenceSettings(
        preferred_provider=settings.preferred_provider,
        ollama_model=settings.ollama_model,
        ollama_host=settings.ollama_host,
        api_keys=api_keys,
    )
    ok, message = save_inference_settings(updated, path=path)
    if not ok:
        return False, message
    if removed is None:
        return True, f"no persisted key found for `{key_name}`"
    return True, f"inference API key cleared for `{key_name}`"


def format_inference_auth_inventory() -> list[str]:
    settings = load_inference_settings()
    lines = ["inference auth inventory:"]
    lines.append(f"preferred provider: {settings.preferred_provider}")
    lines.append(f"ollama model: {settings.ollama_model or '(auto)'}")
    lines.append(f"ollama host: {settings.ollama_host or '(default)'}")

    if settings.api_keys:
        lines.append("persisted API keys:")
        for env_var in sorted(settings.api_keys):
            masked = _mask_secret(settings.api_keys[env_var])
            lines.append(f"- {env_var}: {masked}")
    else:
        lines.append("persisted API keys: (none)")

    oauth_entries = enumerate_pi_oauth_tokens()
    if oauth_entries:
        lines.append("pi oauth providers:")
        for entry in oauth_entries:
            lines.append(f"- {entry}")
    else:
        lines.append("pi oauth providers: (none detected)")
    return lines


def enumerate_pi_oauth_tokens() -> list[str]:
    home = Path.home()
    sources = [
        _workspace_pi_agent_dir() / "auth.json",
        home / ".pi" / "agent" / "auth.json",
        home / ".pi" / "auth.json",
    ]
    results: list[str] = []
    seen: set[str] = set()
    for source in sources:
        payload = _read_json(source)
        if not isinstance(payload, dict):
            continue
        for provider, details in _pi_oauth_entries(payload):
            stamp = _format_epoch_ms(details.get("expires")) if isinstance(details, dict) else "unknown"
            key = f"{provider}|{_tilde_path(source)}"
            if key in seen:
                continue
            seen.add(key)
            results.append(f"{provider} (expires={stamp}, source={_tilde_path(source)})")
    return results


def looks_like_openai_oauth_refresh_failure(error_text: str) -> bool:
    lowered = " ".join((error_text or "").split()).strip().lower()
    if not lowered:
        return False
    token_signals = (
        "token refresh failed",
        "refresh token has already been used",
        "invalid_grant",
        "refresh token",
    )
    auth_signals = (
        "openai-codex",
        "openai",
        "oauth",
        "401",
    )
    return any(token in lowered for token in token_signals) and any(signal in lowered for signal in auth_signals)


def inference_reauth_guidance_lines(
    last_error: str,
    *,
    local_terminal: bool,
) -> tuple[str, ...]:
    if not looks_like_openai_oauth_refresh_failure(last_error):
        return ()
    if local_terminal:
        return (
            "OpenAI auth recovery: run `inference login force` to re-auth now.",
            "If prompted, reply with `inference login answer <text>` until complete.",
            "Then run `inference refresh` and `inference auth` to verify token state.",
            "Fallback if needed: set a key directly with `inference key set OPENAI_API_KEY <key>`.",
        )
    return (
        "OpenAI auth recovery requires terminal input.",
        "Run `inference login force` in the local terminal and complete prompts with `inference login answer <text>`.",
        "After completion, run `inference refresh` and `inference auth`.",
    )


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
    _provider_env_overrides: dict[str, dict[str, str]] = field(default_factory=dict)

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
        env: dict[str, str] = {}
        extras = self._provider_env_overrides.get(provider)
        if extras:
            env.update(extras)
        if provider not in self._api_keys:
            return env
        status = self.statuses.get(provider)
        if not status or not status.key_env_var:
            return env
        env[status.key_env_var] = self._api_keys[provider]
        return env


@dataclass(frozen=True)
class PiModelProfile:
    model: str
    thinking: str
    model_source: str
    thinking_source: str


@dataclass(frozen=True)
class PiLoginPlan:
    auth_ready: bool
    notes: tuple[str, ...] = ()
    commands: tuple[tuple[str, ...], ...] = ()
    reason: str = ""


def prepare_pi_login_plan(runtime: InferenceRuntime | None = None) -> PiLoginPlan:
    notes: list[str] = []
    bootstrap_note = _ensure_workspace_pi_runtime_if_needed()
    if bootstrap_note:
        notes.extend(part.strip() for part in bootstrap_note.split("|") if part.strip())

    auth_notes = _ensure_workspace_pi_auth(_workspace_pi_agent_dir())
    notes.extend(auth_notes)

    auth_ready = _has_pi_auth(_read_json(_workspace_pi_agent_dir() / "auth.json"))
    cli_path = _pi_cli_path_for_login(runtime)
    commands = _pi_login_commands(cli_path)
    reason = ""
    if auth_ready:
        reason = "pi auth is already available in workspace runtime state."
    elif not commands:
        reason = "pi CLI is unavailable; run `inference refresh` to bootstrap workspace-local pi runtime first."

    return PiLoginPlan(
        auth_ready=auth_ready,
        notes=tuple(_dedupe_non_empty_lines(notes)),
        commands=tuple(tuple(command) for command in commands),
        reason=reason,
    )


def build_pi_login_env(runtime: InferenceRuntime | None = None) -> dict[str, str]:
    active_runtime = runtime or InferenceRuntime(
        statuses={},
        selected_provider=None,
        selected_auth_kind="none",
        selected_key_env_var=None,
        selected_key_source=None,
        _api_keys={},
    )
    return _provider_env(active_runtime, "pi")


def discover_inference_runtime() -> InferenceRuntime:
    home = Path.home()
    settings = load_inference_settings()
    env: dict[str, str] = dict(os.environ)
    env.update(settings.api_keys)
    bootstrap_note = _ensure_workspace_pi_runtime_if_needed()
    auth_sync_notes = _ensure_workspace_pi_auth(_workspace_pi_agent_dir())
    provider_env_overrides: dict[str, dict[str, str]] = {}
    ollama_host = settings.ollama_host or _env_non_empty(env, "OLLAMA_HOST")
    if ollama_host:
        env["OLLAMA_HOST"] = ollama_host
        provider_env_overrides["ollama"] = {"OLLAMA_HOST": ollama_host}
    elif _env_non_empty(env, "OLLAMA_HOST"):
        provider_env_overrides["ollama"] = {"OLLAMA_HOST": _env_non_empty(env, "OLLAMA_HOST")}
    if settings.ollama_model:
        env["OLLAMA_MODEL"] = settings.ollama_model
    statuses: dict[str, InferenceProviderStatus] = {}
    api_keys: dict[str, str] = {}

    pi_status, pi_key = _detect_pi(home, env)
    if bootstrap_note:
        note = pi_status.note or ""
        note = f"{note} {bootstrap_note}".strip()
        pi_status = replace(pi_status, note=note)
    if auth_sync_notes:
        note = pi_status.note or ""
        extra = " ".join(_dedupe_non_empty_lines(list(auth_sync_notes)))
        if extra:
            note = f"{note} {extra}".strip()
            pi_status = replace(pi_status, note=note)
    statuses["pi"] = pi_status
    if pi_key:
        api_keys["pi"] = pi_key

    ollama_status, ollama_key = _detect_ollama(home, env)
    statuses["ollama"] = ollama_status
    if ollama_key:
        api_keys["ollama"] = ollama_key

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

    if not pi_key and not pi_status.key_present:
        pi_status, pi_key = _adopt_local_system_api_key_for_pi(
            pi_status,
            codex_status=codex_status,
            codex_key=codex_key,
            claude_status=claude_status,
            claude_key=claude_key,
            gemini_status=gemini_status,
            gemini_key=gemini_key,
        )
        statuses["pi"] = pi_status
        if pi_key:
            api_keys["pi"] = pi_key

    selected_provider = "pi" if statuses["pi"].ready else None

    selected_status = statuses.get(selected_provider or "")
    return InferenceRuntime(
        statuses=statuses,
        selected_provider=selected_provider,
        selected_auth_kind=selected_status.auth_kind if selected_status else "none",
        selected_key_env_var=selected_status.key_env_var if selected_status else None,
        selected_key_source=selected_status.key_source if selected_status else None,
        _api_keys=api_keys,
        _provider_env_overrides=provider_env_overrides,
    )


def _pi_cli_path_for_login(runtime: InferenceRuntime | None) -> str | None:
    if runtime is not None:
        status = runtime.statuses.get("pi")
        if status and status.cli_path:
            return status.cli_path
    workspace_cli = _workspace_pi_cli_path()
    if workspace_cli.exists():
        return str(workspace_cli)
    return shutil.which("pi")


def _pi_login_commands(cli_path: str | None) -> list[list[str]]:
    if not cli_path:
        return []

    help_text = _safe_help_text(cli_path).lower()
    candidates: list[list[str]] = []
    if "auth login" in help_text or (" auth" in help_text and " login" in help_text):
        candidates.append([cli_path, "auth", "login"])
        candidates.append([cli_path, "login"])
    elif " login" in help_text or "login " in help_text:
        candidates.append([cli_path, "login"])
        candidates.append([cli_path, "auth", "login"])
    else:
        candidates.append([cli_path, "auth", "login"])
        candidates.append([cli_path, "login"])

    deduped: list[list[str]] = []
    seen: set[str] = set()
    for command in candidates:
        token = " ".join(command)
        if token in seen:
            continue
        seen.add(token)
        deduped.append(command)
    return deduped


def _adopt_local_system_api_key_for_pi(
    pi_status: InferenceProviderStatus,
    *,
    codex_status: InferenceProviderStatus,
    codex_key: str | None,
    claude_status: InferenceProviderStatus,
    claude_key: str | None,
    gemini_status: InferenceProviderStatus,
    gemini_key: str | None,
) -> tuple[InferenceProviderStatus, str | None]:
    candidates = (
        ("OPENAI_API_KEY", codex_key, codex_status.key_source or "file:~/.codex/auth.json"),
        ("ANTHROPIC_API_KEY", claude_key, claude_status.key_source or "file:~/.claude/credentials.json"),
        ("GEMINI_API_KEY", gemini_key, gemini_status.key_source or "file:~/.gemini/settings.json"),
    )
    for env_var, key_value, key_source in candidates:
        if not key_value:
            continue
        note = (
            f"{pi_status.note} local system key detected ({env_var}).".strip()
            if pi_status.note
            else f"pi runtime detected; key sourced from local system ({env_var})."
        )
        return (
            replace(
                pi_status,
                auth_kind="api_key",
                key_env_var=env_var,
                key_source=f"system:{key_source}",
                key_present=True,
                note=note,
            ),
            key_value,
        )
    return pi_status, None


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


def run_inference_prompt(
    runtime: InferenceRuntime,
    prompt: str,
    *,
    timeout_s: float = 70.0,
    thinking: str = PI_TYPE1_THINKING_DEFAULT,
) -> str:
    provider = runtime.selected_provider
    if not provider:
        raise RuntimeError("no inference provider selected")
    status = runtime.statuses.get(provider)
    if not status or not status.ready:
        raise RuntimeError("selected inference provider is not ready")

    return _run_with_provider(runtime, provider, prompt, timeout_s=timeout_s, thinking=thinking)


def run_inference_prompt_with_fallback(
    runtime: InferenceRuntime,
    prompt: str,
    *,
    timeout_s: float = 70.0,
    thinking: str = PI_TYPE1_THINKING_DEFAULT,
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
            text = _run_with_provider(runtime, provider, prompt, timeout_s=timeout_s, thinking=thinking)
            return provider, text
        except Exception as exc:  # noqa: BLE001
            _log_unexpected_provider_exception(provider=provider, exc=exc, phase="run")
            failures.append(f"{provider}: {_summarize_error_text(str(exc))}")

    detail = "; ".join(failures) if failures else "all provider attempts failed"
    raise RuntimeError(f"inference provider fallback exhausted: {detail}")


async def stream_inference_prompt_with_fallback(
    runtime: InferenceRuntime,
    prompt: str,
    *,
    timeout_s: float = 70.0,
    on_event: StreamEventHook | None = None,
    thinking: str = PI_TYPE1_THINKING_DEFAULT,
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
            text = await _stream_with_provider(
                runtime,
                provider,
                prompt,
                timeout_s=timeout_s,
                on_event=on_event,
                thinking=thinking,
            )
            return provider, text
        except Exception as exc:  # noqa: BLE001
            _log_unexpected_provider_exception(provider=provider, exc=exc, phase="stream")
            failures.append(f"{provider}: {_summarize_error_text(str(exc))}")
            if on_event:
                on_event("status", f"{provider} failed: {_summarize_error_text(str(exc))}")

    detail = "; ".join(failures) if failures else "all provider attempts failed"
    raise RuntimeError(f"inference provider fallback exhausted: {detail}")


def format_runtime_lines(runtime: InferenceRuntime) -> list[str]:
    selected = runtime.selected_provider or "none"
    settings = load_inference_settings()
    lines = [
        f"inference selected: {selected}",
        f"inference ready: {'yes' if runtime.ready else 'no'}",
        f"inference preferred: {settings.preferred_provider}",
    ]
    if runtime.selected_provider:
        lines.append(f"inference auth: {runtime.selected_auth_kind}")
        if runtime.selected_key_source:
            lines.append(f"inference key source: {runtime.selected_key_source}")

    for provider in KNOWN_INFERENCE_PROVIDERS:
        status = runtime.statuses.get(provider)
        if not status:
            continue
        lines.append(
            f"{provider}: cli={'yes' if status.cli_installed else 'no'} "
            f"auth={status.auth_kind} ready={'yes' if status.ready else 'no'} "
            f"source={status.key_source or 'none'}"
        )
    return lines


def resolve_pi_model_profile() -> PiModelProfile:
    model = ""
    thinking = ""
    model_source = ""
    thinking_source = ""

    candidates = (
        Path.home() / ".pi" / "agent" / "settings.json",
        runtime_paths().root / "pi" / "agent" / "settings.json",
        repo_root() / ".pi" / "settings.json",
    )
    for candidate in candidates:
        payload = _read_json(candidate)
        if not isinstance(payload, dict):
            continue
        model_value = _clean_model_setting(payload.get("defaultModel") or payload.get("model"))
        if model_value:
            model = model_value
            model_source = _tilde_path(candidate)
        thinking_value = _clean_thinking_setting(
            payload.get("defaultThinkingLevel") or payload.get("thinkingLevel") or payload.get("thinking")
        )
        if thinking_value:
            thinking = thinking_value
            thinking_source = _tilde_path(candidate)

    if not thinking:
        thinking = "medium"
    return PiModelProfile(
        model=model,
        thinking=thinking,
        model_source=model_source,
        thinking_source=thinking_source,
    )


def _effective_pi_type1_thinking(value: str = "") -> str:
    return _clean_thinking_setting(value) or PI_TYPE1_THINKING_DEFAULT


def _effective_pi_type2_thinking(value: str = "") -> str:
    return _clean_thinking_setting(value) or PI_TYPE2_THINKING_DEFAULT


def format_pi_model_plan_lines(
    *,
    type1_thinking_default: str = PI_TYPE1_THINKING_DEFAULT,
    type2_thinking_default: str = PI_TYPE2_THINKING_DEFAULT,
) -> list[str]:
    profile = resolve_pi_model_profile()
    model = profile.model or "(auto-select)"
    type1_thinking = _effective_pi_type1_thinking(type1_thinking_default)
    type2_thinking = _effective_pi_type2_thinking(type2_thinking_default)
    configured_thinking = _clean_thinking_setting(profile.thinking) or "medium"

    lines = [
        "pi model plan:",
        f"- type1 model: {model}",
        f"- type1 thinking: {type1_thinking}",
        f"- type2 model: {model}",
        f"- type2 thinking: {type2_thinking}",
        f"- configured base thinking: {configured_thinking}",
    ]
    if profile.model_source:
        lines.append(f"- model source: {profile.model_source}")
    else:
        lines.append("- model source: (not set; pi selects first available model)")
    if profile.thinking_source:
        lines.append(f"- thinking source: {profile.thinking_source}")
    else:
        lines.append("- thinking source: default medium")
    return lines


def auto_repair_inference_runtime() -> list[str]:
    note = _ensure_workspace_pi_runtime_if_needed()
    if not note:
        return []
    return [item.strip() for item in note.split(" | ") if item.strip()]


def _ensure_workspace_pi_runtime_if_needed() -> str:
    workspace_cli = _workspace_pi_cli_path()
    if workspace_cli.exists() and _pi_node_available():
        auth_notes = _ensure_workspace_pi_auth(_workspace_pi_agent_dir())
        if not auth_notes:
            return ""
        return " | ".join(auth_notes)
    ok, detail = _ensure_workspace_pi_runtime()
    prefix = "workspace pi bootstrap complete" if ok else "workspace pi bootstrap failed"
    return f"{prefix}: {detail}"


def _ensure_workspace_pi_runtime() -> tuple[bool, str]:
    paths = ensure_runtime_dirs(runtime_paths())
    npm_cache = paths.root / "npm-cache"
    prefix = paths.root / "pi" / "node"
    npm_cache.mkdir(parents=True, exist_ok=True)
    prefix.mkdir(parents=True, exist_ok=True)

    node_runtime = ensure_workspace_node_runtime(min_major=PI_MIN_NODE_MAJOR, require_npm=True)
    if not node_runtime.ok:
        return False, node_runtime.detail
    if not node_runtime.npm_executable:
        return False, "npm is unavailable; cannot install workspace-local pi runtime"

    env = node_runtime.env
    npm_exec = node_runtime.npm_executable

    pi_bin = _workspace_pi_cli_path()
    if pi_bin.exists():
        auth_notes = _ensure_workspace_pi_auth(_workspace_pi_agent_dir())
        detail = f"workspace-local pi runtime already present ({pi_bin})"
        if auth_notes:
            detail = f"{detail} | {' | '.join(auth_notes)}"
        return True, detail

    packages = [
        f"@mariozechner/pi-ai@{PI_PACKAGE_VERSION}",
        f"@mariozechner/pi-coding-agent@{PI_PACKAGE_VERSION}",
    ]
    cmd = [
        npm_exec,
        "--cache",
        str(npm_cache),
        "--prefix",
        str(prefix),
        "install",
        "--no-audit",
        "--no-fund",
        "--silent",
        *packages,
    ]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=600,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit={proc.returncode}"
        return False, f"npm install failed: {_summarize_error_text(detail)}"
    if not pi_bin.exists():
        return False, f"npm install completed but `{pi_bin}` is missing"

    auth_notes = _ensure_workspace_pi_auth(_workspace_pi_agent_dir())
    detail = f"workspace-local pi runtime installed at `{pi_bin}`"
    if auth_notes:
        detail = f"{detail} | {' | '.join(auth_notes)}"
    return True, detail


def _detect_pi(home: Path, env: Mapping[str, str]) -> tuple[InferenceProviderStatus, str | None]:
    cli_name = "pi"
    workspace_cli = _workspace_pi_cli_path()
    workspace_cli_exists = workspace_cli.exists()
    cli_path = str(workspace_cli) if workspace_cli_exists else None
    cli_installed = cli_path is not None
    global_cli = shutil.which(cli_name) if not workspace_cli_exists else None
    global_cli_note = (
        f" global `{cli_name}` detected at `{global_cli}` but workspace-local runtime is required."
        if global_cli
        else ""
    )
    node_ready = _pi_node_available()

    for env_var in PI_KEY_ENV_VARS:
        env_key = _env_non_empty(env, env_var)
        if env_key:
            return (
                InferenceProviderStatus(
                    provider="pi",
                    cli_name=cli_name,
                    cli_path=cli_path,
                    cli_installed=cli_installed,
                    auth_kind="api_key",
                    key_env_var=env_var,
                    key_source=f"env:{env_var}",
                    key_present=True,
                    ready=cli_installed and node_ready,
                    note=(
                        "pi runtime detected; key sourced from environment."
                        if node_ready
                        else f"pi CLI detected but compatible node runtime is unavailable (requires node >= {PI_MIN_NODE_MAJOR})."
                    ),
                ),
                env_key,
            )

    workspace_auth = _workspace_pi_agent_dir() / "auth.json"
    candidates = [
        workspace_auth,
        home / ".pi" / "agent" / "auth.json",
        home / ".pi" / "auth.json",
    ]
    for path in candidates:
        payload = _read_json(path)
        if _has_pi_auth(payload):
            oauth_inventory = _pi_oauth_entries(payload) if isinstance(payload, dict) else []
            oauth_hint = ""
            if oauth_inventory:
                labels = ", ".join(provider for provider, _details in oauth_inventory[:4])
                extra = f" (+{len(oauth_inventory) - 4})" if len(oauth_inventory) > 4 else ""
                oauth_hint = f" oauth providers: {labels}{extra}."
            return (
                InferenceProviderStatus(
                    provider="pi",
                    cli_name=cli_name,
                    cli_path=cli_path,
                    cli_installed=cli_installed,
                    auth_kind="oauth_or_profile",
                    key_env_var=None,
                    key_source=f"file:{_tilde_path(path)}",
                    key_present=True,
                    ready=cli_installed and node_ready,
                    note=(
                        "pi auth profile detected." + oauth_hint
                        if node_ready
                        else f"pi auth profile detected but compatible node runtime is unavailable (requires node >= {PI_MIN_NODE_MAJOR})." + oauth_hint
                    ),
                ),
                None,
            )

    return (
        InferenceProviderStatus(
            provider="pi",
            cli_name=cli_name,
            cli_path=cli_path,
            cli_installed=cli_installed,
            auth_kind="none",
            key_env_var=None,
            key_source=None,
            key_present=False,
            ready=False,
            note=(
                "install workspace-local pi runtime and configure auth to enable."
                if node_ready
                else f"compatible node runtime missing (pi requires node >= {PI_MIN_NODE_MAJOR}); setup will install workspace-local nvm/node before pi runtime."
            )
            + global_cli_note,
        ),
        None,
    )


def _detect_ollama(home: Path, env: Mapping[str, str]) -> tuple[InferenceProviderStatus, str | None]:
    del home
    cli_name = "ollama"
    cli_path = shutil.which(cli_name)
    cli_installed = cli_path is not None

    host = _env_non_empty(env, "OLLAMA_HOST") or DEFAULT_OLLAMA_HOST
    model = _env_non_empty(env, "OLLAMA_MODEL")
    if cli_installed and not model:
        models = _list_ollama_models(cli_path or cli_name, env=env)
        if models:
            model = models[0]

    if cli_installed and model:
        return (
            InferenceProviderStatus(
                provider="ollama",
                cli_name=cli_name,
                cli_path=cli_path,
                cli_installed=True,
                auth_kind="local_model",
                key_env_var=None,
                key_source=f"model:{model}",
                key_present=True,
                ready=True,
                note=f"ollama host={host}",
            ),
            None,
        )

    if cli_installed:
        return (
            InferenceProviderStatus(
                provider="ollama",
                cli_name=cli_name,
                cli_path=cli_path,
                cli_installed=True,
                auth_kind="local_model",
                key_env_var=None,
                key_source=None,
                key_present=False,
                ready=False,
                note="ollama is installed but no model is configured. Set `OLLAMA_MODEL` or run `inference ollama model <name>`.",
            ),
            None,
        )

    return (
        InferenceProviderStatus(
            provider="ollama",
            cli_name=cli_name,
            cli_path=cli_path,
            cli_installed=False,
            auth_kind="local_model",
            key_env_var=None,
            key_source=None,
            key_present=False,
            ready=False,
            note="install Ollama and pull a model, or choose another provider.",
        ),
        None,
    )


def _detect_codex(home: Path, env: Mapping[str, str]) -> tuple[InferenceProviderStatus, str | None]:
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


def _detect_claude(home: Path, env: Mapping[str, str]) -> tuple[InferenceProviderStatus, str | None]:
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


def _detect_gemini(home: Path, env: Mapping[str, str]) -> tuple[InferenceProviderStatus, str | None]:
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
    output_path = _new_workspace_temp_file(prefix="tako-codex-", suffix=".txt")
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
    cached = _PI_HELP_TEXT_CACHE.get(command)
    if cached is not None:
        return cached
    try:
        proc = subprocess.run(
            [command, "--help"],
            check=False,
            capture_output=True,
            text=True,
            timeout=6.0,
            stdin=subprocess.DEVNULL,
        )
    except Exception:
        _PI_HELP_TEXT_CACHE[command] = ""
        return ""
    merged = f"{proc.stdout}\n{proc.stderr}".strip()
    _PI_HELP_TEXT_CACHE[command] = merged
    return merged


def inference_error_log_path() -> Path:
    return ensure_runtime_dirs(runtime_paths()).logs_dir / "error.log"


def _append_inference_error_log(
    *,
    provider: str,
    command: list[str],
    detail: str,
    stdout_text: str = "",
    stderr_text: str = "",
    timeout_s: float | None = None,
    phase: str = "run",
) -> Path:
    log_path = inference_error_log_path()
    stamp = datetime.now(tz=timezone.utc).isoformat()
    cmd_text = _summarize_command_for_log(command)
    stdout_clean = stdout_text.strip()
    stderr_clean = stderr_text.strip()
    lines = [
        f"{stamp} provider={provider} phase={phase}",
        f"command: {cmd_text}",
        f"detail: {_summarize_error_text(detail)}",
    ]
    if timeout_s is not None:
        lines.append(f"timeout_s: {timeout_s:.1f}")
    if stdout_clean:
        lines.append("stdout_tail:")
        lines.append(stdout_clean[-4000:])
    if stderr_clean:
        lines.append("stderr_tail:")
        lines.append(stderr_clean[-4000:])
    lines.append("")
    with log_path.open("a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return log_path


def _raise_inference_command_failure(
    *,
    provider: str,
    command: list[str],
    detail: str,
    stdout_text: str = "",
    stderr_text: str = "",
    timeout_s: float | None = None,
    phase: str = "run",
) -> None:
    log_path = _append_inference_error_log(
        provider=provider,
        command=command,
        detail=detail,
        stdout_text=stdout_text,
        stderr_text=stderr_text,
        timeout_s=timeout_s,
        phase=phase,
    )
    cmd_text = _summarize_command_for_log(command)
    summary = _summarize_error_text(detail)
    raise RuntimeError(f"{provider} inference failed: {summary} (cmd: {cmd_text}; log: {log_path})")


def _list_ollama_models(command: str, *, env: Mapping[str, str]) -> list[str]:
    try:
        proc = subprocess.run(
            [command, "list"],
            check=False,
            capture_output=True,
            text=True,
            env=dict(env),
            timeout=8.0,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    lines = [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        return []
    models: list[str] = []
    for line in lines:
        lowered = line.lower()
        if lowered.startswith("name"):
            continue
        model = line.split(maxsplit=1)[0].strip()
        if model:
            models.append(model)
    return models


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


def _env_non_empty(env: Mapping[str, str], key: str) -> str:
    value = str(env.get(key, "")).strip()
    return value if value else ""


def _tilde_path(path: Path) -> str:
    home = Path.home()
    try:
        return f"~/{path.relative_to(home)}"
    except Exception:
        return str(path)


def _run_with_provider(
    runtime: InferenceRuntime,
    provider: str,
    prompt: str,
    *,
    timeout_s: float,
    thinking: str = PI_TYPE1_THINKING_DEFAULT,
) -> str:
    env = _provider_env(runtime, provider)
    if provider == "pi":
        return _run_pi(runtime, prompt, env=env, timeout_s=timeout_s, thinking=thinking)
    if provider == "ollama":
        return _run_ollama(runtime, prompt, env=env, timeout_s=timeout_s)
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
    thinking: str = PI_TYPE1_THINKING_DEFAULT,
) -> str:
    env = _provider_env(runtime, provider)

    if provider == "pi":
        try:
            return await _stream_pi(runtime, prompt, env=env, timeout_s=timeout_s, on_event=on_event, thinking=thinking)
        except Exception as stream_exc:  # noqa: BLE001
            if _is_interactive_prompt_failure(str(stream_exc)):
                if on_event:
                    on_event("status", "pi stream blocked by interactive prompt; skipping sync fallback.")
                raise
            if on_event:
                on_event("status", f"pi stream fallback: {_summarize_error_text(str(stream_exc))}")
            text = await asyncio.to_thread(_run_pi, runtime, prompt, env=env, timeout_s=timeout_s, thinking=thinking)
            await _simulate_stream(text, on_event=on_event)
            return text
    if provider == "ollama":
        text = await asyncio.to_thread(_run_ollama, runtime, prompt, env=env, timeout_s=timeout_s)
        await _simulate_stream(text, on_event=on_event)
        return text
    if provider == "gemini":
        return await _stream_gemini(prompt, env=env, timeout_s=timeout_s, on_event=on_event)
    if provider == "codex":
        return await _stream_codex(prompt, env=env, timeout_s=timeout_s, on_event=on_event)
    if provider == "claude":
        text = await asyncio.to_thread(_run_claude, prompt, env=env, timeout_s=timeout_s)
        await _simulate_stream(text, on_event=on_event)
        return text

    raise RuntimeError(f"unsupported inference provider: {provider}")


async def _stream_pi(
    runtime: InferenceRuntime,
    prompt: str,
    *,
    env: dict[str, str],
    timeout_s: float,
    on_event: StreamEventHook | None,
    thinking: str = PI_TYPE1_THINKING_DEFAULT,
) -> str:
    status = runtime.statuses.get("pi")
    cli = (status.cli_path if status and status.cli_path else "pi") or "pi"
    help_text = _pi_help_text(cli)
    prepared_prompt, prompt_notes = _prepare_prompt_for_pi(prompt)
    cmd = [cli]
    supports_mode = _pi_help_supports(help_text, "--mode")
    if supports_mode:
        if help_text and "json" not in help_text:
            raise RuntimeError("pi CLI stream mode=json unavailable")
        cmd.extend(["--mode", "json"])
    if _pi_help_supports(help_text, "--no-session"):
        cmd.append("--no-session")
    cmd.extend(_pi_cli_thinking_args(cli, thinking, help_text=help_text))
    cmd.append(prepared_prompt)

    stderr_lines: list[str] = []
    text_chunks: list[str] = []
    final_text = ""
    last_status = ""
    last_thinking = ""
    last_tool_update = ""
    emitted_model = ""

    def emit_status(message: str) -> None:
        nonlocal last_status
        cleaned = _short_status_text(message, max_chars=220)
        if not cleaned or cleaned == last_status:
            return
        last_status = cleaned
        if on_event:
            on_event("status", cleaned)

    def emit_task(message: str) -> None:
        cleaned = _short_status_text(message, max_chars=180)
        if not cleaned:
            return
        if on_event:
            on_event("task", cleaned)

    for note in prompt_notes:
        emit_status(note)

    def maybe_emit_model(payload: dict[str, Any]) -> None:
        nonlocal emitted_model
        model = _pi_model_from_event(payload)
        if not model or model == emitted_model:
            return
        emitted_model = model
        if on_event:
            on_event("model", model)
        emit_status(f"pi model: {model}")

    def handle_stdout_line(line: str) -> None:
        nonlocal final_text, last_thinking, last_tool_update
        stripped = line.strip()
        if not stripped:
            return
        if not stripped.startswith("{"):
            emit_status(f"pi: {stripped}")
            return
        try:
            payload = json.loads(stripped)
        except Exception:
            emit_status(f"pi: {stripped}")
            return
        if not isinstance(payload, dict):
            return

        maybe_emit_model(payload)
        event_type = str(payload.get("type") or "").strip().lower()
        if not event_type:
            return

        if event_type == "message_update":
            assistant_event = payload.get("assistantMessageEvent")
            if not isinstance(assistant_event, dict):
                return
            delta_type = str(assistant_event.get("type") or "").strip().lower()
            if delta_type == "text_delta":
                delta = assistant_event.get("delta")
                if isinstance(delta, str) and delta:
                    text_chunks.append(delta)
                    if on_event:
                        on_event("delta", delta)
                return
            if delta_type == "thinking_start":
                emit_status("pi thinking...")
                return
            if delta_type == "thinking_delta":
                delta = _short_status_text(str(assistant_event.get("delta") or ""), max_chars=140)
                if delta and delta != last_thinking:
                    last_thinking = delta
                    emit_status(f"pi thinking: {delta}")
                return
            if delta_type == "thinking_end":
                emit_status("pi thinking block complete")
                return
            if delta_type == "toolcall_start":
                tool_name = _short_status_text(str(assistant_event.get("toolName") or "tool"), max_chars=80)
                emit_task(f"pi preparing tool call: {tool_name}")
                return
            if delta_type == "toolcall_end":
                tool_name = _short_status_text(str(assistant_event.get("toolName") or "tool"), max_chars=80)
                emit_task(f"pi tool call ready: {tool_name}")
                return
            if delta_type == "done":
                emit_status("pi response stream complete")
                return
            if delta_type == "error":
                reason = _short_status_text(str(assistant_event.get("reason") or "unknown"), max_chars=80)
                emit_status(f"pi stream error: {reason}")
                return
            return

        if event_type == "tool_execution_start":
            tool_name = _short_status_text(str(payload.get("toolName") or "tool"), max_chars=80)
            args = _pi_tool_args_summary(payload.get("args"))
            emit_task(f"pi tool start: {tool_name}{args}")
            return
        if event_type == "tool_execution_update":
            tool_name = _short_status_text(str(payload.get("toolName") or "tool"), max_chars=80)
            partial = _short_status_text(_pi_tool_result_text(payload.get("partialResult")), max_chars=160)
            if partial and partial != last_tool_update:
                last_tool_update = partial
                emit_status(f"{tool_name}: {partial}")
            return
        if event_type == "tool_execution_end":
            tool_name = _short_status_text(str(payload.get("toolName") or "tool"), max_chars=80)
            if bool(payload.get("isError")):
                detail = _short_status_text(_pi_tool_result_text(payload.get("result")), max_chars=140)
                emit_status(f"pi tool error: {tool_name} ({detail or 'no details'})")
            else:
                emit_task(f"pi tool complete: {tool_name}")
            return

        if event_type in {"message_end", "turn_end"}:
            maybe = _pi_message_text(payload.get("message"))
            if maybe:
                final_text = maybe
            return
        if event_type == "agent_end":
            messages = payload.get("messages")
            if isinstance(messages, list):
                for item in reversed(messages):
                    maybe = _pi_message_text(item)
                    if maybe:
                        final_text = maybe
                        break
            return

        if event_type == "auto_retry_start":
            attempt = payload.get("attempt")
            max_attempts = payload.get("maxAttempts")
            emit_status(f"pi auto-retry start: attempt {attempt}/{max_attempts}")
            return
        if event_type == "auto_retry_end":
            success = _yes_no(bool(payload.get("success")))
            emit_status(f"pi auto-retry end: success={success}")
            return
        if event_type == "auto_compaction_start":
            reason = _short_status_text(str(payload.get("reason") or "unknown"), max_chars=60)
            emit_status(f"pi compaction start: {reason}")
            return
        if event_type == "auto_compaction_end":
            aborted = _yes_no(bool(payload.get("aborted")))
            will_retry = _yes_no(bool(payload.get("willRetry")))
            emit_status(f"pi compaction end: aborted={aborted} retry={will_retry}")
            return
        if event_type in {"agent_start", "turn_start", "turn_end", "message_start"}:
            emit_status(f"pi event: {event_type}")
            return

    def handle_stderr_line(line: str) -> None:
        stripped = line.strip()
        if not stripped:
            return
        stderr_lines.append(stripped)
        emit_status(f"pi stderr: {stripped}")

    await _run_streaming_process(
        cmd,
        provider="pi",
        env=env,
        timeout_s=timeout_s,
        on_stdout_line=handle_stdout_line,
        on_stderr_line=handle_stderr_line,
    )

    text = (final_text or "".join(text_chunks)).strip()
    if not text:
        detail = "; ".join(stderr_lines[-5:]) if stderr_lines else "no assistant output received"
        _raise_inference_command_failure(
            provider="pi",
            command=cmd,
            detail=f"pi inference returned no assistant output: {detail}",
            stderr_text="\n".join(stderr_lines[-20:]),
            timeout_s=timeout_s,
            phase="stream",
        )
    return text


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

    await _run_streaming_process(
        cmd,
        provider="gemini",
        env=env,
        timeout_s=timeout_s,
        on_stdout_line=handle_stdout_line,
        on_stderr_line=handle_stderr_line,
    )

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
    last_task_message = ""

    def emit_task(message: str) -> None:
        nonlocal last_task_message
        cleaned = _short_status_text(message, max_chars=180)
        if not cleaned:
            return
        if cleaned == last_task_message:
            return
        last_task_message = cleaned
        if on_event:
            on_event("task", cleaned)

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
        event_name = event_type.strip().lower() if isinstance(event_type, str) else ""
        if event_name:
            task_message = _codex_task_from_payload(event_name, payload)
            if task_message:
                emit_task(task_message)

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

    await _run_streaming_process(
        cmd,
        provider="codex",
        env=env,
        timeout_s=timeout_s,
        on_stdout_line=handle_stdout_line,
        on_stderr_line=handle_stderr_line,
    )

    combined = "\n\n".join(msg.strip() for msg in final_messages if msg.strip())
    if not combined:
        detail = "; ".join(stderr_lines[-5:]) if stderr_lines else "no agent_message item received"
        raise RuntimeError(f"codex inference returned no agent_message output: {detail}")

    if not streamed_any_delta:
        await _simulate_stream(combined, on_event=on_event)
    return combined


def _codex_task_from_payload(event_name: str, payload: dict[str, Any]) -> str | None:
    if not event_name.startswith("item.") and not event_name.startswith("response.output_item."):
        return None
    item = payload.get("item")
    if not isinstance(item, dict):
        return None
    return _codex_item_task_message(event_name, item)


def _codex_item_task_message(event_name: str, item: dict[str, Any]) -> str | None:
    item_type_raw = str(item.get("type") or "").strip()
    item_type = item_type_raw.lower()
    if not item_type or item_type == "agent_message":
        return None

    args = (
        _coerce_json_mapping(item.get("arguments"))
        or _coerce_json_mapping(item.get("args"))
        or _coerce_json_mapping(item.get("input"))
        or _coerce_json_mapping(item.get("parameters"))
        or {}
    )
    tool_name = _first_non_empty(item, args, keys=("name", "tool_name", "tool", "title"))
    command = _first_non_empty(item, args, keys=("command", "cmd", "shell_command", "shell", "exec"))
    url = _first_non_empty(item, args, keys=("url", "href", "target_url", "link"))
    query = _first_non_empty(item, args, keys=("query", "search_query", "q", "keywords", "search"))

    if command:
        action = f"running command: {command}"
    elif "web" in item_type or "browser" in item_type:
        if url:
            action = f"browsing {url}"
        elif query:
            action = f"browsing web for {query}"
        else:
            action = "browsing the web"
    elif "file" in item_type and "search" in item_type:
        if query:
            action = f"searching files for {query}"
        else:
            action = "searching files"
    elif "search" in item_type:
        if url:
            action = f"checking {url}"
        elif query:
            action = f"searching for {query}"
        else:
            action = "searching"
    elif "function" in item_type or "tool" in item_type:
        if tool_name and query:
            action = f"using {tool_name} for {query}"
        elif tool_name and url:
            action = f"using {tool_name} on {url}"
        elif tool_name:
            action = f"using {tool_name}"
        else:
            action = f"using {item_type.replace('_', ' ')}"
    else:
        label = item_type.replace("_", " ")
        if tool_name:
            action = f"working on {label} ({tool_name})"
        else:
            action = f"working on {label}"

    if event_name.endswith("completed") or event_name.endswith(".done"):
        return f"completed {action}"
    return action


def _coerce_json_mapping(value: Any) -> dict[str, Any] | None:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate.startswith("{"):
        return None
    try:
        payload = json.loads(candidate)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def _first_non_empty(*mappings: Mapping[str, Any], keys: tuple[str, ...]) -> str:
    for mapping in mappings:
        if not isinstance(mapping, Mapping):
            continue
        for key in keys:
            value = mapping.get(key)
            if isinstance(value, str):
                cleaned = _short_status_text(value, max_chars=120)
                if cleaned:
                    return cleaned
            elif value is not None and not isinstance(value, (dict, list, tuple, set)):
                cleaned = _short_status_text(str(value), max_chars=120)
                if cleaned:
                    return cleaned
    return ""


def _short_status_text(value: str, *, max_chars: int) -> str:
    cleaned = " ".join(value.split())
    if not cleaned:
        return ""
    if len(cleaned) <= max_chars:
        return cleaned
    return f"{cleaned[: max_chars - 3]}..."


def _pi_model_from_event(payload: dict[str, Any]) -> str:
    candidates: list[Any] = [
        payload.get("model"),
        payload.get("modelId"),
    ]
    assistant_event = payload.get("assistantMessageEvent")
    if isinstance(assistant_event, dict):
        candidates.extend(
            [
                assistant_event.get("model"),
                assistant_event.get("modelId"),
                assistant_event.get("partial"),
            ]
        )
    message = payload.get("message")
    if isinstance(message, dict):
        candidates.extend([message.get("model"), message.get("modelId")])

    for candidate in candidates:
        resolved = _coerce_model_label(candidate)
        if resolved:
            return resolved
    return ""


def _coerce_model_label(value: Any) -> str:
    if isinstance(value, str):
        return _clean_model_setting(value)
    if isinstance(value, dict):
        provider = _clean_model_setting(value.get("provider"))
        model_id = _clean_model_setting(value.get("id") or value.get("model") or value.get("modelId"))
        if provider and model_id:
            return f"{provider}/{model_id}"
        if model_id:
            return model_id
    return ""


def _pi_message_text(message: Any) -> str:
    if not isinstance(message, dict):
        return ""
    role = str(message.get("role") or "").strip().lower()
    if role and role != "assistant":
        return ""

    content = message.get("content")
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip().lower()
            if item_type in {"thinking", "tool_call", "toolcall"}:
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
                continue
            value = item.get("value")
            if isinstance(value, str) and value.strip():
                chunks.append(value.strip())
        combined = "\n".join(chunks).strip()
        if combined:
            return combined

    text = message.get("text")
    if isinstance(text, str) and text.strip():
        return text.strip()
    return ""


def _pi_tool_args_summary(value: Any) -> str:
    if not isinstance(value, Mapping):
        return ""
    command = value.get("command")
    if isinstance(command, str):
        cleaned = _short_status_text(command, max_chars=80)
        if cleaned:
            return f" ({cleaned})"
    query = value.get("query")
    if isinstance(query, str):
        cleaned = _short_status_text(query, max_chars=80)
        if cleaned:
            return f" ({cleaned})"
    return ""


def _pi_tool_result_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, Mapping):
        return ""
    content = value.get("content")
    if isinstance(content, list):
        chunks: list[str] = []
        for item in content:
            if not isinstance(item, Mapping):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                chunks.append(text.strip())
        if chunks:
            return " ".join(chunks)
    details = value.get("details")
    if isinstance(details, Mapping):
        output = details.get("output") or details.get("message")
        if isinstance(output, str) and output.strip():
            return output.strip()
    return ""


def _clean_model_setting(value: Any) -> str:
    cleaned = " ".join(str(value or "").split()).strip()
    if not cleaned:
        return ""
    if len(cleaned) > 180:
        cleaned = cleaned[:180].rstrip()
    return cleaned


def _clean_thinking_setting(value: Any) -> str:
    cleaned = " ".join(str(value or "").split()).strip().lower()
    allowed = {"off", "minimal", "low", "medium", "high", "xhigh"}
    if cleaned in allowed:
        return cleaned
    return ""


def _pi_help_text(cli: str) -> str:
    return _safe_help_text(cli).lower()


def _pi_help_supports(help_text: str, flag: str, *, default_when_unknown: bool = True) -> bool:
    if not help_text:
        return default_when_unknown
    return flag in help_text


def _pi_compat_thinking_level(help_text: str, level: str) -> str:
    if not level:
        return ""
    if not help_text:
        return level
    if level == "minimal" and "minimal" not in help_text and "low" in help_text:
        return "low"
    if level == "xhigh" and "xhigh" not in help_text and "high" in help_text:
        return "high"
    return level


def _pi_cli_thinking_args(cli: str, thinking: str, *, help_text: str | None = None) -> list[str]:
    level = _clean_thinking_setting(thinking)
    if not level:
        return []
    if help_text is None:
        help_text = _pi_help_text(cli)
    level = _pi_compat_thinking_level(help_text, level)
    if not level:
        return []
    if "--thinking-level" in help_text:
        return ["--thinking-level", level]
    if "--thinking" in help_text:
        return ["--thinking", level]
    return []


def _build_pi_command(
    cli: str,
    *,
    help_text: str,
    prepared_prompt: str,
    thinking: str,
    include_optional_flags: bool = True,
) -> list[str]:
    cmd = [cli]
    if include_optional_flags:
        if _pi_help_supports(help_text, "--print"):
            cmd.append("--print")
        if _pi_help_supports(help_text, "--mode"):
            cmd.extend(["--mode", "text"])
        if _pi_help_supports(help_text, "--no-session"):
            cmd.append("--no-session")
    cmd.extend(_pi_cli_thinking_args(cli, thinking, help_text=help_text))
    cmd.append(prepared_prompt)
    return cmd


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"


async def _run_streaming_process(
    cmd: list[str],
    *,
    provider: str,
    env: dict[str, str],
    timeout_s: float,
    on_stdout_line: Callable[[str], None],
    on_stderr_line: Callable[[str], None],
) -> None:
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    assert proc.stdout is not None
    assert proc.stderr is not None

    stdout_lines: list[str] = []
    stderr_lines: list[str] = []
    interactive_prompt_line = ""

    async def pump(stream: asyncio.StreamReader, handler: Callable[[str], None], sink: list[str]) -> None:
        nonlocal interactive_prompt_line
        while True:
            raw = await stream.readline()
            if not raw:
                return
            line = raw.decode("utf-8", errors="replace").rstrip("\r\n")
            if line:
                sink.append(line)
                if len(sink) > 80:
                    sink.pop(0)
            handler(line)
            if line and _looks_like_interactive_prompt_text(line):
                interactive_prompt_line = line.strip()
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                return

    stdout_task = asyncio.create_task(pump(proc.stdout, on_stdout_line, stdout_lines))
    stderr_task = asyncio.create_task(pump(proc.stderr, on_stderr_line, stderr_lines))

    try:
        await asyncio.wait_for(asyncio.gather(stdout_task, stderr_task, proc.wait()), timeout=timeout_s)
    except asyncio.TimeoutError:
        with contextlib.suppress(ProcessLookupError):
            proc.kill()
        _raise_inference_command_failure(
            provider=provider,
            command=cmd,
            detail=f"inference subprocess timed out after {timeout_s:.0f}s",
            stdout_text="\n".join(stdout_lines[-20:]),
            stderr_text="\n".join(stderr_lines[-20:]),
            timeout_s=timeout_s,
            phase="stream",
        )
    finally:
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
        with contextlib.suppress(Exception):
            await proc.wait()

    if interactive_prompt_line:
        _raise_inference_command_failure(
            provider=provider,
            command=cmd,
            detail=f"inference subprocess blocked on interactive prompt: {interactive_prompt_line}",
            stdout_text="\n".join(stdout_lines[-20:]),
            stderr_text="\n".join(stderr_lines[-20:]),
            timeout_s=timeout_s,
            phase="stream",
        )

    if proc.returncode != 0:
        _raise_inference_command_failure(
            provider=provider,
            command=cmd,
            detail=f"inference subprocess failed: exit={proc.returncode}",
            stdout_text="\n".join(stdout_lines[-20:]),
            stderr_text="\n".join(stderr_lines[-20:]),
            timeout_s=timeout_s,
            phase="stream",
        )


def _summarize_error_text(text: str) -> str:
    value = " ".join(text.split())
    if len(value) <= 220:
        return value
    return f"{value[:217]}..."


def _prepare_prompt_for_pi(prompt: str) -> tuple[str, list[str]]:
    text = (prompt or "").replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    if not lines:
        return "", []

    wrapped_lines: list[str] = []
    wrapped_count = 0
    for line in lines:
        chunks = _wrap_prompt_line(line, max_chars=PI_PROMPT_MAX_LINE_CHARS)
        if len(chunks) > 1:
            wrapped_count += 1
        wrapped_lines.extend(chunks)

    normalized = "\n".join(wrapped_lines).strip()
    notes: list[str] = []
    if wrapped_count:
        notes.append(f"pi prompt guard: wrapped {wrapped_count} oversized lines")

    if len(normalized) > PI_PROMPT_MAX_CHARS:
        original_chars = len(normalized)
        normalized = _trim_prompt_middle(
            normalized,
            max_chars=PI_PROMPT_MAX_CHARS,
            marker=PI_PROMPT_TRUNCATION_MARKER,
        )
        notes.append(
            f"pi prompt guard: trimmed prompt from {original_chars} to {len(normalized)} chars"
        )

    return normalized, notes


def _wrap_prompt_line(line: str, *, max_chars: int) -> list[str]:
    if max_chars <= 0:
        return [line]
    if len(line) <= max_chars:
        return [line]

    chunks: list[str] = []
    cursor = 0
    while cursor < len(line):
        end = min(len(line), cursor + max_chars)
        if end >= len(line):
            part = line[cursor:]
            chunks.append(part)
            break

        split_at = line.rfind(" ", cursor + max(8, max_chars // 3), end + 1)
        if split_at <= cursor:
            split_at = end
        part = line[cursor:split_at].rstrip()
        if not part:
            part = line[cursor:end]
            split_at = end
        chunks.append(part)
        cursor = split_at
        while cursor < len(line) and line[cursor] == " ":
            cursor += 1

    return chunks if chunks else [line]


def _trim_prompt_middle(text: str, *, max_chars: int, marker: str) -> str:
    if max_chars <= 0:
        return ""
    if len(text) <= max_chars:
        return text
    marker_text = marker if len(marker) < max_chars else marker[: max(0, max_chars - 1)]
    if not marker_text:
        return text[:max_chars]

    remaining = max_chars - len(marker_text)
    if remaining <= 0:
        return marker_text[:max_chars]

    head = int(remaining * 0.6)
    tail = remaining - head
    prefix = text[:head].rstrip()
    suffix = text[-tail:].lstrip() if tail > 0 else ""
    candidate = f"{prefix}{marker_text}{suffix}".strip()
    if len(candidate) <= max_chars:
        return candidate
    return candidate[:max_chars]


def _summarize_command_for_log(command: list[str]) -> str:
    shortened: list[str] = []
    for arg in command:
        value = str(arg)
        if len(value) > INFERENCE_LOG_MAX_ARG_CHARS:
            value = f"{value[: INFERENCE_LOG_MAX_ARG_CHARS - 3]}..."
        shortened.append(value)

    cmd_text = shlex.join(shortened)
    if len(cmd_text) <= INFERENCE_LOG_MAX_COMMAND_CHARS:
        return cmd_text
    return f"{cmd_text[: INFERENCE_LOG_MAX_COMMAND_CHARS - 3]}..."


def _log_unexpected_provider_exception(*, provider: str, exc: Exception, phase: str) -> None:
    summary = _summarize_error_text(str(exc) or exc.__class__.__name__)
    if " log: " in summary and "cmd:" in summary:
        return
    with contextlib.suppress(Exception):
        _append_inference_error_log(
            provider=provider,
            command=[provider, "<internal-exception>"],
            detail=f"unexpected inference exception: {summary}",
            stderr_text=traceback.format_exc(),
            phase=phase,
        )


def _run_pi(
    runtime: InferenceRuntime,
    prompt: str,
    *,
    env: dict[str, str],
    timeout_s: float,
    thinking: str = PI_TYPE1_THINKING_DEFAULT,
) -> str:
    status = runtime.statuses.get("pi")
    cli = (status.cli_path if status and status.cli_path else "pi") or "pi"
    help_text = _pi_help_text(cli)
    prepared_prompt, _prompt_notes = _prepare_prompt_for_pi(prompt)
    cmd = _build_pi_command(
        cli,
        help_text=help_text,
        prepared_prompt=prepared_prompt,
        thinking=thinking,
        include_optional_flags=True,
    )

    def run_once(command: list[str]) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=env,
            timeout=timeout_s,
            stdin=subprocess.DEVNULL,
        )

    def should_retry_without_optional_flags(proc: subprocess.CompletedProcess[str]) -> bool:
        merged = f"{proc.stderr or ''}\n{proc.stdout or ''}".lower()
        if "unrecognized" in merged or "unknown option" in merged or "no such option" in merged:
            return True
        return False

    def should_retry_with_compat_fallback(proc: subprocess.CompletedProcess[str]) -> bool:
        if should_retry_without_optional_flags(proc):
            return True
        merged = f"{proc.stderr or ''}\n{proc.stdout or ''}".lower()
        if "invalid choice" in merged or "invalid value" in merged or "unsupported value" in merged:
            return True
        if proc.returncode != 0 and not (proc.stderr or "").strip() and not (proc.stdout or "").strip():
            return True
        return False

    def retry_thinking_override(proc: subprocess.CompletedProcess[str]) -> str:
        requested = _clean_thinking_setting(thinking)
        if not requested:
            return ""
        merged = f"{proc.stderr or ''}\n{proc.stdout or ''}".lower()
        if requested == "minimal":
            if (
                "unsupported value: 'minimal'" in merged
                or 'unsupported value: "minimal"' in merged
                or "'minimal' is not supported" in merged
                or '"minimal" is not supported' in merged
                or ("invalid value" in merged and "minimal" in merged and "low" in merged)
            ):
                return "low"
        if requested == "xhigh":
            if (
                "unsupported value: 'xhigh'" in merged
                or 'unsupported value: "xhigh"' in merged
                or "'xhigh' is not supported" in merged
                or '"xhigh" is not supported' in merged
                or ("invalid value" in merged and "xhigh" in merged and "high" in merged)
            ):
                return "high"
        return ""

    try:
        proc = run_once(cmd)
    except subprocess.TimeoutExpired as exc:
        stdout_text = exc.stdout if isinstance(exc.stdout, str) else ""
        stderr_text = exc.stderr if isinstance(exc.stderr, str) else ""
        _raise_inference_command_failure(
            provider="pi",
            command=cmd,
            detail=f"pi inference timed out after {timeout_s:.0f}s",
            stdout_text=stdout_text,
            stderr_text=stderr_text,
            timeout_s=timeout_s,
            phase="sync",
        )
    except Exception as exc:  # noqa: BLE001
        _raise_inference_command_failure(
            provider="pi",
            command=cmd,
            detail=f"pi subprocess spawn failed: {exc}",
            timeout_s=timeout_s,
            phase="sync",
        )

    prompt_line = _first_interactive_prompt_line(proc.stdout, proc.stderr)
    if prompt_line:
        _raise_inference_command_failure(
            provider="pi",
            command=cmd,
            detail=f"pi requested interactive input during non-interactive inference: {prompt_line}",
            stdout_text=proc.stdout,
            stderr_text=proc.stderr,
            timeout_s=timeout_s,
            phase="sync",
        )

    if proc.returncode == 0 and proc.stdout.strip():
        return proc.stdout.strip()

    if should_retry_with_compat_fallback(proc):
        retry_thinking = retry_thinking_override(proc) or thinking
        retry_cmd = _build_pi_command(
            cli,
            help_text=help_text,
            prepared_prompt=prepared_prompt,
            thinking=retry_thinking,
            include_optional_flags=not should_retry_without_optional_flags(proc),
        )
        if retry_cmd != cmd:
            try:
                retry_proc = run_once(retry_cmd)
            except subprocess.TimeoutExpired as exc:
                stdout_text = exc.stdout if isinstance(exc.stdout, str) else ""
                stderr_text = exc.stderr if isinstance(exc.stderr, str) else ""
                _raise_inference_command_failure(
                    provider="pi",
                    command=retry_cmd,
                    detail=f"pi inference timed out after {timeout_s:.0f}s",
                    stdout_text=stdout_text,
                    stderr_text=stderr_text,
                    timeout_s=timeout_s,
                    phase="sync",
                )
            except Exception as exc:  # noqa: BLE001
                _raise_inference_command_failure(
                    provider="pi",
                    command=retry_cmd,
                    detail=f"pi subprocess spawn failed: {exc}",
                    timeout_s=timeout_s,
                    phase="sync",
                )
            retry_prompt_line = _first_interactive_prompt_line(retry_proc.stdout, retry_proc.stderr)
            if retry_prompt_line:
                _raise_inference_command_failure(
                    provider="pi",
                    command=retry_cmd,
                    detail=f"pi requested interactive input during non-interactive inference: {retry_prompt_line}",
                    stdout_text=retry_proc.stdout,
                    stderr_text=retry_proc.stderr,
                    timeout_s=timeout_s,
                    phase="sync",
                )
            if retry_proc.returncode == 0 and retry_proc.stdout.strip():
                return retry_proc.stdout.strip()
            detail = retry_proc.stderr.strip() or retry_proc.stdout.strip() or f"exit={retry_proc.returncode}"
            _raise_inference_command_failure(
                provider="pi",
                command=retry_cmd,
                detail=detail,
                stdout_text=retry_proc.stdout,
                stderr_text=retry_proc.stderr,
                timeout_s=timeout_s,
                phase="sync",
            )

    detail = proc.stderr.strip() or proc.stdout.strip() or f"exit={proc.returncode}"
    _raise_inference_command_failure(
        provider="pi",
        command=cmd,
        detail=detail,
        stdout_text=proc.stdout,
        stderr_text=proc.stderr,
        timeout_s=timeout_s,
        phase="sync",
    )


def _run_ollama(runtime: InferenceRuntime, prompt: str, *, env: dict[str, str], timeout_s: float) -> str:
    status = runtime.statuses.get("ollama")
    cli = (status.cli_path if status and status.cli_path else "ollama") or "ollama"
    model = _ollama_model_for_runtime(status)
    if not model:
        raise RuntimeError("ollama model is not configured")
    cmd = [cli, "run", model, prompt]
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
    raise RuntimeError(f"ollama inference failed: {detail}")


def _ollama_model_for_runtime(status: InferenceProviderStatus | None) -> str:
    if status is None:
        return ""
    source = status.key_source or ""
    if source.startswith("model:"):
        return source[len("model:") :].strip()
    return ""


def _provider_env(runtime: InferenceRuntime, provider: str) -> dict[str, str]:
    env = os.environ.copy()
    env.update(runtime.env_overrides_for(provider))
    tmp_dir = _workspace_tmp_dir()
    tmp_value = str(tmp_dir)
    env["TMPDIR"] = tmp_value
    env["TMP"] = tmp_value
    env["TEMP"] = tmp_value
    if provider == "pi":
        pi_agent_dir = _workspace_pi_agent_dir()
        _sync_workspace_agent_capabilities(pi_agent_dir)
        _ensure_workspace_pi_auth(pi_agent_dir)
        env["PI_CODING_AGENT_DIR"] = str(pi_agent_dir)
        env.setdefault("CI", "1")
        node_bin_dir = _workspace_node_bin_dir()
        if node_bin_dir is not None:
            current_path = env.get("PATH", "")
            env["PATH"] = f"{node_bin_dir}{os.pathsep}{current_path}" if current_path else str(node_bin_dir)
            env["NVM_DIR"] = str(_workspace_nvm_dir())
    return env


def _sync_workspace_agent_capabilities(agent_dir: Path) -> None:
    workspace = repo_root()
    _sync_agent_link(agent_dir / "skills", workspace / "skills")
    extensions_source = workspace / "extensions"
    legacy_tools_source = workspace / "tools"
    if not extensions_source.exists() and legacy_tools_source.exists():
        extensions_source = legacy_tools_source
    _sync_agent_link(agent_dir / "extensions", extensions_source)

    _migrate_legacy_tools_dir(
        agent_dir / "tools",
        extensions_dir=agent_dir / "extensions",
    )
    _migrate_legacy_tools_dir(
        workspace / ".pi" / "tools",
        extensions_dir=workspace / ".pi" / "extensions",
    )


def _sync_agent_link(target: Path, source: Path) -> None:
    if not source.exists():
        return

    with contextlib.suppress(Exception):
        if target.is_symlink():
            if target.resolve() == source.resolve():
                return
            target.unlink()
        elif target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.symlink_to(source, target_is_directory=source.is_dir())
        return
    except Exception:
        pass

    # Fallback for systems that block symlink creation.
    try:
        if source.is_dir():
            shutil.copytree(source, target, dirs_exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    except Exception:
        return


def _migrate_legacy_tools_dir(tools_dir: Path, *, extensions_dir: Path) -> None:
    if not tools_dir.exists() and not tools_dir.is_symlink():
        return

    # Legacy tools symlinks are the main source of interactive migration prompts.
    # Move the link target to extensions and remove tools symlink.
    if tools_dir.is_symlink():
        target: Path | None = None
        with contextlib.suppress(Exception):
            target = tools_dir.resolve()
        if target is not None and target.exists() and not (extensions_dir.exists() or extensions_dir.is_symlink()):
            _sync_agent_link(extensions_dir, target)
        with contextlib.suppress(Exception):
            tools_dir.unlink()
        return

    if not tools_dir.is_dir():
        return

    legacy_entries = _legacy_custom_tool_entries(tools_dir)
    if not legacy_entries:
        return

    with contextlib.suppress(Exception):
        extensions_dir.mkdir(parents=True, exist_ok=True)
    if not extensions_dir.exists():
        return

    for name in legacy_entries:
        source = tools_dir / name
        target = extensions_dir / name
        if target.exists() or target.is_symlink():
            continue
        with contextlib.suppress(Exception):
            shutil.move(str(source), str(target))


def _legacy_custom_tool_entries(tools_dir: Path) -> list[str]:
    if not tools_dir.exists() or not tools_dir.is_dir():
        return []
    names: list[str] = []
    with contextlib.suppress(Exception):
        for child in tools_dir.iterdir():
            name = child.name.strip()
            if not name or name.startswith("."):
                continue
            if name.lower() in _PI_MANAGED_LEGACY_TOOL_NAMES:
                continue
            names.append(name)
    return names


def _workspace_tmp_dir() -> Path:
    paths = ensure_runtime_dirs(runtime_paths())
    return paths.tmp_dir


def _workspace_pi_cli_path() -> Path:
    paths = ensure_runtime_dirs(runtime_paths())
    root = paths.root / "pi" / "node" / "node_modules" / ".bin"
    executable = "pi.cmd" if os.name == "nt" else "pi"
    return root / executable


def _workspace_pi_agent_dir() -> Path:
    paths = ensure_runtime_dirs(runtime_paths())
    agent_dir = paths.root / "pi" / "agent"
    agent_dir.mkdir(parents=True, exist_ok=True)
    return agent_dir


def _workspace_nvm_dir() -> Path:
    return _shared_workspace_nvm_dir()


def _workspace_node_bin_dir() -> Path | None:
    nvm_versions = _workspace_nvm_dir() / "versions" / "node"
    return _shared_latest_node_bin_dir(versions_dir=nvm_versions, min_major=PI_MIN_NODE_MAJOR)


def _pi_node_available() -> bool:
    node_bin_dir = _workspace_node_bin_dir()
    if node_bin_dir is not None:
        return True
    return _node_path_meets_pi_runtime(shutil.which("node"))


def _node_path_meets_pi_runtime(node_path: str | None) -> bool:
    return _shared_node_path_meets_min_major(node_path, min_major=PI_MIN_NODE_MAJOR)


def _node_major_from_version(raw: str) -> int | None:
    return _shared_node_major_from_version(raw)


def _normalize_status_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _looks_like_interactive_prompt_text(value: str) -> bool:
    normalized = _normalize_status_text(value)
    if not normalized:
        return False
    return any(signal in normalized for signal in _INTERACTIVE_PROMPT_SIGNALS)


def _first_interactive_prompt_line(*texts: str) -> str:
    for text in texts:
        for raw_line in str(text or "").splitlines():
            candidate = raw_line.strip()
            if candidate and _looks_like_interactive_prompt_text(candidate):
                return candidate
    return ""


def _is_interactive_prompt_failure(value: str) -> bool:
    normalized = _normalize_status_text(value)
    if "interactive prompt" in normalized:
        return True
    return _looks_like_interactive_prompt_text(normalized)


def _ensure_workspace_pi_auth(agent_dir: Path) -> list[str]:
    notes: list[str] = []
    target = agent_dir / "auth.json"
    home = Path.home()
    candidates = (
        home / ".pi" / "agent" / "auth.json",
        home / ".pi" / "auth.json",
    )
    target_exists = target.exists()
    target_payload = _read_json(target)
    target_has_auth = _has_pi_auth(target_payload)
    target_mtime_ns = _safe_mtime_ns(target)
    for candidate in candidates:
        if not candidate.exists():
            continue
        candidate_payload = _read_json(candidate)
        if not _has_pi_auth(candidate_payload):
            continue
        candidate_mtime_ns = _safe_mtime_ns(candidate)
        should_sync = False
        reason = ""
        if not target_exists:
            should_sync = True
            reason = f"synced workspace pi auth from `{_tilde_path(candidate)}`"
        elif not target_has_auth:
            should_sync = True
            reason = f"repaired workspace pi auth from `{_tilde_path(candidate)}`"
        elif candidate_mtime_ns > target_mtime_ns:
            should_sync = True
            reason = f"refreshed workspace pi auth from newer `{_tilde_path(candidate)}`"
        if not should_sync:
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
            with contextlib.suppress(Exception):
                os.chmod(target, 0o600)
            notes.append(reason)
            target_exists = True
            target_has_auth = True
            target_mtime_ns = max(target_mtime_ns, candidate_mtime_ns)
            break
        except Exception:
            continue

    sync_note = _sync_codex_oauth_into_pi_auth(target, home=home)
    if sync_note:
        notes.append(sync_note)
    return notes


def _sync_codex_oauth_into_pi_auth(target: Path, *, home: Path) -> str:
    codex_payload = _read_json(home / ".codex" / "auth.json")
    credential = _codex_oauth_credential_from_auth(codex_payload)
    if credential is None:
        return ""

    existing_payload = _read_json(target)
    existing_doc: dict[str, Any] = existing_payload if isinstance(existing_payload, dict) else {}
    existing_entry = existing_doc.get("openai-codex")
    existing_oauth = existing_entry if isinstance(existing_entry, dict) else None

    # Do not overwrite an existing workspace openai-codex OAuth entry with local Codex
    # import data; workspace/PI login flow should remain the source of truth once present.
    if existing_oauth is not None and _pi_oauth_entry_complete(existing_oauth):
        return ""

    changed = existing_oauth is None
    if existing_oauth is not None:
        for key in ("type", "access", "refresh", "expires", "accountId"):
            if existing_oauth.get(key) != credential.get(key):
                changed = True
                break

    if not changed:
        return ""

    existing_doc["openai-codex"] = credential
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(existing_doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        with contextlib.suppress(Exception):
            os.chmod(target, 0o600)
    except Exception:
        return ""

    if isinstance(existing_payload, dict) and existing_oauth is not None:
        return "updated workspace pi auth from local Codex OAuth session."
    if isinstance(existing_payload, dict):
        return "imported local Codex OAuth session into workspace pi auth."
    return "repaired workspace pi auth from local Codex OAuth session."


def _codex_oauth_credential_from_auth(payload: dict[str, Any] | list[Any] | None) -> dict[str, Any] | None:
    if not isinstance(payload, dict):
        return None
    candidates: list[dict[str, Any]] = []
    for key in ("tokens", "oauth", "auth", "session"):
        value = payload.get(key)
        if isinstance(value, dict):
            candidates.append(value)
    candidates.append(payload)

    access = ""
    refresh = ""
    id_token = ""
    account_id = ""
    expires = 0
    for candidate in candidates:
        if not access:
            access = str(
                candidate.get("access_token")
                or candidate.get("access")
                or candidate.get("token")
                or ""
            ).strip()
        if not refresh:
            refresh = str(candidate.get("refresh_token") or candidate.get("refresh") or "").strip()
        if not id_token:
            id_token = str(candidate.get("id_token") or candidate.get("idToken") or "").strip()
        if not account_id:
            account_id = str(
                candidate.get("account_id")
                or candidate.get("accountId")
                or candidate.get("chatgpt_account_id")
                or ""
            ).strip()
        if not expires:
            expires = _coerce_epoch_ms(candidate.get("expires_at") or candidate.get("expiresAt") or candidate.get("expires"))
            if not expires:
                expires = _coerce_epoch_ms(candidate.get("expiry") or candidate.get("expiryMs"))
        if access and refresh:
            break

    if not access or not refresh:
        return None

    account_id = account_id or _codex_account_id_from_token(id_token) or _codex_account_id_from_token(access)
    expires = expires or _jwt_expiry_ms(access) or _jwt_expiry_ms(id_token) or int(datetime.now(tz=timezone.utc).timestamp() * 1000)

    credential: dict[str, Any] = {
        "type": "oauth",
        "access": access,
        "refresh": refresh,
        "expires": int(expires),
    }
    if account_id:
        credential["accountId"] = account_id
    return credential


def _codex_account_id_from_token(token: str) -> str:
    payload = _jwt_payload(token)
    if not payload:
        return ""

    direct = str(payload.get("chatgpt_account_id") or payload.get("account_id") or "").strip()
    if direct:
        return direct
    auth_payload = payload.get("https://api.openai.com/auth")
    if isinstance(auth_payload, dict):
        nested = str(auth_payload.get("chatgpt_account_id") or auth_payload.get("account_id") or "").strip()
        if nested:
            return nested
    return ""


def _jwt_payload(token: str) -> dict[str, Any] | None:
    encoded = token.strip()
    if not encoded:
        return None
    parts = encoded.split(".")
    if len(parts) < 2:
        return None
    body = parts[1].strip()
    if not body:
        return None
    padding = "=" * (-len(body) % 4)
    try:
        decoded = base64.urlsafe_b64decode((body + padding).encode("utf-8"))
        payload = json.loads(decoded.decode("utf-8"))
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _jwt_expiry_ms(token: str) -> int | None:
    payload = _jwt_payload(token)
    if not payload:
        return None
    exp_raw = payload.get("exp")
    try:
        exp = int(exp_raw)
    except Exception:
        return None
    if exp <= 0:
        return None
    if exp < 10_000_000_000:
        return exp * 1000
    return exp


def _coerce_epoch_ms(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, (int, float)):
        stamp = float(value)
    else:
        raw = str(value).strip()
        if not raw:
            return 0
        try:
            stamp = float(raw)
        except Exception:
            try:
                parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            except Exception:
                return 0
            stamp = parsed.timestamp()
    if stamp <= 0:
        return 0
    if stamp < 10_000_000_000:
        return int(stamp * 1000)
    return int(stamp)


def _safe_mtime_ns(path: Path) -> int:
    try:
        return int(path.stat().st_mtime_ns)
    except Exception:
        return 0


def _pi_oauth_entry_complete(entry: dict[str, Any]) -> bool:
    access = str(entry.get("access") or "").strip()
    refresh = str(entry.get("refresh") or "").strip()
    return bool(access and refresh)


def _has_pi_auth(payload: dict[str, Any] | list[Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if not payload:
        return False
    for value in payload.values():
        if isinstance(value, dict):
            if _find_first_key(
                value,
                {"apiKey", "api_key", "access_token", "refresh_token", "access", "refresh"},
            ):
                return True
        if isinstance(value, str) and value.strip():
            return True
    return False


def _pi_oauth_entries(payload: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    entries: list[tuple[str, dict[str, Any]]] = []
    for provider, raw in payload.items():
        if not isinstance(provider, str) or not isinstance(raw, dict):
            continue
        entry_type = str(raw.get("type") or "").strip().lower()
        if entry_type == "oauth":
            entries.append((provider, raw))
            continue
        has_refresh = isinstance(raw.get("refresh"), str) and bool(str(raw.get("refresh")).strip())
        has_access = isinstance(raw.get("access"), str) and bool(str(raw.get("access")).strip())
        if has_refresh or has_access:
            entries.append((provider, raw))
    return entries


def _format_epoch_ms(value: Any) -> str:
    try:
        stamp = int(value)
    except Exception:
        return "unknown"
    if stamp <= 0:
        return "unknown"
    if stamp > 10_000_000_000:
        stamp = stamp / 1000
    try:
        return datetime.fromtimestamp(float(stamp), tz=timezone.utc).replace(microsecond=0).isoformat()
    except Exception:
        return "unknown"


def _mask_secret(value: str) -> str:
    cleaned = (value or "").strip()
    if not cleaned:
        return "(empty)"
    if len(cleaned) <= 8:
        return "*" * len(cleaned)
    return f"{cleaned[:4]}...{cleaned[-4:]}"


def _dedupe_non_empty_lines(lines: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in lines:
        cleaned = " ".join((raw or "").split()).strip()
        if not cleaned:
            continue
        if cleaned in seen:
            continue
        seen.add(cleaned)
        out.append(cleaned)
    return out


def _new_workspace_temp_file(*, prefix: str, suffix: str) -> Path:
    tmp_dir = _workspace_tmp_dir()
    with tempfile.NamedTemporaryFile(prefix=prefix, suffix=suffix, dir=tmp_dir, delete=False) as handle:
        return Path(handle.name)
