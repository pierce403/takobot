from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import takobot.xmtp as xmtp_mod
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


class _FakeGroupFfi:
    def __init__(self, *, app_data: str = "") -> None:
        self._app_data = app_data
        self.updates: list[str] = []

    def app_data(self) -> str:
        return self._app_data

    async def update_app_data(self, encoded: str) -> None:
        self._app_data = encoded
        self.updates.append(encoded)


class _FakeGroupWrapperConversation:
    def __init__(self, conversation_id: bytes, *, app_data: str = "") -> None:
        self.id = conversation_id
        self._ffi = _FakeGroupFfi(app_data=app_data)


class _FakeDmFfi:
    def __init__(self) -> None:
        self._app_data = ""
        self.app_data_updates: list[str] = []
        self.raw_sends: list[tuple[bytes, object]] = []

    def app_data(self) -> str:
        return self._app_data

    async def update_app_data(self, encoded: str) -> None:
        self._app_data = encoded
        self.app_data_updates.append(encoded)

    async def send(self, content_bytes: bytes, opts: object) -> bytes:
        self.raw_sends.append((content_bytes, opts))
        return b"msg-id"


class _FakeDmConversation:
    def __init__(self, conversation_id: bytes, *, peer_inbox_id: str) -> None:
        self.id = conversation_id
        self.peer_inbox_id = peer_inbox_id
        self._ffi = _FakeDmFfi()
        self.sent: list[tuple[object, object | None]] = []

    async def send(self, content: object, content_type: object | None = None) -> bytes:
        if content_type is None:
            raise RuntimeError("content_type is required for profile metadata sends")
        self.sent.append((content, content_type))
        return b"msg-id"


class _FakeDmConversationNoCodec(_FakeDmConversation):
    async def send(self, content: object, content_type: object | None = None) -> bytes:
        raise RuntimeError("codec unavailable for converge profile content type")


class _FakeGroupConversation:
    def __init__(self, conversation_id: bytes, *, app_data: str = "") -> None:
        self.conversation_id = conversation_id
        self.app_data = app_data
        self.updates: list[str] = []

    async def update_app_data(self, encoded: str) -> None:
        self.app_data = encoded
        self.updates.append(encoded)


class _FakeConversations:
    def __init__(
        self,
        groups: list[object],
        *,
        dms: list[object] | None = None,
        self_dms: dict[str, object] | None = None,
        reject_non_address_new_dm: bool = False,
    ) -> None:
        self._groups = groups
        self._dms = list(dms or [])
        self._self_dms = {str(key): value for key, value in (self_dms or {}).items()}
        self._reject_non_address_new_dm = reject_non_address_new_dm
        self.new_dm_calls: list[str] = []

    async def list_groups(self) -> list[object]:
        return list(self._groups)

    async def list_dms(self) -> list[object]:
        return list(self._dms)

    async def new_dm(self, recipient: str) -> object:
        self.new_dm_calls.append(recipient)
        if self._reject_non_address_new_dm and not recipient.startswith("0x"):
            raise RuntimeError("AddressValidation: expected 0x address")
        value = self._self_dms.get(recipient)
        if value is None:
            raise RuntimeError("dm unavailable")
        return value


class _ClientWithBroadcastFallback:
    def __init__(self) -> None:
        self.inbox_id = "inbox-self"
        self.account_identifier = _FakeIdentifier("0x1111111111111111111111111111111111111111")
        self.group = _FakeGroupWrapperConversation(b"\x01profile")
        self.conversations = _FakeConversations([self.group])


class _ClientWithDmFallback:
    def __init__(self, *, dm: _FakeDmConversation | None = None) -> None:
        self.inbox_id = "inbox-self"
        self.account_identifier = _FakeIdentifier("0x1111111111111111111111111111111111111111")
        self.dm = dm or _FakeDmConversation(b"\x02profile", peer_inbox_id="inbox-peer")
        self.self_dm = _FakeDmConversation(b"\x03profile", peer_inbox_id="inbox-self")
        self.conversations = _FakeConversations(
            [],
            dms=[self.dm],
            self_dms={
                "inbox-self": self.self_dm,
                "0x1111111111111111111111111111111111111111": self.self_dm,
            },
        )


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

    def test_sync_profile_upserts_profile_metadata_into_group_app_data(self) -> None:
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

            self.assertFalse(result.fallback_self_sent)
            self.assertEqual(1, result.fallback_peer_sent_count)
            self.assertEqual(1, len(client.group._ffi.updates))
            raw_blob, decode_error = xmtp_mod._decode_convos_app_data(client.group._ffi.app_data())
            self.assertIsNone(decode_error)
            proto_classes = xmtp_mod._convos_proto_classes()
            self.assertIsNotNone(proto_classes)
            assert proto_classes is not None
            metadata_cls, _profile_cls = proto_classes
            metadata = metadata_cls()
            metadata.ParseFromString(raw_blob)
            self.assertEqual(1, len(metadata.profiles))
            profile = metadata.profiles[0]
            self.assertEqual(xmtp_mod._inbox_id_to_bytes(client.inbox_id), bytes(profile.inboxId))
            self.assertEqual("InkTako", profile.name)
            self.assertTrue(profile.image.startswith("data:image/svg+xml;base64,"))

    def test_publish_profile_message_sends_converge_metadata_for_dm(self) -> None:
        client = _ClientWithDmFallback()
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            avatar_url = _avatar_data_uri("InkTako")
            result = asyncio.run(
                xmtp_mod.publish_profile_message(
                    client,
                    state_dir=state_dir,
                    identity_name="InkTako",
                    avatar_url=avatar_url,
                    include_self_dm=False,
                    include_known_dm_peers=False,
                    include_known_groups=False,
                    target_conversation=client.dm,
                )
            )

            self.assertFalse(result.self_sent)
            self.assertEqual(1, result.peer_sent_count)
            self.assertEqual(1, len(client.dm.sent))
            self.assertEqual([], client.dm._ffi.app_data_updates)
            payload, content_type = client.dm.sent[0]
            self.assertIsInstance(payload, (bytes, bytearray))
            parsed_payload = json.loads(bytes(payload).decode("utf-8"))
            self.assertEqual("profile", parsed_payload["type"])
            self.assertEqual(1, parsed_payload["v"])
            self.assertEqual("InkTako", parsed_payload["displayName"])
            self.assertEqual(avatar_url, parsed_payload["avatarUrl"])
            self.assertIn("ts", parsed_payload)
            self.assertIsInstance(parsed_payload["ts"], int)
            if isinstance(content_type, dict):
                self.assertEqual("converge.cv", content_type.get("authorityId"))
                self.assertEqual("profile", content_type.get("typeId"))
                self.assertEqual(1, content_type.get("versionMajor"))
                self.assertEqual(0, content_type.get("versionMinor"))
            else:
                self.assertEqual("converge.cv/profile:1.0", str(content_type))

    def test_publish_profile_message_dm_uses_ffi_fallback_when_codec_missing(self) -> None:
        dm = _FakeDmConversationNoCodec(b"\x04profile", peer_inbox_id="inbox-peer")
        client = _ClientWithDmFallback(dm=dm)
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            result = asyncio.run(
                xmtp_mod.publish_profile_message(
                    client,
                    state_dir=state_dir,
                    identity_name="InkTako",
                    avatar_url=_avatar_data_uri("InkTako"),
                    include_self_dm=False,
                    include_known_dm_peers=False,
                    include_known_groups=False,
                    target_conversation=dm,
                )
            )

            self.assertEqual(1, result.peer_sent_count)
            self.assertEqual([], dm.sent)
            self.assertEqual(1, len(dm._ffi.raw_sends))
            raw_payload, send_opts = dm._ffi.raw_sends[0]
            self.assertIsInstance(raw_payload, (bytes, bytearray))
            self.assertGreater(len(raw_payload), 0)
            self.assertFalse(getattr(send_opts, "should_push", True))

    def test_publish_profile_message_self_dm_uses_account_address_when_new_dm_validates_address(self) -> None:
        client = _ClientWithDmFallback()
        client.conversations = _FakeConversations(
            [],
            dms=[],
            self_dms={"0x1111111111111111111111111111111111111111": client.self_dm},
            reject_non_address_new_dm=True,
        )
        with TemporaryDirectory() as tmp:
            state_dir = Path(tmp) / "state"
            result = asyncio.run(
                xmtp_mod.publish_profile_message(
                    client,
                    state_dir=state_dir,
                    identity_name="InkTako",
                    avatar_url=_avatar_data_uri("InkTako"),
                    include_self_dm=True,
                    include_known_dm_peers=False,
                    include_known_groups=False,
                )
            )

            self.assertTrue(result.self_sent)
            self.assertEqual(1, len(client.self_dm.sent))
            self.assertEqual(["0x1111111111111111111111111111111111111111"], client.conversations.new_dm_calls)
            self.assertFalse(any("AddressValidation" in item for item in result.errors))

    def test_parse_profile_message_returns_none_for_non_profile_text(self) -> None:
        self.assertIsNone(parse_profile_message("hello world"))
        self.assertIsNone(parse_profile_message('{"hello":"world"}'))
        self.assertIsNone(parse_profile_message('cv:profile:{"hello":"world"}'))

    def test_parse_profile_message_accepts_legacy_prefixed_payload(self) -> None:
        legacy = 'tako:profile:{"type":"profile","v":1,"display_name":"InkTako"}'
        parsed = parse_profile_message(legacy)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual("InkTako", parsed.name)

    def test_parse_profile_message_accepts_cv_prefixed_payload(self) -> None:
        modern = 'cv:profile:{"type":"profile","v":1,"displayName":"InkTako","avatarUrl":"https://example.com/ink.png","ts":1700000000000}'
        parsed = parse_profile_message(modern)
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual("InkTako", parsed.name)
        self.assertEqual("https://example.com/ink.png", parsed.avatar_url)


if __name__ == "__main__":
    unittest.main()
