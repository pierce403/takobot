from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import inspect
from importlib import metadata
import json
import re
import socket
from pathlib import Path
from typing import Any


XMTP_PROFILE_STATE_VERSION = 1
XMTP_PROFILE_STATE_FILE = "xmtp-profile.json"
XMTP_PROFILE_AVATAR_FILE = "xmtp-avatar.svg"
XMTP_PROFILE_NAME_MAX_CHARS = 40

_AVATAR_BACKGROUNDS: tuple[tuple[str, str], ...] = (
    ("#ECFEFF", "#A5F3FC"),
    ("#EFF6FF", "#BFDBFE"),
    ("#ECFDF5", "#A7F3D0"),
    ("#FEF3C7", "#FDE68A"),
    ("#FEF2F2", "#FECACA"),
    ("#F8FAFC", "#E2E8F0"),
)

_AVATAR_BODY_COLORS: tuple[str, ...] = (
    "#0F766E",
    "#1D4ED8",
    "#047857",
    "#B45309",
    "#BE123C",
    "#334155",
)

_AVATAR_ACCENT_COLORS: tuple[str, ...] = (
    "#22D3EE",
    "#60A5FA",
    "#34D399",
    "#F59E0B",
    "#FB7185",
    "#94A3B8",
)


@dataclass(frozen=True)
class XmtpProfileSyncResult:
    name: str
    state_path: Path
    avatar_path: Path | None
    profile_api_found: bool
    applied_name: bool
    applied_avatar: bool
    errors: tuple[str, ...]


def default_message() -> str:
    hostname = socket.gethostname()
    return f"hi from {hostname} (tako)"


def hint_for_xmtp_error(error: Exception) -> str | None:
    message = str(error)
    if "grpc-status header missing" in message or "IdentityApi" in message:
        return (
            "Tip: check outbound HTTPS/HTTP2 access to "
            "grpc.production.xmtp.network:443 and "
            "message-history.production.ephemera.network."
        )
    if "file is not a database" in message or "sqlcipher" in message:
        return (
            "Tip: the local XMTP database appears corrupted or was created with a "
            "different encryption key. Remove .tako/xmtp-db or set "
            "a fresh runtime directory to recreate it."
        )
    return None


def probe_xmtp_import() -> tuple[bool, str]:
    package_version: str | None = None
    try:
        package_version = metadata.version("xmtp")
    except metadata.PackageNotFoundError:
        package_version = None
    except Exception:
        package_version = None

    try:
        import xmtp  # noqa: F401
    except ModuleNotFoundError as exc:
        missing_name = (exc.name or "").strip()
        if missing_name == "xmtp":
            if package_version:
                return False, f"package xmtp=={package_version} is installed, but import still failed: {exc}"
            return False, "package `xmtp` is not installed in this Python environment."
        if package_version:
            return False, f"xmtp=={package_version} is installed, but a subdependency is missing: {missing_name or exc}"
        return False, f"xmtp import failed: missing module {missing_name or exc}"
    except Exception as exc:  # noqa: BLE001
        if package_version:
            return False, f"xmtp=={package_version} is installed, but import failed: {exc}"
        return False, f"xmtp import failed: {exc}"

    if package_version:
        return True, f"import OK (xmtp=={package_version})"
    return True, "import OK"


async def create_client(env: str, db_root: Path, wallet_key: str, db_encryption_key: str) -> object:
    from xmtp import Client
    from xmtp.signers import create_signer
    from xmtp.types import ClientOptions

    signer = create_signer(wallet_key)

    def db_path_for(inbox_id: str) -> str:
        return str(db_root / f"xmtp-{env}-{inbox_id}.db3")

    # Contract: no user-facing env-var configuration. Defaults are intentionally fixed for now.
    api_url = None
    history_sync_url = None
    gateway_host = None
    disable_history_sync = True
    disable_device_sync = True

    options = ClientOptions(
        env=env,
        api_url=api_url,
        history_sync_url=history_sync_url,
        gateway_host=gateway_host,
        disable_history_sync=disable_history_sync,
        disable_device_sync=disable_device_sync,
        db_path=db_path_for,
        db_encryption_key=db_encryption_key,
    )
    return await Client.create(signer, options)


def canonical_profile_name(identity_name: str) -> str:
    cleaned = " ".join((identity_name or "").split()).strip()
    cleaned = re.sub(r"[^0-9A-Za-z ._-]+", "", cleaned).strip(" ._-")
    if not cleaned:
        return "Tako"
    return cleaned[:XMTP_PROFILE_NAME_MAX_CHARS].strip() or "Tako"


def _avatar_initial(name: str) -> str:
    for char in name:
        if char.isalnum():
            return char.upper()
    return "T"


def build_profile_avatar_svg(name: str) -> str:
    canonical_name = canonical_profile_name(name)
    digest = hashlib.sha256(canonical_name.encode("utf-8")).digest()
    bg_start, bg_end = _AVATAR_BACKGROUNDS[digest[0] % len(_AVATAR_BACKGROUNDS)]
    body = _AVATAR_BODY_COLORS[digest[1] % len(_AVATAR_BODY_COLORS)]
    accent = _AVATAR_ACCENT_COLORS[digest[2] % len(_AVATAR_ACCENT_COLORS)]
    initial = _avatar_initial(canonical_name)
    return (
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 256 256" role="img" '
        f'aria-label="{canonical_name} avatar">'
        "<defs>"
        '<linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">'
        f'<stop offset="0%" stop-color="{bg_start}"/>'
        f'<stop offset="100%" stop-color="{bg_end}"/>'
        "</linearGradient>"
        "</defs>"
        '<rect x="0" y="0" width="256" height="256" rx="56" fill="url(#bg)"/>'
        f'<circle cx="128" cy="106" r="66" fill="{body}"/>'
        f'<circle cx="78" cy="164" r="24" fill="{body}"/>'
        f'<circle cx="108" cy="178" r="26" fill="{body}"/>'
        f'<circle cx="148" cy="178" r="26" fill="{body}"/>'
        f'<circle cx="178" cy="164" r="24" fill="{body}"/>'
        f'<circle cx="102" cy="98" r="13" fill="{accent}"/>'
        f'<circle cx="154" cy="98" r="13" fill="{accent}"/>'
        '<circle cx="102" cy="98" r="5" fill="#0F172A"/>'
        '<circle cx="154" cy="98" r="5" fill="#0F172A"/>'
        '<path d="M95 130C104 142 152 142 161 130" stroke="#0F172A" stroke-width="7" stroke-linecap="round" fill="none"/>'
        f'<text x="128" y="224" font-size="28" text-anchor="middle" fill="#0F172A" font-family="monospace">{initial}</text>'
        "</svg>\n"
    )


def ensure_profile_avatar(state_dir: Path, name: str) -> tuple[Path, str, str]:
    state_dir.mkdir(parents=True, exist_ok=True)
    avatar_path = state_dir / XMTP_PROFILE_AVATAR_FILE
    svg = build_profile_avatar_svg(name)
    existing = ""
    try:
        existing = avatar_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        existing = ""
    except Exception:
        existing = ""
    if existing != svg:
        avatar_path.write_text(svg, encoding="utf-8")
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    data_uri = f"data:image/svg+xml;base64,{encoded}"
    digest = hashlib.sha256(svg.encode("utf-8")).hexdigest()
    return avatar_path, data_uri, digest


def _profile_targets(client: object) -> list[object]:
    targets: list[object] = []
    seen: set[int] = set()
    for candidate in (
        client,
        getattr(client, "preferences", None),
        getattr(client, "_client", None),
        getattr(client, "_ffi", None),
    ):
        if candidate is None:
            continue
        ident = id(candidate)
        if ident in seen:
            continue
        seen.add(ident)
        targets.append(candidate)
    return targets


async def _invoke_method_variants(method: Any, variants: list[tuple[tuple[Any, ...], dict[str, Any]]]) -> tuple[bool, tuple[str, ...]]:
    errors: list[str] = []
    for args, kwargs in variants:
        try:
            result = method(*args, **kwargs)
            if inspect.isawaitable(result):
                await result
            return True, tuple(errors)
        except TypeError:
            continue
        except Exception as exc:  # noqa: BLE001
            summary = f"{exc.__class__.__name__}: {exc}"
            if summary not in errors:
                errors.append(summary)
    return False, tuple(errors)


def _avatar_candidates(avatar_path: Path | None, avatar_data_uri: str) -> tuple[str, ...]:
    values: list[str] = []
    if avatar_data_uri:
        values.append(avatar_data_uri)
    if avatar_path is not None:
        values.append(str(avatar_path))
        try:
            values.append(avatar_path.resolve().as_uri())
        except Exception:
            pass
    deduped: list[str] = []
    for value in values:
        if value and value not in deduped:
            deduped.append(value)
    return tuple(deduped)


async def _apply_profile_metadata(targets: list[object], name: str, avatar_values: tuple[str, ...]) -> tuple[bool, bool, bool, tuple[str, ...]]:
    profile_api_found = False
    applied_name = False
    applied_avatar = False
    errors: list[str] = []

    combined_methods = (
        "set_profile",
        "update_profile",
        "set_user_profile",
        "update_user_profile",
        "set_public_profile",
        "update_public_profile",
    )
    name_methods = (
        "set_display_name",
        "update_display_name",
        "set_name",
        "update_name",
        "set_inbox_name",
        "set_username",
        "update_username",
    )
    avatar_methods = (
        "set_avatar_url",
        "update_avatar_url",
        "set_avatar",
        "update_avatar",
        "set_profile_image",
        "update_profile_image",
        "set_image_url",
    )

    for target in targets:
        target_name = target.__class__.__name__
        for method_name in combined_methods:
            method = getattr(target, method_name, None)
            if not callable(method):
                continue
            profile_api_found = True
            variants: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
            for avatar in avatar_values:
                variants.extend(
                    [
                        ((), {"name": name, "avatar_url": avatar}),
                        ((), {"display_name": name, "avatar_url": avatar}),
                        ((), {"name": name, "avatar": avatar}),
                        ((), {"display_name": name, "avatar": avatar}),
                        (({"name": name, "avatar_url": avatar},), {}),
                        (({"display_name": name, "avatar_url": avatar},), {}),
                    ]
                )
            variants.extend(
                [
                    ((), {"name": name}),
                    ((), {"display_name": name}),
                    (({"name": name},), {}),
                    (({"display_name": name},), {}),
                ]
            )
            success, call_errors = await _invoke_method_variants(method, variants)
            for item in call_errors:
                entry = f"{target_name}.{method_name}: {item}"
                if entry not in errors:
                    errors.append(entry)
            if success:
                applied_name = True
                if avatar_values:
                    applied_avatar = True
                break
        if applied_name and (applied_avatar or not avatar_values):
            break

    if not applied_name:
        for target in targets:
            target_name = target.__class__.__name__
            for method_name in name_methods:
                method = getattr(target, method_name, None)
                if not callable(method):
                    continue
                profile_api_found = True
                success, call_errors = await _invoke_method_variants(
                    method,
                    [
                        ((name,), {}),
                        ((), {"name": name}),
                        ((), {"display_name": name}),
                        ((), {"value": name}),
                    ],
                )
                for item in call_errors:
                    entry = f"{target_name}.{method_name}: {item}"
                    if entry not in errors:
                        errors.append(entry)
                if success:
                    applied_name = True
                    break
            if applied_name:
                break

    if avatar_values and not applied_avatar:
        for target in targets:
            target_name = target.__class__.__name__
            for method_name in avatar_methods:
                method = getattr(target, method_name, None)
                if not callable(method):
                    continue
                profile_api_found = True
                variants: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
                for avatar in avatar_values:
                    variants.extend(
                        [
                            ((avatar,), {}),
                            ((), {"avatar_url": avatar}),
                            ((), {"avatar": avatar}),
                            ((), {"image_url": avatar}),
                            ((), {"value": avatar}),
                        ]
                    )
                success, call_errors = await _invoke_method_variants(method, variants)
                for item in call_errors:
                    entry = f"{target_name}.{method_name}: {item}"
                    if entry not in errors:
                        errors.append(entry)
                if success:
                    applied_avatar = True
                    break
            if applied_avatar:
                break

    trimmed_errors = tuple(errors[:8])
    return profile_api_found, applied_name, applied_avatar, trimmed_errors


def _write_profile_state(
    state_path: Path,
    *,
    name: str,
    avatar_path: Path | None,
    avatar_sha256: str,
    profile_api_found: bool,
    applied_name: bool,
    applied_avatar: bool,
    errors: tuple[str, ...],
) -> None:
    payload = {
        "version": XMTP_PROFILE_STATE_VERSION,
        "updated_at": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
        "name": name,
        "avatar_path": str(avatar_path) if avatar_path is not None else "",
        "avatar_sha256": avatar_sha256,
        "profile_api_found": profile_api_found,
        "applied_name": applied_name,
        "applied_avatar": applied_avatar,
        "errors": list(errors),
    }
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


async def sync_identity_profile(
    client: object,
    *,
    state_dir: Path,
    identity_name: str,
    generate_avatar: bool = True,
) -> XmtpProfileSyncResult:
    name = canonical_profile_name(identity_name)
    avatar_path: Path | None = None
    avatar_data_uri = ""
    avatar_sha256 = ""
    if generate_avatar:
        avatar_path, avatar_data_uri, avatar_sha256 = ensure_profile_avatar(state_dir, name)

    profile_api_found, applied_name, applied_avatar, errors = await _apply_profile_metadata(
        _profile_targets(client),
        name,
        _avatar_candidates(avatar_path, avatar_data_uri),
    )
    state_path = state_dir / XMTP_PROFILE_STATE_FILE
    _write_profile_state(
        state_path,
        name=name,
        avatar_path=avatar_path,
        avatar_sha256=avatar_sha256,
        profile_api_found=profile_api_found,
        applied_name=applied_name,
        applied_avatar=applied_avatar,
        errors=errors,
    )
    return XmtpProfileSyncResult(
        name=name,
        state_path=state_path,
        avatar_path=avatar_path,
        profile_api_found=profile_api_found,
        applied_name=applied_name,
        applied_avatar=applied_avatar,
        errors=errors,
    )


async def set_typing_indicator(conversation: object, active: bool) -> bool:
    targets = [conversation]
    ffi = getattr(conversation, "_ffi", None)
    if ffi is not None:
        targets.append(ffi)

    if active:
        simple_names = ("set_typing", "send_typing", "typing", "set_typing_indicator", "send_typing_indicator")
        state_names = ("start_typing", "begin_typing", "typing_start")
    else:
        simple_names = ("set_typing", "send_typing", "typing", "set_typing_indicator", "send_typing_indicator")
        state_names = ("stop_typing", "end_typing", "typing_stop")

    for target in targets:
        for name in simple_names:
            method = getattr(target, name, None)
            if not callable(method):
                continue
            if await _call_maybe_async(method, active):
                return True
            if await _call_maybe_async(method):
                return True
        for name in state_names:
            method = getattr(target, name, None)
            if not callable(method):
                continue
            if await _call_maybe_async(method):
                return True

    return False


async def _call_maybe_async(method, *args) -> bool:
    try:
        result = method(*args)
        if inspect.isawaitable(result):
            await result
        return True
    except TypeError:
        return False
    except Exception:
        return False


async def close_client(client: object) -> None:
    for attr in ("close", "disconnect"):
        method = getattr(client, attr, None)
        if not callable(method):
            continue
        try:
            result = method()
            if inspect.isawaitable(result):
                await result
        except Exception:
            pass
        return


async def send_dm(
    recipient: str,
    message: str,
    env: str,
    db_root: Path,
    wallet_key: str,
    db_encryption_key: str,
) -> None:
    client = await create_client(env, db_root, wallet_key, db_encryption_key)
    dm = await client.conversations.new_dm(recipient)
    await dm.send(message)


def send_dm_sync(
    recipient: str,
    message: str,
    env: str,
    db_root: Path,
    wallet_key: str,
    db_encryption_key: str,
) -> None:
    asyncio.run(send_dm(recipient, message, env, db_root, wallet_key, db_encryption_key))
