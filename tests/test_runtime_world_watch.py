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
                },
            }
        ]


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
            self.assertIn("Possible mission relevance:", notebook_text)
            self.assertIn("Questions:", notebook_text)

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

            briefing_state = json.loads((state_dir / "briefing_state.json").read_text(encoding="utf-8"))
            self.assertLessEqual(int(briefing_state.get("briefings_today", 0)), 3)
            self.assertEqual(event_bus.events_written, len((state_dir / "events.jsonl").read_text(encoding="utf-8").splitlines()))


if __name__ == "__main__":
    unittest.main()
