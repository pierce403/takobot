from __future__ import annotations

import unittest
from unittest.mock import patch

from takobot.app import (
    _active_work_summary,
    _activity_text,
    _octopus_panel_text,
    _build_terminal_chat_prompt,
    _build_memory_rag_query,
    _canonical_identity_name,
    _command_completion_context,
    _command_completion_matches,
    _dose_channel_label,
    _format_explore_completion_message,
    _local_chat_unavailable_message,
    _looks_like_local_command,
    _parse_command,
    _parse_dose_set_request,
    _slash_command_matches,
    _stream_focus_summary,
    _task_hint_from_status_line,
    TakoTerminalApp,
    run_terminal_app,
)


class TestAppCommands(unittest.TestCase):
    def test_parse_command_accepts_slash_prefix(self) -> None:
        cmd, rest = _parse_command("/models")
        self.assertEqual("models", cmd)
        self.assertEqual("", rest)

    def test_dose_set_request_supports_short_aliases(self) -> None:
        parsed = _parse_dose_set_request("o 0.4")
        self.assertEqual(("d", 0.4), parsed)
        self.assertEqual("dopamine", _dose_channel_label("d"))

        parsed_ox = _parse_dose_set_request("ox 0.3")
        self.assertEqual(("o", 0.3), parsed_ox)
        self.assertEqual("oxytocin", _dose_channel_label("o"))

    def test_dose_set_request_clamps_values(self) -> None:
        parsed = _parse_dose_set_request("s 2")
        self.assertEqual(("s", 1.0), parsed)

        parsed_low = _parse_dose_set_request("e -1")
        self.assertEqual(("e", 0.0), parsed_low)

    def test_looks_like_local_command_new_shortcuts(self) -> None:
        self.assertTrue(_looks_like_local_command("stats"))
        self.assertTrue(_looks_like_local_command("models"))
        self.assertTrue(_looks_like_local_command("mission"))
        self.assertTrue(_looks_like_local_command("mission set keep things safe; stay curious"))
        self.assertTrue(_looks_like_local_command("jobs list"))
        self.assertTrue(_looks_like_local_command("upgrade check"))
        self.assertTrue(_looks_like_local_command("dose o 0.4"))
        self.assertTrue(_looks_like_local_command("exec printf 'ok'"))
        self.assertTrue(_looks_like_local_command("explore"))
        self.assertTrue(_looks_like_local_command("explore ocean biodiversity"))
        self.assertTrue(_looks_like_local_command("/"))

    def test_slash_command_matches_lists_new_commands(self) -> None:
        items = _slash_command_matches("", limit=128)
        commands = {command for command, _summary in items}
        self.assertIn("/mission", commands)
        self.assertIn("/models", commands)
        self.assertIn("/jobs", commands)
        self.assertIn("/upgrade", commands)
        self.assertIn("/stats", commands)
        self.assertIn("/exec", commands)
        self.assertIn("/explore", commands)

        dose_items = _slash_command_matches("dose")
        self.assertTrue(any(command == "/dose" for command, _summary in dose_items))

    def test_command_completion_context_handles_prefixes(self) -> None:
        base, token, slash = _command_completion_context("/st") or ("", "", False)
        self.assertEqual("/", base)
        self.assertEqual("st", token)
        self.assertTrue(slash)

        base2, token2, slash2 = _command_completion_context("takobot sta") or ("", "", True)
        self.assertEqual("takobot ", base2)
        self.assertEqual("sta", token2)
        self.assertFalse(slash2)

        self.assertIsNone(_command_completion_context("status now"))

    def test_command_completion_matches_for_plain_and_slash(self) -> None:
        plain = _command_completion_matches("sta", slash=False)
        self.assertIn("status", plain)
        self.assertIn("stats", plain)
        plain_explore = _command_completion_matches("ex", slash=False)
        self.assertIn("explore", plain_explore)

        slash = _command_completion_matches("up", slash=True)
        self.assertIn("update", slash)
        self.assertIn("upgrade", slash)

    def test_stream_focus_summary_is_sanitized_and_truncated(self) -> None:
        self.assertEqual("hello world", _stream_focus_summary(" hello   world "))
        long_text = "x" * 200
        summarized = _stream_focus_summary(long_text)
        self.assertTrue(len(summarized) <= 120)
        self.assertTrue(summarized.endswith("..."))

    def test_task_hint_from_status_line_detects_research_actions(self) -> None:
        self.assertEqual(
            "browsing https://example.com/docs",
            _task_hint_from_status_line("tool:web fetching https://example.com/docs"),
        )
        self.assertEqual("browsing the web", _task_hint_from_status_line("item.started web_search_call"))
        self.assertEqual("searching local files", _task_hint_from_status_line("item.started file_search_call"))

    def test_active_work_summary_shows_queue_depth(self) -> None:
        self.assertEqual("idle", _active_work_summary([]))
        self.assertEqual("browsing the web", _active_work_summary(["browsing the web"]))
        self.assertEqual(
            "browsing the web (+1 more)",
            _active_work_summary(["browsing the web", "searching files for tests"]),
        )

    def test_activity_text_escapes_markup_sequences(self) -> None:
        rendered = _activity_text(["14:44:57 inference: provider attempt: [pi]"])
        self.assertIn(r"- 14:44:57 inference: provider attempt: \[pi]", rendered)

    def test_run_terminal_app_uses_default_mouse_mode(self) -> None:
        with patch.object(TakoTerminalApp, "run", return_value=None) as run_mock:
            code = run_terminal_app(interval=11.0)
        self.assertEqual(0, code)
        run_mock.assert_called_once_with()

    def test_canonical_identity_name_defaults_to_tako(self) -> None:
        self.assertEqual("Tako", _canonical_identity_name(""))
        self.assertEqual("ProTako", _canonical_identity_name("  ProTako  "))

    def test_terminal_chat_prompt_uses_identity_name(self) -> None:
        prompt = _build_terminal_chat_prompt(
            text="hello",
            identity_name="ProTako",
            identity_role="Your highly autonomous octopus friend",
            mission_objectives=["Keep outcomes clear", "Stay curious"],
            mode="paired",
            state="RUNNING",
            operator_paired=True,
            history="User: hi",
            soul_excerpt="# SOUL.md\n- Name: ProTako\n- Role: keep outcomes clear",
        )
        self.assertIn("You are ProTako", prompt)
        self.assertIn("Canonical identity name: ProTako", prompt)
        self.assertIn("Never claim your name is `Tako`", prompt)
        self.assertIn("Mission objectives: Keep outcomes clear | Stay curious", prompt)
        self.assertIn("Operator control surfaces: terminal app and paired XMTP channel.", prompt)
        self.assertIn("If the operator asks for identity/config changes, apply them directly", prompt)
        self.assertIn("soul_identity_boundaries=", prompt)
        self.assertIn("SOUL.md", prompt)
        self.assertIn("skills_frontmatter=", prompt)
        self.assertIn("tools_frontmatter=", prompt)
        self.assertIn("skills_inventory=", prompt)
        self.assertIn("tools_inventory=", prompt)
        self.assertIn("runtime supports profile sync with Converge 1:1 metadata", prompt)

    def test_build_memory_rag_query_includes_mission_objective(self) -> None:
        query = _build_memory_rag_query(
            text="what changed with policy today?",
            mission_objectives=["Keep mission alignment strong.", "Maintain operator trust."],
        )
        self.assertIn("what changed with policy today?", query)
        self.assertIn("Keep mission alignment strong.", query)

    def test_octopus_panel_places_stacked_dose_meters_top_right(self) -> None:
        panel = _octopus_panel_text(
            "adult",
            frame=2,
            panel_width=42,
            version="0.1.44",
            stage_title="Adult",
            stage_tone="steady",
            dose_state=None,
            dose_label="pending",
            thinking="idle",
        )
        lines = panel.splitlines()
        self.assertGreaterEqual(len(lines), 10)
        self.assertTrue(lines[0].rstrip().endswith("D ○○○○"))
        self.assertTrue(lines[1].rstrip().endswith("O ○○○○"))
        self.assertTrue(lines[2].rstrip().endswith("S ○○○○"))
        self.assertTrue(lines[3].rstrip().endswith("E ○○○○"))

    def test_explore_completion_message_includes_topic_learning_highlight(self) -> None:
        message = _format_explore_completion_message(
            requested_topic="potatoes",
            selected_topic="potatoes",
            new_world_count=0,
            report={
                "sensor_count": 2,
                "sensor_events": 5,
                "sensor_failures": 0,
                "topic_research_notes": 4,
                "topic_research_path": "memory/world/2026-02-17.md",
                "topic_research_highlight": "Potatoes spread globally because tubers store dense energy and travel well.",
            },
            sensor_count=2,
            life_stage="child",
            dose_label="curious",
        )
        self.assertIn("topic: potatoes", message)
        self.assertIn("topic research notes: 4", message)
        self.assertIn("oooh, this stood out:", message)
        self.assertIn("Potatoes spread globally", message)
        self.assertNotIn("I just learned something exciting:", message)

    def test_explore_completion_message_includes_mission_link_when_provided(self) -> None:
        message = _format_explore_completion_message(
            requested_topic="farcaster",
            selected_topic="farcaster",
            new_world_count=1,
            report={
                "topic_research_notes": 3,
                "topic_research_path": "memory/world/2026-02-17.md",
            },
            sensor_count=2,
            interesting="Farcaster developers are converging on open social graph portability.",
            mission_link="This could reduce lock-in risk for operator communication workflows.",
            life_stage="adult",
            dose_label="steady",
        )
        self.assertIn("topic research notes: 3", message)
        self.assertIn("key finding:", message)
        self.assertIn("mission implication:", message)
        self.assertNotIn("I just learned something exciting:", message)

    def test_local_input_queue_count_includes_active_processing(self) -> None:
        app = TakoTerminalApp(interval=5.0)
        self.assertEqual(0, app._queued_input_total())

        pending_after_first = app._enqueue_local_input("first")
        self.assertEqual(1, pending_after_first)
        self.assertEqual(1, app._queued_input_total())

        app.input_processing = True
        self.assertEqual(2, app._queued_input_total())

    def test_inference_stream_model_event_updates_state(self) -> None:
        app = TakoTerminalApp(interval=5.0)
        with (
            patch.object(app, "_stream_render", return_value=None),
            patch.object(app, "_add_activity", return_value=None),
            patch.object(app, "_append_app_log", return_value=None),
        ):
            app._on_inference_stream_event("model", "openai/gpt-5.3-codex")
        self.assertEqual("openai/gpt-5.3-codex", app.stream_model)
        self.assertTrue(any("model: openai/gpt-5.3-codex" in line for line in app.stream_status_lines))

    def test_inference_stream_thinking_status_merges_token_chunks(self) -> None:
        app = TakoTerminalApp(interval=5.0)
        with (
            patch.object(app, "_stream_render", return_value=None),
            patch.object(app, "_append_app_log", return_value=None),
        ):
            app._on_inference_stream_event("status", "pi thinking: hello")
            app._on_inference_stream_event("status", "pi thinking: world")
        thinking_lines = [line for line in app.stream_status_lines if line.startswith("pi thinking:")]
        self.assertEqual(["pi thinking: hello world"], thinking_lines)

    def test_inference_stream_thinking_status_accepts_cumulative_snapshots(self) -> None:
        app = TakoTerminalApp(interval=5.0)
        with (
            patch.object(app, "_stream_render", return_value=None),
            patch.object(app, "_append_app_log", return_value=None),
        ):
            app._on_inference_stream_event("status", "pi thinking: building")
            app._on_inference_stream_event("status", "pi thinking: building context")
        thinking_lines = [line for line in app.stream_status_lines if line.startswith("pi thinking:")]
        self.assertEqual(["pi thinking: building context"], thinking_lines)

    def test_inference_stream_thinking_status_keeps_special_tokens_separate(self) -> None:
        app = TakoTerminalApp(interval=5.0)
        with (
            patch.object(app, "_stream_render", return_value=None),
            patch.object(app, "_append_app_log", return_value=None),
        ):
            app._on_inference_stream_event("status", "pi thinking: analyzing web notes")
            app._on_inference_stream_event("status", "pi thinking: ```json")
        thinking_lines = [line for line in app.stream_status_lines if line.startswith("pi thinking:")]
        self.assertEqual(2, len(thinking_lines))
        self.assertEqual("pi thinking: analyzing web notes", thinking_lines[0])
        self.assertEqual("pi thinking: ```json", thinking_lines[1])

    def test_local_chat_unavailable_message_is_clear(self) -> None:
        message = _local_chat_unavailable_message(
            operator_paired=True,
            runtime=None,
            last_error="inference timed out",
            error_log_path=".tako/logs/error.log",
        )
        self.assertIn("Inference is unavailable right now", message)
        self.assertIn("Chat remains available here and over XMTP.", message)
        self.assertIn("Run `doctor` to auto-repair runtime/auth.", message)
        self.assertIn("Last inference error: inference timed out.", message)
        self.assertIn("Detailed command errors are logged at: .tako/logs/error.log.", message)


if __name__ == "__main__":
    unittest.main()
