from __future__ import annotations

import asyncio
import contextlib
from dataclasses import dataclass
from datetime import date
import inspect
import json
import random
import re
import time
from pathlib import Path
from typing import Any, Callable

from ..daily import append_daily_note, ensure_daily_log
from ..sensors.base import Sensor, SensorContext
from .events import EventBus

BRIEFING_MAX_PER_DAY = 3
BRIEFING_COOLDOWN_S = 90 * 60
BRIEFING_MAX_TRACKED_ITEM_IDS = 5_000


@dataclass(frozen=True)
class RuntimeHeartbeatTick:
    tick: int
    at_monotonic: float
    at_wall: float


class Runtime:
    def __init__(
        self,
        *,
        event_bus: EventBus,
        state_dir: Path,
        resources_root: Path,
        daily_log_root: Path,
        sensors: list[Sensor],
        heartbeat_interval_s: float,
        heartbeat_jitter_ratio: float = 0.2,
        explore_interval_s: float = 5 * 60,
        explore_jitter_ratio: float = 0.1,
        sensor_timeout_s: float = 12.0,
        sensor_user_agent: str = "takobot/1.0 (+https://tako.bot; world-watch)",
        mission_objectives_getter: Callable[[], list[str]] | None = None,
        open_tasks_count_getter: Callable[[], int] | None = None,
        on_heartbeat_tick: Callable[[RuntimeHeartbeatTick], Any] | None = None,
        on_activity: Callable[[str, str], Any] | None = None,
        on_briefing: Callable[[str], Any] | None = None,
    ) -> None:
        self.event_bus = event_bus
        self.state_dir = state_dir
        self.resources_root = resources_root
        self.daily_log_root = daily_log_root
        self.sensors = list(sensors)
        self.heartbeat_interval_s = max(1.0, float(heartbeat_interval_s))
        self.heartbeat_jitter_ratio = max(0.0, float(heartbeat_jitter_ratio))
        self.explore_interval_s = max(1.0, float(explore_interval_s))
        self.explore_jitter_ratio = max(0.0, float(explore_jitter_ratio))
        self.sensor_timeout_s = max(1.0, float(sensor_timeout_s))
        self.sensor_user_agent = sensor_user_agent.strip() or "takobot/1.0 (+https://tako.bot; world-watch)"
        self.mission_objectives_getter = mission_objectives_getter
        self.open_tasks_count_getter = open_tasks_count_getter
        self.on_heartbeat_tick = on_heartbeat_tick
        self.on_activity = on_activity
        self.on_briefing = on_briefing

        self.heartbeat_ticks = 0
        self.last_heartbeat_at: float | None = None
        self.explore_ticks = 0
        self.last_explore_at: float | None = None

        self._heartbeat_task: asyncio.Task[None] | None = None
        self._explore_task: asyncio.Task[None] | None = None
        self._running = False

        self._error_counts: dict[str, int] = {}
        self._repeating_errors: set[str] = set()
        self._last_open_tasks_count: int | None = None

        self._world_dir = self.resources_root / "world"
        self._briefing_state_path = self.state_dir / "briefing_state.json"
        self._briefing_state = self._load_briefing_state()
        self._unsubscribe_error_listener = self.event_bus.subscribe(self._track_errors)

    @property
    def running(self) -> bool:
        return self._running

    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop(), name="tako-runtime-heartbeat")
        self._explore_task = asyncio.create_task(self._explore_loop(), name="tako-runtime-explore")
        self.event_bus.publish_event(
            "runtime.service.started",
            "Runtime service started (heartbeat, exploration, sensors).",
            source="runtime",
            metadata={
                "heartbeat_interval_s": self.heartbeat_interval_s,
                "explore_interval_s": self.explore_interval_s,
                "sensors": [sensor.name for sensor in self.sensors],
            },
        )
        self._emit_activity("runtime", "service started")

    async def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        await _cancel_task(self._heartbeat_task)
        await _cancel_task(self._explore_task)
        self._heartbeat_task = None
        self._explore_task = None
        self.event_bus.publish_event(
            "runtime.service.stopped",
            "Runtime service stopped.",
            source="runtime",
        )
        self._emit_activity("runtime", "service stopped")
        self._save_briefing_state()

    def handle_input(self, text: str) -> None:
        cleaned = " ".join((text or "").split())
        if not cleaned:
            return
        self.event_bus.publish_event(
            "runtime.input.received",
            "Operator input received by runtime.",
            source="runtime",
            metadata={"chars": len(cleaned), "preview": cleaned[:120]},
        )

    async def _heartbeat_loop(self) -> None:
        while True:
            self.heartbeat_ticks += 1
            tick = RuntimeHeartbeatTick(
                tick=self.heartbeat_ticks,
                at_monotonic=time.monotonic(),
                at_wall=time.time(),
            )
            self.last_heartbeat_at = tick.at_monotonic
            if self.on_heartbeat_tick is not None:
                with contextlib.suppress(Exception):
                    await _maybe_await(self.on_heartbeat_tick(tick))
            await asyncio.sleep(_with_jitter(self.heartbeat_interval_s, self.heartbeat_jitter_ratio))

    async def _explore_loop(self) -> None:
        while True:
            self.explore_ticks += 1
            self.last_explore_at = time.monotonic()
            with contextlib.suppress(Exception):
                await self._run_exploration_tick()
            await asyncio.sleep(_with_jitter(self.explore_interval_s, self.explore_jitter_ratio))

    async def _run_exploration_tick(self) -> None:
        today = date.today()
        ensure_daily_log(self.daily_log_root, today)
        ctx = SensorContext.create(
            state_dir=self.state_dir,
            user_agent=self.sensor_user_agent,
            timeout_s=self.sensor_timeout_s,
        )

        world_items: list[WorldItem] = []
        for sensor in self.sensors:
            try:
                sensor_events = await sensor.tick(ctx)
            except Exception as exc:  # noqa: BLE001
                self.event_bus.publish_event(
                    "sensor.tick.error",
                    f"{sensor.name} sensor tick failed: {exc}",
                    severity="warn",
                    source=f"sensor:{sensor.name}",
                )
                continue
            for event in sensor_events:
                published = self.event_bus.publish(event)
                if str(published.get("type", "")) == "world.news.item":
                    item = _world_item_from_event(published)
                    if item is not None:
                        world_items.append(item)

        new_world_count = 0
        if world_items:
            notebook_path, new_world_count = _append_world_notebook_entries(self._world_dir, today, world_items)
            if new_world_count > 0:
                append_daily_note(
                    self.daily_log_root,
                    today,
                    f"World Watch picked up {new_world_count} new items.",
                )
                self.event_bus.publish_event(
                    "world.watch.batch",
                    f"World Watch captured {new_world_count} new items.",
                    source="sensor:rss",
                    metadata={"count": new_world_count, "path": str(notebook_path)},
                )
                self._emit_activity("world-watch", f"{new_world_count} new items")

        tasks_unblocked = self._detect_unblocked_tasks()
        repeated_errors = sorted(self._repeating_errors)

        if await self._maybe_emit_briefing(
            world_items=world_items,
            new_world_count=new_world_count,
            tasks_unblocked=tasks_unblocked,
            repeated_errors=repeated_errors,
        ):
            for signature in repeated_errors:
                self._repeating_errors.discard(signature)

        self._maybe_write_daily_mission_review(
            world_items=world_items,
            new_world_count=new_world_count,
            tasks_unblocked=tasks_unblocked,
            repeated_errors=repeated_errors,
        )

    def _detect_unblocked_tasks(self) -> int:
        if self.open_tasks_count_getter is None:
            return 0
        try:
            current = max(0, int(self.open_tasks_count_getter()))
        except Exception:
            return 0
        previous = self._last_open_tasks_count
        self._last_open_tasks_count = current
        if previous is None:
            return 0
        if current >= previous:
            return 0
        return previous - current

    async def _maybe_emit_briefing(
        self,
        *,
        world_items: list["WorldItem"],
        new_world_count: int,
        tasks_unblocked: int,
        repeated_errors: list[str],
    ) -> bool:
        now_ts = time.time()
        today = date.today().isoformat()
        self._rollover_day(today)

        recent_world = [item for item in world_items if item.item_id not in self._briefed_world_item_ids()]
        has_signal = bool(recent_world or tasks_unblocked > 0 or repeated_errors)
        if not has_signal:
            return False
        if int(self._briefing_state.get("briefings_today", 0)) >= BRIEFING_MAX_PER_DAY:
            return False
        last_ts = float(self._briefing_state.get("last_briefing_ts", 0.0) or 0.0)
        if last_ts and (now_ts - last_ts) < BRIEFING_COOLDOWN_S:
            return False

        lines = ["briefing:"]
        if new_world_count > 0:
            lines.append(f"- world watch: {new_world_count} new item(s).")
            for item in sorted(recent_world, key=lambda entry: entry.sort_key())[:3]:
                lines.append(f"- signal: {item.title} ({item.source}) -> watch mission impact.")
        if tasks_unblocked > 0:
            lines.append(f"- execution: {tasks_unblocked} task(s) were unblocked.")
        if repeated_errors:
            lines.append(f"- reliability: recurring issue `{_summarize_error_signature(repeated_errors[0])}`.")
        if len(lines) == 1:
            return False

        message = "\n".join(lines)
        if self.on_briefing is not None:
            with contextlib.suppress(Exception):
                await _maybe_await(self.on_briefing(message))

        briefed_ids = self._briefed_world_item_ids()
        for item in recent_world:
            if item.item_id in briefed_ids:
                continue
            briefed_ids.append(item.item_id)
        if len(briefed_ids) > BRIEFING_MAX_TRACKED_ITEM_IDS:
            briefed_ids = briefed_ids[-BRIEFING_MAX_TRACKED_ITEM_IDS:]

        self._briefing_state["briefings_today"] = int(self._briefing_state.get("briefings_today", 0)) + 1
        self._briefing_state["last_briefing_ts"] = now_ts
        self._briefing_state["day"] = today
        self._briefing_state["briefed_world_item_ids"] = briefed_ids
        self._save_briefing_state()

        self.event_bus.publish_event(
            "briefing.published",
            "Runtime briefing published.",
            source="runtime",
            metadata={
                "new_world_items": new_world_count,
                "tasks_unblocked": tasks_unblocked,
                "repeated_error_count": len(repeated_errors),
            },
        )
        return True

    def _maybe_write_daily_mission_review(
        self,
        *,
        world_items: list["WorldItem"],
        new_world_count: int,
        tasks_unblocked: int,
        repeated_errors: list[str],
    ) -> None:
        today = date.today()
        today_iso = today.isoformat()
        last_written = str(self._briefing_state.get("last_mission_review_day", "")).strip()
        if last_written == today_iso:
            return

        objectives = self._mission_objectives()
        mission_status = _mission_status(new_world_count=new_world_count, repeated_errors=repeated_errors, objectives=objectives)
        actions = _candidate_actions(world_items=world_items, objectives=objectives)
        question = _research_question(world_items=world_items, objectives=objectives)
        world_summary = _world_change_summary(new_world_count=new_world_count, repeated_errors=repeated_errors, tasks_unblocked=tasks_unblocked)

        review_dir = self._world_dir / "mission-review"
        review_dir.mkdir(parents=True, exist_ok=True)
        review_path = review_dir / f"{today_iso}.md"
        review_path.write_text(
            _format_mission_review(
                day=today_iso,
                mission_status=mission_status,
                world_summary=world_summary,
                actions=actions,
                question=question,
            ),
            encoding="utf-8",
        )

        append_daily_note(
            self.daily_log_root,
            today,
            f"Mission Review Lite updated: status={mission_status}; actions={len(actions)}.",
        )
        self.event_bus.publish_event(
            "mission.review.lite.written",
            "Mission Review Lite file written.",
            source="runtime",
            metadata={"path": str(review_path), "status": mission_status},
        )
        self._briefing_state["last_mission_review_day"] = today_iso
        self._save_briefing_state()
        self._emit_activity("mission", "daily mission review updated")

    def _mission_objectives(self) -> list[str]:
        if self.mission_objectives_getter is None:
            return []
        try:
            values = self.mission_objectives_getter()
        except Exception:
            return []
        out: list[str] = []
        for value in values:
            cleaned = " ".join(str(value).split()).strip()
            if cleaned:
                out.append(cleaned)
        return out

    def _track_errors(self, event: dict[str, Any]) -> None:
        severity = str(event.get("severity", "info")).lower()
        if severity not in {"warn", "error", "critical"}:
            return
        source = str(event.get("source", "")).lower()
        if source in {"runtime", "type1", "type2"}:
            return
        event_type = str(event.get("type", "")).strip()
        message = " ".join(str(event.get("message", "")).split())
        if not event_type or not message:
            return
        signature = _error_signature(event_type, message)
        count = self._error_counts.get(signature, 0) + 1
        self._error_counts[signature] = count
        if count >= 2:
            self._repeating_errors.add(signature)
        if len(self._error_counts) > 500:
            # Keep memory bounded for long sessions.
            trimmed = sorted(self._error_counts.items(), key=lambda entry: entry[1], reverse=True)[:300]
            self._error_counts = dict(trimmed)
            self._repeating_errors = {item for item in self._repeating_errors if item in self._error_counts}

    def _rollover_day(self, today_iso: str) -> None:
        current_day = str(self._briefing_state.get("day", "")).strip()
        if current_day == today_iso:
            return
        self._briefing_state["day"] = today_iso
        self._briefing_state["briefings_today"] = 0
        self._briefing_state["last_briefing_ts"] = 0.0
        self._briefing_state["briefed_world_item_ids"] = []
        self._briefing_state["last_mission_review_day"] = ""

    def _briefed_world_item_ids(self) -> list[str]:
        values = self._briefing_state.get("briefed_world_item_ids")
        if isinstance(values, list):
            return [str(value) for value in values if str(value).strip()]
        return []

    def _load_briefing_state(self) -> dict[str, Any]:
        if not self._briefing_state_path.exists():
            return {
                "day": date.today().isoformat(),
                "briefings_today": 0,
                "last_briefing_ts": 0.0,
                "briefed_world_item_ids": [],
                "last_mission_review_day": "",
            }
        try:
            payload = json.loads(self._briefing_state_path.read_text(encoding="utf-8"))
        except Exception:
            payload = {}
        if not isinstance(payload, dict):
            payload = {}
        payload.setdefault("day", date.today().isoformat())
        payload.setdefault("briefings_today", 0)
        payload.setdefault("last_briefing_ts", 0.0)
        payload.setdefault("briefed_world_item_ids", [])
        payload.setdefault("last_mission_review_day", "")
        return payload

    def _save_briefing_state(self) -> None:
        try:
            self._briefing_state_path.parent.mkdir(parents=True, exist_ok=True)
            self._briefing_state_path.write_text(
                json.dumps(self._briefing_state, sort_keys=True, ensure_ascii=True, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception:
            return

    def _emit_activity(self, kind: str, detail: str) -> None:
        if self.on_activity is None:
            return
        with contextlib.suppress(Exception):
            self.on_activity(kind, detail)


@dataclass(frozen=True)
class WorldItem:
    item_id: str
    title: str
    source: str
    link: str
    published: str

    def sort_key(self) -> tuple[str, str, str]:
        return (self.source.lower(), self.title.lower(), self.link.lower())


def _world_item_from_event(event: dict[str, Any]) -> WorldItem | None:
    metadata = event.get("metadata")
    if not isinstance(metadata, dict):
        return None
    item_id = _clean_value(metadata.get("item_id"))
    title = _clean_value(metadata.get("title")) or "(untitled)"
    source = _clean_value(metadata.get("source")) or "unknown source"
    link = _clean_value(metadata.get("link"))
    published = _clean_value(metadata.get("published"))
    if not item_id:
        return None
    return WorldItem(
        item_id=item_id,
        title=title,
        source=source,
        link=link,
        published=published,
    )


def _append_world_notebook_entries(world_dir: Path, day: date, items: list[WorldItem]) -> tuple[Path, int]:
    world_dir.mkdir(parents=True, exist_ok=True)
    path = world_dir / f"{day.isoformat()}.md"
    if not path.exists():
        path.write_text(f"# World Notebook — {day.isoformat()}\n\n", encoding="utf-8")

    text = path.read_text(encoding="utf-8")
    section_header = f"## {day.isoformat()}"
    if section_header not in text:
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"\n{section_header}\n"
        path.write_text(text, encoding="utf-8")
        text = path.read_text(encoding="utf-8")

    existing_ids = set(re.findall(r"<!-- world_item_id: (.+?) -->", text))
    pending = [item for item in sorted(items, key=lambda entry: entry.sort_key()) if item.item_id not in existing_ids]
    if not pending:
        return path, 0

    with path.open("a", encoding="utf-8") as handle:
        for item in pending:
            safe_id = item.item_id.replace("--", "-")
            safe_title = _clean_value(item.title) or "(untitled)"
            safe_source = _clean_value(item.source) or "unknown source"
            safe_link = _clean_value(item.link) or "(no link)"
            handle.write(f"<!-- world_item_id: {safe_id} -->\n")
            handle.write(f"- **[{safe_title}]** ({safe_source}) — {safe_link}\n")
            handle.write("  - Why it matters:\n")
            handle.write("  - Possible mission relevance:\n")
            handle.write("  - Questions:\n")
    return path, len(pending)


def _mission_status(*, new_world_count: int, repeated_errors: list[str], objectives: list[str]) -> str:
    if repeated_errors:
        return "off track"
    if new_world_count > 0 and objectives:
        return "on track"
    return "unknown"


def _world_change_summary(*, new_world_count: int, repeated_errors: list[str], tasks_unblocked: int) -> str:
    parts: list[str] = []
    if new_world_count > 0:
        parts.append(f"{new_world_count} new world-watch item(s).")
    if tasks_unblocked > 0:
        parts.append(f"{tasks_unblocked} task(s) unblocked.")
    if repeated_errors:
        parts.append(f"Recurring issue: {_summarize_error_signature(repeated_errors[0])}.")
    if not parts:
        return "No major external changes detected yet."
    return " ".join(parts)


def _candidate_actions(*, world_items: list[WorldItem], objectives: list[str]) -> list[str]:
    target_objective = objectives[0] if objectives else "the current mission"
    actions: list[str] = []
    for item in sorted(world_items, key=lambda entry: entry.sort_key())[:3]:
        actions.append(f"Review `{item.title}` and map concrete impact on {target_objective}.")
    if not actions:
        actions.append("Run a focused world-watch scan and capture any relevant deltas.")
    return actions[:3]


def _research_question(*, world_items: list[WorldItem], objectives: list[str]) -> str:
    if world_items and objectives:
        item = sorted(world_items, key=lambda entry: entry.sort_key())[0]
        return f"How does `{item.title}` change our approach to `{objectives[0]}`?"
    if objectives:
        return f"What evidence would prove progress on `{objectives[0]}` this week?"
    return "Which external signal should we monitor next to reduce uncertainty?"


def _format_mission_review(
    *,
    day: str,
    mission_status: str,
    world_summary: str,
    actions: list[str],
    question: str,
) -> str:
    lines = [
        f"# Mission Review Lite — {day}",
        "",
        f"- Mission status: {mission_status}",
        f"- What changed in world watch that affects it: {world_summary}",
        "- Candidate next actions:",
    ]
    for action in actions[:3]:
        lines.append(f"  - {action}")
    lines.append("- Research question:")
    lines.append(f"  - {question}")
    lines.append("")
    return "\n".join(lines)


def _clean_value(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _error_signature(event_type: str, message: str) -> str:
    prefix = _clean_value(event_type).lower()[:120]
    detail = _clean_value(message).lower()[:160]
    return f"{prefix}|{detail}"


def _summarize_error_signature(signature: str) -> str:
    if "|" not in signature:
        return signature[:120]
    event_type, detail = signature.split("|", 1)
    if len(detail) > 70:
        detail = detail[:67] + "..."
    return f"{event_type}: {detail}"


def _with_jitter(base_s: float, jitter_ratio: float) -> float:
    if jitter_ratio <= 0.0:
        return max(0.05, base_s)
    spread = base_s * jitter_ratio
    jittered = base_s + random.uniform(-spread, spread)
    return max(0.05, jittered)


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


async def _cancel_task(task: asyncio.Task[None] | None) -> None:
    if task is None:
        return
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
