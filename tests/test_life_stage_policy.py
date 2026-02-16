from __future__ import annotations

import unittest

from takobot.ascii_octo import octopus_ascii_for_stage
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
        adult = octopus_ascii_for_stage("adult")
        self.assertNotEqual(hatch, child)
        self.assertNotEqual(child, adult)
        self.assertIn("hatchling", hatch)
        self.assertIn("adult", adult)


if __name__ == "__main__":
    unittest.main()
