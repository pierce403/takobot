from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from takobot.cli import (
    _ConversationWithTyping,
    RuntimeHooks,
    _canonical_identity_name,
    _chat_prompt,
    _close_xmtp_client,
    _is_retryable_xmtp_error,
    _rebuild_xmtp_client,
)


class _DummyAsyncClosable:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _DummySyncClosable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class _DummyConversation:
    def __init__(self) -> None:
        self.peer_inbox_id = "peer-inbox-123456"
        self.sent: list[object] = []

    async def send(self, content: object, content_type: object | None = None) -> object:
        if content_type is None:
            self.sent.append(content)
        else:
            self.sent.append((content, content_type))
        return {"ok": True}


class TestCliXmtpResilience(unittest.TestCase):
    def test_cli_canonical_identity_name_defaults(self) -> None:
        self.assertEqual("Tako", _canonical_identity_name(""))
        self.assertEqual("ProTako", _canonical_identity_name(" ProTako "))

    def test_cli_chat_prompt_uses_identity_name(self) -> None:
        prompt = _chat_prompt(
            "hello",
            history="User: hi",
            is_operator=True,
            operator_paired=True,
            identity_name="ProTako",
        )
        self.assertIn("You are ProTako", prompt)
        self.assertIn("Canonical identity name: ProTako", prompt)
        self.assertIn("Never claim your name is `Tako`", prompt)

    def test_retryable_xmtp_error_detection(self) -> None:
        self.assertTrue(_is_retryable_xmtp_error(RuntimeError("grpc-status header missing")))
        self.assertTrue(_is_retryable_xmtp_error(RuntimeError("deadline exceeded while sending message")))
        self.assertFalse(_is_retryable_xmtp_error(RuntimeError("invalid inbox id")))

    def test_close_xmtp_client_supports_async_and_sync(self) -> None:
        async_client = _DummyAsyncClosable()
        sync_client = _DummySyncClosable()
        asyncio.run(_close_xmtp_client(async_client))
        asyncio.run(_close_xmtp_client(sync_client))
        self.assertTrue(async_client.closed)
        self.assertTrue(sync_client.closed)

    def test_rebuild_xmtp_client_success(self) -> None:
        old_client = _DummySyncClosable()
        new_client = object()
        with TemporaryDirectory() as tmp:
            with patch("takobot.cli.create_client", return_value=new_client):
                rebuilt = asyncio.run(
                    _rebuild_xmtp_client(
                        old_client,
                        env="production",
                        db_root=Path(tmp),
                        wallet_key="0xabc",
                        db_encryption_key="0xdef",
                        hooks=RuntimeHooks(emit_console=False),
                    )
                )
        self.assertIs(rebuilt, new_client)
        self.assertTrue(old_client.closed)

    def test_rebuild_xmtp_client_failure_returns_none(self) -> None:
        old_client = _DummySyncClosable()
        with TemporaryDirectory() as tmp:
            with patch("takobot.cli.create_client", side_effect=RuntimeError("timeout")):
                rebuilt = asyncio.run(
                    _rebuild_xmtp_client(
                        old_client,
                        env="production",
                        db_root=Path(tmp),
                        wallet_key="0xabc",
                        db_encryption_key="0xdef",
                        hooks=RuntimeHooks(emit_console=False),
                    )
                )
        self.assertIsNone(rebuilt)

    def test_conversation_send_emits_outbound_hook(self) -> None:
        outbound: list[tuple[str, str]] = []

        def _capture(recipient: str, text: str) -> None:
            outbound.append((recipient, text))

        convo = _DummyConversation()
        wrapped = _ConversationWithTyping(convo, hooks=RuntimeHooks(outbound_message=_capture, emit_console=False))
        with patch("takobot.cli.set_typing_indicator", return_value=False):
            asyncio.run(wrapped.send("hello from takobot"))
        self.assertEqual(["hello from takobot"], convo.sent)
        self.assertEqual([("peer-inbox-123456", "hello from takobot")], outbound)


if __name__ == "__main__":
    unittest.main()
