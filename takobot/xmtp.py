from __future__ import annotations

import asyncio
import base64
import contextlib
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


XMTP_PROFILE_STATE_VERSION = 2
XMTP_PROFILE_STATE_FILE = "xmtp-profile.json"
XMTP_PROFILE_AVATAR_FILE = "xmtp-avatar.svg"
XMTP_PROFILE_NAME_MAX_CHARS = 40
XMTP_PROFILE_BROADCAST_STATE_VERSION = 1
XMTP_PROFILE_BROADCAST_STATE_FILE = "xmtp-profile-broadcast.json"
XMTP_PROFILE_MESSAGE_PREFIX = "tako:profile:"
XMTP_PROFILE_TEXT_CONTENT_TYPE = "xmtp.org/text:1.0"

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
    profile_read_api_found: bool
    profile_api_found: bool
    applied_name: bool
    applied_avatar: bool
    observed_name: str | None
    observed_avatar: str | None
    name_in_sync: bool
    avatar_in_sync: bool
    fallback_self_sent: bool
    fallback_peer_sent_count: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class XmtpProfileBroadcastResult:
    payload_sha256: str
    self_sent: bool
    peer_sent_count: int
    errors: tuple[str, ...]


@dataclass(frozen=True)
class XmtpProfileMessage:
    name: str | None
    avatar_url: str | None
    raw: str


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


def _trim_profile_avatar_url(value: str | None) -> str:
    avatar = (value or "").strip()
    if not avatar:
        return ""
    return avatar[:4096]


def build_profile_message(name: str, avatar_url: str) -> str:
    payload: dict[str, Any] = {
        "type": "profile",
        "v": 1,
        "display_name": canonical_profile_name(name),
        "ts": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
    }
    trimmed_avatar = _trim_profile_avatar_url(avatar_url)
    if trimmed_avatar:
        payload["avatar_url"] = trimmed_avatar
    encoded = json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return f"{XMTP_PROFILE_MESSAGE_PREFIX}{encoded}"


def parse_profile_message(text: str) -> XmtpProfileMessage | None:
    if not isinstance(text, str):
        return None
    stripped = text.strip()
    if not stripped.startswith(XMTP_PROFILE_MESSAGE_PREFIX):
        return None
    raw_json = stripped[len(XMTP_PROFILE_MESSAGE_PREFIX) :].strip()
    try:
        payload = json.loads(raw_json)
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    raw_name = payload.get("display_name")
    if not isinstance(raw_name, str):
        raw_name = payload.get("name")
    parsed_name = canonical_profile_name(raw_name) if isinstance(raw_name, str) and raw_name.strip() else None
    raw_avatar = payload.get("avatar_url")
    if not isinstance(raw_avatar, str):
        raw_avatar = payload.get("avatar")
    parsed_avatar = _trim_profile_avatar_url(raw_avatar if isinstance(raw_avatar, str) else "")
    return XmtpProfileMessage(
        name=parsed_name,
        avatar_url=parsed_avatar or None,
        raw=stripped,
    )


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


def _coerce_nonempty_string(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        try:
            value = value.decode("utf-8", errors="ignore")
        except Exception:
            return None
    if not isinstance(value, str):
        return None
    text = value.strip()
    return text or None


def _looks_like_avatar_value(value: str) -> bool:
    lowered = value.strip().lower()
    if not lowered:
        return False
    if lowered.startswith(("data:image/", "http://", "https://", "ipfs://", "file://")):
        return True
    if lowered.startswith("/"):
        return True
    return lowered.endswith((".png", ".jpg", ".jpeg", ".svg", ".webp", ".gif"))


def _extract_profile_fields(payload: Any) -> tuple[str | None, str | None]:
    if payload is None:
        return None, None
    if isinstance(payload, str):
        text = _coerce_nonempty_string(payload)
        if not text:
            return None, None
        if _looks_like_avatar_value(text):
            return None, text
        return text, None

    keys_name = ("display_name", "displayName", "name", "username", "profile_name", "profileName", "inbox_name", "inboxName")
    keys_avatar = ("avatar_url", "avatarUrl", "avatar", "image_url", "imageUrl", "profile_image", "profileImage")

    if isinstance(payload, dict):
        name = None
        avatar = None
        for key in keys_name:
            if key in payload:
                name = _coerce_nonempty_string(payload.get(key))
                if name:
                    break
        for key in keys_avatar:
            if key in payload:
                avatar = _coerce_nonempty_string(payload.get(key))
                if avatar:
                    break
        return name, avatar

    name = None
    avatar = None
    for key in keys_name:
        with contextlib.suppress(Exception):
            candidate = _coerce_nonempty_string(getattr(payload, key))
            if candidate:
                name = candidate
                break
    for key in keys_avatar:
        with contextlib.suppress(Exception):
            candidate = _coerce_nonempty_string(getattr(payload, key))
            if candidate:
                avatar = candidate
                break
    return name, avatar


async def _call_noarg_member(member: Any) -> tuple[bool, Any, str | None]:
    try:
        result = member() if callable(member) else member
        if inspect.isawaitable(result):
            result = await result
        return True, result, None
    except TypeError:
        return False, None, None
    except Exception as exc:  # noqa: BLE001
        return False, None, f"{exc.__class__.__name__}: {exc}"


def _name_matches(observed_name: str | None, desired_name: str) -> bool:
    if not observed_name:
        return False
    return canonical_profile_name(observed_name) == desired_name


def _avatar_matches(observed_avatar: str | None, avatar_values: tuple[str, ...]) -> bool:
    if not observed_avatar:
        return False
    probe = observed_avatar.strip()
    if not probe:
        return False
    if probe in avatar_values:
        return True
    lowered = probe.lower()
    for value in avatar_values:
        if lowered == value.strip().lower():
            return True
    return False


async def _read_profile_metadata(targets: list[object]) -> tuple[bool, str | None, str | None, tuple[str, ...]]:
    read_api_found = False
    observed_name: str | None = None
    observed_avatar: str | None = None
    errors: list[str] = []

    combined_members = (
        "get_profile",
        "profile",
        "get_user_profile",
        "user_profile",
        "get_public_profile",
        "public_profile",
        "get_identity_profile",
        "identity_profile",
        "get_profile_metadata",
        "profile_metadata",
    )
    name_members = (
        "get_display_name",
        "display_name",
        "get_inbox_name",
        "inbox_name",
        "get_profile_name",
        "profile_name",
        "get_username",
        "username",
        "get_name",
    )
    avatar_members = (
        "get_avatar_url",
        "avatar_url",
        "get_avatar",
        "avatar",
        "get_profile_image",
        "profile_image",
        "get_image_url",
        "image_url",
    )

    async def inspect_member(target: object, member_name: str, *, mode: str) -> None:
        nonlocal read_api_found, observed_name, observed_avatar
        member = getattr(target, member_name, None)
        if member is None:
            return
        read_api_found = True
        success, value, call_error = await _call_noarg_member(member)
        if call_error:
            entry = f"{target.__class__.__name__}.{member_name}: {call_error}"
            if entry not in errors:
                errors.append(entry)
        if not success:
            return
        if mode == "name":
            candidate = _coerce_nonempty_string(value)
            if candidate and observed_name is None:
                observed_name = candidate
            return
        if mode == "avatar":
            candidate = _coerce_nonempty_string(value)
            if candidate and observed_avatar is None:
                observed_avatar = candidate
            return
        extracted_name, extracted_avatar = _extract_profile_fields(value)
        if extracted_name and observed_name is None:
            observed_name = extracted_name
        if extracted_avatar and observed_avatar is None:
            observed_avatar = extracted_avatar

    for target in targets:
        for member_name in combined_members:
            await inspect_member(target, member_name, mode="combined")
        for member_name in name_members:
            await inspect_member(target, member_name, mode="name")
        for member_name in avatar_members:
            await inspect_member(target, member_name, mode="avatar")
        if observed_name is not None and observed_avatar is not None:
            break

    return read_api_found, observed_name, observed_avatar, tuple(errors[:8])


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


def _read_profile_broadcast_state(path: Path) -> tuple[str, str, dict[str, str]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return "", "", {}
    except Exception:
        return "", "", {}
    if not isinstance(payload, dict):
        return "", "", {}
    payload_sha256 = str(payload.get("payload_sha256") or "").strip().lower()
    self_sent_at = str(payload.get("self_sent_at") or "").strip()
    peers_raw = payload.get("peer_sent")
    peer_sent: dict[str, str] = {}
    if isinstance(peers_raw, dict):
        for key, value in peers_raw.items():
            if not isinstance(key, str):
                continue
            inbox = key.strip().lower()
            stamp = str(value or "").strip()
            if inbox and stamp:
                peer_sent[inbox] = stamp
    return payload_sha256, self_sent_at, peer_sent


def _write_profile_broadcast_state(
    path: Path,
    *,
    payload_sha256: str,
    self_sent_at: str,
    peer_sent: dict[str, str],
) -> None:
    payload = {
        "version": XMTP_PROFILE_BROADCAST_STATE_VERSION,
        "updated_at": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
        "payload_sha256": payload_sha256,
        "self_sent_at": self_sent_at,
        "peer_sent": dict(sorted(peer_sent.items())),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _client_eth_address(client: object) -> str:
    for candidate in (
        getattr(client, "account_identifier", None),
        getattr(client, "_identifier", None),
    ):
        if candidate is None:
            continue
        for attr in ("value", "identifier"):
            value = getattr(candidate, attr, None)
            if isinstance(value, str):
                trimmed = value.strip()
                if trimmed.startswith(("0x", "0X")) and len(trimmed) == 42:
                    return trimmed
    return ""


async def _list_dm_conversations(client: object) -> list[object]:
    conversations = getattr(client, "conversations", None)
    if conversations is None:
        return []
    list_dms = getattr(conversations, "list_dms", None)
    if callable(list_dms):
        try:
            result = list_dms()
            if inspect.isawaitable(result):
                result = await result
            if isinstance(result, list):
                return result
        except Exception:
            return []
    return []


async def _open_self_dm(client: object) -> object | None:
    inbox_id = _coerce_nonempty_string(getattr(client, "inbox_id", None))
    if inbox_id:
        for dm in await _list_dm_conversations(client):
            peer = _coerce_nonempty_string(getattr(dm, "peer_inbox_id", None))
            if peer and peer.lower() == inbox_id.lower():
                return dm

    address = _client_eth_address(client)
    if not address:
        return None
    conversations = getattr(client, "conversations", None)
    if conversations is None:
        return None
    new_dm = getattr(conversations, "new_dm", None)
    if not callable(new_dm):
        return None
    try:
        dm = new_dm(address)
        if inspect.isawaitable(dm):
            dm = await dm
        return dm
    except Exception:
        return None


def _profile_text_content_type() -> Any | None:
    try:
        from xmtp_content_type_primitives import ContentTypeId
    except Exception:
        return None
    return ContentTypeId(
        authority_id="xmtp.org",
        type_id="text",
        version_major=1,
        version_minor=0,
    )


def _register_silent_text_codec(client: object) -> Any | None:
    register = getattr(client, "register_codec", None)
    if not callable(register):
        return None
    content_type = _profile_text_content_type()
    if content_type is None:
        return None
    try:
        from xmtp_content_type_primitives import BaseContentCodec, EncodedContent
        from xmtp_bindings import xmtpv3
    except Exception:
        return None

    class _SilentTextCodec(BaseContentCodec[str]):
        @property
        def content_type(self):  # type: ignore[override]
            return content_type

        def encode(self, content: str, registry=None):  # type: ignore[override]
            encoded = xmtpv3.encode_text(content)
            return EncodedContent(
                type_id=content_type,
                parameters={"encoding": "UTF-8"},
                content=encoded,
            )

        def decode(self, content, registry=None):  # type: ignore[override]
            payload = getattr(content, "content", b"")
            if not isinstance(payload, (bytes, bytearray)):
                raise TypeError("profile codec payload must be bytes")
            return xmtpv3.decode_text(bytes(payload))

        def fallback(self, content: str):  # type: ignore[override]
            return None

        def should_push(self, content: str):  # type: ignore[override]
            return False

    try:
        register(_SilentTextCodec())
    except Exception:
        return None
    return content_type


async def _send_profile_message(
    conversation: object,
    *,
    message: str,
    content_type: Any | None,
) -> tuple[bool, str | None]:
    send = getattr(conversation, "send", None)
    if not callable(send):
        return False, "conversation.send missing"

    if content_type is not None:
        for args, kwargs in (
            ((message, content_type), {}),
            ((message,), {"content_type": content_type}),
        ):
            try:
                result = send(*args, **kwargs)
                if inspect.isawaitable(result):
                    await result
                return True, None
            except TypeError:
                continue
            except Exception as exc:  # noqa: BLE001
                return False, f"{exc.__class__.__name__}: {exc}"
    try:
        result = send(message)
        if inspect.isawaitable(result):
            await result
        return True, None
    except Exception as exc:  # noqa: BLE001
        return False, f"{exc.__class__.__name__}: {exc}"


async def publish_profile_message(
    client: object,
    *,
    state_dir: Path,
    identity_name: str,
    avatar_url: str = "",
    include_self_dm: bool = True,
    include_known_dm_peers: bool = True,
    target_conversation: object | None = None,
) -> XmtpProfileBroadcastResult:
    message = build_profile_message(identity_name, avatar_url)
    payload_sha256 = hashlib.sha256(message.encode("utf-8")).hexdigest()
    state_path = state_dir / XMTP_PROFILE_BROADCAST_STATE_FILE
    previous_hash, self_sent_at, peer_sent = _read_profile_broadcast_state(state_path)
    if previous_hash != payload_sha256:
        self_sent_at = ""
        peer_sent = {}

    self_sent = False
    peer_sent_count = 0
    errors: list[str] = []
    content_type = _register_silent_text_codec(client)
    now_stamp = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()

    if include_self_dm and not self_sent_at:
        dm = await _open_self_dm(client)
        if dm is not None:
            ok, error = await _send_profile_message(dm, message=message, content_type=content_type)
            if ok:
                self_sent = True
                self_sent_at = now_stamp
            elif error:
                errors.append(f"self-dm: {error}")

    target_peer = _coerce_nonempty_string(getattr(target_conversation, "peer_inbox_id", None))
    if target_conversation is not None and target_peer:
        peer_key = target_peer.lower()
        if peer_key not in peer_sent:
            ok, error = await _send_profile_message(target_conversation, message=message, content_type=content_type)
            if ok:
                peer_sent[peer_key] = now_stamp
                peer_sent_count += 1
            elif error:
                errors.append(f"peer:{peer_key}: {error}")

    if include_known_dm_peers:
        for dm in await _list_dm_conversations(client):
            peer = _coerce_nonempty_string(getattr(dm, "peer_inbox_id", None))
            if not peer:
                continue
            peer_key = peer.lower()
            if peer_key in peer_sent:
                continue
            ok, error = await _send_profile_message(dm, message=message, content_type=content_type)
            if ok:
                peer_sent[peer_key] = now_stamp
                peer_sent_count += 1
            elif error:
                errors.append(f"peer:{peer_key}: {error}")

    _write_profile_broadcast_state(
        state_path,
        payload_sha256=payload_sha256,
        self_sent_at=self_sent_at,
        peer_sent=peer_sent,
    )
    return XmtpProfileBroadcastResult(
        payload_sha256=payload_sha256,
        self_sent=self_sent,
        peer_sent_count=peer_sent_count,
        errors=tuple(errors[:8]),
    )


async def _apply_profile_metadata(
    targets: list[object],
    name: str,
    avatar_values: tuple[str, ...],
    *,
    apply_name: bool,
    apply_avatar: bool,
) -> tuple[bool, bool, bool, tuple[str, ...]]:
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

    if apply_name or (apply_avatar and avatar_values):
        for target in targets:
            target_name = target.__class__.__name__
            for method_name in combined_methods:
                method = getattr(target, method_name, None)
                if not callable(method):
                    continue
                profile_api_found = True
                success = False
                avatar_success = False
                if apply_avatar and avatar_values:
                    avatar_variants: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
                    for avatar in avatar_values:
                        avatar_variants.extend(
                            [
                                ((), {"name": name, "avatar_url": avatar}),
                                ((), {"display_name": name, "avatar_url": avatar}),
                                ((), {"name": name, "avatar": avatar}),
                                ((), {"display_name": name, "avatar": avatar}),
                                (({"name": name, "avatar_url": avatar},), {}),
                                (({"display_name": name, "avatar_url": avatar},), {}),
                            ]
                        )
                    success, call_errors = await _invoke_method_variants(method, avatar_variants)
                    for item in call_errors:
                        entry = f"{target_name}.{method_name}: {item}"
                        if entry not in errors:
                            errors.append(entry)
                    if success:
                        avatar_success = True
                if not success and apply_name:
                    success, call_errors = await _invoke_method_variants(
                        method,
                        [
                            ((), {"name": name}),
                            ((), {"display_name": name}),
                            (({"name": name},), {}),
                            (({"display_name": name},), {}),
                        ],
                    )
                    for item in call_errors:
                        entry = f"{target_name}.{method_name}: {item}"
                        if entry not in errors:
                            errors.append(entry)
                if success:
                    if apply_name:
                        applied_name = True
                    if avatar_success:
                        applied_avatar = True
                    break
            name_done = (not apply_name) or applied_name
            avatar_done = (not apply_avatar) or (not avatar_values) or applied_avatar
            if name_done and avatar_done:
                break

    if apply_name and not applied_name:
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

    if apply_avatar and avatar_values and not applied_avatar:
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
    profile_read_api_found: bool,
    profile_api_found: bool,
    applied_name: bool,
    applied_avatar: bool,
    observed_name: str | None,
    observed_avatar: str | None,
    name_in_sync: bool,
    avatar_in_sync: bool,
    fallback_self_sent: bool,
    fallback_peer_sent_count: int,
    errors: tuple[str, ...],
) -> None:
    payload = {
        "version": XMTP_PROFILE_STATE_VERSION,
        "updated_at": datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat(),
        "name": name,
        "avatar_path": str(avatar_path) if avatar_path is not None else "",
        "avatar_sha256": avatar_sha256,
        "profile_read_api_found": profile_read_api_found,
        "profile_api_found": profile_api_found,
        "applied_name": applied_name,
        "applied_avatar": applied_avatar,
        "observed_name": observed_name or "",
        "observed_avatar": observed_avatar or "",
        "name_in_sync": name_in_sync,
        "avatar_in_sync": avatar_in_sync,
        "fallback_self_sent": fallback_self_sent,
        "fallback_peer_sent_count": fallback_peer_sent_count,
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
    avatar_values: tuple[str, ...] = ()
    if generate_avatar:
        avatar_path, avatar_data_uri, avatar_sha256 = ensure_profile_avatar(state_dir, name)
        avatar_values = _avatar_candidates(avatar_path, avatar_data_uri)

    targets = _profile_targets(client)
    profile_read_api_found, observed_name, observed_avatar, read_errors = await _read_profile_metadata(targets)
    name_verified = _name_matches(observed_name, name)
    avatar_verified = (not avatar_values) or _avatar_matches(observed_avatar, avatar_values)
    needs_name_update = not name_verified
    needs_avatar_update = bool(avatar_values) and not avatar_verified

    profile_api_found = False
    applied_name = False
    applied_avatar = False
    apply_errors: tuple[str, ...] = ()
    if needs_name_update or needs_avatar_update:
        profile_api_found, applied_name, applied_avatar, apply_errors = await _apply_profile_metadata(
            targets,
            name,
            avatar_values,
            apply_name=needs_name_update,
            apply_avatar=needs_avatar_update,
        )
    name_in_sync = name_verified or applied_name
    avatar_in_sync = (not avatar_values) or avatar_verified or applied_avatar
    fallback_result = await publish_profile_message(
        client,
        state_dir=state_dir,
        identity_name=name,
        avatar_url=avatar_data_uri,
        include_self_dm=True,
        include_known_dm_peers=True,
    )
    errors = tuple(list(read_errors) + list(apply_errors) + list(fallback_result.errors))[:8]

    state_path = state_dir / XMTP_PROFILE_STATE_FILE
    _write_profile_state(
        state_path,
        name=name,
        avatar_path=avatar_path,
        avatar_sha256=avatar_sha256,
        profile_read_api_found=profile_read_api_found,
        profile_api_found=profile_api_found,
        applied_name=applied_name,
        applied_avatar=applied_avatar,
        observed_name=observed_name,
        observed_avatar=observed_avatar,
        name_in_sync=name_in_sync,
        avatar_in_sync=avatar_in_sync,
        fallback_self_sent=fallback_result.self_sent,
        fallback_peer_sent_count=fallback_result.peer_sent_count,
        errors=errors,
    )
    return XmtpProfileSyncResult(
        name=name,
        state_path=state_path,
        avatar_path=avatar_path,
        profile_read_api_found=profile_read_api_found,
        profile_api_found=profile_api_found,
        applied_name=applied_name,
        applied_avatar=applied_avatar,
        observed_name=observed_name,
        observed_avatar=observed_avatar,
        name_in_sync=name_in_sync,
        avatar_in_sync=avatar_in_sync,
        fallback_self_sent=fallback_result.self_sent,
        fallback_peer_sent_count=fallback_result.peer_sent_count,
        errors=errors,
    )


async def ensure_profile_message_for_conversation(
    client: object,
    conversation: object,
    *,
    state_dir: Path,
    identity_name: str,
    avatar_url: str = "",
) -> XmtpProfileBroadcastResult:
    return await publish_profile_message(
        client,
        state_dir=state_dir,
        identity_name=identity_name,
        avatar_url=avatar_url,
        include_self_dm=False,
        include_known_dm_peers=False,
        target_conversation=conversation,
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
