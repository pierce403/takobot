from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.mission import activity_alignment_score, is_activity_mission_aligned
from takobot.soul import (
    DEFAULT_SOUL_ROLE,
    load_soul_excerpt,
    parse_mission_objectives_text,
    read_identity_mission,
    read_mission_objectives,
    update_identity_mission,
    update_mission_objectives,
)


class TestIdentityAndMission(unittest.TestCase):
    def test_update_and_read_identity_mission_roundtrip(self) -> None:
        with TemporaryDirectory() as tmp:
            soul_path = Path(tmp) / "SOUL.md"
            update_identity_mission("Inkster", "Your highly autonomous octopus friend", path=soul_path)

            name, mission = read_identity_mission(soul_path)
            self.assertEqual("Inkster", name)
            self.assertEqual("Your highly autonomous octopus friend", mission)

            content = soul_path.read_text(encoding="utf-8")
            self.assertIn("- Name: Inkster", content)
            self.assertIn("- Role: Your highly autonomous octopus friend", content)

    def test_read_identity_accepts_legacy_mission_field(self) -> None:
        with TemporaryDirectory() as tmp:
            soul_path = Path(tmp) / "SOUL.md"
            soul_path.write_text(
                "# SOUL.md\n\n"
                "## Identity\n\n"
                "- Name: Tako\n"
                "- Mission: Keep projects moving safely.\n",
                encoding="utf-8",
            )

            name, mission = read_identity_mission(soul_path)
            self.assertEqual("Tako", name)
            self.assertEqual("Keep projects moving safely.", mission)

    def test_activity_alignment_scores_mission_fit(self) -> None:
        mission = DEFAULT_SOUL_ROLE
        aligned_activity = "Run a safe diagnostic and summarize results clearly for the operator."
        off_mission_activity = "Generate random confetti and ignore any planning context."

        self.assertGreater(activity_alignment_score(aligned_activity, mission), 0.0)
        self.assertTrue(is_activity_mission_aligned(aligned_activity, mission))
        self.assertFalse(is_activity_mission_aligned(off_mission_activity, mission))

    def test_mission_objectives_roundtrip(self) -> None:
        with TemporaryDirectory() as tmp:
            soul_path = Path(tmp) / "SOUL.md"
            update_identity_mission("Inkster", "Your highly autonomous octopus friend", path=soul_path)
            stored = update_mission_objectives(
                ["Keep outcomes clear", "Stay curious", "Keep outcomes clear"],
                path=soul_path,
            )
            self.assertEqual(["Keep outcomes clear", "Stay curious"], stored)
            loaded = read_mission_objectives(soul_path)
            self.assertEqual(["Keep outcomes clear", "Stay curious"], loaded)
            content = soul_path.read_text(encoding="utf-8")
            self.assertIn("## Mission Objectives", content)
            self.assertIn("- Keep outcomes clear", content)

    def test_parse_mission_objectives_text_supports_semicolons_and_bullets(self) -> None:
        parsed = parse_mission_objectives_text("- Keep outcomes clear; 2) Stay curious; * Ask before risky changes")
        self.assertEqual(
            ["Keep outcomes clear", "Stay curious", "Ask before risky changes"],
            parsed,
        )

    def test_load_soul_excerpt_truncates(self) -> None:
        with TemporaryDirectory() as tmp:
            soul_path = Path(tmp) / "SOUL.md"
            soul_path.write_text("# SOUL.md\n\n## Identity\n\n- Name: Tako\n- Role: " + ("x" * 400), encoding="utf-8")
            excerpt = load_soul_excerpt(path=soul_path, max_chars=240)
            self.assertTrue(excerpt.startswith("# SOUL.md"))
            self.assertTrue(len(excerpt) <= 240)
            self.assertTrue(excerpt.endswith("..."))
