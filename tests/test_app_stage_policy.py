from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest

from takobot.app import TakoTerminalApp, _build_terminal_chat_prompt, _looks_like_local_command
from takobot.life_stage import stage_policy_for_name


class TestAppStagePolicy(unittest.TestCase):
    def test_stage_command_is_local_command(self) -> None:
        self.assertTrue(_looks_like_local_command("stage"))
        self.assertTrue(_looks_like_local_command("stage set child"))

    def test_terminal_prompt_includes_stage_and_memory_frontmatter(self) -> None:
        prompt = _build_terminal_chat_prompt(
            text="summarize today's world watch",
            identity_name="Tako",
            identity_role="Your highly autonomous octopus friend",
            mission_objectives=["Track mission signals"],
            mode="running",
            state="RUNNING",
            operator_paired=True,
            history="User: hi",
            life_stage="teen",
            stage_tone="skeptical",
            memory_frontmatter="# MEMORY frontmatter\n- daily notes under memory/dailies",
        )
        self.assertIn("Life stage: teen (skeptical).", prompt)
        self.assertIn("memory_frontmatter=", prompt)
        self.assertIn("MEMORY frontmatter", prompt)
        self.assertIn("ask sharp follow-up questions", prompt)

    def test_child_stage_prompt_prefers_gentle_context_questions(self) -> None:
        prompt = _build_terminal_chat_prompt(
            text="hi",
            identity_name="Tako",
            identity_role="Your highly autonomous octopus friend",
            mission_objectives=["Track mission signals"],
            mode="running",
            state="RUNNING",
            operator_paired=True,
            history="User: hi",
            life_stage="child",
            stage_tone="curious",
            memory_frontmatter="# MEMORY frontmatter",
        )
        self.assertIn("Child-stage behavior", prompt)
        self.assertIn("Ask one gentle question", prompt)
        self.assertIn("Do not push structured plans", prompt)

    def test_child_stage_includes_curiosity_sensor(self) -> None:
        with TemporaryDirectory() as tmp:
            app = TakoTerminalApp(interval=5.0)
            app.paths = SimpleNamespace(state_dir=Path(tmp))
            app.life_stage = "child"
            app.stage_policy = stage_policy_for_name("child")
            sensors = app._build_stage_sensors()
            names = [getattr(sensor, "name", "") for sensor in sensors]
            self.assertIn("rss", names)
            self.assertIn("curiosity", names)

    def test_non_child_stage_skips_curiosity_sensor(self) -> None:
        with TemporaryDirectory() as tmp:
            app = TakoTerminalApp(interval=5.0)
            app.paths = SimpleNamespace(state_dir=Path(tmp))
            app.life_stage = "teen"
            app.stage_policy = stage_policy_for_name("teen")
            sensors = app._build_stage_sensors()
            names = [getattr(sensor, "name", "") for sensor in sensors]
            self.assertIn("rss", names)
            self.assertNotIn("curiosity", names)


if __name__ == "__main__":
    unittest.main()
