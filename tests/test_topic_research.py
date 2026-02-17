from __future__ import annotations

import unittest
from unittest.mock import patch

from takobot.topic_research import collect_topic_research


class TestTopicResearch(unittest.TestCase):
    def test_collect_topic_research_returns_structured_notes(self) -> None:
        def fake_fetch(url: str, *, timeout_s: float, user_agent: str):
            if "wikipedia.org/api/rest_v1/page/summary" in url:
                return {
                    "title": "Potato",
                    "extract": "The potato is a starchy tuber first domesticated in the Andes.",
                    "content_urls": {"desktop": {"page": "https://en.wikipedia.org/wiki/Potato"}},
                }
            if "hn.algolia.com/api/v1/search" in url:
                return {
                    "hits": [
                        {
                            "title": "Open potato breeding datasets",
                            "url": "https://example.com/hn-potato",
                            "objectID": "123",
                            "points": 55,
                            "num_comments": 19,
                        }
                    ]
                }
            if "reddit.com/search.json" in url:
                return {
                    "data": {
                        "children": [
                            {
                                "data": {
                                    "title": "Potato disease tracking pipeline",
                                    "permalink": "/r/science/comments/abc123/potato_pipeline/",
                                    "subreddit": "science",
                                    "score": 321,
                                    "num_comments": 42,
                                    "selftext": "New method for detecting crop blight early.",
                                }
                            }
                        ]
                    }
                }
            if "api.duckduckgo.com" in url:
                return {
                    "Heading": "Potato",
                    "AbstractText": "Potato cultivation changed food security in multiple regions.",
                    "AbstractURL": "https://duckduckgo.com/Potato",
                }
            raise AssertionError(f"unexpected URL {url}")

        with patch("takobot.topic_research._fetch_json", side_effect=fake_fetch):
            result = collect_topic_research(
                "potatoes",
                mission_objectives=["Keep operator intent explicit and outcomes measurable."],
            )

        self.assertEqual("potatoes", result.topic)
        self.assertGreaterEqual(len(result.notes), 3)
        self.assertTrue(result.highlight)
        self.assertTrue(any(note.source == "Wikipedia" for note in result.notes))
        self.assertTrue(any("Hacker News" in note.source for note in result.notes))
        self.assertTrue(any("Reddit" in note.source for note in result.notes))
        self.assertTrue(all(note.mission_relevance.strip() for note in result.notes))

    def test_collect_topic_research_requires_non_empty_topic(self) -> None:
        result = collect_topic_research("   ")
        self.assertEqual("", result.topic)
        self.assertEqual(0, len(result.notes))
        self.assertEqual("", result.highlight)

    def test_collect_topic_research_ignores_low_signal_duckduckgo_abstract(self) -> None:
        def fake_fetch(url: str, *, timeout_s: float, user_agent: str):
            if "api.duckduckgo.com" in url:
                return {
                    "Heading": "XMTP",
                    "AbstractText": "Source: https://x.com/i/status/123 https://example.com/2",
                    "AbstractURL": "https://duckduckgo.com/XMTP",
                }
            return {}

        with patch("takobot.topic_research._fetch_json", side_effect=fake_fetch):
            result = collect_topic_research("XMTP", max_notes=4)
        self.assertEqual(0, len(result.notes))


if __name__ == "__main__":
    unittest.main()
