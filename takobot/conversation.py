from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import secrets


SESSION_STORE_FILE = "sessions.json"
SESSION_TRANSCRIPTS_DIR = "sessions"
_ASSISTANT_FALLBACK_HISTORY_COMPACT = "Inference unavailable fallback reply (details omitted)."


@dataclass(frozen=True)
class ConversationMessage:
    role: str
    text: str


def limit_history_turns(messages: list[ConversationMessage], limit: int | None) -> list[ConversationMessage]:
    if not limit or limit <= 0 or not messages:
        return messages

    user_count = 0
    last_user_index = len(messages)
    for idx in range(len(messages) - 1, -1, -1):
        message = messages[idx]
        if message.role == "user":
            user_count += 1
            if user_count > limit:
                return messages[last_user_index:]
            last_user_index = idx
    return messages


class ConversationStore:
    def __init__(self, state_dir: Path) -> None:
        self.root = state_dir / "conversations"
        self.sessions_path = self.root / SESSION_STORE_FILE
        self.transcripts_dir = self.root / SESSION_TRANSCRIPTS_DIR
        self.root.mkdir(parents=True, exist_ok=True)
        self.transcripts_dir.mkdir(parents=True, exist_ok=True)

    def append_user_assistant(self, session_key: str, user_text: str, assistant_text: str) -> None:
        self.append_message(session_key, role="user", text=user_text)
        self.append_message(session_key, role="assistant", text=assistant_text)

    def append_message(self, session_key: str, *, role: str, text: str) -> None:
        clean_text = _clean_text(text)
        if not clean_text:
            return
        if role not in {"user", "assistant", "system"}:
            return

        store = self._load_store()
        entry = self._ensure_session_entry(store, session_key)
        transcript_path = self.transcripts_dir / f"{entry['session_id']}.jsonl"
        record = {
            "type": "message",
            "role": role,
            "text": clean_text,
            "created_at": _utc_now(),
        }
        with transcript_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True) + "\n")

        entry["updated_at"] = _utc_now()
        entry["message_count"] = int(entry.get("message_count", 0)) + 1
        self._save_store(store)

    def recent_messages(
        self,
        session_key: str,
        *,
        user_turn_limit: int = 12,
        max_chars: int = 8_000,
    ) -> list[ConversationMessage]:
        messages = self._load_messages(session_key)
        limited = limit_history_turns(messages, user_turn_limit)
        return _trim_messages_to_chars(limited, max_chars=max_chars)

    def format_prompt_context(
        self,
        session_key: str,
        *,
        user_turn_limit: int = 12,
        max_chars: int = 8_000,
        user_label: str = "User",
        assistant_label: str = "Takobot",
    ) -> str:
        messages = self.recent_messages(
            session_key,
            user_turn_limit=user_turn_limit,
            max_chars=max_chars,
        )
        if not messages:
            return ""

        lines = ["Recent conversation context (oldest to newest):"]
        for message in messages:
            if message.role == "user":
                label = user_label
            elif message.role == "assistant":
                label = assistant_label
            else:
                label = "System"
            lines.append(f"{label}: {_history_text_for_prompt(message)}")
        return "\n".join(lines)

    def _load_messages(self, session_key: str) -> list[ConversationMessage]:
        store = self._load_store()
        sessions = store.get("sessions", {})
        if not isinstance(sessions, dict):
            return []
        entry = sessions.get(session_key)
        if not isinstance(entry, dict):
            return []
        session_id = entry.get("session_id")
        if not isinstance(session_id, str) or not session_id.strip():
            return []

        transcript_path = self.transcripts_dir / f"{session_id}.jsonl"
        if not transcript_path.exists():
            return []

        messages: list[ConversationMessage] = []
        for raw in transcript_path.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            try:
                payload = json.loads(raw)
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(payload, dict):
                continue
            if payload.get("type") != "message":
                continue
            role = payload.get("role")
            text = payload.get("text")
            if role not in {"user", "assistant", "system"}:
                continue
            if not isinstance(text, str):
                continue
            clean_text = _clean_text(text)
            if not clean_text:
                continue
            messages.append(ConversationMessage(role=role, text=clean_text))
        return messages

    def _load_store(self) -> dict:
        if not self.sessions_path.exists():
            return {"version": 1, "sessions": {}}
        try:
            payload = json.loads(self.sessions_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {"version": 1, "sessions": {}}
        if not isinstance(payload, dict):
            return {"version": 1, "sessions": {}}
        sessions = payload.get("sessions")
        if not isinstance(sessions, dict):
            payload["sessions"] = {}
        payload.setdefault("version", 1)
        return payload

    def _save_store(self, store: dict) -> None:
        self.sessions_path.parent.mkdir(parents=True, exist_ok=True)
        self.sessions_path.write_text(json.dumps(store, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def _ensure_session_entry(self, store: dict, session_key: str) -> dict:
        sessions = store.setdefault("sessions", {})
        if not isinstance(sessions, dict):
            sessions = {}
            store["sessions"] = sessions

        existing = sessions.get(session_key)
        if isinstance(existing, dict):
            session_id = existing.get("session_id")
            if isinstance(session_id, str) and session_id:
                transcript_path = self.transcripts_dir / f"{session_id}.jsonl"
                if not transcript_path.exists():
                    self._write_transcript_header(transcript_path, session_key=session_key, session_id=session_id)
                return existing

        session_id = _new_session_id(session_key)
        transcript_path = self.transcripts_dir / f"{session_id}.jsonl"
        self._write_transcript_header(transcript_path, session_key=session_key, session_id=session_id)
        entry = {
            "session_id": session_id,
            "updated_at": _utc_now(),
            "message_count": 0,
        }
        sessions[session_key] = entry
        return entry

    def _write_transcript_header(self, path: Path, *, session_key: str, session_id: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        header = {
            "type": "session",
            "session_key": session_key,
            "session_id": session_id,
            "created_at": _utc_now(),
        }
        with path.open("w", encoding="utf-8") as handle:
            handle.write(json.dumps(header, sort_keys=True) + "\n")


def _new_session_id(session_key: str) -> str:
    digest = hashlib.sha1(session_key.encode("utf-8")).hexdigest()[:8]
    suffix = secrets.token_hex(4)
    stamp = datetime.now(tz=timezone.utc).strftime("%Y%m%d%H%M%S")
    return f"{stamp}-{digest}-{suffix}"


def _clean_text(text: str) -> str:
    return " ".join((text or "").split()).strip()


def _utc_now() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def _trim_messages_to_chars(messages: list[ConversationMessage], *, max_chars: int) -> list[ConversationMessage]:
    if max_chars <= 0 or not messages:
        return messages

    kept: list[ConversationMessage] = []
    used = 0
    for message in reversed(messages):
        cost = len(message.text) + len(message.role) + 4
        if not kept and cost > max_chars:
            keep_len = max(1, max_chars - len(message.role) - 4)
            kept.append(ConversationMessage(role=message.role, text=message.text[-keep_len:]))
            break
        if kept and used + cost > max_chars:
            break
        kept.append(message)
        used += cost
    kept.reverse()
    return kept


def _history_text_for_prompt(message: ConversationMessage) -> str:
    text = message.text
    if message.role != "assistant":
        return text
    lowered = text.lower()
    if "inference is unavailable right now" in lowered:
        return _ASSISTANT_FALLBACK_HISTORY_COMPACT
    if "i'm replying in fallback mode" in lowered or "diagnostic status only" in lowered:
        return _ASSISTANT_FALLBACK_HISTORY_COMPACT
    if "last inference error:" in lowered and "detailed command logs:" in lowered:
        return _ASSISTANT_FALLBACK_HISTORY_COMPACT
    return text
