from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.config import add_world_watch_sites, load_tako_toml


class TestWorldWatchConfig(unittest.TestCase):
    def test_world_watch_section_parses(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "tako.toml"
            path.write_text(
                "\n".join(
                    [
                        "[workspace]",
                        'name = "Tako"',
                        "version = 1",
                        "",
                        "[world_watch]",
                        "feeds = [\"https://example.com/rss.xml\", \"https://example.com/atom.xml\"]",
                        "sites = [\"https://example.com\", \"https://news.ycombinator.com\"]",
                        "poll_minutes = 22",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            cfg, warn = load_tako_toml(path)
            self.assertEqual("", warn)
            self.assertEqual(2, len(cfg.world_watch.feeds))
            self.assertEqual(2, len(cfg.world_watch.sites))
            self.assertEqual(22, cfg.world_watch.poll_minutes)

    def test_top_level_fallback_fields_parse(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "tako.toml"
            path.write_text(
                "\n".join(
                    [
                        "feeds = [\"https://example.com/rss.xml\"]",
                        "sites = [\"example.org\"]",
                        "poll_minutes = 17",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            cfg, warn = load_tako_toml(path)
            self.assertEqual("", warn)
            self.assertEqual(["https://example.com/rss.xml"], cfg.world_watch.feeds)
            self.assertEqual(["https://example.org"], cfg.world_watch.sites)
            self.assertEqual(17, cfg.world_watch.poll_minutes)

    def test_add_world_watch_sites_updates_config(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "tako.toml"
            path.write_text(
                "\n".join(
                    [
                        "[world_watch]",
                        "feeds = [\"https://example.com/rss.xml\"]",
                        "sites = [\"https://example.com\"]",
                        "poll_minutes = 20",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            ok, summary, added = add_world_watch_sites(
                path,
                ["news.ycombinator.com", "https://example.com", "https://www.reddit.com/r/python"],
            )
            self.assertTrue(ok, summary)
            self.assertEqual(
                ["https://news.ycombinator.com", "https://www.reddit.com/r/python"],
                added,
            )
            cfg, warn = load_tako_toml(path)
            self.assertEqual("", warn)
            self.assertEqual(
                [
                    "https://example.com",
                    "https://news.ycombinator.com",
                    "https://www.reddit.com/r/python",
                ],
                cfg.world_watch.sites,
            )


if __name__ == "__main__":
    unittest.main()
