from __future__ import annotations

import unittest

from takobot.input_history import InputHistory


class TestInputHistory(unittest.TestCase):
    def test_up_down_navigation_restores_draft(self) -> None:
        history = InputHistory()
        history.add("first")
        history.add("second")

        self.assertEqual("second", history.navigate_up("draft"))
        self.assertEqual("first", history.navigate_up("draft"))
        self.assertEqual("second", history.navigate_down())
        self.assertEqual("draft", history.navigate_down())
        self.assertIsNone(history.navigate_down())

    def test_ignores_empty_and_consecutive_duplicates(self) -> None:
        history = InputHistory()
        history.add("")
        history.add("same")
        history.add("same")
        history.add("different")

        self.assertEqual("different", history.navigate_up(""))
        self.assertEqual("same", history.navigate_up(""))
        self.assertEqual("different", history.navigate_down())

    def test_max_items_trims_oldest(self) -> None:
        history = InputHistory(max_items=2)
        history.add("one")
        history.add("two")
        history.add("three")

        self.assertEqual("three", history.navigate_up(""))
        self.assertEqual("two", history.navigate_up(""))
        self.assertEqual("three", history.navigate_down())

    def test_rejects_invalid_max_items(self) -> None:
        with self.assertRaises(ValueError):
            InputHistory(max_items=0)
