from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.runtime.events import EventBus


class TestEventBus(unittest.TestCase):
    def test_publish_flushes_pending_events_when_log_path_is_set(self) -> None:
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            event_log = state_dir / "events.jsonl"
            captured: list[dict[str, object]] = []

            bus = EventBus()
            bus.subscribe(lambda event: captured.append(event))
            event = bus.publish_event("test.event", "hello", source="tests", metadata={"a": 1})

            self.assertEqual(1, len(captured))
            self.assertEqual("test.event", captured[0]["type"])
            self.assertEqual("hello", captured[0]["message"])
            self.assertEqual(0, bus.events_written)
            self.assertTrue(str(event.get("id", "")).startswith("evt-"))

            bus.set_log_path(event_log)
            self.assertEqual(1, bus.events_written)
            self.assertTrue(event_log.exists())
            payload = event_log.read_text(encoding="utf-8")
            self.assertIn('"type": "test.event"', payload)
            self.assertIn('"source": "tests"', payload)


if __name__ == "__main__":
    unittest.main()
