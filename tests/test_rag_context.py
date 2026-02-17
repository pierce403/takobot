from __future__ import annotations

import json
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from takobot.rag_context import (
    FocusProfile,
    focus_profile_from_dose,
    format_focus_summary,
    query_memory_with_ragrep,
)


class DummyDoseState:
    def __init__(self, *, d: float, o: float, s: float, e: float) -> None:
        self.d = d
        self.o = o
        self.s = s
        self.e = e


class TestRagContext(unittest.TestCase):
    def test_focus_profile_is_low_context_when_focused(self) -> None:
        profile = focus_profile_from_dose(DummyDoseState(d=0.56, o=0.62, s=0.88, e=0.83))
        self.assertEqual("focused", profile.level)
        self.assertLessEqual(profile.rag_limit, 4)
        self.assertLess(profile.rag_char_budget, 1500)

    def test_focus_profile_is_wide_context_when_diffuse(self) -> None:
        profile = focus_profile_from_dose(DummyDoseState(d=0.95, o=0.20, s=0.15, e=0.20))
        self.assertEqual("diffuse", profile.level)
        self.assertGreaterEqual(profile.rag_limit, 16)
        self.assertGreaterEqual(profile.rag_char_budget, 3000)

    def test_query_memory_with_ragrep_handles_missing_binary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_root = root / "memory"
            state_dir = root / ".tako" / "state"
            memory_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)

            with patch("takobot.rag_context.shutil.which", return_value=None):
                result = query_memory_with_ragrep(
                    query="chip policy shifts",
                    workspace_root=root,
                    memory_root=memory_root,
                    state_dir=state_dir,
                    focus_profile=FocusProfile(score=0.5, level="balanced", rag_limit=8, rag_char_budget=1700),
                )
            self.assertEqual("ragrep-missing", result.status)
            self.assertEqual(0, result.hits)
            self.assertIn("`ragrep` is unavailable", result.context)

    def test_query_memory_with_ragrep_formats_json_matches(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            memory_root = root / "memory"
            state_dir = root / ".tako" / "state"
            memory_root.mkdir(parents=True, exist_ok=True)
            state_dir.mkdir(parents=True, exist_ok=True)

            payload = {
                "matches": [
                    {
                        "score": 0.9123,
                        "text": "A durable mission note about policy movement and execution implications.",
                        "metadata": {"source": str(memory_root / "world" / "2026-02-17.md")},
                    },
                    {
                        "score": 0.7401,
                        "text": "Operator preference mentions Hacker News as a recurring source.",
                        "metadata": {"source": str(memory_root / "people" / "operator.md")},
                    },
                ]
            }
            completed = subprocess.CompletedProcess(
                args=["ragrep"],
                returncode=0,
                stdout=json.dumps(payload),
                stderr="",
            )
            with (
                patch("takobot.rag_context.shutil.which", return_value="/usr/bin/ragrep"),
                patch("takobot.rag_context.subprocess.run", return_value=completed) as run_mock,
            ):
                result = query_memory_with_ragrep(
                    query="what changed that affects mission",
                    workspace_root=root,
                    memory_root=memory_root,
                    state_dir=state_dir,
                    focus_profile=FocusProfile(score=0.3, level="diffuse", rag_limit=16, rag_char_budget=3600),
                )

            self.assertEqual("ok", result.status)
            self.assertEqual(2, result.hits)
            self.assertEqual(16, result.limit)
            self.assertIn("score=0.9123", result.context)
            self.assertIn("memory/world/2026-02-17.md", result.context)
            self.assertIn("Hacker News", result.context)

            invoked = run_mock.call_args[0][0]
            self.assertEqual("/usr/bin/ragrep", invoked[0])
            self.assertIn("--limit", invoked)
            self.assertIn("16", invoked)
            self.assertIn("--json", invoked)

    def test_format_focus_summary(self) -> None:
        summary = format_focus_summary(FocusProfile(score=0.734, level="focused", rag_limit=4, rag_char_budget=900))
        self.assertEqual("focused (0.73)", summary)


if __name__ == "__main__":
    unittest.main()
