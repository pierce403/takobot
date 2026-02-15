from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.conversation import ConversationMessage, ConversationStore, limit_history_turns


class TestConversationHistory(unittest.TestCase):
    def test_limit_history_turns_keeps_last_user_turns(self) -> None:
        messages = [
            ConversationMessage(role="user", text="u1"),
            ConversationMessage(role="assistant", text="a1"),
            ConversationMessage(role="user", text="u2"),
            ConversationMessage(role="assistant", text="a2"),
            ConversationMessage(role="user", text="u3"),
            ConversationMessage(role="assistant", text="a3"),
        ]
        limited = limit_history_turns(messages, 2)
        self.assertEqual(["u2", "a2", "u3", "a3"], [item.text for item in limited])

    def test_store_roundtrip_and_prompt_context(self) -> None:
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / ".tako" / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            store = ConversationStore(state_dir)
            session_key = "terminal:main"

            store.append_user_assistant(session_key, "hello octopus", "hello human")
            store.append_user_assistant(session_key, "can you summarize?", "yes. short version.")

            recent = store.recent_messages(session_key, user_turn_limit=2, max_chars=8_000)
            self.assertEqual(4, len(recent))
            self.assertEqual("hello octopus", recent[0].text)
            self.assertEqual("yes. short version.", recent[-1].text)

            context = store.format_prompt_context(session_key, user_turn_limit=2, max_chars=8_000)
            self.assertIn("Recent conversation context", context)
            self.assertIn("User: hello octopus", context)
            self.assertIn("Takobot: yes. short version.", context)

    def test_recent_messages_respects_char_budget(self) -> None:
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / ".tako" / "state"
            state_dir.mkdir(parents=True, exist_ok=True)
            store = ConversationStore(state_dir)
            session_key = "xmtp:conversation-1"

            store.append_user_assistant(
                session_key,
                "one " * 20,
                "reply one " * 20,
            )
            store.append_user_assistant(
                session_key,
                "two " * 20,
                "reply two " * 20,
            )

            recent = store.recent_messages(session_key, user_turn_limit=5, max_chars=120)
            self.assertGreaterEqual(len(recent), 1)
            self.assertLessEqual(sum(len(item.text) for item in recent), 120)
