from __future__ import annotations

import asyncio
from pathlib import Path
import random
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from takobot.sensors.base import SensorContext
from takobot.sensors.curiosity import CuriositySensor


class TestCuriositySensor(unittest.TestCase):
    def test_emits_mission_linked_question_and_dedupes_after_restart(self) -> None:
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            seen_path = state_dir / "curiosity_seen.json"

            def reddit_fetcher(_ctx: SensorContext, _rng: random.Random) -> dict[str, str]:
                return {
                    "item_id": "reddit:test:abc123",
                    "title": "Ocean battery chemistry hits new milestone",
                    "link": "https://example.com/ocean-battery",
                    "source": "Reddit r/technology",
                }

            ctx = SensorContext.create(
                state_dir=state_dir,
                user_agent="takobot-test",
                timeout_s=2.0,
                mission_objectives=["Build evidence-backed mission decisions"],
            )
            sensor = CuriositySensor(
                sources=["reddit"],
                poll_minutes=1,
                seen_path=seen_path,
                rng=random.Random(1),
                source_fetchers={"reddit": reddit_fetcher},
            )
            first = asyncio.run(sensor.tick(ctx))
            self.assertEqual(1, len(first))
            event = first[0]
            self.assertEqual("world.news.item", event["type"])
            self.assertEqual("sensor:curiosity", event["source"])
            metadata = event["metadata"]
            self.assertEqual("reddit", metadata["origin_source"])
            self.assertIn("Build evidence-backed mission decisions", metadata["mission_relevance"])
            self.assertIn("Build evidence-backed mission decisions", metadata["question"])
            self.assertTrue(seen_path.exists())

            sensor_restarted = CuriositySensor(
                sources=["reddit"],
                poll_minutes=1,
                seen_path=seen_path,
                rng=random.Random(1),
                source_fetchers={"reddit": reddit_fetcher},
            )
            second = asyncio.run(sensor_restarted.tick(ctx))
            self.assertEqual([], second)

    def test_random_source_selection_uses_configured_sources(self) -> None:
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)

            def reddit_fetcher(_ctx: SensorContext, _rng: random.Random) -> dict[str, str]:
                return {
                    "item_id": "reddit:test:r-1",
                    "title": "Reddit signal",
                    "link": "https://example.com/reddit",
                    "source": "Reddit r/science",
                }

            def hn_fetcher(_ctx: SensorContext, _rng: random.Random) -> dict[str, str]:
                return {
                    "item_id": "hackernews:42",
                    "title": "HN signal",
                    "link": "https://example.com/hn",
                    "source": "Hacker News",
                }

            ctx = SensorContext.create(
                state_dir=state_dir,
                user_agent="takobot-test",
                timeout_s=2.0,
            )
            sensor = CuriositySensor(
                sources=["reddit", "hackernews"],
                poll_minutes=1,
                seen_path=state_dir / "curiosity_seen.json",
                rng=random.Random(7),
                source_fetchers={
                    "reddit": reddit_fetcher,
                    "hackernews": hn_fetcher,
                },
            )
            events = asyncio.run(sensor.tick(ctx))
            self.assertEqual(1, len(events))
            origin = events[0]["metadata"].get("origin_source")
            self.assertIn(origin, {"reddit", "hackernews"})

    def test_operator_sites_are_sampled_when_configured(self) -> None:
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            ctx = SensorContext.create(
                state_dir=state_dir,
                user_agent="takobot-test",
                timeout_s=2.0,
            )
            sensor = CuriositySensor(
                sources=[],
                site_urls=["https://example.com"],
                poll_minutes=1,
                seen_path=state_dir / "curiosity_seen.json",
                rng=random.Random(3),
            )
            with patch("takobot.sensors.curiosity._fetch_html_title", return_value="Example Domain"):
                events = asyncio.run(sensor.tick(ctx))
            self.assertEqual(1, len(events))
            metadata = events[0]["metadata"]
            self.assertEqual("operator_sites", metadata.get("origin_source"))
            self.assertIn("Example Domain", metadata.get("title", ""))

    def test_manual_trigger_bypasses_poll_interval(self) -> None:
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            seen_path = state_dir / "curiosity_seen.json"
            calls = 0

            def reddit_fetcher(_ctx: SensorContext, _rng: random.Random) -> dict[str, str]:
                nonlocal calls
                calls += 1
                return {
                    "item_id": f"reddit:test:{calls}",
                    "title": f"Signal {calls}",
                    "link": f"https://example.com/signal-{calls}",
                    "source": "Reddit r/technology",
                }

            auto_ctx = SensorContext.create(
                state_dir=state_dir,
                user_agent="takobot-test",
                timeout_s=2.0,
            )
            manual_ctx = SensorContext.create(
                state_dir=state_dir,
                user_agent="takobot-test",
                timeout_s=2.0,
                trigger="manual",
            )
            sensor = CuriositySensor(
                sources=["reddit"],
                poll_minutes=60,
                seen_path=seen_path,
                rng=random.Random(4),
                source_fetchers={"reddit": reddit_fetcher},
            )

            first = asyncio.run(sensor.tick(auto_ctx))
            self.assertEqual(1, len(first))
            blocked = asyncio.run(sensor.tick(auto_ctx))
            self.assertEqual([], blocked)
            manual = asyncio.run(sensor.tick(manual_ctx))
            self.assertEqual(1, len(manual))
            self.assertEqual("reddit:test:2", manual[0]["metadata"].get("item_id"))
            self.assertEqual(2, calls)


if __name__ == "__main__":
    unittest.main()
