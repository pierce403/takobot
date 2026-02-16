from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.config import load_tako_toml, set_life_stage
from takobot.life_stage import DEFAULT_LIFE_STAGE


class TestLifeStageConfig(unittest.TestCase):
    def test_life_stage_parses_from_toml(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "tako.toml"
            path.write_text(
                "\n".join(
                    [
                        "[workspace]",
                        'name = "Tako"',
                        "version = 1",
                        "",
                        "[life]",
                        'stage = "teen"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            cfg, warn = load_tako_toml(path)
            self.assertEqual("", warn)
            self.assertEqual("teen", cfg.life.stage)

    def test_invalid_life_stage_falls_back_to_default(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "tako.toml"
            path.write_text(
                "\n".join(
                    [
                        "[life]",
                        'stage = "kraken"',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            cfg, warn = load_tako_toml(path)
            self.assertEqual("", warn)
            self.assertEqual(DEFAULT_LIFE_STAGE, cfg.life.stage)

    def test_set_life_stage_updates_toml(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "tako.toml"
            path.write_text("[workspace]\nname = \"Tako\"\n", encoding="utf-8")
            ok, summary = set_life_stage(path, "adult")
            self.assertTrue(ok, summary)
            cfg, warn = load_tako_toml(path)
            self.assertEqual("", warn)
            self.assertEqual("adult", cfg.life.stage)


if __name__ == "__main__":
    unittest.main()
