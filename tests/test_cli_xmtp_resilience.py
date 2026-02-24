from __future__ import annotations

import asyncio
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from takobot.conversation import ConversationStore
from takobot.cli import (
    _ConversationWithTyping,
    _fallback_chat_reply,
    RuntimeHooks,
    _chat_reply,
    _canonical_identity_name,
    _chat_prompt,
    _close_xmtp_client,
    _looks_like_command,
    _notify_update_applied,
    _is_retryable_xmtp_error,
    _rebuild_xmtp_client,
    _send_operator_startup_presence,
    _startup_profile_confirmation_line,
    _startup_presence_message,
)
from takobot.inference import InferenceProviderStatus, InferenceRuntime


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


class _DummyConversationFactory:
    def __init__(self, *, fail_for: set[str] | None = None) -> None:
        self.fail_for = set(fail_for or set())
        self.recipients: list[str] = []
        self.created: list[_DummyConversation] = []

    async def new_dm(self, recipient: str):
        self.recipients.append(recipient)
        if recipient in self.fail_for:
            raise RuntimeError(f"cannot open dm for {recipient}")
        convo = _DummyConversation()
        self.created.append(convo)
        return convo


class TestCliXmtpResilience(unittest.TestCase):
    @staticmethod
    def _pi_runtime() -> InferenceRuntime:
        status = InferenceProviderStatus(
            provider="pi",
            cli_name="pi",
            cli_path="/usr/bin/pi",
            cli_installed=True,
            auth_kind="oauth_or_profile",
            key_env_var=None,
            key_source="file:~/.pi/agent/auth.json",
            key_present=True,
            ready=True,
            note="",
        )
        return InferenceRuntime(
            statuses={"pi": status},
            selected_provider="pi",
            selected_auth_kind=status.auth_kind,
            selected_key_env_var=status.key_env_var,
            selected_key_source=status.key_source,
            _api_keys={},
        )

    @staticmethod
    def _pi_runtime_not_ready() -> InferenceRuntime:
        status = InferenceProviderStatus(
            provider="pi",
            cli_name="pi",
            cli_path="/usr/bin/pi",
            cli_installed=True,
            auth_kind="oauth_or_profile",
            key_env_var=None,
            key_source="file:~/.pi/agent/auth.json",
            key_present=False,
            ready=False,
            note="auth missing",
        )
        return InferenceRuntime(
            statuses={"pi": status},
            selected_provider="pi",
            selected_auth_kind=status.auth_kind,
            selected_key_env_var=status.key_env_var,
            selected_key_source=status.key_source,
            _api_keys={},
        )

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
            identity_role="Your highly autonomous octopus friend",
            mission_objectives=["Keep outcomes clear", "Stay curious"],
            life_stage="child",
            stage_tone="curious",
            memory_frontmatter="# MEMORY frontmatter",
            soul_excerpt="# SOUL.md\n- Name: ProTako",
            focus_summary="balanced (0.50)",
            rag_context="1. score=0.9123 source=memory/world/2026-02-17.md",
        )
        self.assertIn("You are ProTako", prompt)
        self.assertIn("Canonical identity name: ProTako", prompt)
        self.assertIn("Never claim your name is `Tako`", prompt)
        self.assertIn("Mission objectives: Keep outcomes clear | Stay curious", prompt)
        self.assertIn("soul_identity_boundaries=", prompt)
        self.assertIn("skills_frontmatter=", prompt)
        self.assertIn("tools_frontmatter=", prompt)
        self.assertIn("skills_inventory=", prompt)
        self.assertIn("tools_inventory=", prompt)
        self.assertIn("focus_state=balanced (0.50)", prompt)
        self.assertIn("memory_rag_context=", prompt)
        self.assertIn("Do not ask which channel the operator is using", prompt)
        self.assertIn("If the operator asks for identity/config changes, apply them directly", prompt)
        self.assertIn("runtime supports profile sync with Converge 1:1 metadata", prompt)

    def test_retryable_xmtp_error_detection(self) -> None:
        self.assertTrue(_is_retryable_xmtp_error(RuntimeError("grpc-status header missing")))
        self.assertTrue(_is_retryable_xmtp_error(RuntimeError("deadline exceeded while sending message")))
        self.assertFalse(_is_retryable_xmtp_error(RuntimeError("invalid inbox id")))

    def test_command_detection_includes_jobs_and_exec(self) -> None:
        self.assertTrue(_looks_like_command("jobs"))
        self.assertTrue(_looks_like_command("jobs add every day at 3pm run doctor"))
        self.assertTrue(_looks_like_command("exec printf 'ok'"))
        self.assertFalse(_looks_like_command("tell me about octopus habitats"))

    def test_operator_fallback_reply_includes_openai_reauth_guidance(self) -> None:
        reply = _fallback_chat_reply(
            is_operator=True,
            operator_paired=True,
            last_error=(
                "inference provider fallback exhausted: pi: token refresh failed: 401 "
                "refresh token has already been used (openai-codex)"
            ),
            error_log_path="/tmp/error.log",
        )
        self.assertIn("inference login force", reply)
        self.assertIn("local terminal", reply)
        self.assertIn("exec", reply)

    def test_operator_fallback_reply_mentions_auto_repair_attempt(self) -> None:
        reply = _fallback_chat_reply(
            is_operator=True,
            operator_paired=True,
            auto_repair_attempted=True,
        )
        self.assertIn("already attempted automatic inference recovery", reply)

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

    def test_chat_reply_logs_pi_turn_summaries(self) -> None:
        runtime = self._pi_runtime()
        with TemporaryDirectory() as tmp:
            conversations = ConversationStore(Path(tmp))
            runtime_logs: list[tuple[str, str]] = []

            def _capture(level: str, message: str) -> None:
                runtime_logs.append((level, message))

            hooks = RuntimeHooks(log=_capture, emit_console=False)
            with patch("takobot.cli.run_inference_prompt_with_fallback", return_value=("pi", "assistant reply")):
                reply = asyncio.run(
                    _chat_reply(
                        "hello there",
                        runtime,
                        paths=SimpleNamespace(state_dir=Path(tmp) / ".tako" / "state"),
                        conversations=conversations,
                        session_key="xmtp:test",
                        is_operator=True,
                        operator_paired=True,
                        hooks=hooks,
                    )
                )

        self.assertEqual("assistant reply", reply)
        combined = "\n".join(message for _level, message in runtime_logs)
        self.assertIn("pi chat user: hello there", combined)
        self.assertIn("pi chat assistant: assistant reply", combined)

    def test_chat_reply_attempts_auto_repair_when_runtime_not_ready(self) -> None:
        runtime = self._pi_runtime_not_ready()
        recovered_runtime = self._pi_runtime()
        with TemporaryDirectory() as tmp:
            conversations = ConversationStore(Path(tmp))
            with (
                patch("takobot.cli.auto_repair_inference_runtime", return_value=["auth synced from workspace"]),
                patch("takobot.cli.discover_inference_runtime", return_value=recovered_runtime),
                patch("takobot.cli.run_inference_prompt_with_fallback", return_value=("pi", "recovered reply")),
            ):
                reply = asyncio.run(
                    _chat_reply(
                        "hello there",
                        runtime,
                        paths=SimpleNamespace(state_dir=Path(tmp) / ".tako" / "state"),
                        conversations=conversations,
                        session_key="xmtp:test",
                        is_operator=True,
                        operator_paired=True,
                        hooks=RuntimeHooks(emit_console=False),
                    )
                )
        self.assertEqual("recovered reply", reply)

    def test_startup_presence_message_contains_state_summary(self) -> None:
        message = _startup_presence_message(
            identity_name="ProTako",
            env="production",
            address="0xabc123",
            stage="adult",
            inference_runtime=self._pi_runtime(),
            jobs_count=3,
            open_tasks_count=5,
            xmtp_profile=_startup_profile_confirmation_line(None),
        )
        self.assertIn("ProTako is back online.", message)
        self.assertIn("version:", message)
        self.assertIn("stage: adult", message)
        self.assertIn("inference: pi ready=yes", message)
        self.assertIn("xmtp profile: converge.cv/profile:1.0 status=sync-failed", message)
        self.assertIn("jobs: 3", message)
        self.assertIn("open tasks: 5", message)

    def test_send_operator_startup_presence_prefers_address_then_falls_back_to_inbox(self) -> None:
        factory = _DummyConversationFactory(fail_for={"0xoperator"})
        client = SimpleNamespace(conversations=factory)
        with patch("takobot.cli.set_typing_indicator", return_value=False):
            sent = asyncio.run(
                _send_operator_startup_presence(
                    client,
                    operator_cfg={"operator_inbox_id": "inbox-123", "operator_address": "0xoperator"},
                    message="Takobot is back online.",
                    hooks=RuntimeHooks(emit_console=False),
                )
            )
        self.assertTrue(sent)
        self.assertEqual(["0xoperator", "inbox-123"], factory.recipients)
        self.assertEqual(1, len(factory.created))
        self.assertEqual(["Takobot is back online."], factory.created[0].sent)

    def test_notify_update_applied_supports_sync_callback(self) -> None:
        calls: list[str] = []

        def _capture(summary: str) -> None:
            calls.append(summary)

        changed = asyncio.run(_notify_update_applied(RuntimeHooks(update_applied=_capture, emit_console=False), "updated"))
        self.assertTrue(changed)
        self.assertEqual(["updated"], calls)

    def test_notify_update_applied_supports_async_callback(self) -> None:
        calls: list[str] = []

        async def _capture(summary: str) -> None:
            calls.append(summary)

        changed = asyncio.run(_notify_update_applied(RuntimeHooks(update_applied=_capture, emit_console=False), "updated"))
        self.assertTrue(changed)
        self.assertEqual(["updated"], calls)


if __name__ == "__main__":
    unittest.main()
