from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.mission import activity_alignment_score, is_activity_mission_aligned
from takobot.soul import DEFAULT_SOUL_ROLE, read_identity_mission, update_identity_mission


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
