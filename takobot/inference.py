from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping

from .paths import ensure_runtime_dirs, runtime_paths


PROVIDER_PRIORITY = ("pi", "ollama", "codex", "claude", "gemini")
SUPPORTED_PROVIDER_PREFERENCES = ("auto", *PROVIDER_PRIORITY)
CODEX_AGENTIC_EXEC_ARGS = [
    "--skip-git-repo-check",
    "--dangerously-bypass-approvals-and-sandbox",
]
INFERENCE_SETTINGS_FILENAME = "inference-settings.json"
PI_KEY_ENV_VARS = (
    "OPENAI_API_KEY",
    "ANTHROPIC_API_KEY",
    "GEMINI_API_KEY",
    "OPENROUTER_API_KEY",
    "XAI_API_KEY",
    "GROQ_API_KEY",
    "CEREBRAS_API_KEY",
    "MISTRAL_API_KEY",
    "AI_GATEWAY_API_KEY",
    "ZAI_API_KEY",
    "MINIMAX_API_KEY",
    "KIMI_API_KEY",
    "AWS_BEARER_TOKEN_BEDROCK",
)
CONFIGURABLE_API_KEY_VARS = tuple(
    sorted(
        {
            *PI_KEY_ENV_VARS,
            "CLAUDE_API_KEY",
            "GOOGLE_API_KEY",
        }
    )
)
DEFAULT_OLLAMA_HOST = "http://127.0.0.1:11434"

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


def discover_inference_runtime() -> InferenceRuntime:
    home = Path.home()
    settings = load_inference_settings()
    env: dict[str, str] = dict(os.environ)
    env.update(settings.api_keys)
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

    requested_provider = os.environ.get("TAKO_INFERENCE_PROVIDER", "").strip().lower()
    preferred_provider = settings.preferred_provider if settings.preferred_provider in SUPPORTED_PROVIDER_PREFERENCES else "auto"
    selected_provider = None
    if requested_provider in statuses and statuses[requested_provider].ready:
        selected_provider = requested_provider
    if not selected_provider and preferred_provider != "auto":
        status = statuses.get(preferred_provider)
        if status and status.ready:
            selected_provider = preferred_provider
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
        _provider_env_overrides=provider_env_overrides,
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


def _detect_pi(home: Path, env: Mapping[str, str]) -> tuple[InferenceProviderStatus, str | None]:
    cli_name = "pi"
    workspace_cli = _workspace_pi_cli_path()
    if workspace_cli.exists():
        cli_path = str(workspace_cli)
    else:
        cli_path = shutil.which(cli_name)
    cli_installed = cli_path is not None
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
                        else "pi CLI detected but node runtime is unavailable."
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
                        else "pi auth profile detected but node runtime is unavailable." + oauth_hint
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
                "install pi runtime and configure auth to enable."
                if node_ready
                else "node runtime missing; setup will install workspace-local nvm/node before pi runtime."
            ),
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


def _run_with_provider(runtime: InferenceRuntime, provider: str, prompt: str, *, timeout_s: float) -> str:
    env = _provider_env(runtime, provider)
    if provider == "pi":
        return _run_pi(runtime, prompt, env=env, timeout_s=timeout_s)
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
) -> str:
    env = _provider_env(runtime, provider)

    if provider == "pi":
        text = await asyncio.to_thread(_run_pi, runtime, prompt, env=env, timeout_s=timeout_s)
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


def _run_pi(runtime: InferenceRuntime, prompt: str, *, env: dict[str, str], timeout_s: float) -> str:
    status = runtime.statuses.get("pi")
    cli = (status.cli_path if status and status.cli_path else "pi") or "pi"
    cmd = [
        cli,
        "--print",
        "--mode",
        "text",
        "--no-session",
        "--no-tools",
        "--no-extensions",
        "--no-skills",
        prompt,
    ]
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
    raise RuntimeError(f"pi inference failed: {detail}")


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
        _ensure_workspace_pi_auth(pi_agent_dir)
        env["PI_CODING_AGENT_DIR"] = str(pi_agent_dir)
        node_bin_dir = _workspace_node_bin_dir()
        if node_bin_dir is not None:
            current_path = env.get("PATH", "")
            env["PATH"] = f"{node_bin_dir}{os.pathsep}{current_path}" if current_path else str(node_bin_dir)
            env["NVM_DIR"] = str(_workspace_nvm_dir())
    return env


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
    paths = ensure_runtime_dirs(runtime_paths())
    return paths.root / "nvm"


def _workspace_node_bin_dir() -> Path | None:
    nvm_versions = _workspace_nvm_dir() / "versions" / "node"
    if not nvm_versions.exists():
        return None

    node_name = "node.exe" if os.name == "nt" else "node"
    candidates: list[tuple[tuple[int, ...], Path]] = []
    for child in nvm_versions.iterdir():
        if not child.is_dir():
            continue
        bin_dir = child / "bin"
        if not (bin_dir / node_name).exists():
            continue
        version = child.name.lstrip("v")
        parts: list[int] = []
        for token in version.split("."):
            if token.isdigit():
                parts.append(int(token))
            else:
                break
        candidates.append((tuple(parts), bin_dir))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    return candidates[-1][1]


def _pi_node_available() -> bool:
    if shutil.which("node"):
        return True
    return _workspace_node_bin_dir() is not None


def _ensure_workspace_pi_auth(agent_dir: Path) -> None:
    target = agent_dir / "auth.json"
    if target.exists():
        return
    home = Path.home()
    candidates = (
        home / ".pi" / "agent" / "auth.json",
        home / ".pi" / "auth.json",
    )
    for candidate in candidates:
        if not candidate.exists():
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(candidate.read_text(encoding="utf-8"), encoding="utf-8")
            return
        except Exception:
            continue


def _has_pi_auth(payload: dict[str, Any] | list[Any] | None) -> bool:
    if not isinstance(payload, dict):
        return False
    if not payload:
        return False
    for value in payload.values():
        if isinstance(value, dict):
            if _find_first_key(value, {"apiKey", "api_key", "access_token", "refresh_token"}):
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


def _new_workspace_temp_file(*, prefix: str, suffix: str) -> Path:
    tmp_dir = _workspace_tmp_dir()
    with tempfile.NamedTemporaryFile(prefix=prefix, suffix=suffix, dir=tmp_dir, delete=False) as handle:
        return Path(handle.name)
