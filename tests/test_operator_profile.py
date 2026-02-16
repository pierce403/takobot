from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.operator_profile import (
    OperatorProfileState,
    apply_operator_profile_update,
    extract_operator_profile_update,
    load_operator_profile,
    next_child_followup_question,
    save_operator_profile,
    write_operator_profile_note,
)


class TestOperatorProfile(unittest.TestCase):
    def test_extract_and_apply_profile_updates(self) -> None:
        update = extract_operator_profile_update(
            "My name is Pierce. I'm in Austin. I work on agent tooling. "
            "Currently focused on local-first workflows. "
            "I check https://news.ycombinator.com and reddit.com/r/python."
        )
        profile = OperatorProfileState()
        changed, added_sites = apply_operator_profile_update(profile, update)
        self.assertTrue(any(item.startswith("name=") for item in changed))
        self.assertTrue(any(item.startswith("location=") for item in changed))
        self.assertTrue(any(item.startswith("work=") for item in changed))
        self.assertTrue(any(item.startswith("focus=") for item in changed))
        self.assertIn("https://news.ycombinator.com", added_sites)
        self.assertIn("https://reddit.com/r/python", added_sites)

    def test_profile_state_persistence_and_note_render(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            state_dir = root / ".tako" / "state"
            memory_root = root / "memory"
            state_dir.mkdir(parents=True, exist_ok=True)
            memory_root.mkdir(parents=True, exist_ok=True)

            profile = OperatorProfileState(
                name="Pierce",
                location="Austin",
                what_they_do="builds developer tools",
                current_focus="runtime reliability",
                preferred_sites=["https://news.ycombinator.com"],
            )
            save_operator_profile(state_dir, profile)
            loaded = load_operator_profile(state_dir)
            self.assertEqual("Pierce", loaded.name)
            path = write_operator_profile_note(memory_root, loaded)
            text = path.read_text(encoding="utf-8")
            self.assertIn("# Operator Profile", text)
            self.assertIn("news.ycombinator.com", text)

    def test_child_followup_questions_are_bounded(self) -> None:
        profile = OperatorProfileState()
        first = next_child_followup_question(profile)
        self.assertIn("where are you right now", first)
        second = next_child_followup_question(profile)
        self.assertIn("what websites do you like checking", second)
        third = next_child_followup_question(profile)
        self.assertEqual("", third)


if __name__ == "__main__":
    unittest.main()
