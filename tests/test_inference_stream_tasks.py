from __future__ import annotations

import unittest

from takobot.inference import _codex_item_task_message, _codex_task_from_payload


class TestInferenceStreamTasks(unittest.TestCase):
    def test_codex_item_task_message_detects_web_research(self) -> None:
        task = _codex_item_task_message(
            "item.started",
            {
                "type": "web_search_call",
                "query": "latest XMTP python sdk updates",
            },
        )
        self.assertEqual("browsing web for latest XMTP python sdk updates", task)

    def test_codex_item_task_message_detects_function_call_url(self) -> None:
        task = _codex_item_task_message(
            "item.started",
            {
                "type": "function_call",
                "name": "web.fetch",
                "arguments": "{\"url\":\"https://docs.example.com/guide\"}",
            },
        )
        self.assertEqual("using web.fetch on https://docs.example.com/guide", task)

    def test_codex_item_task_message_marks_completion(self) -> None:
        task = _codex_item_task_message(
            "item.completed",
            {
                "type": "shell_call",
                "command": "ls -la",
            },
        )
        self.assertEqual("completed running command: ls -la", task)

    def test_codex_task_from_payload_ignores_agent_messages(self) -> None:
        task = _codex_task_from_payload(
            "item.completed",
            {
                "item": {
                    "type": "agent_message",
                    "text": "done",
                }
            },
        )
        self.assertIsNone(task)


if __name__ == "__main__":
    unittest.main()
