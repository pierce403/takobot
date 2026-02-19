from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.xmtp import (
    build_profile_avatar_svg,
    parse_profile_message,
    canonical_profile_name,
    sync_identity_profile,
)


class _ClientWithoutProfileApi:
    pass


class _ClientWithProfileApi:
    def __init__(self) -> None:
        self.name_updates: list[str] = []
        self.avatar_updates: list[str] = []

    async def set_display_name(self, value: str) -> None:
        self.name_updates.append(value)

    async def set_avatar_url(self, value: str) -> None:
        self.avatar_updates.append(value)


class _ClientWithReadableProfileApi:
    def __init__(self, *, display_name: str, avatar_url: str) -> None:
        self.profile = {"display_name": display_name, "avatar_url": avatar_url}
        self.name_updates: list[str] = []
        self.avatar_updates: list[str] = []

    async def get_profile(self) -> dict[str, str]:
        return dict(self.profile)

    async def set_display_name(self, value: str) -> None:
        self.name_updates.append(value)
        self.profile["display_name"] = value

    async def set_avatar_url(self, value: str) -> None:
        self.avatar_updates.append(value)
        self.profile["avatar_url"] = value


class _FakeIdentifier:
    def __init__(self, value: str) -> None:
        self.value = value


class _FakeDmConversation:
    def __init__(self, peer_inbox_id: str) -> None:
        self.peer_inbox_id = peer_inbox_id
        self.sent: list[tuple[str, object | None]] = []

    async def send(self, content: str, content_type: object | None = None) -> None:
        self.sent.append((content, content_type))


class _FakeConversations:
    def __init__(self, dms: list[_FakeDmConversation], self_dm: _FakeDmConversation) -> None:
        self._dms = dms
        self._self_dm = self_dm

    async def list_dms(self) -> list[_FakeDmConversation]:
        return list(self._dms)

    async def new_dm(self, _address: str) -> _FakeDmConversation:
        return self._self_dm


class _ClientWithBroadcastFallback:
    def __init__(self) -> None:
        self.inbox_id = "inbox-self"
        self.account_identifier = _FakeIdentifier("0x1111111111111111111111111111111111111111")
        self.self_dm = _FakeDmConversation("inbox-self")
        self.peer_dm = _FakeDmConversation("inbox-peer")
        self.conversations = _FakeConversations([self.peer_dm], self.self_dm)
        self.codecs: list[object] = []

    def register_codec(self, codec: object) -> None:
        self.codecs.append(codec)


def _avatar_data_uri(name: str) -> str:
    svg = build_profile_avatar_svg(name)
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


class TestXmtpProfile(unittest.TestCase):
    def test_canonical_profile_name_defaults_and_sanitizes(self) -> None:
        self.assertEqual("Tako", canonical_profile_name(""))
        self.assertEqual("InkTako-01", canonical_profile_name("  InkTako-01!@#  "))

    def test_avatar_svg_is_deterministic(self) -> None:
        first = build_profile_avatar_svg("InkTako")
        second = build_profile_avatar_svg("InkTako")
        self.assertEqual(first, second)
        self.assertIn("aria-label=\"InkTako avatar\"", first)

    def test_sync_profile_generates_state_when_api_missing(self) -> None:
        client = _ClientWithoutProfileApi()
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            result = asyncio.run(
                sync_identity_profile(
                    client,
                    state_dir=state_dir,
                    identity_name="InkTako",
                    generate_avatar=True,
                )
            )

            self.assertEqual("InkTako", result.name)
            self.assertFalse(result.profile_read_api_found)
            self.assertFalse(result.profile_api_found)
            self.assertFalse(result.applied_name)
            self.assertFalse(result.applied_avatar)
            self.assertFalse(result.name_in_sync)
            self.assertFalse(result.avatar_in_sync)
            self.assertFalse(result.fallback_self_sent)
            self.assertEqual(0, result.fallback_peer_sent_count)
            self.assertIsNotNone(result.avatar_path)
            self.assertTrue(result.avatar_path.exists())
            self.assertTrue(result.state_path.exists())

            payload = json.loads(result.state_path.read_text(encoding="utf-8"))
            self.assertEqual("InkTako", payload["name"])
            self.assertFalse(payload["profile_read_api_found"])
            self.assertFalse(payload["profile_api_found"])
            self.assertFalse(payload["applied_name"])
            self.assertFalse(payload["applied_avatar"])
            self.assertFalse(payload["name_in_sync"])
            self.assertFalse(payload["avatar_in_sync"])
            self.assertFalse(payload["fallback_self_sent"])
            self.assertEqual(0, payload["fallback_peer_sent_count"])

    def test_sync_profile_uses_available_profile_methods(self) -> None:
        client = _ClientWithProfileApi()
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            result = asyncio.run(
                sync_identity_profile(
                    client,
                    state_dir=state_dir,
                    identity_name="InkTako",
                    generate_avatar=True,
                )
            )

            self.assertFalse(result.profile_read_api_found)
            self.assertTrue(result.profile_api_found)
            self.assertTrue(result.applied_name)
            self.assertTrue(result.applied_avatar)
            self.assertTrue(result.name_in_sync)
            self.assertTrue(result.avatar_in_sync)
            self.assertFalse(result.fallback_self_sent)
            self.assertEqual(0, result.fallback_peer_sent_count)
            self.assertEqual(["InkTako"], client.name_updates)
            self.assertEqual(1, len(client.avatar_updates))
            self.assertTrue(client.avatar_updates[0].startswith("data:image/svg+xml;base64,"))

    def test_sync_profile_skips_write_when_profile_already_matches(self) -> None:
        client = _ClientWithReadableProfileApi(
            display_name="InkTako",
            avatar_url=_avatar_data_uri("InkTako"),
        )
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            result = asyncio.run(
                sync_identity_profile(
                    client,
                    state_dir=state_dir,
                    identity_name="InkTako",
                    generate_avatar=True,
                )
            )

            self.assertTrue(result.profile_read_api_found)
            self.assertFalse(result.profile_api_found)
            self.assertFalse(result.applied_name)
            self.assertFalse(result.applied_avatar)
            self.assertTrue(result.name_in_sync)
            self.assertTrue(result.avatar_in_sync)
            self.assertFalse(result.fallback_self_sent)
            self.assertEqual(0, result.fallback_peer_sent_count)
            self.assertEqual([], client.name_updates)
            self.assertEqual([], client.avatar_updates)

    def test_sync_profile_updates_when_verified_profile_mismatched(self) -> None:
        client = _ClientWithReadableProfileApi(
            display_name="Old Name",
            avatar_url="https://example.com/old-avatar.png",
        )
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            result = asyncio.run(
                sync_identity_profile(
                    client,
                    state_dir=state_dir,
                    identity_name="InkTako",
                    generate_avatar=True,
                )
            )

            self.assertTrue(result.profile_read_api_found)
            self.assertTrue(result.profile_api_found)
            self.assertTrue(result.applied_name)
            self.assertTrue(result.applied_avatar)
            self.assertTrue(result.name_in_sync)
            self.assertTrue(result.avatar_in_sync)
            self.assertFalse(result.fallback_self_sent)
            self.assertEqual(0, result.fallback_peer_sent_count)
            self.assertEqual(["InkTako"], client.name_updates)
            self.assertEqual(1, len(client.avatar_updates))
            self.assertTrue(client.avatar_updates[0].startswith("data:image/svg+xml;base64,"))

    def test_sync_profile_broadcasts_profile_message_to_self_and_peer_dm(self) -> None:
        client = _ClientWithBroadcastFallback()
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            result = asyncio.run(
                sync_identity_profile(
                    client,
                    state_dir=state_dir,
                    identity_name="InkTako",
                    generate_avatar=True,
                )
            )

            self.assertTrue(result.fallback_self_sent)
            self.assertEqual(1, result.fallback_peer_sent_count)
            self.assertEqual(1, len(client.self_dm.sent))
            self.assertEqual(1, len(client.peer_dm.sent))

            self_message = client.self_dm.sent[0][0]
            peer_message = client.peer_dm.sent[0][0]
            self.assertTrue(self_message.startswith("tako:profile:"))
            self.assertTrue(peer_message.startswith("tako:profile:"))

            parsed = parse_profile_message(peer_message)
            self.assertIsNotNone(parsed)
            assert parsed is not None
            self.assertEqual("InkTako", parsed.name)
            self.assertTrue((parsed.avatar_url or "").startswith("data:image/svg+xml;base64,"))

    def test_parse_profile_message_returns_none_for_non_profile_text(self) -> None:
        self.assertIsNone(parse_profile_message("hello world"))


if __name__ == "__main__":
    unittest.main()
