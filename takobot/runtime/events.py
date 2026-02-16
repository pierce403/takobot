from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
import contextlib
from datetime import datetime, timezone
import inspect
import json
import secrets
import time
from pathlib import Path
from typing import Any

EventHandler = Callable[[dict[str, Any]], Any]


def utc_now_iso() -> str:
    return datetime.now(tz=timezone.utc).replace(microsecond=0).isoformat()


def new_event_id() -> str:
    stamp = int(time.time() * 1000)
    token = secrets.token_hex(4)
    return f"evt-{stamp}-{token}"


class EventBus:
    """In-memory pub/sub bus with JSONL audit logging."""

    def __init__(self, log_path: Path | None = None) -> None:
        self._log_path = log_path
        self._pending: list[dict[str, Any]] = []
        self._handlers: list[EventHandler] = []
        self.events_written = 0
        if self._log_path is not None:
            self._prepare_log_path()

    @property
    def log_path(self) -> Path | None:
        return self._log_path

    def set_log_path(self, path: Path) -> None:
        self._log_path = path
        self._prepare_log_path()
        if not self._pending:
            return
        pending = list(self._pending)
        self._pending.clear()
        for event in pending:
            self._append_to_disk(event)

    def subscribe(self, handler: EventHandler) -> Callable[[], None]:
        self._handlers.append(handler)

        def _unsubscribe() -> None:
            with contextlib.suppress(ValueError):
                self._handlers.remove(handler)

        return _unsubscribe

    def publish(self, event: dict[str, Any]) -> dict[str, Any]:
        normalized = self._normalize_event(event)
        if self._log_path is None:
            self._pending.append(normalized)
        else:
            self._append_to_disk(normalized)
        self._dispatch(normalized)
        return normalized

    def publish_event(
        self,
        event_type: str,
        message: str,
        *,
        severity: str = "info",
        source: str = "system",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.publish(
            {
                "type": str(event_type or "system.event"),
                "severity": str(severity or "info"),
                "source": str(source or "system"),
                "message": str(message or ""),
                "metadata": metadata or {},
            }
        )

    def _prepare_log_path(self) -> None:
        if self._log_path is None:
            return
        self._log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log_path.touch(exist_ok=True)

    def _append_to_disk(self, event: dict[str, Any]) -> None:
        if self._log_path is None:
            return
        with self._log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, sort_keys=True, ensure_ascii=True))
            handle.write("\n")
        self.events_written += 1

    def _normalize_event(self, event: dict[str, Any]) -> dict[str, Any]:
        metadata = event.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        return {
            "id": str(event.get("id") or new_event_id()),
            "ts": str(event.get("ts") or utc_now_iso()),
            "type": str(event.get("type") or "system.event"),
            "severity": str(event.get("severity") or "info").lower(),
            "source": str(event.get("source") or "system"),
            "message": str(event.get("message") or ""),
            "metadata": metadata,
        }

    def _dispatch(self, event: dict[str, Any]) -> None:
        for handler in list(self._handlers):
            try:
                result = handler(event)
            except Exception:
                continue
            if inspect.isawaitable(result):
                self._schedule_async_handler(result)

    @staticmethod
    def _schedule_async_handler(awaitable: Awaitable[Any]) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        loop.create_task(awaitable)
