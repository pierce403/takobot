from __future__ import annotations

import asyncio
from contextlib import ExitStack
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from takobot.app import TakoTerminalApp, _looks_like_local_command
from takobot.cli import RuntimeHooks, _chat_prompt, _chat_reply, _handle_incoming_message, _looks_like_command
from takobot.conversation import ConversationStore
from takobot.learning import LearningError
from takobot.learning_runtime import LearningService


PROCEDURE = {
    "name": "Validate document JSON", "trigger": "When converting a document to strict JSON",
    "steps": ["Identify required keys.", "Return only valid JSON with the required keys."],
    "pitfalls": ["Do not add Markdown fences."], "verification": ["Parse the output as JSON."],
}
REQUEST = "Convert this document into a validated JSON object."
RESPONSE = "I returned a JSON object with the requested keys and checked that it parses."


class LearningRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.state_dir = self.root / ".tako" / "state"
        self.runtime = SimpleNamespace(ready=True, selected_provider="pi", providers=[], statuses={})
        self.configure()
        self.service = LearningService(self.root, self.state_dir, self.runtime)
        self.model_patch = patch("takobot.learning_runtime.inference_model_for_lane", return_value="provider/model")
        self.model_patch.start()

    def tearDown(self) -> None:
        self.model_patch.stop()
        self.tmp.cleanup()

    def configure(self, *, enabled: bool = True, review_every: int = 2,
                  budget: int = 6, cooldown: int = 0, auto_promote: bool = False) -> None:
        (self.root / "tako.toml").write_text(
            f"[learning]\nenabled = {str(enabled).lower()}\nreview_every = {review_every}\n"
            f"daily_call_budget = {budget}\ncooldown_seconds = {cooldown}\n"
            f"auto_promote = {str(auto_promote).lower()}\n", encoding="utf-8",
        )

    async def drain(self, service: LearningService | None = None) -> None:
        task = (service or self.service)._task
        if task is not None:
            await asyncio.wait_for(task, timeout=3)

    def evidence(self, index: int = 0) -> str:
        return self.service.store.record_turn("terminal:main", f"{REQUEST} {index}", RESPONSE)

    async def test_auto_review_cadence_unknown_outcome_and_no_auto_activation(self) -> None:
        with patch("takobot.learning_runtime.run_learning_inference", return_value=json.dumps(PROCEDURE)) as infer:
            first = self.service.record_turn("terminal:main", REQUEST, RESPONSE)
            await self.drain()
            infer.assert_not_called()
            second = self.service.record_turn("terminal:main", REQUEST + " More detail.", RESPONSE)
            await self.drain()
        self.assertNotEqual(first, second)
        self.assertEqual(1, infer.call_count)
        self.assertEqual(["unknown", "unknown"], [e["outcome"] for e in self.service.store.recent_experiences()])
        self.assertEqual(1, len(self.service.status()["candidates"]))
        self.assertEqual([], self.service.status()["active"])
        self.assertEqual(1, self.service.status()["calls_used"])

    async def test_failure_reserves_budget_and_dedup_survives_restart(self) -> None:
        self.configure(budget=1)
        self.evidence()
        with patch("takobot.learning_runtime.run_learning_inference", side_effect=RuntimeError("secret-token-value")) as infer:
            self.service.schedule_review(manual=True)
            await self.drain()
            restarted = LearningService(self.root, self.state_dir, self.runtime)
            restarted.schedule_review(manual=True)
            await self.drain(restarted)
            restarted.store.record_turn("terminal:main", REQUEST + " new evidence", RESPONSE)
            restarted.schedule_review(manual=True)
            await self.drain(restarted)
        self.assertEqual(1, infer.call_count)
        state = restarted.status()
        self.assertEqual(1, state["calls_used"])
        self.assertNotIn("secret-token-value", json.dumps(state))
        self.assertIn("budget", state["last_result"])

    async def test_nonoperator_disabled_and_short_turns_do_not_learn(self) -> None:
        self.assertIsNone(self.service.record_turn("xmtp:stranger", REQUEST, RESPONSE, operator=False))
        self.assertEqual(("", ()), self.service.context(REQUEST, operator=False))
        self.assertIsNone(self.service.record_turn("terminal:main", "hi", "hello"))
        self.configure(enabled=False)
        self.assertIsNone(self.service.record_turn("terminal:main", REQUEST, RESPONSE))
        self.assertEqual(("", ()), self.service.context(REQUEST))
        self.assertFalse(self.state_dir.exists())
        response = await self.service.command("review", operator=False)
        self.assertIn("Operator-only", response)
        self.assertFalse(self.state_dir.exists())

    async def test_config_reread_and_budget_shared_by_all_inference_calls(self) -> None:
        with patch("takobot.learning_runtime.run_learning_inference", return_value="ok") as infer:
            await self.service._infer("first", model="provider/model")
            self.configure(budget=1)
            with self.assertRaisesRegex(LearningError, "budget"):
                await self.service._infer("second", model="provider/model")
            self.configure(enabled=False)
            with self.assertRaisesRegex(LearningError, "disabled"):
                await self.service._infer("third", model="provider/model")
        self.assertEqual(1, infer.call_count)

    async def test_auto_promote_requires_complete_independent_gates(self) -> None:
        self.configure(review_every=1, auto_promote=True)
        self.service.store.evaluations_path.write_text(json.dumps({"version": 1, "cases": [
            {"id": "dev", "split": "development", "prompt": "Return development value", "expected": "dev-ok", "check": "exact"},
            {"id": "held", "split": "holdout", "prompt": "Return heldout value", "expected": "held-ok", "check": "exact"},
        ]}), encoding="utf-8")

        def infer(runtime, prompt, **kwargs):
            if "Extract one reusable" in prompt:
                return json.dumps(PROCEDURE)
            if "heldout value" in prompt:
                return "held-ok"
            return "dev-ok" if "Advisory procedure" in prompt else "wrong"

        with patch("takobot.learning_runtime.run_learning_inference", side_effect=infer) as calls:
            self.service.record_turn("terminal:main", REQUEST, RESPONSE)
            await self.drain()
        status = self.service.status()
        self.assertEqual(5, calls.call_count)
        self.assertEqual(5, status["calls_used"])
        self.assertEqual(1, len(status["active"]))
        report = self.service.store.report(status["active"][0])
        self.assertTrue(report["eligible"])
        self.assertEqual(0, report["heldout_regressions"])

    async def test_generation_runs_in_background_without_blocking_chat(self) -> None:
        started, finish = asyncio.Event(), asyncio.Event()

        async def propose(infer, *, model):
            started.set()
            await finish.wait()
            return None

        self.configure(review_every=1)
        with patch.object(self.service.store, "propose", side_effect=propose):
            experience_id = self.service.record_turn("terminal:main", REQUEST, RESPONSE)
            self.assertTrue(experience_id)
            await asyncio.wait_for(started.wait(), 1)
            self.assertTrue(self.service.status()["running"])
            self.assertIn("already running", self.service.schedule_review(manual=True))
            finish.set()
            await self.drain()
        self.assertIn("No reusable", self.service.status()["last_result"])

    async def test_pause_cancels_evaluation_and_blocks_follow_on_promotion(self) -> None:
        self.configure(auto_promote=True)
        evidence_id = self.evidence()
        revision = self.service.store.register_candidate(PROCEDURE, model="provider/model", source_ids=[evidence_id])
        self.service.store.evaluations_path.write_text(json.dumps({"version": 1, "cases": [
            {"id": "dev", "split": "development", "prompt": "dev", "expected": "ok", "check": "exact"},
            {"id": "held", "split": "holdout", "prompt": "held", "expected": "ok", "check": "exact"},
        ]}), encoding="utf-8")
        started = asyncio.Event()

        async def pending(prompt, *, model):
            started.set()
            await asyncio.Event().wait()

        with patch.object(self.service, "_infer", side_effect=pending):
            self.service._queue(lambda: self.service._evaluate(revision["id"], auto_promote=True), name="evaluation")
            await asyncio.wait_for(started.wait(), 1)
            await self.service.pause()
        report = self.service.store.report(revision["id"])
        self.assertFalse(report["eligible"])
        self.assertFalse(report["completed"])
        self.assertEqual([], self.service.status()["active"])
        self.assertTrue(self.service.status()["paused"])
        self.assertIn("paused", self.service.schedule_review(manual=True))
        self.assertIsNone(self.service.record_turn("terminal:main", REQUEST, RESPONSE))
        self.service.resume()
        self.assertFalse(self.service.status()["paused"])

    async def test_terminal_safe_mode_and_shutdown_pause_shared_learning(self) -> None:
        app = TakoTerminalApp()
        app.paths = SimpleNamespace(state_dir=self.state_dir)
        service = Mock(pause=AsyncMock(), resume=Mock())
        with ExitStack() as stack:
            stack.enter_context(patch("takobot.app.learning_service", return_value=service))
            for method in ("_cancel_pi_login", "_stop_local_heartbeat", "_stop_xmtp_runtime",
                           "_start_local_heartbeat", "_cleanup_pairing_resources", "_stop_periodic_update_checks"):
                stack.enter_context(patch.object(app, method, new=AsyncMock()))
            stack.enter_context(patch.object(app, "_write_tako"))
            stack.enter_context(patch.object(app, "_record_event"))
            await app._enable_safe_mode()
            service.pause.assert_awaited_once()
            await app._disable_safe_mode()
            service.resume.assert_called_once()
            await app.on_unmount()
        self.assertEqual(2, service.pause.await_count)

    async def test_cooldown_prevents_manual_repeated_generation(self) -> None:
        self.configure(cooldown=300)
        self.evidence()
        with patch("takobot.learning_runtime.run_learning_inference", return_value=json.dumps(PROCEDURE)) as infer:
            self.service.schedule_review(manual=True)
            await self.drain()
            self.evidence(1)
            self.service.schedule_review(manual=True)
            await self.drain()
        self.assertEqual(1, infer.call_count)
        self.assertIn("cooldown", self.service.status()["last_result"])

    async def test_provider_mismatch_never_silently_switches(self) -> None:
        self.runtime.selected_provider = "local"
        with patch("takobot.learning_runtime.run_learning_inference") as infer:
            with self.assertRaisesRegex(LearningError, "selected pi"):
                await self.service._infer("private operator text", model="provider/model")
        infer.assert_not_called()

    async def test_context_records_exact_ids_and_feedback_is_explicit(self) -> None:
        evidence_id = self.evidence()
        revision = self.service.store.register_candidate(PROCEDURE, model="provider/model", source_ids=[evidence_id])
        with patch.object(self.service.store, "context", return_value=("advice", (revision["id"],))) as context:
            self.assertEqual(("advice", (revision["id"],)), self.service.context(REQUEST))
        self.assertEqual("provider/model", context.call_args.kwargs["model"])
        with patch("takobot.learning_runtime.run_learning_inference", return_value="null"):
            experience_id = self.service.record_turn("terminal:main", REQUEST, RESPONSE, revision_ids=(revision["id"],))
            await self.drain()
        latest = self.service.store.recent_experiences()[-1]
        self.assertEqual([revision["id"]], latest["revision_ids"])
        self.assertEqual("unknown", latest["outcome"])
        result = await self.service.command(f"feedback {experience_id} success passed external check", operator=True)
        await self.drain()
        self.assertEqual("success", json.loads(result)["outcome"])
        self.assertEqual("operator", json.loads(result)["outcome_source"])

    async def test_corrupt_and_symlink_runtime_state_fails_closed(self) -> None:
        self.service.runtime_path.parent.mkdir(parents=True)
        self.service.runtime_path.write_text("broken", encoding="utf-8")
        with patch("takobot.learning_runtime.run_learning_inference") as infer:
            with self.assertRaises(ValueError):
                await self.service._infer("prompt", model="provider/model")
        infer.assert_not_called()
        self.assertEqual("broken", self.service.runtime_path.read_text())
        self.service.runtime_path.unlink()
        target = self.root / "operator-file"
        target.write_text("preserve", encoding="utf-8")
        self.service.runtime_path.symlink_to(target)
        with self.assertRaises(LearningError):
            self.service.status()
        self.assertEqual("preserve", target.read_text())

    async def test_terminal_command_routes_directly_and_command_detection(self) -> None:
        app = TakoTerminalApp()
        app.paths = SimpleNamespace(state_dir=self.state_dir)
        service = Mock(command=AsyncMock(return_value="learning report"))
        with patch("takobot.app.learning_service", return_value=service), patch.object(app, "_write_tako") as write:
            await app._handle_running_input("/learn status")
        service.command.assert_awaited_once_with("status", operator=True)
        write.assert_called_once_with("learning report")
        for command in ("learn", "learn feedback e-x failure", "/learn review"):
            self.assertTrue(_looks_like_command(command))
            self.assertTrue(_looks_like_local_command(command))

    async def test_xmtp_command_authentication_precedes_learning_dispatch(self) -> None:
        conversation = SimpleNamespace(send=AsyncMock())
        client = SimpleNamespace(inbox_id="self", conversations=SimpleNamespace(
            get_conversation_by_id=AsyncMock(return_value=conversation)))
        paths = SimpleNamespace(state_dir=self.state_dir, operator_json=self.root / "operator.json")
        service = Mock(command=AsyncMock(return_value="learning report"))
        item = SimpleNamespace(sender_inbox_id="stranger", content="learn review", conversation_id=b"conversation")
        with (
            patch("takobot.cli.repo_root", return_value=self.root),
            patch("takobot.cli._preferred_git_identity_name", return_value="Tako"),
            patch("takobot.cli.ensure_profile_message_for_conversation", new=AsyncMock()),
            patch("takobot.cli._ConversationWithTyping", return_value=conversation),
            patch("takobot.cli.load_operator", return_value={"operator_inbox_id": "operator"}),
            patch("takobot.cli.learning_service", return_value=service) as factory,
        ):
            await _handle_incoming_message(item, client, paths, "addr", "test", 0, self.runtime,
                                           ConversationStore(self.state_dir), RuntimeHooks(emit_console=False))
            factory.assert_not_called()
            self.assertIn("Operator-only", conversation.send.call_args.args[0])
            item.sender_inbox_id = "operator"
            await _handle_incoming_message(item, client, paths, "addr", "test", 0, self.runtime,
                                           ConversationStore(self.state_dir), RuntimeHooks(emit_console=False))
        service.command.assert_awaited_once_with("review", operator=True)

    async def test_xmtp_prompt_and_capture_share_exact_revisions(self) -> None:
        service = Mock(context=Mock(return_value=("JSON procedure r-exact", ("r-exact",))))
        rag = SimpleNamespace(context="", status="ok", hits=0, limit=0)
        with (
            patch("takobot.cli.repo_root", return_value=self.root),
            patch("takobot.cli.query_memory_with_ragrep", return_value=rag),
            patch("takobot.cli.learning_service", return_value=service),
            patch("takobot.cli.run_inference_prompt_with_fallback", return_value=("pi", RESPONSE)) as infer,
        ):
            result = await _chat_reply(REQUEST, self.runtime, paths=SimpleNamespace(state_dir=self.state_dir),
                                      conversations=ConversationStore(self.state_dir), session_key="xmtp:operator",
                                      is_operator=True, operator_paired=True, hooks=RuntimeHooks(emit_console=False))
        self.assertIn("JSON procedure r-exact", infer.call_args.args[1])
        service.record_turn.assert_called_once_with("xmtp:operator", REQUEST, result,
                                                   revision_ids=("r-exact",), operator=True)

    async def test_terminal_prompt_and_capture_share_exact_revisions(self) -> None:
        app = TakoTerminalApp()
        app.paths = SimpleNamespace(state_dir=self.state_dir)
        app.inference_runtime = self.runtime
        service = Mock(context=Mock(return_value=("JSON procedure r-exact", ("r-exact",))))
        with ExitStack() as stack:
            stack.enter_context(patch("takobot.app.repo_root", return_value=self.root))
            stack.enter_context(patch("takobot.app.learning_service", return_value=service))
            infer = stack.enter_context(patch("takobot.app.stream_inference_prompt_with_fallback",
                                               new=AsyncMock(return_value=("pi", RESPONSE))))
            stack.enter_context(patch.object(app, "_collect_inference_rag_context", new=AsyncMock(return_value=("", ""))))
            stack.enter_context(patch.object(app, "_ready_inference_providers", return_value=[]))
            for method in ("_stream_begin", "_stream_render", "_add_activity", "_record_event", "_append_app_log"):
                stack.enter_context(patch.object(app, method))
            result = await app._local_chat_reply(REQUEST)
        self.assertIn("JSON procedure r-exact", infer.call_args.args[1])
        service.record_turn.assert_called_once_with("terminal:main", REQUEST, result, revision_ids=("r-exact",))

    def test_nonoperator_prompt_omits_learned_content_even_if_supplied(self) -> None:
        prompt = _chat_prompt("hello", history="", is_operator=False, operator_paired=True,
                              identity_name="Tako", learned_context="PRIVATE LEARNED PROCEDURE")
        self.assertNotIn("PRIVATE LEARNED PROCEDURE", prompt)


if __name__ == "__main__":
    unittest.main()
