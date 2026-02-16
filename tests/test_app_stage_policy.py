from __future__ import annotations

import unittest

from takobot.app import _build_terminal_chat_prompt, _looks_like_local_command


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


if __name__ == "__main__":
    unittest.main()
