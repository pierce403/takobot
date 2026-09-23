from __future__ import annotations

import asyncio
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.learning import LearningError, LearningStore, redact


def procedure(name: str = "Normalize tags") -> dict:
    return {"name": name, "trigger": "normalize tags into canonical JSON", "steps": ["Return a JSON tag list."],
            "pitfalls": ["Do not invent tags."], "verification": ["Check canonical JSON formatting."]}


def suite() -> dict:
    return {"version": 1, "cases": [
        {"id": "dev", "split": "development", "prompt": "Normalize these tags: A", "expected": ["a"], "check": "json"},
        {"id": "hold", "split": "holdout", "prompt": "Normalize these tags: B", "expected": ["b"], "check": "json"},
    ]}


class TestLearning(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.state = Path(self.tmp.name) / ".tako" / "state"
        self.store = LearningStore(self.state)
        self.experience_id = self.store.record_turn("terminal", "normalize tags", '["a"]')
        self.store.evaluations_path.write_text(json.dumps(suite()))

    def candidate(self, *, name: str = "Normalize tags", parent_id: str | None = None) -> dict:
        return self.store.register_candidate(procedure(name), model="test/model", source_ids=[self.experience_id], parent_id=parent_id)

    async def good_infer(self, prompt: str) -> str:
        if "Advisory procedure:" not in prompt:
            return "wrong"
        return '["a"]' if "Task:\nNormalize these tags: A" in prompt else '["b"]'

    async def promote(self, revision: dict) -> None:
        report = await self.store.evaluate(revision["id"], self.good_infer, model="test/model")
        self.assertTrue(report["eligible"])
        self.store.promote(revision["id"], model="test/model")

    async def test_real_generation_replay_promotion_and_exact_failure_feedback(self) -> None:
        prompts = []

        async def generate(prompt: str) -> str:
            prompts.append(prompt)
            return json.dumps(procedure())

        revision = await self.store.propose(generate, model="test/model")
        self.assertEqual("candidate", revision["status"])
        self.assertNotIn("Normalize these tags: B", prompts[0])
        self.assertNotIn("expected", prompts[0])
        self.assertEqual(("", ()), self.store.context("normalize tags"))
        with self.assertRaises(LearningError):
            self.store.promote(revision["id"], model="test/model")
        await self.promote(revision)
        context, used = self.store.context("normalize tags")
        self.assertIn("Normalize tags", context)
        self.assertEqual((revision["id"],), used)
        turn = self.store.record_turn("terminal", "normalize tags", "bad", revision_ids=used)
        self.assertEqual("unknown", self.store.recent_experiences()[-1]["outcome"])
        self.store.feedback(turn, "failure", note="Incorrect schema")
        self.assertEqual("rejected", self.store.show(revision["id"])["status"])
        self.assertEqual(("", ()), self.store.context("normalize tags"))
        child = await self.store.propose(generate, model="test/model")
        self.assertEqual(revision["id"], child["parent_id"])
        self.assertNotEqual(revision["id"], child["id"])
        self.assertIn("Incorrect schema", prompts[-1])
        self.assertNotIn("holdout", prompts[-1])
        self.assertEqual(revision["body"], self.store.show(revision["id"])["body"])

    async def test_operator_success_cannot_bypass_fixed_evaluation(self) -> None:
        revision = self.candidate()
        self.store.feedback(self.experience_id, "success")
        with self.assertRaises(LearningError):
            self.store.promote(revision["id"], model="test/model")
        with self.assertRaises(LearningError):
            self.store.feedback(self.experience_id, "success", operator=False)
        with self.assertRaises(LearningError):
            self.store.record_turn("attacker", "poison", "approved", operator=False)

    async def test_eval_never_discloses_expected_answers_or_case_splits(self) -> None:
        test_suite = suite()
        test_suite["cases"][0]["expected"] = "TOP_SECRET_EXPECTATION"
        self.store.evaluations_path.write_text(json.dumps(test_suite))
        prompts = []

        async def infer(prompt: str) -> str:
            prompts.append(prompt)
            return "wrong"

        report = await self.store.evaluate(self.candidate()["id"], infer, model="test/model")
        self.assertFalse(report["eligible"])
        self.assertEqual(4, len(prompts))
        for prompt in prompts:
            self.assertNotIn("TOP_SECRET_EXPECTATION", prompt)
            self.assertNotIn("holdout", prompt)
        self.assertNotIn("TOP_SECRET_EXPECTATION", self.store.path.read_text())

    async def test_per_case_holdout_regression_rejects_equal_aggregate_score(self) -> None:
        data = suite()
        data["cases"].append({"id": "hold2", "split": "holdout", "prompt": "third task", "expected": ["c"], "check": "json"})
        self.store.evaluations_path.write_text(json.dumps(data))

        async def infer(prompt: str) -> str:
            candidate = "Advisory procedure:" in prompt
            if "third task" in prompt:
                return '["c"]' if candidate else "wrong"
            if "Task:\nNormalize these tags: B" in prompt:
                return "wrong" if candidate else '["b"]'
            return '["a"]' if candidate else "wrong"

        revision = self.candidate()
        report = await self.store.evaluate(revision["id"], infer, model="test/model")
        self.assertEqual(1, report["holdout_baseline"])
        self.assertEqual(1, report["holdout_candidate"])
        self.assertEqual(1, report["heldout_regressions"])
        self.assertFalse(report["eligible"])
        with self.assertRaises(LearningError):
            self.store.promote(revision["id"], model="test/model")

    async def test_budget_timeout_suite_change_and_model_change_fail_closed(self) -> None:
        revision = self.candidate()
        calls = []

        async def slow(prompt: str) -> str:
            calls.append(prompt)
            await asyncio.sleep(1)
            return "wrong"

        with self.assertRaises(LearningError):
            await self.store.evaluate(revision["id"], slow, model="test/model", max_calls=3)
        self.assertEqual([], calls)
        report = await self.store.evaluate(revision["id"], slow, model="test/model", deadline_seconds=.01)
        self.assertFalse(report["completed"])
        self.assertFalse(report["eligible"])
        self.assertEqual(1, len(calls))
        await self.store.evaluate(revision["id"], self.good_infer, model="test/model")
        with self.assertRaises(LearningError):
            self.store.promote(revision["id"], model="different/model")
        changed = suite()
        changed["cases"][1]["expected"] = ["changed"]
        self.store.evaluations_path.write_text(json.dumps(changed))
        with self.assertRaises(LearningError):
            self.store.promote(revision["id"], model="test/model")
        self.store.evaluations_path.unlink()
        with self.assertRaises(LearningError):
            self.store.promote(revision["id"], model="test/model")

    async def test_active_context_is_bounded_and_invalidated_by_suite_change(self) -> None:
        revision = self.candidate()
        await self.promote(revision)
        self.assertEqual(("", ()), self.store.context("unrelated zebra"))
        self.assertEqual(("", ()), self.store.context("normalize tags", max_chars=20))
        self.assertEqual(("", ()), self.store.context("normalize tags", max_skills=0))
        self.assertEqual(("", ()), self.store.context("normalize tags", model="different/model"))
        text, _ = self.store.context("normalize tags", max_chars=1000)
        self.assertLessEqual(len(text), 1000)
        self.store.evaluations_path.write_text("{}")
        self.assertEqual(("", ()), self.store.context("normalize tags"))

    async def test_recursive_child_rollback_restores_evaluated_ancestor(self) -> None:
        data = suite()
        data["cases"].insert(1, {"id": "dev2", "split": "development", "prompt": "second development task", "expected": "two", "check": "exact"})
        self.store.evaluations_path.write_text(json.dumps(data))

        async def infer(prompt: str) -> str:
            if "Advisory procedure:" not in prompt:
                return "wrong"
            if "second development task" in prompt:
                return "two" if "Procedure: Normalize tags better" in prompt else "wrong"
            return '["a"]' if "Task:\nNormalize these tags: A" in prompt else '["b"]'

        parent = self.candidate()
        await self.store.evaluate(parent["id"], infer, model="test/model")
        self.store.promote(parent["id"], model="test/model")
        child = self.candidate(name="Normalize tags better", parent_id=parent["id"])
        report = await self.store.evaluate(child["id"], infer, model="test/model")
        self.assertTrue(report["eligible"])
        self.store.promote(child["id"], model="test/model")
        result = self.store.rollback(child["id"])
        self.assertEqual(parent["id"], result["active"])
        self.assertEqual("active", self.store.show(parent["id"])["status"])
        self.assertEqual("rejected", self.store.show(child["id"])["status"])

    async def test_current_baseline_binding_rejects_concurrent_promotion(self) -> None:
        parent = self.candidate()
        # A child proposed before its parent is activated measures an empty baseline.
        child = self.candidate(name="Normalize tags better", parent_id=parent["id"])
        await self.store.evaluate(child["id"], self.good_infer, model="test/model")
        await self.promote(parent)
        with self.assertRaises(LearningError):
            self.store.promote(child["id"], model="test/model")

    async def test_body_tampering_corruption_symlinks_and_redaction(self) -> None:
        self.store.record_turn("terminal", "inference key set OPENAI_API_KEY sk-super-secret-token12345", "Bearer abcdef0123456789")
        serialized = self.store.path.read_text()
        self.assertNotIn("sk-super-secret-token12345", serialized)
        self.assertNotIn("abcdef0123456789", serialized)
        self.candidate()
        data = json.loads(self.store.path.read_text())
        next(iter(data["revisions"].values()))["body"]["steps"] = ["tamper"]
        corrupted = json.dumps(data)
        self.store.path.write_text(corrupted)
        with self.assertRaises(LearningError):
            self.store.status()
        self.assertEqual(corrupted, self.store.path.read_text())
        self.store.path.write_text("not json")
        with self.assertRaises(LearningError):
            self.store.record_turn("terminal", "hi", "there")
        self.assertEqual("not json", self.store.path.read_text())
        outside = Path(self.tmp.name) / "outside"
        outside.mkdir()
        link = Path(self.tmp.name) / "link"
        link.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(LearningError):
            LearningStore(link / "state")
        self.store.path.unlink()
        external_file = outside / "state.json"
        external_file.write_text("untouched")
        self.store.path.symlink_to(external_file)
        with self.assertRaises(LearningError):
            self.store.record_turn("terminal", "hi", "there")
        self.assertEqual("untouched", external_file.read_text())

    async def test_schema_and_bounded_archive(self) -> None:
        bad = procedure()
        bad["executable"] = "anything"
        with self.assertRaises(LearningError):
            self.store.register_candidate(bad, model="test/model", source_ids=[self.experience_id])
        small = LearningStore(self.state, max_experiences=2, max_revisions=1)
        revision = self.candidate()
        self.assertEqual(revision["id"], small.register_candidate(procedure(), model="test/model", source_ids=[self.experience_id])["id"])
        with self.assertRaises(LearningError):
            small.register_candidate(procedure("Different"), model="test/model", source_ids=[self.experience_id])
        small.record_turn("terminal", "second", "reply")
        small.record_turn("terminal", "third", "reply")
        self.assertEqual(2, len(small.recent_experiences()))
        self.assertEqual(1, len(small.list_revisions()))
        self.assertEqual(self.experience_id, small.show(revision["id"])["source_evidence"][0]["id"])
        # Exact typed JSON equality does not accept true for numeric 1.
        data = suite()
        data["cases"][0]["expected"] = 1
        self.store.evaluations_path.write_text(json.dumps(data))

        async def truth(_: str) -> str:
            return "true"

        report = await small.evaluate(revision["id"], truth, model="test/model")
        self.assertEqual(0, report["development_candidate"])

    async def test_quoted_credentials_and_private_keys_never_reach_proposal(self) -> None:
        examples = [
            ('{"password": "example-placeholder-password"}', "example-placeholder-password"),
            ('{"api_key": "example-placeholder-api-value"}', "example-placeholder-api-value"),
            ("token='example placeholder token with spaces'", "example placeholder token with spaces"),
            ('{"refresh_token": "escaped \\" quote credential"}', "quote credential"),
            ('"client_secret": "unterminated credential', "unterminated credential"),
            ("-----BEGIN RSA PRIVATE KEY-----\nexample-private-material\n-----END RSA PRIVATE KEY-----", "example-private-material"),
            ("-----BEGIN OPENSSH PRIVATE KEY-----\ntruncated-key-material", "truncated-key-material"),
        ]
        for raw, secret in examples:
            with self.subTest(raw=raw):
                self.assertNotIn(secret, redact(raw))
        text = "\n".join(raw for raw, _ in examples[:4])
        text += "\n" + examples[5][0] + "\nPublic context remains useful."
        turn = self.store.record_turn("terminal", text, text)
        self.store.feedback(turn, "failure", note=text)
        prompt, source_ids, parent_id = self.store.proposal_prompt()
        candidate = self.store.register_candidate(procedure(), model="test/model", source_ids=source_ids, parent_id=parent_id)
        for _, secret in examples:
            self.assertNotIn(secret, self.store.path.read_text())
            self.assertNotIn(secret, prompt)
            self.assertNotIn(secret, json.dumps(candidate["source_evidence"]))
        self.assertIn("Public context remains useful", prompt)
        self.assertEqual("-----BEGIN PUBLIC KEY-----\npublic-material\n-----END PUBLIC KEY-----",
                         redact("-----BEGIN PUBLIC KEY-----\npublic-material\n-----END PUBLIC KEY-----"))

    async def test_procedures_fit_default_context_and_keep_verification(self) -> None:
        body = procedure()
        body["steps"] = ["Check each field. " * 27] * 3
        revision = self.store.register_candidate(body, model="test/model", source_ids=[self.experience_id])
        await self.promote(revision)
        context, ids = self.store.context("normalize tags", max_chars=2400)
        self.assertEqual((revision["id"],), ids)
        self.assertLessEqual(len(context), 2400)
        self.assertIn(body["verification"][-1], context)
        body["steps"] = ["Check each field. " * 27] * 5
        with self.assertRaisesRegex(LearningError, "2000 rendered"):
            self.store.register_candidate(body, model="test/model", source_ids=[self.experience_id])

    async def test_redundant_generation_preserves_original_evidence_and_can_abstain(self) -> None:
        original = self.candidate()
        fresh_id = self.store.record_turn("terminal", "normalize new tags", "new reply")
        duplicate = self.store.register_candidate(procedure(), model="test/model", source_ids=[fresh_id])
        self.assertEqual(original, duplicate)
        self.assertEqual([self.experience_id], duplicate["source_ids"])
        self.assertEqual(1, len(self.store.list_revisions()))

        async def abstain(prompt: str) -> str:
            self.assertIn("return JSON null", prompt)
            return "null"

        self.assertIsNone(await self.store.propose(abstain, model="test/model"))
        self.assertEqual(1, len(self.store.list_revisions()))


if __name__ == "__main__":
    unittest.main()
