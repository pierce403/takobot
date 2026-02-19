from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.xmtp import (
    build_profile_avatar_svg,
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
            self.assertEqual(["InkTako"], client.name_updates)
            self.assertEqual(1, len(client.avatar_updates))
            self.assertTrue(client.avatar_updates[0].startswith("data:image/svg+xml;base64,"))


if __name__ == "__main__":
    unittest.main()
