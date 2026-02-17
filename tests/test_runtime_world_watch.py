from __future__ import annotations

import asyncio
import json
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.runtime.events import EventBus
from takobot.runtime.runtime import Runtime


class OneShotWorldSensor:
    name = "rss"

    def __init__(self) -> None:
        self._emitted = False

    async def tick(self, _ctx) -> list[dict[str, object]]:
        if self._emitted:
            return []
        self._emitted = True
        return [
            {
                "type": "world.news.item",
                "severity": "info",
                "source": "sensor:rss",
                "message": "Oceanic chip policy update (Example News)",
                "metadata": {
                    "item_id": "item-001",
                    "title": "Oceanic chip policy update",
                    "link": "https://example.com/world/oceanic-chip-policy",
                    "source": "Example News",
                    "published": "Mon, 16 Feb 2026 12:00:00 GMT",
                    "why_it_matters": "Signals a supply-side policy shift with downstream impacts.",
                    "mission_relevance": "Could alter planning assumptions for mission execution this quarter.",
                    "question": "How does this policy shift change our mission timeline assumptions?",
                },
            }
        ]


class CountingSensor:
    name = "curiosity"

    def __init__(self) -> None:
        self.ticks = 0

    async def tick(self, _ctx) -> list[dict[str, object]]:
        self.ticks += 1
        return []


class MissionObjectiveCaptureSensor:
    name = "capture"

    def __init__(self) -> None:
        self.last_mission_objectives: tuple[str, ...] = ()

    async def tick(self, ctx) -> list[dict[str, object]]:
        self.last_mission_objectives = tuple(ctx.mission_objectives)
        return []


class TestRuntimeWorldWatch(unittest.TestCase):
    def test_runtime_writes_world_notebook_mission_review_and_briefing(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / ".tako" / "state"
            memory_root = root / "memory"
            daily_root = root / "memory" / "dailies"
            state_dir.mkdir(parents=True, exist_ok=True)
            memory_root.mkdir(parents=True, exist_ok=True)
            daily_root.mkdir(parents=True, exist_ok=True)

            event_bus = EventBus(state_dir / "events.jsonl")
            briefings: list[str] = []
            sensor = OneShotWorldSensor()
            runtime = Runtime(
                event_bus=event_bus,
                state_dir=state_dir,
                memory_root=memory_root,
                daily_log_root=daily_root,
                sensors=[sensor],
                heartbeat_interval_s=1.0,
                heartbeat_jitter_ratio=0.0,
                explore_interval_s=1.0,
                explore_jitter_ratio=0.0,
                mission_objectives_getter=lambda: ["Keep mission-aligned research current."],
                open_tasks_count_getter=lambda: 4,
                on_briefing=lambda message: briefings.append(message),
            )

            async def _run() -> None:
                await runtime.start()
                await asyncio.sleep(1.25)
                await runtime.stop()

            asyncio.run(_run())
            today = date.today().isoformat()

            notebook_path = memory_root / "world" / f"{today}.md"
            self.assertTrue(notebook_path.exists())
            notebook_text = notebook_path.read_text(encoding="utf-8")
            self.assertIn("Oceanic chip policy update", notebook_text)
            self.assertIn("Why it matters:", notebook_text)
            self.assertIn("Signals a supply-side policy shift", notebook_text)
            self.assertIn("Possible mission relevance:", notebook_text)
            self.assertIn("Could alter planning assumptions", notebook_text)
            self.assertIn("Questions:", notebook_text)
            self.assertIn("How does this policy shift change our mission timeline assumptions?", notebook_text)

            self.assertTrue((memory_root / "world" / "model.md").exists())
            self.assertTrue((memory_root / "world" / "entities.md").exists())
            self.assertTrue((memory_root / "world" / "assumptions.md").exists())
            entities_text = (memory_root / "world" / "entities.md").read_text(encoding="utf-8")
            self.assertIn("Example News", entities_text)

            mission_review_path = memory_root / "world" / "mission-review" / f"{today}.md"
            self.assertTrue(mission_review_path.exists())
            mission_text = mission_review_path.read_text(encoding="utf-8")
            self.assertIn("Mission Review Lite", mission_text)
            self.assertIn("Mission status:", mission_text)
            self.assertIn("Candidate next actions:", mission_text)
            self.assertIn("Research question:", mission_text)

            daily_log_path = daily_root / f"{today}.md"
            self.assertTrue(daily_log_path.exists())
            daily_text = daily_log_path.read_text(encoding="utf-8")
            self.assertIn("World Watch picked up 1 new items", daily_text)
            self.assertIn("Mission Review Lite updated", daily_text)

            self.assertGreaterEqual(len(briefings), 1)
            self.assertIn("briefing:", briefings[0])
            self.assertIn("world watch", briefings[0])
            self.assertIn("question:", briefings[0])

            briefing_state = json.loads((state_dir / "briefing_state.json").read_text(encoding="utf-8"))
            self.assertLessEqual(int(briefing_state.get("briefings_today", 0)), 3)
            self.assertEqual(event_bus.events_written, len((state_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()))

    def test_runtime_boredom_triggers_idle_decay_and_hourly_style_explore(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / ".tako" / "state"
            memory_root = root / "memory"
            daily_root = memory_root / "dailies"
            state_dir.mkdir(parents=True, exist_ok=True)
            memory_root.mkdir(parents=True, exist_ok=True)
            daily_root.mkdir(parents=True, exist_ok=True)

            event_bus = EventBus(state_dir / "events.jsonl")
            sensor = CountingSensor()
            runtime = Runtime(
                event_bus=event_bus,
                state_dir=state_dir,
                memory_root=memory_root,
                daily_log_root=daily_root,
                sensors=[sensor],
                heartbeat_interval_s=0.05,
                heartbeat_jitter_ratio=0.0,
                explore_interval_s=3600.0,
                explore_jitter_ratio=0.0,
                boredom_idle_decay_start_s=0.08,
                boredom_idle_decay_interval_s=0.08,
                boredom_explore_interval_s=0.16,
            )
            runtime.heartbeat_interval_s = 0.05

            async def _run() -> None:
                await runtime.start()
                await asyncio.sleep(0.45)
                await runtime.stop()

            asyncio.run(_run())

            event_lines = (state_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
            event_types = [json.loads(line).get("type", "") for line in event_lines if line.strip()]
            self.assertIn("dose.bored.idle", event_types)
            self.assertIn("dose.bored.explore", event_types)
            self.assertGreaterEqual(sensor.ticks, 2)

    def test_manual_explore_command_uses_topic_and_emits_events(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / ".tako" / "state"
            memory_root = root / "memory"
            daily_root = memory_root / "dailies"
            state_dir.mkdir(parents=True, exist_ok=True)
            memory_root.mkdir(parents=True, exist_ok=True)
            daily_root.mkdir(parents=True, exist_ok=True)

            event_bus = EventBus(state_dir / "events.jsonl")
            sensor = MissionObjectiveCaptureSensor()
            runtime = Runtime(
                event_bus=event_bus,
                state_dir=state_dir,
                memory_root=memory_root,
                daily_log_root=daily_root,
                sensors=[sensor],
                heartbeat_interval_s=1.0,
                heartbeat_jitter_ratio=0.0,
                explore_interval_s=3600.0,
                explore_jitter_ratio=0.0,
                mission_objectives_getter=lambda: ["Track mission-relevant shifts."],
            )

            selected_topic, new_world_count = asyncio.run(runtime.request_explore("  decentralized identity trends  "))
            self.assertEqual("decentralized identity trends", selected_topic)
            self.assertEqual(0, new_world_count)
            self.assertEqual("Exploration focus: decentralized identity trends", sensor.last_mission_objectives[0])
            self.assertIn("Track mission-relevant shifts.", sensor.last_mission_objectives)

            today = date.today().isoformat()
            daily_path = daily_root / f"{today}.md"
            self.assertTrue(daily_path.exists())
            daily_text = daily_path.read_text(encoding="utf-8")
            self.assertIn("Manual explore requested: decentralized identity trends.", daily_text)

            events = [
                json.loads(line)
                for line in (state_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            event_types = [str(event.get("type", "")) for event in events]
            self.assertIn("runtime.explore.manual.requested", event_types)
            self.assertIn("runtime.explore.manual.completed", event_types)
            requested = next(event for event in events if event.get("type") == "runtime.explore.manual.requested")
            completed = next(event for event in events if event.get("type") == "runtime.explore.manual.completed")
            self.assertEqual("decentralized identity trends", requested.get("metadata", {}).get("topic"))
            self.assertEqual(0, completed.get("metadata", {}).get("new_world_items"))

    def test_manual_explore_without_topic_suggests_from_today_world_notes(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / ".tako" / "state"
            memory_root = root / "memory"
            daily_root = memory_root / "dailies"
            world_dir = memory_root / "world"
            state_dir.mkdir(parents=True, exist_ok=True)
            memory_root.mkdir(parents=True, exist_ok=True)
            daily_root.mkdir(parents=True, exist_ok=True)
            world_dir.mkdir(parents=True, exist_ok=True)

            today = date.today().isoformat()
            (world_dir / f"{today}.md").write_text(
                "\n".join(
                    [
                        f"# World Notebook — {today}",
                        "",
                        f"## {today}",
                        "- **[Oceanic chip policy update]** (Example News) — https://example.com/a",
                        "  - Why it matters: supply dynamics",
                        "  - Possible mission relevance: planning",
                        "  - Questions:",
                        "    - how does this change priorities?",
                        "- **[New autonomous robotics stack]** (Research Lab) — https://example.com/b",
                        "  - Why it matters: capability shift",
                        "  - Possible mission relevance: execution speed",
                        "  - Questions:",
                        "    - what is production readiness?",
                        "",
                    ]
                ),
                encoding="utf-8",
            )

            event_bus = EventBus(state_dir / "events.jsonl")
            runtime = Runtime(
                event_bus=event_bus,
                state_dir=state_dir,
                memory_root=memory_root,
                daily_log_root=daily_root,
                sensors=[CountingSensor()],
                heartbeat_interval_s=1.0,
                heartbeat_jitter_ratio=0.0,
                explore_interval_s=3600.0,
                explore_jitter_ratio=0.0,
                mission_objectives_getter=lambda: ["Maintain mission agility."],
            )

            selected_topic, new_world_count = asyncio.run(runtime.request_explore(""))
            self.assertEqual(0, new_world_count)
            self.assertIn("Oceanic chip policy update", selected_topic)
            self.assertIn("New autonomous robotics stack", selected_topic)
            self.assertIn("Maintain mission agility.", selected_topic)

            daily_text = (daily_root / f"{today}.md").read_text(encoding="utf-8")
            self.assertIn(f"Manual explore requested: {selected_topic}.", daily_text)


if __name__ == "__main__":
    unittest.main()
