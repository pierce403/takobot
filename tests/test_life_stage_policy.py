from __future__ import annotations

import unittest

from takobot.ascii_octo import octopus_ascii_for_stage, stage_box
from takobot.life_stage import DEFAULT_LIFE_STAGE, StagePolicy, normalize_life_stage_name, stage_policy_for_name


class TestLifeStagePolicy(unittest.TestCase):
    def test_stage_policy_lookup(self) -> None:
        policy = stage_policy_for_name("child")
        self.assertIsInstance(policy, StagePolicy)
        self.assertEqual("child", policy.stage.value)
        self.assertTrue(policy.world_watch_enabled)
        self.assertGreater(policy.type2_budget_per_day, 0)

    def test_unknown_stage_normalizes_to_default(self) -> None:
        self.assertEqual(DEFAULT_LIFE_STAGE, normalize_life_stage_name("kraken"))

    def test_ascii_art_changes_by_stage(self) -> None:
        hatch = octopus_ascii_for_stage("hatchling")
        child = octopus_ascii_for_stage("child")
        teen = octopus_ascii_for_stage("teen")
        adult = octopus_ascii_for_stage("adult")
        self.assertNotEqual(hatch, child)
        self.assertNotEqual(child, adult)
        self.assertNotEqual(teen, adult)

    def test_ascii_stage_boxes_match_style_guide(self) -> None:
        expected = {
            "hatchling": (7, 3),
            "child": (9, 3),
            "teen": (13, 5),
            "adult": (15, 6),
        }
        for stage, (width, height) in expected.items():
            self.assertEqual((width, height), stage_box(stage))
            frame = octopus_ascii_for_stage(stage, frame=0, canvas_cols=width)
            lines = frame.splitlines()
            self.assertEqual(height, len(lines))
            self.assertTrue(all(len(line) == width for line in lines))

    def test_ascii_swim_frame_shifts_horizontally_when_canvas_allows(self) -> None:
        frame_a = octopus_ascii_for_stage("adult", frame=3, canvas_cols=26)
        frame_b = octopus_ascii_for_stage("adult", frame=21, canvas_cols=26)
        self.assertNotEqual(frame_a, frame_b)


if __name__ == "__main__":
    unittest.main()
