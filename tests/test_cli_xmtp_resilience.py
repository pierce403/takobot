from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from takobot.cli import RuntimeHooks, _close_xmtp_client, _is_retryable_xmtp_error, _rebuild_xmtp_client


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


class TestCliXmtpResilience(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
