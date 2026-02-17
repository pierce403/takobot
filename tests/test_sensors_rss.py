from __future__ import annotations

import asyncio
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory
import threading
import unittest
from unittest.mock import patch

from takobot.sensors.base import SensorContext
from takobot.sensors.rss import RSSSensor


@contextmanager
def local_feed_server(xml_payload: str):
    payload = xml_payload.encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "application/rss+xml; charset=utf-8")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, _format, *_args):  # noqa: A003
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/feed.xml"
    finally:
        server.shutdown()
        thread.join(timeout=5.0)
        server.server_close()


class TestRSSSensor(unittest.TestCase):
    def test_sensor_reads_feed_and_dedupes_by_seen_ids(self) -> None:
        feed = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>World Feed</title>
    <item>
      <title>First Signal</title>
      <link>https://example.com/a</link>
      <guid>a-1</guid>
    </item>
    <item>
      <title>Second Signal</title>
      <link>https://example.com/b</link>
      <guid>b-2</guid>
    </item>
  </channel>
</rss>"""
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            seen_path = state_dir / "rss_seen.json"
            with local_feed_server(feed) as url:
                ctx = SensorContext.create(
                    state_dir=state_dir,
                    user_agent="takobot-test",
                    timeout_s=3.0,
                )
                sensor = RSSSensor([url], poll_minutes=1, seen_path=seen_path)
                first = asyncio.run(sensor.tick(ctx))
                self.assertEqual(2, len(first))
                self.assertTrue(all(event["type"] == "world.news.item" for event in first))
                self.assertTrue(seen_path.exists())

                # Rebuild sensor to ensure dedupe survives process restarts via rss_seen.json.
                sensor_restarted = RSSSensor([url], poll_minutes=1, seen_path=seen_path)
                second = asyncio.run(sensor_restarted.tick(ctx))
                self.assertEqual([], second)

    def test_manual_trigger_bypasses_poll_interval(self) -> None:
        first_feed = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>World Feed</title>
    <item>
      <title>First Signal</title>
      <link>https://example.com/a</link>
      <guid>a-1</guid>
    </item>
  </channel>
</rss>"""
        second_feed = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
  <channel>
    <title>World Feed</title>
    <item>
      <title>Second Signal</title>
      <link>https://example.com/b</link>
      <guid>b-2</guid>
    </item>
  </channel>
</rss>"""
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp)
            seen_path = state_dir / "rss_seen.json"
            auto_ctx = SensorContext.create(
                state_dir=state_dir,
                user_agent="takobot-test",
                timeout_s=3.0,
            )
            manual_ctx = SensorContext.create(
                state_dir=state_dir,
                user_agent="takobot-test",
                timeout_s=3.0,
                trigger="manual",
            )
            sensor = RSSSensor(["https://example.com/feed.xml"], poll_minutes=60, seen_path=seen_path)

            with patch(
                "takobot.sensors.rss._fetch_feed",
                side_effect=[
                    ("https://example.com/feed.xml", first_feed),
                    ("https://example.com/feed.xml", second_feed),
                ],
            ):
                first = asyncio.run(sensor.tick(auto_ctx))
                self.assertEqual(1, len(first))
                blocked = asyncio.run(sensor.tick(auto_ctx))
                self.assertEqual([], blocked)
                manual = asyncio.run(sensor.tick(manual_ctx))
                self.assertEqual(1, len(manual))
                self.assertEqual("b-2", manual[0]["metadata"].get("item_id"))


if __name__ == "__main__":
    unittest.main()
