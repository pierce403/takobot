from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import takobot.xmtp as xmtp_mod
from takobot.xmtp import (
    build_profile_avatar_svg,
    canonical_profile_name,
    close_client,
    create_client,
    ensure_profile_message_for_conversation,
    parse_profile_message,
    publish_profile_message,
    sync_identity_profile,
)


class _FakeConversations:
    def __init__(self, *, dms: list[object] | None = None, groups: list[object] | None = None) -> None:
        self._dms = list(dms or [])
        self._groups = list(groups or [])

    async def list_dms(self) -> list[object]:
        return list(self._dms)

    async def list_groups(self) -> list[object]:
        return list(self._groups)


class _AsyncClosable:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


class _SyncClosable:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


class TestXmtpProfile(unittest.TestCase):
    def test_canonical_profile_name_defaults_and_sanitizes(self) -> None:
        self.assertEqual("Tako", canonical_profile_name(""))
        self.assertEqual("InkTako-01", canonical_profile_name("  InkTako-01!@#  "))

    def test_avatar_svg_is_deterministic(self) -> None:
        first = build_profile_avatar_svg("InkTako")
        second = build_profile_avatar_svg("InkTako")
        self.assertEqual(first, second)
        self.assertIn('aria-label="InkTako avatar"', first)

    def test_parse_profile_message_accepts_legacy_and_cv_prefixes(self) -> None:
        legacy = 'tako:profile:{"type":"profile","v":1,"display_name":"InkTako"}'
        modern = (
            'cv:profile:{"type":"profile","v":1,"displayName":"InkTako",'
            '"avatarUrl":"https://example.com/ink.png","ts":1700000000000}'
        )
        parsed_legacy = parse_profile_message(legacy)
        parsed_modern = parse_profile_message(modern)
        self.assertIsNotNone(parsed_legacy)
        self.assertIsNotNone(parsed_modern)
        assert parsed_legacy is not None
        assert parsed_modern is not None
        self.assertEqual("InkTako", parsed_legacy.name)
        self.assertEqual("InkTako", parsed_modern.name)
        self.assertEqual("https://example.com/ink.png", parsed_modern.avatar_url)

    def test_create_client_uses_cli_info_payload(self) -> None:
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "client.env"
            env_file.write_text("XMTP_WALLET_KEY=0xabc\nXMTP_DB_ENCRYPTION_KEY=0xdef\n", encoding="utf-8")
            db_root = Path(tmp) / "xmtp-db"

            with (
                patch("takobot.xmtp.ensure_workspace_xmtp_runtime_if_needed", return_value=""),
                patch(
                    "takobot.xmtp.ensure_workspace_node_runtime",
                    return_value=SimpleNamespace(ok=True, detail="ok", env={"PATH": "/usr/bin"}),
                ),
                patch("takobot.xmtp.workspace_xmtp_cli_path", return_value=Path("/tmp/fake-xmtp")),
                patch("takobot.xmtp._write_xmtp_client_env", return_value=env_file),
                patch.object(
                    xmtp_mod.XmtpCliClient,
                    "run_json",
                    new=AsyncMock(
                        return_value={
                            "properties": {
                                "inboxId": "a" * 64,
                                "address": "0x1111111111111111111111111111111111111111",
                            }
                        }
                    ),
                ),
            ):
                client = asyncio.run(create_client("production", db_root, "0xabc", "0xdef"))

        self.assertEqual("a" * 64, client.inbox_id)
        self.assertEqual("0x1111111111111111111111111111111111111111", client.address)
        self.assertEqual("xmtp-production.db3", client.db_path.name)

    def test_create_client_rejects_invalid_address(self) -> None:
        with TemporaryDirectory() as tmp:
            env_file = Path(tmp) / "client.env"
            env_file.write_text("XMTP_WALLET_KEY=0xabc\nXMTP_DB_ENCRYPTION_KEY=0xdef\n", encoding="utf-8")
            db_root = Path(tmp) / "xmtp-db"
            with (
                patch("takobot.xmtp.ensure_workspace_xmtp_runtime_if_needed", return_value=""),
                patch(
                    "takobot.xmtp.ensure_workspace_node_runtime",
                    return_value=SimpleNamespace(ok=True, detail="ok", env={"PATH": "/usr/bin"}),
                ),
                patch("takobot.xmtp.workspace_xmtp_cli_path", return_value=Path("/tmp/fake-xmtp")),
                patch("takobot.xmtp._write_xmtp_client_env", return_value=env_file),
                patch.object(
                    xmtp_mod.XmtpCliClient,
                    "run_json",
                    new=AsyncMock(return_value={"properties": {"inboxId": "a" * 64, "address": "not-an-address"}}),
                ),
            ):
                with self.assertRaises(RuntimeError):
                    asyncio.run(create_client("production", db_root, "0xabc", "0xdef"))

    def test_publish_profile_message_queues_known_dm_and_group(self) -> None:
        dm = SimpleNamespace(id_hex="11" * 16, type="dm", peer_inbox_id="peer-inbox")
        self_dm = SimpleNamespace(id_hex="22" * 16, type="dm", peer_inbox_id="self-inbox")
        group = SimpleNamespace(id_hex="33" * 16, type="group", peer_inbox_id="")
        client = SimpleNamespace(
            inbox_id="self-inbox",
            conversations=_FakeConversations(dms=[dm, self_dm], groups=[group]),
        )

        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            with patch(
                "takobot.xmtp._run_profile_helper",
                new=AsyncMock(
                    return_value={
                        "fallbackSelfSent": True,
                        "sentConversationIds": [dm.id_hex, group.id_hex],
                        "errors": [],
                    }
                ),
            ) as helper_mock:
                result = asyncio.run(
                    publish_profile_message(
                        client,
                        state_dir=state_dir,
                        identity_name="InkTako",
                        avatar_url="data:image/svg+xml;base64,AAA",
                        include_self_dm=True,
                        include_known_dm_peers=True,
                        include_known_groups=True,
                    )
                )

            helper_kwargs = helper_mock.call_args.kwargs
            self.assertEqual([dm.id_hex], helper_kwargs["dm_conversation_ids"])
            self.assertEqual([group.id_hex], helper_kwargs["group_conversation_ids"])
            self.assertTrue(result.self_sent)
            self.assertEqual(2, result.peer_sent_count)

            state_payload = json.loads((state_dir / "xmtp-profile-broadcast.json").read_text(encoding="utf-8"))
            self.assertEqual(2, len(state_payload.get("peer_sent", {})))

    def test_ensure_profile_message_for_conversation_targets_single_conversation(self) -> None:
        target = SimpleNamespace(id=b"\xAA\xBB", type="dm", peer_inbox_id="peer-inbox")
        client = SimpleNamespace(
            inbox_id="self-inbox",
            conversations=_FakeConversations(),
        )

        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            with patch(
                "takobot.xmtp._run_profile_helper",
                new=AsyncMock(
                    return_value={
                        "fallbackSelfSent": False,
                        "sentConversationIds": ["aabb"],
                        "errors": [],
                    }
                ),
            ) as helper_mock:
                result = asyncio.run(
                    ensure_profile_message_for_conversation(
                        client,
                        target,
                        state_dir=state_dir,
                        identity_name="InkTako",
                        avatar_url="https://example.com/ink.png",
                    )
                )
            self.assertFalse(result.self_sent)
            self.assertEqual(1, result.peer_sent_count)
            helper_kwargs = helper_mock.call_args.kwargs
            self.assertEqual("aabb", helper_kwargs["target_conversation_id"])
            self.assertEqual(["aabb"], helper_kwargs["dm_conversation_ids"])
            self.assertEqual([], helper_kwargs["group_conversation_ids"])

    def test_sync_identity_profile_writes_state_from_publish_result(self) -> None:
        client = SimpleNamespace(inbox_id="self-inbox", conversations=_FakeConversations())
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            fake_publish = xmtp_mod.XmtpProfileBroadcastResult(
                payload_sha256="abc123",
                self_sent=True,
                peer_sent_count=2,
                errors=(),
            )
            with patch("takobot.xmtp.publish_profile_message", new=AsyncMock(return_value=fake_publish)):
                result = asyncio.run(
                    sync_identity_profile(
                        client,
                        state_dir=state_dir,
                        identity_name="InkTako",
                        generate_avatar=True,
                    )
                )

            self.assertEqual("InkTako", result.name)
            self.assertTrue(result.applied_name)
            self.assertTrue(result.applied_avatar)
            self.assertTrue(result.name_in_sync)
            self.assertTrue(result.avatar_in_sync)
            self.assertTrue(result.state_path.exists())
            payload = json.loads(result.state_path.read_text(encoding="utf-8"))
            self.assertEqual("InkTako", payload["name"])
            self.assertTrue(payload["fallback_self_sent"])
            self.assertEqual(2, payload["fallback_peer_sent_count"])

    def test_close_client_supports_async_and_sync(self) -> None:
        async_client = _AsyncClosable()
        sync_client = _SyncClosable()
        asyncio.run(close_client(async_client))
        asyncio.run(close_client(sync_client))
        self.assertTrue(async_client.closed)
        self.assertTrue(sync_client.closed)


if __name__ == "__main__":
    unittest.main()
