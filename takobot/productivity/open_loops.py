from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .outcomes import Outcome
from .tasks import Task


@dataclass(frozen=True)
class OpenLoop:
    id: str
    kind: str
    title: str
    created_ts: float
    updated_ts: float
    source: str


def _to_ts(value: datetime) -> float:
    return float(value.timestamp())


def _safe_title(value: str) -> str:
    text = " ".join((value or "").strip().split())
    return text[:140] + "..." if len(text) > 143 else text


def _task_created_ts(task: Task) -> float:
    return _to_ts(datetime.combine(task.created, datetime.min.time()))


def _task_updated_ts(task: Task) -> float:
    return _to_ts(datetime.combine(task.updated, datetime.min.time()))


def compute_open_loops(
    *,
    tasks: list[Task],
    outcomes: list[Outcome],
    session: dict[str, Any],
    now_ts: float | None = None,
) -> list[OpenLoop]:
    now = float(now_ts if now_ts is not None else time.time())
    loops: list[OpenLoop] = []

    for task in tasks:
        if not task.is_open:
            continue
        loops.append(
            OpenLoop(
                id=f"task:{task.id}",
                kind="task",
                title=_safe_title(task.title),
                created_ts=_task_created_ts(task),
                updated_ts=_task_updated_ts(task),
                source="tasks",
            )
        )

    for idx, outcome in enumerate(outcomes, start=1):
        if not outcome.text.strip():
            continue
        if outcome.done:
            continue
        loops.append(
            OpenLoop(
                id=f"outcome:{idx}",
                kind="outcome",
                title=_safe_title(outcome.text),
                created_ts=now,  # outcomes are day-scoped; treat as "now" for age display
                updated_ts=now,
                source="daily",
            )
        )

    state = str(session.get("state") or "")
    operator_paired = bool(session.get("operator_paired"))
    awaiting_xmtp_handle = bool(session.get("awaiting_xmtp_handle"))
    safe_mode = bool(session.get("safe_mode"))
    inference_ready = bool(session.get("inference_ready"))

    if not operator_paired:
        loops.append(
            OpenLoop(
                id="pairing:operator",
                kind="pairing",
                title="Pair XMTP operator channel",
                created_ts=now,
                updated_ts=now,
                source="session",
            )
        )

    if state == "ASK_XMTP_HANDLE":
        prompt = "Answer: do you have an XMTP handle? (yes/no)"
        if awaiting_xmtp_handle:
            prompt = "Provide XMTP handle (.eth or 0x...)"
        loops.append(
            OpenLoop(
                id="onboarding:xmtp",
                kind="onboarding",
                title=prompt,
                created_ts=now,
                updated_ts=now,
                source="session",
            )
        )
    elif state == "PAIRING_OUTBOUND":
        loops.append(
            OpenLoop(
                id="pairing:resolve",
                kind="pairing",
                title="Resolve pairing (retry/change/local-only)",
                created_ts=now,
                updated_ts=now,
                source="session",
            )
        )
    elif state == "ONBOARDING_IDENTITY":
        loops.append(
            OpenLoop(
                id="onboarding:identity",
                kind="onboarding",
                title="Answer identity prompt (name/purpose)",
                created_ts=now,
                updated_ts=now,
                source="session",
            )
        )
    elif state == "ONBOARDING_ROUTINES":
        loops.append(
            OpenLoop(
                id="onboarding:routines",
                kind="onboarding",
                title="Answer routines prompt (what to watch/do daily)",
                created_ts=now,
                updated_ts=now,
                source="session",
            )
        )

    if not inference_ready:
        loops.append(
            OpenLoop(
                id="setup:inference",
                kind="setup",
                title="Inference not ready (configure Codex/Claude/Gemini auth)",
                created_ts=now,
                updated_ts=now,
                source="session",
            )
        )

    if safe_mode:
        loops.append(
            OpenLoop(
                id="runtime:safe_mode",
                kind="runtime",
                title="Safe mode is enabled",
                created_ts=now,
                updated_ts=now,
                source="session",
            )
        )

    return loops


def summarize_open_loops(loops: list[OpenLoop], *, now_ts: float | None = None) -> dict[str, Any]:
    now = float(now_ts if now_ts is not None else time.time())
    if not loops:
        return {"count": 0, "oldest_age_s": 0.0, "top": []}
    oldest = min(loop.created_ts for loop in loops)
    oldest_age = max(0.0, now - float(oldest))
    top = [loop.title for loop in sorted(loops, key=lambda item: item.created_ts)[:5]]
    return {"count": len(loops), "oldest_age_s": oldest_age, "top": top}


def load_open_loops(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict):
        return None
    return payload


def save_open_loops(path: Path, loops: list[OpenLoop]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_ts": time.time(),
        "open_loops": [
            {
                "id": loop.id,
                "kind": loop.kind,
                "title": loop.title,
                "created_ts": loop.created_ts,
                "updated_ts": loop.updated_ts,
                "source": loop.source,
            }
            for loop in loops
        ],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")
    return payload


