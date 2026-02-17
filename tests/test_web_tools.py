from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def _load_tool_module(path: Path):
    spec = importlib.util.spec_from_file_location(f"test_tool_{path.stem}", str(path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed loading module {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[call-arg]
    return module


class _Headers:
    def __init__(self, content_type: str) -> None:
        self._content_type = content_type

    def get(self, name: str, default=None):
        if name.lower() == "content-type":
            return self._content_type
        return default

    def get_content_charset(self):
        lowered = self._content_type.lower()
        marker = "charset="
        if marker not in lowered:
            return None
        value = lowered.split(marker, 1)[1].split(";", 1)[0].strip()
        return value or None


class _Response:
    def __init__(self, body: bytes, *, content_type: str = "text/html; charset=utf-8", final_url: str = "") -> None:
        self._body = body
        self.headers = _Headers(content_type)
        self._final_url = final_url

    def read(self, _size: int = -1) -> bytes:
        return self._body

    def geturl(self) -> str:
        return self._final_url

    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        return None


class TestWebFetchTool(unittest.TestCase):
    def test_web_fetch_extracts_title_and_body(self) -> None:
        module = _load_tool_module(ROOT / "tools" / "web_fetch" / "tool.py")
        html_doc = b"""
            <html>
              <head><title>Example Title</title></head>
              <body>
                <h1>Hello world</h1>
                <script>ignored()</script>
                <p>Useful text.</p>
              </body>
            </html>
        """
        response = _Response(html_doc, final_url="https://example.com/final")
        with patch.object(module, "urlopen", return_value=response):
            result = module.run({"url": "https://example.com"}, {})

        self.assertTrue(result.get("ok"))
        self.assertEqual("https://example.com/final", result.get("url"))
        self.assertEqual("Example Title", result.get("title"))
        self.assertIn("Hello world", result.get("text", ""))
        self.assertIn("Useful text.", result.get("text", ""))


class TestWebSearchTool(unittest.TestCase):
    def test_web_search_parses_duckduckgo_results(self) -> None:
        module = _load_tool_module(ROOT / "tools" / "web_search" / "tool.py")
        search_html = b"""
            <html><body>
              <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Farticle">Example Article</a>
              <a class="result__snippet">Example snippet content.</a>
            </body></html>
        """
        response = _Response(search_html)
        with patch.object(module, "urlopen", return_value=response):
            result = module.run({"query": "example topic"}, {})

        self.assertTrue(result.get("ok"))
        self.assertEqual("example topic", result.get("query"))
        self.assertEqual(1, result.get("count"))
        first = result["results"][0]
        self.assertEqual("https://example.com/article", first["url"])
        self.assertEqual("Example Article", first["title"])
        self.assertIn("Example snippet", first["snippet"])

    def test_web_search_optional_page_fetch_adds_page_text(self) -> None:
        module = _load_tool_module(ROOT / "tools" / "web_search" / "tool.py")
        search_html = b"""
            <html><body>
              <a class="result__a" href="https://duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com%2Ftopic">Topic Page</a>
              <a class="result__snippet">Topic snippet.</a>
            </body></html>
        """
        page_html = b"""
            <html><head><title>Topic Title</title></head><body><p>Page details for this topic.</p></body></html>
        """
        responses = [
            _Response(search_html),
            _Response(page_html, final_url="https://example.com/topic"),
        ]
        with patch.object(module, "urlopen", side_effect=responses):
            result = module.run(
                {
                    "query": "topic",
                    "include_page_text": True,
                    "page_fetch_limit": 1,
                },
                {},
            )

        self.assertTrue(result.get("ok"))
        self.assertEqual(1, result.get("count"))
        first = result["results"][0]
        self.assertIn("page_text", first)
        self.assertIn("Page details for this topic.", first["page_text"])


if __name__ == "__main__":
    unittest.main()
