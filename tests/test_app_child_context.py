from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from takobot.app import TakoTerminalApp
from takobot.config import load_tako_toml


class TestAppChildContext(unittest.TestCase):
    def test_child_chat_updates_operator_profile_and_watch_sites(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / ".tako" / "state"
            daily_dir = root / "memory" / "dailies"
            state_dir.mkdir(parents=True, exist_ok=True)
            daily_dir.mkdir(parents=True, exist_ok=True)
            (root / "tako.toml").write_text(
                "\n".join(
                    [
                        "[workspace]",
                        'name = "Tako"',
                        "version = 1",
                        "",
                        "[life]",
                        'stage = "child"',
                        "",
                        "[world_watch]",
                        "feeds = []",
                        "sites = []",
                        "poll_minutes = 30",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )

            app = TakoTerminalApp(interval=5.0)
            app.paths = SimpleNamespace(state_dir=state_dir)
            app.life_stage = "child"
            app._add_activity = lambda *_args, **_kwargs: None  # type: ignore[method-assign]
            cfg, warn = load_tako_toml(root / "tako.toml")
            self.assertEqual("", warn)
            app.config = cfg

            with patch("takobot.app.repo_root", return_value=root), patch("takobot.app.daily_root", return_value=daily_dir):
                notes = asyncio.run(
                    app._capture_child_stage_operator_context(
                        "I'm in Austin and I work as a developer. I read https://news.ycombinator.com daily."
                    )
                )

            updated_cfg, warn2 = load_tako_toml(root / "tako.toml")
            self.assertEqual("", warn2)
            self.assertIn("https://news.ycombinator.com", updated_cfg.world_watch.sites)
            self.assertTrue((root / "memory" / "people" / "operator.md").exists())
            self.assertTrue(any("watch list" in line for line in notes))


if __name__ == "__main__":
    unittest.main()
