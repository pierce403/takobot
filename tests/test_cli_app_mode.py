from __future__ import annotations

from types import SimpleNamespace
import unittest
from unittest.mock import patch

from takobot import cli


class TestCliAppMode(unittest.TestCase):
    def test_cmd_app_uses_tui_when_terminal_is_capable(self) -> None:
        args = SimpleNamespace(interval=12.0)
        with (
            patch("takobot.cli._terminal_text_ui_unavailable_reason", return_value=""),
            patch("takobot.cli._run_terminal_app_entry", return_value=7) as app_mock,
            patch("takobot.cli.cmd_run", return_value=99) as run_mock,
        ):
            code = cli.cmd_app(args)

        self.assertEqual(7, code)
        app_mock.assert_called_once_with(interval=12.0)
        run_mock.assert_not_called()

    def test_cmd_app_falls_back_to_text_logs_when_terminal_is_dumb(self) -> None:
        args = SimpleNamespace(interval=0.2)
        with (
            patch("takobot.cli._terminal_text_ui_unavailable_reason", return_value="TERM=dumb"),
            patch("takobot.cli._run_terminal_app_entry", return_value=7) as app_mock,
            patch("takobot.cli.cmd_run", return_value=42) as run_mock,
        ):
            code = cli.cmd_app(args)

        self.assertEqual(42, code)
        app_mock.assert_not_called()
        run_mock.assert_called_once()
        run_args = run_mock.call_args.args[0]
        self.assertEqual(1.0, run_args.interval)
        self.assertFalse(run_args.once)

    def test_cmd_app_falls_back_to_text_logs_when_textual_missing(self) -> None:
        args = SimpleNamespace(interval=30.0)
        missing = ModuleNotFoundError("No module named 'textual'")
        missing.name = "textual"
        with (
            patch("takobot.cli._terminal_text_ui_unavailable_reason", return_value=""),
            patch("takobot.cli._run_terminal_app_entry", side_effect=missing),
            patch("takobot.cli.cmd_run", return_value=5) as run_mock,
        ):
            code = cli.cmd_app(args)

        self.assertEqual(5, code)
        run_mock.assert_called_once()
        run_args = run_mock.call_args.args[0]
        self.assertEqual(30.0, run_args.interval)
        self.assertFalse(run_args.once)


if __name__ == "__main__":
    unittest.main()
