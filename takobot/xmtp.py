from __future__ import annotations

import asyncio
import base64
import contextlib
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import inspect
import json
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
from typing import Any

from .node_runtime import ensure_workspace_node_runtime
from .paths import ensure_runtime_dirs, runtime_paths
from .xmtp_runtime import (
    XMTP_CLI_VERSION,
    XMTP_MIN_NODE_MAJOR,
    ensure_workspace_xmtp_runtime_if_needed,
    probe_xmtp_runtime as _probe_xmtp_runtime,
    workspace_xmtp_cli_path,
    workspace_xmtp_helper_script_path,
)


XMTP_PROFILE_STATE_VERSION = 3
XMTP_PROFILE_STATE_FILE = "xmtp-profile.json"
XMTP_PROFILE_AVATAR_FILE = "xmtp-avatar.svg"
XMTP_PROFILE_NAME_MAX_CHARS = 40
XMTP_PROFILE_BROADCAST_STATE_VERSION = 2
XMTP_PROFILE_BROADCAST_STATE_FILE = "xmtp-profile-broadcast.json"
XMTP_PROFILE_TEXT_FALLBACK_PREFIX = "cv:profile:"
_LEGACY_XMTP_PROFILE_MESSAGE_PREFIX = "tako:profile:"

XMTPCMD_TIMEOUT_S = 75.0
XMTPCMD_SYNC_TIMEOUT_S = 120.0
XMTPCMD_STREAM_TIMEOUT_S = 0.0

_ETH_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")
_INBOX_ID_RE = re.compile(r"^[a-fA-F0-9]{64}$")

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


@dataclass(frozen=True)
class XmtpCliConversation:
    _client: "XmtpCliClient"
    id_hex: str
    type: str
    peer_inbox_id: str

    @property
    def id(self) -> bytes:
        return _hex_or_text_to_bytes(self.id_hex)

    @property
    def conversation_id(self) -> bytes:
        return self.id

    async def send(self, content: object, content_type: object | None = None) -> bytes:
        if content_type is not None:
            raise RuntimeError("custom content send is handled via profile helper in CLI transport")
        if not isinstance(content, str):
            raise RuntimeError("conversation.send expects text content in CLI transport")
        payload = await self._client.run_json(
            ["conversation", "send-text", self.id_hex, content, "--json"],
            timeout_s=XMTPCMD_TIMEOUT_S,
        )
        if not isinstance(payload, dict):
            raise RuntimeError("unexpected send-text payload")
        message_id = str(payload.get("messageId") or "").strip()
        if not message_id:
            raise RuntimeError("send-text succeeded but returned no messageId")
        return _hex_or_text_to_bytes(message_id)


@dataclass(frozen=True)
class XmtpCliMessage:
    id: bytes
    conversation_id: bytes
    sender_inbox_id: str
    content: str | None
    content_type: dict[str, Any] | None
    sent_at: datetime


class XmtpCliMessageStream:
    def __init__(self, client: "XmtpCliClient") -> None:
        self._client = client
        self._proc: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_tail: list[str] = []
        self._stdout_tail: list[str] = []

    def __aiter__(self) -> "XmtpCliMessageStream":
        return self

    async def __anext__(self) -> XmtpCliMessage:
        await self._ensure_started()
        assert self._proc is not None
        assert self._proc.stdout is not None

        while True:
            chunk = await self._proc.stdout.readline()
            if chunk:
                line = chunk.decode("utf-8", errors="replace").strip()
                if line:
                    _tail_append(self._stdout_tail, line)
                payload = _try_parse_json_line(line)
                if not isinstance(payload, dict):
                    continue
                message = _message_from_payload(payload)
                if message is None:
                    continue
                return message

            rc = await self._proc.wait()
            if self._stderr_task is not None:
                with contextlib.suppress(Exception):
                    await self._stderr_task
            if rc == 0:
                raise StopAsyncIteration
            stderr_text = "\n".join(self._stderr_tail[-6:]).strip()
            stdout_text = "\n".join(self._stdout_tail[-6:]).strip()
            detail = stderr_text or stdout_text or f"exit={rc}"
            raise RuntimeError(
                "xmtp stream-all-messages failed: "
                f"{_summarize_error_text(detail)}"
            )

    async def close(self) -> None:
        if self._proc is None:
            return
        proc = self._proc
        self._proc = None
        if proc.returncode is None:
            with contextlib.suppress(Exception):
                proc.terminate()
            with contextlib.suppress(Exception):
                await asyncio.wait_for(proc.wait(), timeout=2.0)
        if proc.returncode is None:
            with contextlib.suppress(Exception):
                proc.kill()
            with contextlib.suppress(Exception):
                await proc.wait()
        if self._stderr_task is not None:
            with contextlib.suppress(Exception):
                await self._stderr_task
        self._stderr_task = None

    async def _ensure_started(self) -> None:
        if self._proc is not None:
            return
        cmd = self._client.command_for(
            [
                "conversations",
                "stream-all-messages",
                "--json",
            ]
        )
        self._proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=self._client.env,
        )
        self._stderr_task = asyncio.create_task(self._drain_stderr())

    async def _drain_stderr(self) -> None:
        if self._proc is None or self._proc.stderr is None:
            return
        while True:
            chunk = await self._proc.stderr.readline()
            if not chunk:
                break
            line = chunk.decode("utf-8", errors="replace").strip()
            if line:
                _tail_append(self._stderr_tail, line)


class XmtpCliConversations:
    def __init__(self, client: "XmtpCliClient") -> None:
        self._client = client

    async def create_dm(self, recipient: str) -> XmtpCliConversation:
        return await self.new_dm(recipient)

    async def new_dm(self, recipient: str) -> XmtpCliConversation:
        target = " ".join((recipient or "").split()).strip()
        if not target:
            raise RuntimeError("missing recipient")
        if _looks_like_inbox_id(target) and not _looks_like_eth_address(target):
            resolved = await self._client.resolve_address_for_inbox_id(target)
            if resolved:
                target = resolved
        payload = await self._client.run_json(
            ["conversations", "create-dm", target, "--json"],
            timeout_s=XMTPCMD_TIMEOUT_S,
        )
        return _conversation_from_payload(self._client, payload)

    async def get_conversation_by_id(self, conversation_id: bytes | str) -> XmtpCliConversation | None:
        cid = _conversation_id_text(conversation_id)
        if not cid:
            return None
        try:
            payload = await self._client.run_json(
                ["conversations", "get", cid, "--json"],
                timeout_s=XMTPCMD_TIMEOUT_S,
            )
        except Exception:
            return None
        return _conversation_from_payload(self._client, payload)

    async def list(self) -> list[XmtpCliConversation]:
        payload = await self._client.run_json(
            ["conversations", "list", "--sync", "--json"],
            timeout_s=XMTPCMD_SYNC_TIMEOUT_S,
        )
        if not isinstance(payload, list):
            return []
        out: list[XmtpCliConversation] = []
        for item in payload:
            with contextlib.suppress(Exception):
                out.append(_conversation_from_payload(self._client, item))
        return out

    async def list_dms(self) -> list[XmtpCliConversation]:
        payload = await self._client.run_json(
            ["conversations", "list", "--sync", "--type", "dm", "--json"],
            timeout_s=XMTPCMD_SYNC_TIMEOUT_S,
        )
        if not isinstance(payload, list):
            return []
        out: list[XmtpCliConversation] = []
        for item in payload:
            with contextlib.suppress(Exception):
                convo = _conversation_from_payload(self._client, item)
                if convo.type == "dm":
                    out.append(convo)
        return out

    async def list_groups(self) -> list[XmtpCliConversation]:
        payload = await self._client.run_json(
            ["conversations", "list", "--sync", "--type", "group", "--json"],
            timeout_s=XMTPCMD_SYNC_TIMEOUT_S,
        )
        if not isinstance(payload, list):
            return []
        out: list[XmtpCliConversation] = []
        for item in payload:
            with contextlib.suppress(Exception):
                convo = _conversation_from_payload(self._client, item)
                if convo.type == "group":
                    out.append(convo)
        return out

    async def sync_all_conversations(self) -> None:
        await self._client.run_json(
            ["conversations", "sync-all", "--json"],
            timeout_s=XMTPCMD_SYNC_TIMEOUT_S,
            json_expected=False,
        )

    async def messages(self, conversation_id: bytes | str, *, limit: int) -> list[XmtpCliMessage]:
        cid = _conversation_id_text(conversation_id)
        if not cid:
            return []
        payload = await self._client.run_json(
            [
                "conversation",
                "messages",
                cid,
                "--json",
                "--limit",
                str(max(1, int(limit))),
                "--direction",
                "ascending",
            ],
            timeout_s=XMTPCMD_SYNC_TIMEOUT_S,
            json_expected=False,
        )
        if not isinstance(payload, list):
            return []
        out: list[XmtpCliMessage] = []
        for item in payload:
            if not isinstance(item, dict):
                continue
            message = _message_from_payload(item)
            if message is not None:
                out.append(message)
        return out

    def stream_all_messages(self) -> XmtpCliMessageStream:
        return XmtpCliMessageStream(self._client)


class XmtpCliClient:
    def __init__(
        self,
        *,
        env_name: str,
        cli_path: Path,
        env_file: Path,
        db_path: Path,
        runtime_env: dict[str, str],
        inbox_id: str,
        address: str,
    ) -> None:
        self.env_name = env_name
        self.cli_path = cli_path
        self.env_file = env_file
        self.db_path = db_path
        self.env = dict(runtime_env)
        self.inbox_id = inbox_id
        self.inboxId = inbox_id
        self.address = address
        self.account_address = address
        self.conversations = XmtpCliConversations(self)

    def command_for(self, args: list[str]) -> list[str]:
        cmd = [str(self.cli_path), *args]
        if "--env-file" not in args:
            cmd.extend(["--env-file", str(self.env_file)])
        if "--db-path" not in args:
            cmd.extend(["--db-path", str(self.db_path)])
        if "--env" not in args:
            cmd.extend(["--env", self.env_name])
        return cmd

    async def run_json(
        self,
        args: list[str],
        *,
        timeout_s: float,
        json_expected: bool = True,
    ) -> Any:
        cmd = self.command_for(args)
        proc = await asyncio.to_thread(_run_process, cmd, self.env, timeout_s)
        if proc.returncode != 0:
            detail = proc.stderr.strip() or proc.stdout.strip() or f"exit={proc.returncode}"
            raise RuntimeError(
                f"xmtp command failed: {_summarize_error_text(detail)}"
            )
        if not json_expected:
            payload = _extract_first_json_value(proc.stdout)
            return payload if payload is not None else {}
        payload = _extract_first_json_value(proc.stdout)
        if payload is None:
            merged = "\n".join(part for part in (proc.stdout.strip(), proc.stderr.strip()) if part)
            raise RuntimeError(
                "xmtp command returned no JSON payload: "
                f"{_summarize_error_text(merged)}"
            )
        return payload

    async def resolve_address_for_inbox_id(self, inbox_id: str) -> str:
        target = " ".join((inbox_id or "").split()).strip().lower()
        if not _looks_like_inbox_id(target):
            return ""
        payload = await self.run_json(
            ["inbox-states", target, "--json"],
            timeout_s=XMTPCMD_TIMEOUT_S,
        )
        if not isinstance(payload, list):
            return ""
        for item in payload:
            if not isinstance(item, dict):
                continue
            recovery = item.get("recoveryIdentifier")
            address = _extract_identifier_address(recovery)
            if address:
                return address
            identifiers = item.get("identifiers")
            if isinstance(identifiers, list):
                for identifier in identifiers:
                    address = _extract_identifier_address(identifier)
                    if address:
                        return address
        return ""

    async def resolve_inbox_id_for_address(self, address: str) -> str:
        dm = await self.conversations.new_dm(address)
        return dm.peer_inbox_id


def default_message() -> str:
    hostname = socket.gethostname()
    return f"hi from {hostname} (tako)"


def hint_for_xmtp_error(error: Exception) -> str | None:
    message = str(error)
    lowered = message.lower()
    if "addressvalidation" in lowered or "invalid address" in lowered:
        return "Tip: XMTP CLI DM creation expects an Ethereum address (`0x...`) for create-dm."
    if "file is not a database" in lowered or "sqlcipher" in lowered:
        return (
            "Tip: the local XMTP database appears corrupted or uses a different "
            "encryption key. Remove `.tako/xmtp-db` to rebuild it from network state."
        )
    if "grpc-status header missing" in lowered or "identityapi" in lowered:
        return (
            "Tip: check outbound HTTPS/HTTP2 access to "
            "grpc.production.xmtp.network:443 and "
            "message-history.production.ephemera.network."
        )
    return None


def probe_xmtp_runtime() -> tuple[bool, str]:
    probe = _probe_xmtp_runtime()
    return probe.ok, probe.status


def probe_xmtp_import() -> tuple[bool, str]:
    # Compatibility shim: runtime health now reflects CLI status, not Python imports.
    return probe_xmtp_runtime()


async def create_client(env: str, db_root: Path, wallet_key: str, db_encryption_key: str) -> XmtpCliClient:
    bootstrap_note = ensure_workspace_xmtp_runtime_if_needed()
    if bootstrap_note.startswith("workspace xmtp bootstrap failed"):
        raise RuntimeError(bootstrap_note)

    node_runtime = ensure_workspace_node_runtime(min_major=XMTP_MIN_NODE_MAJOR, require_npm=False)
    if not node_runtime.ok:
        raise RuntimeError(node_runtime.detail)

    env_file = _write_xmtp_client_env(wallet_key, db_encryption_key)
    db_root.mkdir(parents=True, exist_ok=True)
    db_path = db_root / "xmtp-production.db3"

    probe_client = XmtpCliClient(
        env_name=(env or "production").strip() or "production",
        cli_path=workspace_xmtp_cli_path(),
        env_file=env_file,
        db_path=db_path,
        runtime_env=node_runtime.env,
        inbox_id="",
        address="",
    )
    payload = await probe_client.run_json(
        ["client", "info", "--json"],
        timeout_s=XMTPCMD_TIMEOUT_S,
        json_expected=False,
    )
    info = payload.get("properties") if isinstance(payload, dict) else None
    if not isinstance(info, dict):
        raise RuntimeError("xmtp client info returned unexpected payload")
    inbox_id = str(info.get("inboxId") or "").strip()
    address = str(info.get("address") or "").strip().lower()
    if not inbox_id:
        raise RuntimeError("xmtp client info did not return inboxId")
    if not _looks_like_eth_address(address):
        raise RuntimeError("xmtp client info did not return a valid wallet address")

    return XmtpCliClient(
        env_name=(env or "production").strip() or "production",
        cli_path=workspace_xmtp_cli_path(),
        env_file=env_file,
        db_path=db_path,
        runtime_env=node_runtime.env,
        inbox_id=inbox_id,
        address=address,
    )


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


def _conversation_state_key(conversation: object) -> str:
    peer = " ".join((str(getattr(conversation, "peer_inbox_id", "") or "")).split()).strip().lower()
    if peer:
        return f"peer:{peer}"
    cid = _conversation_id_hex(conversation)
    if cid:
        return f"conversation:{cid}"
    return ""


def _conversation_id_hex(conversation: object) -> str:
    id_hex = getattr(conversation, "id_hex", None)
    if isinstance(id_hex, str) and id_hex.strip():
        return id_hex.strip().lower()
    for attr in ("id", "conversation_id"):
        raw = getattr(conversation, attr, None)
        if isinstance(raw, (bytes, bytearray)):
            value = bytes(raw).hex()
            if value:
                return value.lower()
        if isinstance(raw, str) and raw.strip():
            return raw.strip().lower()
    return ""


def _conversation_kind(conversation: object) -> str:
    kind = str(getattr(conversation, "type", "") or "").strip().lower()
    if kind in {"dm", "group"}:
        return kind
    peer = " ".join((str(getattr(conversation, "peer_inbox_id", "") or "")).split()).strip().lower()
    if peer:
        return "dm"
    if any(
        hasattr(conversation, attr)
        for attr in ("update_app_data", "updateAppData", "app_data", "appData")
    ):
        return "group"
    return "dm"


async def publish_profile_message(
    client: XmtpCliClient,
    *,
    state_dir: Path,
    identity_name: str,
    avatar_url: str = "",
    include_self_dm: bool = True,
    include_known_dm_peers: bool = True,
    include_known_groups: bool = True,
    target_conversation: XmtpCliConversation | None = None,
) -> XmtpProfileBroadcastResult:
    payload_sha256 = _payload_sha256(identity_name, avatar_url)
    state_path = state_dir / XMTP_PROFILE_BROADCAST_STATE_FILE
    previous_hash, self_sent_at, peer_sent = _read_profile_broadcast_state(state_path)
    if previous_hash != payload_sha256:
        self_sent_at = ""
        peer_sent = {}

    errors: list[str] = []
    state_key_by_conversation_id: dict[str, str] = {}

    dm_ids: list[str] = []
    group_ids: list[str] = []

    async def queue_conversation(conversation: object, *, label: str) -> None:
        key = _conversation_state_key(conversation)
        if not key:
            errors.append(f"{label}: missing stable conversation key")
            return
        if key in peer_sent:
            return
        cid = _conversation_id_hex(conversation)
        if not cid:
            errors.append(f"{label}: conversation id is missing")
            return
        state_key_by_conversation_id[cid] = key
        if _conversation_kind(conversation) == "group":
            group_ids.append(cid)
            return
        dm_ids.append(cid)

    if target_conversation is not None:
        await queue_conversation(target_conversation, label="target-conversation")

    if include_known_groups:
        for group in await client.conversations.list_groups():
            await queue_conversation(group, label="group")

    if include_known_dm_peers:
        for dm in await client.conversations.list_dms():
            peer = dm.peer_inbox_id.strip().lower()
            if peer and peer == client.inbox_id.lower():
                continue
            await queue_conversation(dm, label="dm")

    helper_target_id = _conversation_id_hex(target_conversation) if target_conversation is not None else ""
    helper = await _run_profile_helper(
        client,
        mode="publish",
        display_name=identity_name,
        avatar_url=avatar_url,
        target_conversation_id=helper_target_id,
        include_self_dm=include_self_dm and not bool(self_sent_at),
        dm_conversation_ids=dm_ids,
        group_conversation_ids=group_ids,
    )

    helper_errors = helper.get("errors")
    if isinstance(helper_errors, list):
        for item in helper_errors:
            if isinstance(item, str) and item.strip():
                errors.append(item.strip())

    self_sent = bool(helper.get("fallbackSelfSent"))
    sent_ids_raw = helper.get("sentConversationIds")
    sent_ids: set[str] = set()
    if isinstance(sent_ids_raw, list):
        for item in sent_ids_raw:
            if isinstance(item, str) and item.strip():
                sent_ids.add(item.strip().lower())

    now_stamp = datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()
    peer_sent_count = 0
    for cid in sorted(sent_ids):
        key = state_key_by_conversation_id.get(cid)
        if not key:
            continue
        peer_sent[key] = now_stamp
        peer_sent_count += 1

    if self_sent:
        self_sent_at = now_stamp

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
    client: XmtpCliClient,
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

    fallback_result = await publish_profile_message(
        client,
        state_dir=state_dir,
        identity_name=name,
        avatar_url=avatar_data_uri,
        include_self_dm=True,
        include_known_dm_peers=True,
        include_known_groups=True,
    )

    applied_name = fallback_result.self_sent or fallback_result.peer_sent_count > 0
    applied_avatar = bool(avatar_data_uri) and applied_name
    name_in_sync = applied_name or not bool(fallback_result.errors)
    avatar_in_sync = (not avatar_data_uri) or applied_avatar or not bool(fallback_result.errors)
    observed_name = name if name_in_sync else None
    observed_avatar = avatar_data_uri if avatar_in_sync and avatar_data_uri else None

    errors = tuple(fallback_result.errors)[:8]
    state_path = state_dir / XMTP_PROFILE_STATE_FILE
    _write_profile_state(
        state_path,
        name=name,
        avatar_path=avatar_path,
        avatar_sha256=avatar_sha256,
        profile_read_api_found=True,
        profile_api_found=True,
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
        profile_read_api_found=True,
        profile_api_found=True,
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
    client: XmtpCliClient,
    conversation: XmtpCliConversation,
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
    return False


async def close_client(client: object) -> None:
    close_fn = getattr(client, "close", None)
    if not callable(close_fn):
        return
    with contextlib.suppress(Exception):
        maybe_result = close_fn()
        if inspect.isawaitable(maybe_result):
            await maybe_result


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


def _conversation_from_payload(client: XmtpCliClient, payload: Any) -> XmtpCliConversation:
    if not isinstance(payload, dict):
        raise RuntimeError("conversation payload must be an object")
    cid = str(payload.get("id") or "").strip().lower()
    if not cid:
        raise RuntimeError("conversation payload missing id")
    kind = str(payload.get("type") or "").strip().lower()
    if kind not in {"dm", "group"}:
        kind = "dm" if isinstance(payload.get("peerInboxId"), str) else "group"
    peer = str(payload.get("peerInboxId") or "").strip().lower()
    return XmtpCliConversation(
        _client=client,
        id_hex=cid,
        type=kind,
        peer_inbox_id=peer,
    )


def _message_from_payload(payload: dict[str, Any]) -> XmtpCliMessage | None:
    message_id = str(payload.get("id") or "").strip()
    conversation_id = str(payload.get("conversationId") or payload.get("conversation_id") or "").strip()
    sender = str(payload.get("senderInboxId") or payload.get("sender_inbox_id") or "").strip().lower()
    if not message_id or not conversation_id or not sender:
        return None
    content = payload.get("content")
    if not isinstance(content, str):
        content = None
    content_type = payload.get("contentType")
    if not isinstance(content_type, dict):
        content_type = None
    sent_text = str(payload.get("sentAt") or "").strip()
    sent_at = _parse_sent_at(sent_text)
    return XmtpCliMessage(
        id=_hex_or_text_to_bytes(message_id),
        conversation_id=_hex_or_text_to_bytes(conversation_id),
        sender_inbox_id=sender,
        content=content,
        content_type=content_type,
        sent_at=sent_at,
    )


def _extract_identifier_address(value: Any) -> str:
    if not isinstance(value, dict):
        return ""
    identifier = str(value.get("identifier") or "").strip().lower()
    if not _looks_like_eth_address(identifier):
        return ""
    kind = value.get("identifierKind")
    if kind in {0, "0", "ethereum", "ETHEREUM", None}:
        return identifier
    return ""


def _extract_first_json_value(text: str) -> Any | None:
    source = text or ""
    decoder = json.JSONDecoder()
    for idx, char in enumerate(source):
        if char not in "[{":
            continue
        with contextlib.suppress(Exception):
            value, _end = decoder.raw_decode(source[idx:])
            return value
    return None


def _try_parse_json_line(line: str) -> Any | None:
    stripped = (line or "").strip()
    if not stripped or stripped[0] not in "[{":
        return None
    with contextlib.suppress(Exception):
        return json.loads(stripped)
    return None


def _parse_sent_at(value: str) -> datetime:
    text = " ".join((value or "").split()).strip()
    if text:
        with contextlib.suppress(Exception):
            if text.endswith("Z"):
                return datetime.fromisoformat(text[:-1] + "+00:00")
            parsed = datetime.fromisoformat(text)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
    return datetime.now(tz=timezone.utc)


def _conversation_id_text(value: bytes | str) -> str:
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, str):
        return value.strip().lower()
    return ""


def _hex_or_text_to_bytes(value: str) -> bytes:
    text = " ".join((value or "").split()).strip()
    if not text:
        return b""
    lowered = text.lower()
    if lowered.startswith("0x"):
        lowered = lowered[2:]
    if lowered and len(lowered) % 2 == 0 and re.fullmatch(r"[0-9a-f]+", lowered):
        with contextlib.suppress(Exception):
            return bytes.fromhex(lowered)
    return text.encode("utf-8", errors="ignore")


def _looks_like_eth_address(value: str) -> bool:
    return bool(_ETH_ADDRESS_RE.fullmatch(" ".join((value or "").split()).strip()))


def _looks_like_inbox_id(value: str) -> bool:
    return bool(_INBOX_ID_RE.fullmatch(" ".join((value or "").split()).strip()))


def _tail_append(lines: list[str], line: str, *, limit: int = 40) -> None:
    lines.append(line)
    if len(lines) > limit:
        del lines[: len(lines) - limit]


def _run_process(cmd: list[str], env: dict[str, str], timeout_s: float) -> subprocess.CompletedProcess[str]:
    timeout = None if timeout_s <= 0 else float(timeout_s)
    return subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )


def _summarize_error_text(value: str, limit: int = 220) -> str:
    text = " ".join((value or "").split())
    if not text:
        return "no details available"
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _write_xmtp_client_env(wallet_key: str, db_encryption_key: str) -> Path:
    runtime = ensure_runtime_dirs(runtime_paths())
    env_path = runtime.root / "xmtp" / "client.env"
    env_path.parent.mkdir(parents=True, exist_ok=True)
    payload = (
        f"XMTP_WALLET_KEY={wallet_key.strip()}\n"
        f"XMTP_DB_ENCRYPTION_KEY={db_encryption_key.strip()}\n"
    )
    env_path.write_text(payload, encoding="utf-8")
    with contextlib.suppress(Exception):
        os.chmod(env_path, 0o600)
    return env_path


_PROFILE_HELPER_SCRIPT = r'''#!/usr/bin/env node
import fs from "node:fs";
import zlib from "node:zlib";
import { Client } from "@xmtp/node-sdk";
import { isHex, toBytes } from "viem";
import { privateKeyToAccount } from "viem/accounts";

const MARKER = 0x1f;

function readInput() {
  const text = fs.readFileSync(0, "utf8");
  if (!text.trim()) {
    return {};
  }
  return JSON.parse(text);
}

function normalizeHex(input) {
  const raw = String(input || "").trim();
  if (!raw) return "";
  return raw.startsWith("0x") ? raw : `0x${raw}`;
}

function createSigner(walletKey) {
  const hex = normalizeHex(walletKey);
  if (!isHex(hex, { strict: true })) {
    throw new Error("walletKey is not valid hex");
  }
  const account = privateKeyToAccount(hex);
  return {
    type: "EOA",
    getIdentifier: () => ({
      identifierKind: 0,
      identifier: account.address.toLowerCase(),
    }),
    signMessage: async (message) => {
      const signature = await account.signMessage({ message });
      return toBytes(signature);
    },
  };
}

function hexToBytes(value) {
  const hex = normalizeHex(value);
  if (!isHex(hex, { strict: true })) {
    throw new Error("dbEncryptionKey is not valid hex");
  }
  return toBytes(hex);
}

function toBase64Url(bytes) {
  return Buffer.from(bytes)
    .toString("base64")
    .replace(/\+/g, "-")
    .replace(/\//g, "_")
    .replace(/=+$/g, "");
}

function fromBase64Url(value) {
  const base64 = String(value || "").replace(/-/g, "+").replace(/_/g, "/");
  const padding = base64.length % 4 === 0 ? "" : "=".repeat(4 - (base64.length % 4));
  return Uint8Array.from(Buffer.from(base64 + padding, "base64"));
}

function readVarint(bytes, start) {
  let offset = start;
  let result = 0n;
  let shift = 0n;
  while (offset < bytes.length) {
    const byte = bytes[offset++];
    result |= BigInt(byte & 0x7f) << shift;
    if ((byte & 0x80) === 0) {
      return { value: result, offset };
    }
    shift += 7n;
    if (shift > 63n) {
      throw new Error("malformed varint");
    }
  }
  throw new Error("unexpected EOF while reading varint");
}

function encodeVarint(value) {
  let current = typeof value === "bigint" ? value : BigInt(value);
  const out = [];
  while (current >= 0x80n) {
    out.push(Number((current & 0x7fn) | 0x80n));
    current >>= 7n;
  }
  out.push(Number(current));
  return Uint8Array.from(out);
}

function encodeKey(fieldNumber, wireType) {
  return encodeVarint((BigInt(fieldNumber) << 3n) | BigInt(wireType));
}

function parseFields(bytes) {
  const fields = [];
  let offset = 0;
  while (offset < bytes.length) {
    const fieldStart = offset;
    const key = readVarint(bytes, offset);
    offset = key.offset;
    const keyNum = Number(key.value);
    const fieldNumber = keyNum >> 3;
    const wireType = keyNum & 0x7;
    let value;
    if (wireType === 0) {
      const parsed = readVarint(bytes, offset);
      value = parsed.value;
      offset = parsed.offset;
    } else if (wireType === 1) {
      const end = offset + 8;
      if (end > bytes.length) throw new Error("fixed64 exceeds payload");
      value = bytes.slice(offset, end);
      offset = end;
    } else if (wireType === 2) {
      const len = readVarint(bytes, offset);
      offset = len.offset;
      const length = Number(len.value);
      const end = offset + length;
      if (end > bytes.length) throw new Error("length-delimited exceeds payload");
      value = bytes.slice(offset, end);
      offset = end;
    } else if (wireType === 5) {
      const end = offset + 4;
      if (end > bytes.length) throw new Error("fixed32 exceeds payload");
      value = bytes.slice(offset, end);
      offset = end;
    } else {
      throw new Error(`unsupported wire type ${wireType}`);
    }
    fields.push({
      fieldNumber,
      wireType,
      value,
      raw: bytes.slice(fieldStart, offset),
    });
  }
  return fields;
}

function decodeUtf8(bytes) {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return "";
  }
}

function encodeLengthDelimited(fieldNumber, value) {
  return concatBytes(encodeKey(fieldNumber, 2), encodeVarint(value.length), value);
}

function encodeStringField(fieldNumber, value) {
  const text = String(value || "").trim();
  if (!text) return null;
  return encodeLengthDelimited(fieldNumber, new TextEncoder().encode(text));
}

function concatBytes(...chunks) {
  if (!chunks.length) return new Uint8Array();
  const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0);
  const out = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) {
    out.set(chunk, offset);
    offset += chunk.length;
  }
  return out;
}

function parseSfixed64(bytes) {
  if (bytes.length !== 8) return 0n;
  let value = 0n;
  for (let i = 0; i < 8; i++) {
    value |= BigInt(bytes[i]) << BigInt(i * 8);
  }
  if (value & (1n << 63n)) {
    value -= 1n << 64n;
  }
  return value;
}

function encodeSfixed64(fieldNumber, value) {
  let intValue = BigInt(value);
  if (intValue < 0n) {
    intValue = (1n << 64n) + intValue;
  }
  const bytes = new Uint8Array(8);
  for (let i = 0; i < 8; i++) {
    bytes[i] = Number((intValue >> BigInt(i * 8)) & 0xffn);
  }
  return concatBytes(encodeKey(fieldNumber, 1), bytes);
}

function bytesToHex(bytes) {
  let out = "";
  for (const byte of bytes) {
    out += byte.toString(16).padStart(2, "0");
  }
  return out;
}

function hexToRawBytes(value) {
  const text = String(value || "").trim().replace(/^0x/i, "").toLowerCase();
  if (!text || text.length % 2 !== 0 || !/^[0-9a-f]+$/.test(text)) {
    return null;
  }
  const out = new Uint8Array(text.length / 2);
  for (let i = 0; i < text.length; i += 2) {
    out[i / 2] = parseInt(text.slice(i, i + 2), 16);
  }
  return out;
}

function decodeAppData(encoded) {
  const text = String(encoded || "").trim();
  if (!text) {
    return { payload: new Uint8Array(), error: "" };
  }
  let raw;
  try {
    raw = fromBase64Url(text);
  } catch (error) {
    return { payload: new Uint8Array(), error: `base64url decode failed: ${String(error)}` };
  }
  if (!raw.length) {
    return { payload: new Uint8Array(), error: "" };
  }
  if (raw[0] !== MARKER) {
    return { payload: raw, error: "" };
  }
  if (raw.length < 5) {
    return { payload: new Uint8Array(), error: "compressed payload marker missing size header" };
  }
  const expected = (raw[1] << 24) | (raw[2] << 16) | (raw[3] << 8) | raw[4];
  try {
    const inflated = zlib.inflateSync(Buffer.from(raw.slice(5)));
    const payload = Uint8Array.from(inflated);
    if (expected > 0 && payload.length !== expected) {
      return { payload: new Uint8Array(), error: `decompressed size mismatch expected=${expected} got=${payload.length}` };
    }
    return { payload, error: "" };
  } catch (error) {
    return { payload: new Uint8Array(), error: `inflate failed: ${String(error)}` };
  }
}

function encodeAppData(payload) {
  if (!payload.length) {
    return "";
  }
  const compressed = Uint8Array.from(zlib.deflateSync(Buffer.from(payload)));
  const marker = concatBytes(
    Uint8Array.from([MARKER]),
    Uint8Array.from([
      (payload.length >>> 24) & 0xff,
      (payload.length >>> 16) & 0xff,
      (payload.length >>> 8) & 0xff,
      payload.length & 0xff,
    ]),
    compressed,
  );
  return toBase64Url(marker.length < payload.length ? marker : payload);
}

function parseProfile(bytes) {
  const fields = parseFields(bytes);
  const profile = {
    inboxId: "",
    name: "",
    image: "",
    extra: [],
  };
  for (const field of fields) {
    if (field.fieldNumber === 1 && field.wireType === 2 && field.value instanceof Uint8Array) {
      profile.inboxId = bytesToHex(field.value).toLowerCase();
      continue;
    }
    if (field.fieldNumber === 2 && field.wireType === 2 && field.value instanceof Uint8Array) {
      profile.name = decodeUtf8(field.value).trim();
      continue;
    }
    if (field.fieldNumber === 3 && field.wireType === 2 && field.value instanceof Uint8Array) {
      profile.image = decodeUtf8(field.value).trim();
      continue;
    }
    profile.extra.push(field.raw);
  }
  return profile;
}

function encodeProfile(profile) {
  const inbox = hexToRawBytes(profile.inboxId);
  if (!inbox || !inbox.length) return null;
  const chunks = [encodeLengthDelimited(1, inbox)];
  const nameField = encodeStringField(2, profile.name);
  if (nameField) chunks.push(nameField);
  const imageField = encodeStringField(3, profile.image);
  if (imageField) chunks.push(imageField);
  if (Array.isArray(profile.extra)) {
    for (const item of profile.extra) {
      if (item instanceof Uint8Array) chunks.push(item);
    }
  }
  return concatBytes(...chunks);
}

function parseMetadata(payload) {
  const fields = parseFields(payload);
  const metadata = {
    tag: "",
    expiresAtUnix: 0n,
    profiles: [],
    extra: [],
  };
  for (const field of fields) {
    if (field.fieldNumber === 1 && field.wireType === 2 && field.value instanceof Uint8Array) {
      metadata.tag = decodeUtf8(field.value).trim();
      continue;
    }
    if (field.fieldNumber === 2 && field.wireType === 2 && field.value instanceof Uint8Array) {
      const profile = parseProfile(field.value);
      if (profile.inboxId) metadata.profiles.push(profile);
      continue;
    }
    if (field.fieldNumber === 3 && field.wireType === 1 && field.value instanceof Uint8Array) {
      metadata.expiresAtUnix = parseSfixed64(field.value);
      continue;
    }
    metadata.extra.push(field.raw);
  }
  return metadata;
}

function encodeMetadata(metadata) {
  const chunks = [];
  const tagField = encodeStringField(1, metadata.tag);
  if (tagField) chunks.push(tagField);
  for (const profile of metadata.profiles || []) {
    const encoded = encodeProfile(profile);
    if (encoded) {
      chunks.push(encodeLengthDelimited(2, encoded));
    }
  }
  if (metadata.expiresAtUnix && metadata.expiresAtUnix !== 0n) {
    chunks.push(encodeSfixed64(3, metadata.expiresAtUnix));
  }
  if (Array.isArray(metadata.extra)) {
    for (const item of metadata.extra) {
      if (item instanceof Uint8Array) chunks.push(item);
    }
  }
  return chunks.length ? concatBytes(...chunks) : new Uint8Array();
}

function sanitizeDisplayName(value) {
  const text = String(value || "").trim();
  if (!text) return "Tako";
  return text.slice(0, 50);
}

function sanitizeImage(value) {
  const text = String(value || "").trim();
  if (!text) return "";
  return text.slice(0, 4096);
}

function conversationKind(conversation) {
  if (!conversation) return "unknown";
  if (typeof conversation.peerInboxId === "string" && conversation.peerInboxId) {
    return "dm";
  }
  if (typeof conversation.appData === "string" || typeof conversation.updateAppData === "function") {
    return "group";
  }
  return "unknown";
}

async function maybeArray(value) {
  const out = await Promise.resolve(value);
  if (Array.isArray(out)) return out;
  if (out && typeof out[Symbol.iterator] === "function") {
    return Array.from(out);
  }
  return [];
}

async function main() {
  const input = readInput();
  const mode = String(input.mode || "sync").trim().toLowerCase() || "sync";
  const env = String(input.env || "production").trim() || "production";
  const displayName = sanitizeDisplayName(input.displayName);
  const avatarUrl = sanitizeImage(input.avatarUrl);

  const result = {
    ok: true,
    nameInSync: false,
    avatarInSync: avatarUrl ? false : true,
    appliedName: false,
    appliedAvatar: false,
    fallbackSelfSent: false,
    fallbackPeerSentCount: 0,
    sentConversationIds: [],
    errors: [],
  };

  const signer = createSigner(input.walletKey || "");
  const client = await Client.create(signer, {
    env,
    dbPath: String(input.dbPath || "").trim(),
    dbEncryptionKey: hexToBytes(input.dbEncryptionKey || ""),
    appVersion: `takobot-xmtp-helper/${String(input.version || "dev")}`,
  });

  const payload = {
    type: "profile",
    v: 1,
    displayName,
    ...(avatarUrl ? { avatarUrl } : {}),
    ts: Date.now(),
  };
  const encodedContent = {
    type: {
      authorityId: "converge.cv",
      typeId: "profile",
      versionMajor: 1,
      versionMinor: 0,
    },
    parameters: {},
    content: new TextEncoder().encode(JSON.stringify(payload)),
    fallback: undefined,
  };

  const dmTargets = new Set();
  const groupTargets = new Set();

  const explicitDmIds = Array.isArray(input.dmConversationIds) ? input.dmConversationIds : [];
  const explicitGroupIds = Array.isArray(input.groupConversationIds) ? input.groupConversationIds : [];

  for (const item of explicitDmIds) {
    const id = String(item || "").trim().toLowerCase();
    if (id) dmTargets.add(id);
  }
  for (const item of explicitGroupIds) {
    const id = String(item || "").trim().toLowerCase();
    if (id) groupTargets.add(id);
  }

  const targetConversationId = String(input.targetConversationId || "").trim().toLowerCase();
  if (targetConversationId) {
    try {
      const targetConversation = await client.conversations.getConversationById(targetConversationId);
      const kind = conversationKind(targetConversation);
      if (kind === "group") {
        groupTargets.add(targetConversationId);
      } else if (kind === "dm") {
        dmTargets.add(targetConversationId);
      }
    } catch (error) {
      result.errors.push(`target conversation lookup failed: ${String(error)}`);
    }
  }

  if (mode === "sync" && !dmTargets.size && !groupTargets.size) {
    const dms = await maybeArray(client.conversations.listDms());
    for (const dm of dms) {
      if (dm && dm.id) dmTargets.add(String(dm.id).toLowerCase());
    }
    const groups = await maybeArray(client.conversations.listGroups());
    for (const group of groups) {
      if (group && group.id) groupTargets.add(String(group.id).toLowerCase());
    }
  }

  const shouldSendSelf = Boolean(input.includeSelfDm);
  if (shouldSendSelf) {
    try {
      let selfDm = await Promise.resolve(client.conversations.getDmByInboxId(client.inboxId));
      if (!selfDm) {
        if (client.accountIdentifier && typeof client.conversations.createDmWithIdentifier === "function") {
          selfDm = await client.conversations.createDmWithIdentifier(client.accountIdentifier);
        } else if (typeof client.conversations.createDm === "function") {
          selfDm = await client.conversations.createDm(client.inboxId);
        }
      }
      if (!selfDm) {
        throw new Error("unable to resolve self DM");
      }
      await selfDm.send(encodedContent, { shouldPush: false });
      result.fallbackSelfSent = true;
      result.appliedName = true;
      if (avatarUrl) result.appliedAvatar = true;
      result.nameInSync = true;
      if (avatarUrl) result.avatarInSync = true;
    } catch (error) {
      result.errors.push(`self-dm publish failed: ${String(error)}`);
    }
  }

  for (const conversationId of dmTargets) {
    try {
      const dm = await client.conversations.getConversationById(conversationId);
      if (!dm || conversationKind(dm) !== "dm") {
        continue;
      }
      await dm.send(encodedContent, { shouldPush: false });
      result.sentConversationIds.push(conversationId);
      result.fallbackPeerSentCount += 1;
      result.appliedName = true;
      if (avatarUrl) result.appliedAvatar = true;
      result.nameInSync = true;
      if (avatarUrl) result.avatarInSync = true;
    } catch (error) {
      result.errors.push(`dm publish failed (${conversationId}): ${String(error)}`);
    }
  }

  for (const conversationId of groupTargets) {
    try {
      const group = await client.conversations.getConversationById(conversationId);
      if (!group || conversationKind(group) !== "group" || typeof group.updateAppData !== "function") {
        continue;
      }
      const rawAppData = typeof group.appData === "string" ? group.appData : "";
      const decoded = decodeAppData(rawAppData);
      if (decoded.error) {
        result.errors.push(`group appData decode failed (${conversationId}): ${decoded.error}`);
        continue;
      }
      const metadata = parseMetadata(decoded.payload);
      const selfInboxId = String(client.inboxId || "").trim().replace(/^0x/i, "").toLowerCase();
      if (!selfInboxId) {
        result.errors.push(`group profile upsert failed (${conversationId}): missing inboxId`);
        continue;
      }
      let found = false;
      for (const profile of metadata.profiles) {
        if (String(profile.inboxId || "").trim().toLowerCase() !== selfInboxId) {
          continue;
        }
        profile.inboxId = selfInboxId;
        profile.name = displayName;
        profile.image = avatarUrl;
        found = true;
        break;
      }
      if (!found) {
        metadata.profiles.push({
          inboxId: selfInboxId,
          name: displayName,
          image: avatarUrl,
          extra: [],
        });
      }
      const encoded = encodeAppData(encodeMetadata(metadata));
      if ((rawAppData || "").trim() !== encoded) {
        await group.updateAppData(encoded);
        result.sentConversationIds.push(conversationId);
        result.fallbackPeerSentCount += 1;
        result.appliedName = true;
        if (avatarUrl) result.appliedAvatar = true;
      }
      result.nameInSync = true;
      if (avatarUrl) result.avatarInSync = true;
    } catch (error) {
      result.errors.push(`group profile upsert failed (${conversationId}): ${String(error)}`);
    }
  }

  if (!result.nameInSync && result.errors.length === 0) {
    result.nameInSync = true;
  }
  if (!avatarUrl && result.errors.length === 0) {
    result.avatarInSync = true;
  }

  if (result.errors.length > 0) {
    result.ok = false;
  }

  process.stdout.write(JSON.stringify(result));
}

main().catch((error) => {
  process.stderr.write(String(error && error.stack ? error.stack : error));
  process.exit(1);
});
'''


async def _run_profile_helper(
    client: XmtpCliClient,
    *,
    mode: str,
    display_name: str,
    avatar_url: str,
    target_conversation_id: str = "",
    include_self_dm: bool = True,
    dm_conversation_ids: list[str] | None = None,
    group_conversation_ids: list[str] | None = None,
) -> dict[str, Any]:
    ensure_workspace_xmtp_runtime_if_needed()
    node_runtime = ensure_workspace_node_runtime(min_major=XMTP_MIN_NODE_MAJOR, require_npm=False)
    if not node_runtime.ok:
        raise RuntimeError(node_runtime.detail)

    node_exec = _resolve_node_exec(node_runtime.node_bin_dir)
    if not node_exec:
        raise RuntimeError(f"compatible node executable is unavailable (requires node >= {XMTP_MIN_NODE_MAJOR})")

    script_path = _ensure_profile_helper_script()
    payload = {
        "version": XMTP_CLI_VERSION,
        "env": client.env_name,
        "walletKey": _read_env_var(client.env_file, "XMTP_WALLET_KEY"),
        "dbEncryptionKey": _read_env_var(client.env_file, "XMTP_DB_ENCRYPTION_KEY"),
        "dbPath": str(client.db_path),
        "displayName": canonical_profile_name(display_name),
        "avatarUrl": _trim_profile_avatar_url(avatar_url),
        "mode": mode,
        "targetConversationId": target_conversation_id,
        "includeSelfDm": bool(include_self_dm),
        "dmConversationIds": sorted({str(item).strip().lower() for item in (dm_conversation_ids or []) if str(item).strip()}),
        "groupConversationIds": sorted({str(item).strip().lower() for item in (group_conversation_ids or []) if str(item).strip()}),
    }
    cmd = [node_exec, str(script_path)]
    proc = await asyncio.to_thread(
        subprocess.run,
        cmd,
        check=False,
        capture_output=True,
        text=True,
        env=node_runtime.env,
        input=json.dumps(payload, ensure_ascii=True),
        timeout=120,
    )
    if proc.returncode != 0:
        detail = proc.stderr.strip() or proc.stdout.strip() or f"exit={proc.returncode}"
        raise RuntimeError(f"profile helper failed: {_summarize_error_text(detail)}")
    parsed = _extract_first_json_value(proc.stdout)
    if not isinstance(parsed, dict):
        merged = "\n".join(part for part in (proc.stdout.strip(), proc.stderr.strip()) if part)
        raise RuntimeError(f"profile helper returned invalid JSON: {_summarize_error_text(merged)}")
    return parsed


def _ensure_profile_helper_script() -> Path:
    path = workspace_xmtp_helper_script_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    current = ""
    try:
        current = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        current = ""
    except Exception:
        current = ""
    if current != _PROFILE_HELPER_SCRIPT:
        path.write_text(_PROFILE_HELPER_SCRIPT, encoding="utf-8")
    with contextlib.suppress(Exception):
        os.chmod(path, 0o700)
    return path


def _resolve_node_exec(node_bin_dir: Path | None) -> str:
    if node_bin_dir is not None:
        candidate = node_bin_dir / ("node.exe" if os.name == "nt" else "node")
        if candidate.exists():
            return str(candidate)
    system_node = shutil.which("node")
    return system_node or ""


def _read_env_var(path: Path, key: str) -> str:
    needle = f"{key}="
    try:
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or not line.startswith(needle):
                continue
            return line[len(needle) :].strip()
    except Exception:
        return ""
    return ""
