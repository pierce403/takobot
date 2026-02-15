from __future__ import annotations

from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from takobot.research import take_research_notes
from takobot.soul import DEFAULT_SOUL_ROLE

from tests.helpers import local_html_server


class TestResearchWorkflow(unittest.TestCase):
    def test_research_topic_is_fetched_and_logged_as_notes(self) -> None:
        with TemporaryDirectory() as tmp:
            notes_root = Path(tmp) / "memory" / "dailies"
            with local_html_server(title="Octopus Cognition", body="Octopuses solve puzzles and learn quickly.") as url:
                result = take_research_notes(
                    "octopus cognition",
                    [url],
                    notes_root=notes_root,
                )

            self.assertEqual(1, result.sources_ok)
            self.assertEqual(0, result.sources_failed)
            self.assertEqual("octopus cognition", result.topic)
            self.assertEqual(1, len(result.sources))
            self.assertTrue(result.sources[0].ok)
            self.assertIn("Octopus Cognition", result.sources[0].title)

            expected_log = notes_root / f"{date.today().isoformat()}.md"
            self.assertEqual(expected_log, result.notes_path)
            content = expected_log.read_text(encoding="utf-8")
            self.assertIn("Research topic: octopus cognition", content)
            self.assertIn("Research note: topic=octopus cognition", content)
            self.assertIn("Octopus Cognition", content)

    def test_research_notes_include_source_failures(self) -> None:
        with TemporaryDirectory() as tmp:
            notes_root = Path(tmp) / "memory" / "dailies"
            with local_html_server(title="Marine Notes", body="Ocean research source.") as url:
                result = take_research_notes(
                    "marine biology",
                    [url, "notaurl"],
                    notes_root=notes_root,
                )

            self.assertEqual(1, result.sources_ok)
            self.assertEqual(1, result.sources_failed)
            self.assertEqual(2, len(result.sources))
            self.assertFalse(result.sources[1].ok)
            self.assertIn("URL must be http(s)", result.sources[1].error)

            content = result.notes_path.read_text(encoding="utf-8")
            self.assertIn("Research source failed: topic=marine biology", content)
            self.assertIn("sources_ok=1/2", content)

    def test_default_role_is_explicitly_curious(self) -> None:
        lowered = DEFAULT_SOUL_ROLE.lower()
        self.assertIn("curious", lowered)
        self.assertIn("world", lowered)
        root_soul = Path("SOUL.md").read_text(encoding="utf-8").lower()
        template_soul = Path("takobot/templates/workspace/SOUL.md").read_text(encoding="utf-8").lower()
        self.assertIn("curious", root_soul)
        self.assertIn("curious", template_soul)
