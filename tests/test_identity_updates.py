from __future__ import annotations

import unittest

from takobot.identity import (
    build_identity_name_intent_prompt,
    extract_name_intent_from_model_output,
    extract_name_from_model_output,
    extract_name_from_text,
    extract_role_from_model_output,
    extract_role_from_text,
    looks_like_name_change_hint,
    looks_like_role_info_query,
    looks_like_role_change_request,
)


class TestIdentityUpdates(unittest.TestCase):
    def test_build_identity_name_intent_prompt_mentions_schema(self) -> None:
        prompt = build_identity_name_intent_prompt(
            text="can you set your name on xmtp?",
            current_name="Tako",
        )
        self.assertIn('{"intent":"rename|none","name":"..."}', prompt)
        self.assertIn("current_name=Tako", prompt)

    def test_extract_name_intent_from_model_output_rename_with_name(self) -> None:
        requested, name = extract_name_intent_from_model_output('{"intent":"rename","name":"DantoBot"}')
        self.assertTrue(requested)
        self.assertEqual("DantoBot", name)

    def test_extract_name_intent_from_model_output_rename_without_name(self) -> None:
        requested, name = extract_name_intent_from_model_output('{"intent":"rename","name":""}')
        self.assertTrue(requested)
        self.assertEqual("", name)

    def test_extract_name_intent_from_model_output_none(self) -> None:
        requested, name = extract_name_intent_from_model_output('{"intent":"none","name":""}')
        self.assertFalse(requested)
        self.assertEqual("", name)

    def test_extract_name_from_text_accepts_plain_name_when_allowed(self) -> None:
        self.assertEqual("DantoBot", extract_name_from_text("DantoBot", allow_plain_name=True))

    def test_extract_name_from_text_parses_explicit_request(self) -> None:
        self.assertEqual("DantoBot", extract_name_from_text("call yourself DantoBot"))

    def test_extract_name_from_text_rejects_non_name_acks(self) -> None:
        self.assertEqual("", extract_name_from_text("yes", allow_plain_name=True))
        self.assertEqual("", extract_name_from_model_output('{"name":"yes"}'))

    def test_name_change_hint_gate_skips_plain_smalltalk(self) -> None:
        self.assertFalse(looks_like_name_change_hint("hi"))
        self.assertFalse(looks_like_name_change_hint("how are you today?"))

    def test_name_change_hint_gate_accepts_name_and_profile_phrases(self) -> None:
        self.assertTrue(looks_like_name_change_hint("can you set your name on xmtp?"))
        self.assertTrue(looks_like_name_change_hint("please update your display name"))
        self.assertTrue(looks_like_name_change_hint("call yourself DantoBot"))

    def test_role_change_detection_ignores_information_only_questions(self) -> None:
        self.assertFalse(looks_like_role_change_request("what is your purpose?"))
        self.assertFalse(looks_like_role_change_request("can you tell me what your purpose is?"))
        self.assertFalse(looks_like_role_change_request("tell me what your mission is"))

    def test_role_info_query_detection_handles_natural_phrasing(self) -> None:
        self.assertTrue(looks_like_role_info_query("can you tell me what your purpose is?"))
        self.assertTrue(looks_like_role_info_query("what is your mission"))
        self.assertTrue(looks_like_role_info_query("share your role"))
        self.assertFalse(looks_like_role_info_query("please update your purpose"))

    def test_role_change_detection_handles_fix_requests(self) -> None:
        self.assertTrue(
            looks_like_role_change_request("I made a typo in your purpose, can you fix it?")
        )

    def test_extract_role_from_text_direct_assignment(self) -> None:
        parsed = extract_role_from_text("your purpose is Help the operator think clearly and act safely.")
        self.assertEqual("Help the operator think clearly and act safely", parsed)

    def test_extract_role_from_text_update_phrase(self) -> None:
        parsed = extract_role_from_text("please update your mission to help me learn robotics, please.")
        self.assertEqual("help me learn robotics", parsed)

    def test_extract_role_from_text_returns_empty_without_replacement(self) -> None:
        parsed = extract_role_from_text("I think I made a spelling mistake when I told you your purpose.")
        self.assertEqual("", parsed)

    def test_extract_role_from_model_output_json(self) -> None:
        parsed = extract_role_from_model_output('{"role":"Help the operator build durable systems."}')
        self.assertEqual("Help the operator build durable systems", parsed)


if __name__ == "__main__":
    unittest.main()
