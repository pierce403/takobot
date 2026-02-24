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
import zlib


XMTP_PROFILE_STATE_VERSION = 2
XMTP_PROFILE_STATE_FILE = "xmtp-profile.json"
XMTP_PROFILE_AVATAR_FILE = "xmtp-avatar.svg"
XMTP_PROFILE_NAME_MAX_CHARS = 40
XMTP_PROFILE_BROADCAST_STATE_VERSION = 1
XMTP_PROFILE_BROADCAST_STATE_FILE = "xmtp-profile-broadcast.json"
XMTP_PROFILE_TEXT_FALLBACK_PREFIX = "cv:profile:"
_LEGACY_XMTP_PROFILE_MESSAGE_PREFIX = "tako:profile:"
CONVERGE_PROFILE_CONTENT_TYPE: dict[str, Any] = {
    "authorityId": "converge.cv",
    "typeId": "profile",
    "versionMajor": 1,
    "versionMinor": 0,
}

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

_CONVOS_PROTO_CACHE: tuple[Any, Any] | None = None
_CONVOS_PROTO_UNAVAILABLE = False


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


def _build_profile_payload(
    name: str,
    avatar_url: str,
    *,
    include_timestamp: bool = True,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "type": "profile",
        "v": 1,
        "displayName": canonical_profile_name(name),
    }
    trimmed_avatar = _trim_profile_avatar_url(avatar_url)
    if trimmed_avatar:
        payload["avatarUrl"] = trimmed_avatar
    if include_timestamp:
        payload["ts"] = int(datetime.now(tz=timezone.utc).timestamp() * 1000)
    return payload


def _encode_profile_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)


def _payload_sha256(name: str, avatar_url: str) -> str:
    payload = _build_profile_payload(name, avatar_url, include_timestamp=False)
    return hashlib.sha256(_encode_profile_payload(payload).encode("utf-8")).hexdigest()


def _is_profile_payload(payload: dict[str, Any]) -> bool:
    payload_type = str(payload.get("type") or "").strip().lower()
    if payload_type not in {"profile", "tako_profile", "takobot_profile"}:
        return False
    version = payload.get("v")
    if isinstance(version, str) and version.strip():
        if version.strip() not in {"1", "1.0"}:
            return False
    if isinstance(version, (int, float)) and int(version) != 1:
        return False
    for key in ("displayName", "display_name", "name", "avatarUrl", "avatar_url", "avatar"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return True
    return False


def _parse_profile_payload(text: str) -> tuple[dict[str, Any] | None, str]:
    stripped = text.strip()
    if not stripped:
        return None, stripped

    raw_json = ""
    if stripped.startswith(XMTP_PROFILE_TEXT_FALLBACK_PREFIX):
        raw_json = stripped[len(XMTP_PROFILE_TEXT_FALLBACK_PREFIX) :].strip()
    elif stripped.startswith(_LEGACY_XMTP_PROFILE_MESSAGE_PREFIX):
        raw_json = stripped[len(_LEGACY_XMTP_PROFILE_MESSAGE_PREFIX) :].strip()
    else:
        return None, stripped

    try:
        payload = json.loads(raw_json)
    except Exception:
        return None, stripped
    if not isinstance(payload, dict):
        return None, stripped
    if _is_profile_payload(payload):
        return payload, stripped
    return None, stripped


def parse_profile_message(text: str) -> XmtpProfileMessage | None:
    if not isinstance(text, str):
        return None
    payload, stripped = _parse_profile_payload(text)
    if payload is None:
        return None
    raw_name = payload.get("displayName")
    if not isinstance(raw_name, str):
        raw_name = payload.get("display_name")
    if not isinstance(raw_name, str):
        raw_name = payload.get("name")
    parsed_name = canonical_profile_name(raw_name) if isinstance(raw_name, str) and raw_name.strip() else None
    raw_avatar = payload.get("avatarUrl")
    if not isinstance(raw_avatar, str):
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


def _inbox_id_to_bytes(inbox_id: str) -> bytes:
    value = (inbox_id or "").strip()
    if not value:
        return b""
    if value.startswith(("0x", "0X")):
        value = value[2:]
    if value and len(value) % 2 == 0:
        with contextlib.suppress(Exception):
            return bytes.fromhex(value)
    return value.encode("utf-8")


def _client_inbox_id_bytes(client: object) -> bytes:
    for attr in ("inbox_id_bytes", "inboxIdBytes"):
        candidate = getattr(client, attr, None)
        if isinstance(candidate, (bytes, bytearray)):
            return bytes(candidate)
        if isinstance(candidate, str):
            converted = _inbox_id_to_bytes(candidate)
            if converted:
                return converted
    inbox_id = _coerce_nonempty_string(getattr(client, "inbox_id", None))
    if inbox_id is None:
        inbox_id = _coerce_nonempty_string(getattr(client, "inboxId", None))
    if inbox_id is None:
        return b""
    return _inbox_id_to_bytes(inbox_id)


def _conversation_peer_inbox_id(conversation: object) -> str | None:
    for target in _conversation_targets(conversation, include_ffi=True):
        for attr in ("peer_inbox_id", "peerInboxId", "dm_peer_inbox_id", "dmPeerInboxId"):
            member = getattr(target, attr, None)
            if member is None:
                continue
            try:
                value = member() if callable(member) else member
            except Exception:
                continue
            peer = _coerce_nonempty_string(value)
            if peer:
                return peer
    return None


def _conversation_state_key(conversation: object) -> str:
    peer = _conversation_peer_inbox_id(conversation)
    if peer:
        return f"peer:{peer.lower()}"

    for attr in ("conversation_id", "group_id", "id"):
        value = getattr(conversation, attr, None)
        if isinstance(value, (bytes, bytearray)):
            return f"conversation:{bytes(value).hex()}"
        if isinstance(value, str):
            text = value.strip().lower()
            if text:
                return f"conversation:{text}"
    return ""


def _conversation_targets(conversation: object, *, include_ffi: bool = False) -> list[object]:
    targets: list[object] = []
    seen: set[int] = set()
    ffi_target = getattr(conversation, "_ffi", None) if include_ffi else None
    for candidate in (
        conversation,
        ffi_target,
        getattr(conversation, "group", None),
        getattr(conversation, "_group", None),
    ):
        if candidate is None:
            continue
        ident = id(candidate)
        if ident in seen:
            continue
        seen.add(ident)
        targets.append(candidate)
    return targets


def _conversation_supports_app_data(conversation: object) -> bool:
    for target in _conversation_targets(conversation, include_ffi=True):
        for attr in ("app_data", "appData", "get_app_data", "getAppData", "update_app_data", "updateAppData"):
            if getattr(target, attr, None) is not None:
                return True
    return False


def _conversation_kind(conversation: object) -> str:
    peer = _conversation_peer_inbox_id(conversation)
    if peer:
        return "dm"
    if _conversation_supports_app_data(conversation):
        return "group"
    return "unknown"


def _client_inbox_id(client: object) -> str:
    inbox = _coerce_nonempty_string(getattr(client, "inbox_id", None))
    if inbox:
        return inbox
    inbox = _coerce_nonempty_string(getattr(client, "inboxId", None))
    return inbox or ""


async def _list_group_conversations(client: object) -> list[object]:
    conversations = getattr(client, "conversations", None)
    if conversations is None:
        return []

    for attr in ("list_groups", "listGroups", "list_group_conversations"):
        list_groups = getattr(conversations, attr, None)
        if not callable(list_groups):
            continue
        try:
            result = list_groups()
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            continue
        if isinstance(result, list):
            return [item for item in result if _conversation_supports_app_data(item)]
    return []


async def _list_dm_conversations(client: object) -> list[object]:
    conversations = getattr(client, "conversations", None)
    if conversations is None:
        return []

    for attr in ("list_dms", "listDms", "list_dm_conversations"):
        list_dms = getattr(conversations, attr, None)
        if not callable(list_dms):
            continue
        try:
            result = list_dms()
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            continue
        if isinstance(result, list):
            return [item for item in result if _conversation_kind(item) == "dm"]

    for attr in ("list", "list_conversations", "listConversations"):
        list_all = getattr(conversations, attr, None)
        if not callable(list_all):
            continue
        try:
            result = list_all()
            if inspect.isawaitable(result):
                result = await result
        except Exception:
            continue
        if isinstance(result, list):
            return [item for item in result if _conversation_kind(item) == "dm"]
    return []


async def _get_or_create_dm_conversation(client: object, inbox_id: str) -> tuple[object | None, str | None]:
    conversations = getattr(client, "conversations", None)
    if conversations is None:
        return None, "client conversations API unavailable"
    target_inbox = " ".join((inbox_id or "").split()).strip()
    if not target_inbox:
        return None, "missing inbox id for DM lookup"

    lookup_errors: list[str] = []
    for attr in ("get_dm_by_inbox_id", "getDmByInboxId", "get_dm", "getDm"):
        method = getattr(conversations, attr, None)
        if not callable(method):
            continue
        try:
            result = method(target_inbox)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001
            lookup_errors.append(f"{attr}: {exc.__class__.__name__}: {exc}")
            continue
        if result is not None:
            return result, None

    create_errors: list[str] = []
    for attr in ("create_dm", "createDm", "new_dm", "newDm"):
        method = getattr(conversations, attr, None)
        if not callable(method):
            continue
        try:
            result = method(target_inbox)
            if inspect.isawaitable(result):
                result = await result
        except Exception as exc:  # noqa: BLE001
            create_errors.append(f"{attr}: {exc.__class__.__name__}: {exc}")
            continue
        if result is not None:
            return result, None

    all_errors = tuple(lookup_errors + create_errors)
    if all_errors:
        return None, all_errors[0]
    return None, "DM lookup/create API unavailable"


async def _read_group_app_data(conversation: object) -> tuple[str | None, str | None]:
    found = False
    for target in _conversation_targets(conversation, include_ffi=True):
        for attr in ("app_data", "appData", "get_app_data", "getAppData"):
            member = getattr(target, attr, None)
            if member is None:
                continue
            found = True
            try:
                value = member() if callable(member) else member
                if inspect.isawaitable(value):
                    value = await value
            except Exception as exc:  # noqa: BLE001
                return None, f"read appData failed via {target.__class__.__name__}.{attr}: {exc.__class__.__name__}: {exc}"
            if isinstance(value, bytes):
                value = value.decode("utf-8", errors="ignore")
            if value is None:
                return "", None
            if isinstance(value, str):
                return value, None
    if found:
        return "", None
    return None, "group appData read API unavailable"


async def _update_group_app_data(conversation: object, encoded: str) -> tuple[bool, str | None]:
    errors: list[str] = []
    for target in _conversation_targets(conversation, include_ffi=True):
        for attr in ("update_app_data", "updateAppData", "set_app_data", "setAppData"):
            method = getattr(target, attr, None)
            if not callable(method):
                continue
            for args, kwargs in (
                ((encoded,), {}),
                ((), {"app_data": encoded}),
                ((), {"appData": encoded}),
                ((), {"value": encoded}),
            ):
                try:
                    result = method(*args, **kwargs)
                    if inspect.isawaitable(result):
                        await result
                    return True, None
                except TypeError:
                    continue
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{target.__class__.__name__}.{attr}: {exc.__class__.__name__}: {exc}")
                    break
    if errors:
        return False, errors[0]
    return False, "group appData update API unavailable"


def _base64url_decode(value: str) -> bytes:
    padded = value + ("=" * (-len(value) % 4))
    return base64.urlsafe_b64decode(padded.encode("ascii"))


def _base64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")


def _decode_convos_app_data(encoded: str) -> tuple[bytes, str | None]:
    text = (encoded or "").strip()
    if not text:
        return b"", None
    try:
        raw = _base64url_decode(text)
    except Exception as exc:  # noqa: BLE001
        return b"", f"base64url decode failed: {exc.__class__.__name__}: {exc}"
    if not raw:
        return b"", None
    if raw[0] != 0x1F:
        return raw, None
    if len(raw) < 5:
        return b"", "convos marker present but payload is too short"
    expected_size = int.from_bytes(raw[1:5], byteorder="big", signed=False)
    try:
        decompressed = zlib.decompress(raw[5:])
    except Exception as exc:  # noqa: BLE001
        return b"", f"convos zlib decompress failed: {exc.__class__.__name__}: {exc}"
    if expected_size > 0 and expected_size != len(decompressed):
        return b"", f"convos decompressed size mismatch: expected={expected_size} got={len(decompressed)}"
    return decompressed, None


def _encode_convos_app_data(payload: bytes) -> str:
    if not payload:
        return ""
    compressed = zlib.compress(payload)
    marker_payload = bytes([0x1F]) + len(payload).to_bytes(4, byteorder="big", signed=False) + compressed
    encoded_source = marker_payload if len(marker_payload) < len(payload) else payload
    return _base64url_encode(encoded_source)


def _convos_proto_classes() -> tuple[Any, Any] | None:
    global _CONVOS_PROTO_CACHE, _CONVOS_PROTO_UNAVAILABLE
    if _CONVOS_PROTO_CACHE is not None:
        return _CONVOS_PROTO_CACHE
    if _CONVOS_PROTO_UNAVAILABLE:
        return None
    try:
        from google.protobuf import descriptor_pb2, descriptor_pool, message_factory
    except Exception:
        _CONVOS_PROTO_UNAVAILABLE = True
        return None

    try:
        file_proto = descriptor_pb2.FileDescriptorProto()
        file_proto.name = "converge_cv_profile_metadata.proto"
        file_proto.package = "converge.cv"
        file_proto.syntax = "proto3"

        profile = file_proto.message_type.add()
        profile.name = "ConversationProfile"

        field = profile.field.add()
        field.name = "inboxId"
        field.number = 1
        field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
        field.type = descriptor_pb2.FieldDescriptorProto.TYPE_BYTES

        field = profile.field.add()
        field.name = "name"
        field.number = 2
        field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
        field.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING

        field = profile.field.add()
        field.name = "image"
        field.number = 3
        field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
        field.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING

        field = profile.field.add()
        field.name = "encryptedImage"
        field.number = 4
        field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
        field.type = descriptor_pb2.FieldDescriptorProto.TYPE_BYTES

        metadata = file_proto.message_type.add()
        metadata.name = "ConversationCustomMetadata"

        field = metadata.field.add()
        field.name = "tag"
        field.number = 1
        field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
        field.type = descriptor_pb2.FieldDescriptorProto.TYPE_STRING

        field = metadata.field.add()
        field.name = "profiles"
        field.number = 2
        field.label = descriptor_pb2.FieldDescriptorProto.LABEL_REPEATED
        field.type = descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE
        field.type_name = ".converge.cv.ConversationProfile"

        field = metadata.field.add()
        field.name = "expiresAtUnix"
        field.number = 3
        field.label = descriptor_pb2.FieldDescriptorProto.LABEL_OPTIONAL
        field.type = descriptor_pb2.FieldDescriptorProto.TYPE_SFIXED64

        pool = descriptor_pool.DescriptorPool()
        pool.Add(file_proto)
        metadata_descriptor = pool.FindMessageTypeByName("converge.cv.ConversationCustomMetadata")
        profile_descriptor = pool.FindMessageTypeByName("converge.cv.ConversationProfile")

        get_message_class = getattr(message_factory, "GetMessageClass", None)
        if callable(get_message_class):
            metadata_cls = get_message_class(metadata_descriptor)
            profile_cls = get_message_class(profile_descriptor)
        else:
            factory = message_factory.MessageFactory(pool)
            metadata_cls = factory.GetPrototype(metadata_descriptor)
            profile_cls = factory.GetPrototype(profile_descriptor)
    except Exception:
        _CONVOS_PROTO_UNAVAILABLE = True
        return None

    _CONVOS_PROTO_CACHE = (metadata_cls, profile_cls)
    return _CONVOS_PROTO_CACHE


def _convos_profile_name(name: str) -> str:
    trimmed = " ".join((name or "").split()).strip()
    if not trimmed:
        return "Tako"
    return trimmed[:50].strip() or "Tako"


def _upsert_profile_metadata_blob(
    metadata_blob: bytes,
    *,
    inbox_id: bytes,
    display_name: str,
    avatar_url: str,
) -> tuple[bytes | None, str | None]:
    classes = _convos_proto_classes()
    if classes is None:
        return None, "protobuf runtime unavailable for Convos metadata"
    metadata_cls, _profile_cls = classes

    metadata = metadata_cls()
    if metadata_blob:
        try:
            metadata.ParseFromString(metadata_blob)
        except Exception as exc:  # noqa: BLE001
            return None, f"ConversationCustomMetadata parse failed: {exc.__class__.__name__}: {exc}"

    profile = None
    for item in getattr(metadata, "profiles", []):
        if bytes(getattr(item, "inboxId", b"")) == inbox_id:
            profile = item
            break
    if profile is None:
        profile = metadata.profiles.add()

    profile.inboxId = inbox_id
    profile.name = _convos_profile_name(display_name)

    trimmed_avatar = _trim_profile_avatar_url(avatar_url)
    if trimmed_avatar:
        profile.image = trimmed_avatar
        with contextlib.suppress(Exception):
            profile.ClearField("encryptedImage")

    try:
        return metadata.SerializeToString(), None
    except Exception as exc:  # noqa: BLE001
        return None, f"ConversationCustomMetadata serialize failed: {exc.__class__.__name__}: {exc}"


async def _upsert_profile_metadata_for_conversation(
    conversation: object,
    *,
    inbox_id: bytes,
    display_name: str,
    avatar_url: str,
) -> tuple[bool, str | None]:
    encoded_app_data, read_error = await _read_group_app_data(conversation)
    if read_error:
        return False, read_error
    raw_blob, decode_error = _decode_convos_app_data(encoded_app_data or "")
    if decode_error:
        return False, decode_error
    updated_blob, upsert_error = _upsert_profile_metadata_blob(
        raw_blob,
        inbox_id=inbox_id,
        display_name=display_name,
        avatar_url=avatar_url,
    )
    if updated_blob is None:
        return False, upsert_error
    updated_encoded = _encode_convos_app_data(updated_blob)
    if (encoded_app_data or "").strip() == updated_encoded:
        return True, None
    return await _update_group_app_data(conversation, updated_encoded)


def _build_converge_dm_profile_message(name: str, avatar_url: str) -> dict[str, Any]:
    payload = _build_profile_payload(name, avatar_url, include_timestamp=True)
    return {
        "type": dict(CONVERGE_PROFILE_CONTENT_TYPE),
        "parameters": {},
        "content": _encode_profile_payload(payload).encode("utf-8"),
    }


def _converge_profile_content_type_string() -> str:
    return (
        f"{CONVERGE_PROFILE_CONTENT_TYPE['authorityId']}/"
        f"{CONVERGE_PROFILE_CONTENT_TYPE['typeId']}:"
        f"{int(CONVERGE_PROFILE_CONTENT_TYPE['versionMajor'])}."
        f"{int(CONVERGE_PROFILE_CONTENT_TYPE['versionMinor'])}"
    )


def _converge_profile_content_type_variants() -> tuple[Any, ...]:
    variants: list[Any] = [
        dict(CONVERGE_PROFILE_CONTENT_TYPE),
        _converge_profile_content_type_string(),
    ]
    with contextlib.suppress(Exception):
        from xmtp_content_type_primitives import ContentTypeId

        variants.insert(
            0,
            ContentTypeId(
                authority_id=str(CONVERGE_PROFILE_CONTENT_TYPE["authorityId"]),
                type_id=str(CONVERGE_PROFILE_CONTENT_TYPE["typeId"]),
                version_major=int(CONVERGE_PROFILE_CONTENT_TYPE["versionMajor"]),
                version_minor=int(CONVERGE_PROFILE_CONTENT_TYPE["versionMinor"]),
            ),
        )
    deduped: list[Any] = []
    seen: set[tuple[str, str]] = set()
    for value in variants:
        key = (value.__class__.__name__, str(value))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(value)
    return tuple(deduped)


def _encode_converge_profile_ffi_content(payload: bytes) -> tuple[bytes | None, str | None]:
    try:
        from xmtp_bindings import xmtpv3 as bindings
    except Exception as exc:  # noqa: BLE001
        return None, f"xmtp bindings unavailable for custom content encode: {exc.__class__.__name__}: {exc}"
    converter = getattr(bindings, "_UniffiConverterTypeFfiEncodedContent", None)
    if converter is None or not hasattr(converter, "lower"):
        return None, "xmtp bindings encoded-content converter unavailable"
    try:
        type_id = bindings.FfiContentTypeId(
            authority_id=str(CONVERGE_PROFILE_CONTENT_TYPE["authorityId"]),
            type_id=str(CONVERGE_PROFILE_CONTENT_TYPE["typeId"]),
            version_major=int(CONVERGE_PROFILE_CONTENT_TYPE["versionMajor"]),
            version_minor=int(CONVERGE_PROFILE_CONTENT_TYPE["versionMinor"]),
        )
        encoded = bindings.FfiEncodedContent(
            type_id=type_id,
            parameters={},
            fallback=None,
            compression=None,
            content=payload,
        )
        rust_buf = converter.lower(encoded)
        try:
            size = int(getattr(rust_buf, "len", 0))
            data = getattr(rust_buf, "data", None)
            if data is None:
                return None, "xmtp bindings encoded-content buffer has no data pointer"
            raw = bytes(data[0:size])
        finally:
            free = getattr(rust_buf, "free", None)
            if callable(free):
                with contextlib.suppress(Exception):
                    free()
        if not raw:
            return None, "xmtp bindings encoded-content result is empty"
        return raw, None
    except Exception as exc:  # noqa: BLE001
        return None, f"encode custom content via xmtp bindings failed: {exc.__class__.__name__}: {exc}"


def _build_converge_profile_ffi_send_options(*, should_push: bool) -> tuple[Any | None, str | None]:
    try:
        from xmtp_bindings import xmtpv3 as bindings
    except Exception as exc:  # noqa: BLE001
        return None, f"xmtp bindings unavailable for send options: {exc.__class__.__name__}: {exc}"
    opts_cls = getattr(bindings, "FfiSendMessageOpts", None)
    if opts_cls is None:
        return None, "xmtp bindings send options type unavailable"
    attempts: tuple[tuple[tuple[Any, ...], dict[str, Any]], ...] = (
        ((), {"should_push": should_push}),
        ((), {"shouldPush": should_push}),
        ((should_push,), {}),
    )
    for args, kwargs in attempts:
        try:
            return opts_cls(*args, **kwargs), None
        except TypeError:
            continue
        except Exception as exc:  # noqa: BLE001
            return None, f"build send options failed: {exc.__class__.__name__}: {exc}"
    return None, "unable to build xmtp send options for custom content"


def _conversation_ffi_send_targets(conversation: object) -> list[object]:
    targets: list[object] = []
    seen: set[int] = set()
    for candidate in (getattr(conversation, "_ffi", None), conversation):
        if candidate is None:
            continue
        # Wrapper objects expose send(content, content_type); the low-level FFI target
        # exposes send(encoded_bytes, opts), which is what we need for custom content.
        if getattr(candidate, "_ffi", None) is not None and getattr(candidate, "_client", None) is not None:
            continue
        ident = id(candidate)
        if ident in seen:
            continue
        seen.add(ident)
        targets.append(candidate)
    return targets


async def _send_converge_profile_via_ffi(conversation: object, *, payload: bytes) -> tuple[bool, str | None]:
    encoded_bytes, encode_error = _encode_converge_profile_ffi_content(payload)
    if encoded_bytes is None:
        return False, encode_error
    send_options, options_error = _build_converge_profile_ffi_send_options(should_push=False)
    if send_options is None:
        return False, options_error
    errors: list[str] = []
    for target in _conversation_ffi_send_targets(conversation):
        target_name = target.__class__.__name__
        for method_name in ("send", "send_optimistic", "sendOptimistic"):
            method = getattr(target, method_name, None)
            if not callable(method):
                continue
            variants: list[tuple[tuple[Any, ...], dict[str, Any]]] = [
                ((encoded_bytes, send_options), {}),
                ((encoded_bytes,), {"opts": send_options}),
                ((encoded_bytes,), {"options": send_options}),
            ]
            success, call_errors = await _invoke_method_variants(method, variants)
            if success:
                return True, None
            for item in call_errors:
                entry = f"{target_name}.{method_name}: {item}"
                if entry not in errors:
                    errors.append(entry)
    if errors:
        return False, errors[0]
    return False, "DM custom content low-level send API unavailable"


async def _send_converge_profile_message_to_dm(
    conversation: object,
    *,
    display_name: str,
    avatar_url: str,
) -> tuple[bool, str | None]:
    encoded = _build_converge_dm_profile_message(display_name, avatar_url)
    payload = encoded["content"]
    payload_types = _converge_profile_content_type_variants()
    errors: list[str] = []
    targets = _conversation_targets(conversation)

    for target in targets:
        target_name = target.__class__.__name__
        for method_name in ("send_encoded_content", "sendEncodedContent", "send_content", "sendContent"):
            method = getattr(target, method_name, None)
            if not callable(method):
                continue
            variants: list[tuple[tuple[Any, ...], dict[str, Any]]] = [
                ((encoded,), {"should_push": False}),
                ((encoded,), {"shouldPush": False}),
                ((encoded,), {"options": {"should_push": False}}),
                ((encoded,), {"options": {"shouldPush": False}}),
                ((encoded, {"should_push": False}), {}),
                ((encoded, {"shouldPush": False}), {}),
                ((encoded,), {}),
            ]
            success, call_errors = await _invoke_method_variants(method, variants)
            if success:
                return True, None
            for item in call_errors:
                entry = f"{target_name}.{method_name}: {item}"
                if entry not in errors:
                    errors.append(entry)

        send_method = getattr(target, "send", None)
        if callable(send_method):
            variants: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
            for payload_type in payload_types:
                variants.extend(
                    [
                        ((payload,), {"content_type": payload_type}),
                        ((payload,), {"contentType": payload_type}),
                        ((payload, payload_type), {}),
                        ((payload, payload_type), {"should_push": False}),
                        ((payload, payload_type), {"shouldPush": False}),
                        ((payload, payload_type), {"options": {"should_push": False}}),
                        ((payload, payload_type), {"options": {"shouldPush": False}}),
                        ((payload, payload_type, {"should_push": False}), {}),
                        ((payload, payload_type, {"shouldPush": False}), {}),
                    ]
                )
            success, call_errors = await _invoke_method_variants(send_method, variants)
            if success:
                return True, None
            for item in call_errors:
                entry = f"{target_name}.send: {item}"
                if entry not in errors:
                    errors.append(entry)

    ffi_success, ffi_error = await _send_converge_profile_via_ffi(conversation, payload=payload)
    if ffi_success:
        return True, None
    if ffi_error:
        errors.append(ffi_error)

    if errors:
        return False, errors[0]
    return False, "DM custom content send API unavailable"


async def publish_profile_message(
    client: object,
    *,
    state_dir: Path,
    identity_name: str,
    avatar_url: str = "",
    include_self_dm: bool = True,
    include_known_dm_peers: bool = True,
    include_known_groups: bool = True,
    target_conversation: object | None = None,
) -> XmtpProfileBroadcastResult:
    payload_sha256 = _payload_sha256(identity_name, avatar_url)
    state_path = state_dir / XMTP_PROFILE_BROADCAST_STATE_FILE
    previous_hash, self_sent_at, peer_sent = _read_profile_broadcast_state(state_path)
    if previous_hash != payload_sha256:
        self_sent_at = ""
        peer_sent = {}

    self_sent = False
    peer_sent_count = 0
    errors: list[str] = []
    inbox_id = _client_inbox_id_bytes(client)
    inbox_id_text = _client_inbox_id(client)
    if not inbox_id:
        errors.append("client inbox_id unavailable for Convos appData profile upsert")
    if not inbox_id_text:
        errors.append("client inbox_id unavailable for Converge DM profile metadata")
    now_stamp = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()

    async def publish_for_conversation(conversation: object, *, label: str) -> None:
        nonlocal peer_sent_count
        key = _conversation_state_key(conversation)
        if not key:
            errors.append(f"{label}: missing stable conversation key")
            return
        if key in peer_sent:
            return
        kind = _conversation_kind(conversation)
        if kind == "group":
            if not inbox_id:
                errors.append(f"{label}: missing inbox_id bytes for group appData upsert")
                return
            ok, error = await _upsert_profile_metadata_for_conversation(
                conversation,
                inbox_id=inbox_id,
                display_name=identity_name,
                avatar_url=avatar_url,
            )
        elif kind == "dm":
            ok, error = await _send_converge_profile_message_to_dm(
                conversation,
                display_name=identity_name,
                avatar_url=avatar_url,
            )
        else:
            ok, error = False, "unknown conversation type for profile publish"
        if ok:
            peer_sent[key] = now_stamp
            peer_sent_count += 1
            return
        if error:
            errors.append(f"{label}: {error}")

    if target_conversation is not None:
        await publish_for_conversation(target_conversation, label="target-conversation")

    if include_known_groups:
        for group in await _list_group_conversations(client):
            await publish_for_conversation(group, label="group")

    if include_known_dm_peers:
        for dm in await _list_dm_conversations(client):
            peer_id = _conversation_peer_inbox_id(dm)
            if peer_id and inbox_id_text and peer_id.lower() == inbox_id_text.lower():
                continue
            await publish_for_conversation(dm, label="dm")

    if include_self_dm and not self_sent_at:
        if not inbox_id_text:
            errors.append("self-dm: client inbox_id unavailable")
        else:
            self_dm, dm_error = await _get_or_create_dm_conversation(client, inbox_id_text)
            if self_dm is None:
                if dm_error:
                    errors.append(f"self-dm: {dm_error}")
            else:
                ok, send_error = await _send_converge_profile_message_to_dm(
                    self_dm,
                    display_name=identity_name,
                    avatar_url=avatar_url,
                )
                if ok:
                    self_sent = True
                    self_sent_at = now_stamp
                elif send_error:
                    errors.append(f"self-dm: {send_error}")

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
        include_known_groups=False,
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
