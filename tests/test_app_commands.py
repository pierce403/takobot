from __future__ import annotations

import unittest

from takobot.app import (
    _dose_channel_label,
    _looks_like_local_command,
    _parse_command,
    _parse_dose_set_request,
    _slash_command_matches,
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


if __name__ == "__main__":
    unittest.main()
