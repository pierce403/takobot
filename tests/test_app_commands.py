from __future__ import annotations

import unittest
from unittest.mock import patch

from takobot.app import (
    _build_terminal_chat_prompt,
    _canonical_identity_name,
    _command_completion_context,
    _command_completion_matches,
    _dose_channel_label,
    _looks_like_local_command,
    _parse_command,
    _parse_dose_set_request,
    _slash_command_matches,
    _stream_focus_summary,
    TakoTerminalApp,
    run_terminal_app,
)


class TestAppCommands(unittest.TestCase):
    def test_parse_command_accepts_slash_prefix(self) -> None:
        cmd, rest = _parse_command("/models")
        self.assertEqual("models", cmd)
        self.assertEqual("", rest)

    def test_dose_set_request_supports_short_aliases(self) -> None:
        parsed = _parse_dose_set_request("o 0.4")
        self.assertEqual(("d", 0.4), parsed)
        self.assertEqual("dopamine", _dose_channel_label("d"))

        parsed_ox = _parse_dose_set_request("ox 0.3")
        self.assertEqual(("o", 0.3), parsed_ox)
        self.assertEqual("oxytocin", _dose_channel_label("o"))

    def test_dose_set_request_clamps_values(self) -> None:
        parsed = _parse_dose_set_request("s 2")
        self.assertEqual(("s", 1.0), parsed)

        parsed_low = _parse_dose_set_request("e -1")
        self.assertEqual(("e", 0.0), parsed_low)

    def test_looks_like_local_command_new_shortcuts(self) -> None:
        self.assertTrue(_looks_like_local_command("stats"))
        self.assertTrue(_looks_like_local_command("models"))
        self.assertTrue(_looks_like_local_command("upgrade check"))
        self.assertTrue(_looks_like_local_command("dose o 0.4"))
        self.assertTrue(_looks_like_local_command("/"))

    def test_slash_command_matches_lists_new_commands(self) -> None:
        items = _slash_command_matches("", limit=128)
        commands = {command for command, _summary in items}
        self.assertIn("/models", commands)
        self.assertIn("/upgrade", commands)
        self.assertIn("/stats", commands)

        dose_items = _slash_command_matches("dose")
        self.assertTrue(any(command == "/dose" for command, _summary in dose_items))

    def test_command_completion_context_handles_prefixes(self) -> None:
        base, token, slash = _command_completion_context("/st") or ("", "", False)
        self.assertEqual("/", base)
        self.assertEqual("st", token)
        self.assertTrue(slash)

        base2, token2, slash2 = _command_completion_context("takobot sta") or ("", "", True)
        self.assertEqual("takobot ", base2)
        self.assertEqual("sta", token2)
        self.assertFalse(slash2)

        self.assertIsNone(_command_completion_context("status now"))

    def test_command_completion_matches_for_plain_and_slash(self) -> None:
        plain = _command_completion_matches("sta", slash=False)
        self.assertIn("status", plain)
        self.assertIn("stats", plain)

        slash = _command_completion_matches("up", slash=True)
        self.assertIn("update", slash)
        self.assertIn("upgrade", slash)

    def test_stream_focus_summary_is_sanitized_and_truncated(self) -> None:
        self.assertEqual("hello world", _stream_focus_summary(" hello   world "))
        long_text = "x" * 200
        summarized = _stream_focus_summary(long_text)
        self.assertTrue(len(summarized) <= 120)
        self.assertTrue(summarized.endswith("..."))

    def test_run_terminal_app_uses_default_mouse_mode(self) -> None:
        with patch.object(TakoTerminalApp, "run", return_value=None) as run_mock:
            code = run_terminal_app(interval=11.0)
        self.assertEqual(0, code)
        run_mock.assert_called_once_with()

    def test_canonical_identity_name_defaults_to_tako(self) -> None:
        self.assertEqual("Tako", _canonical_identity_name(""))
        self.assertEqual("ProTako", _canonical_identity_name("  ProTako  "))

    def test_terminal_chat_prompt_uses_identity_name(self) -> None:
        prompt = _build_terminal_chat_prompt(
            text="hello",
            identity_name="ProTako",
            identity_role="Your highly autonomous octopus friend",
            mode="paired",
            state="RUNNING",
            operator_paired=True,
            history="User: hi",
        )
        self.assertIn("You are ProTako", prompt)
        self.assertIn("Canonical identity name: ProTako", prompt)
        self.assertIn("Never claim your name is `Tako`", prompt)


if __name__ == "__main__":
    unittest.main()
