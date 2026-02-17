from __future__ import annotations

import html
from html.parser import HTMLParser
import json
from urllib.parse import parse_qs, quote_plus, unquote, urlparse
from urllib.request import Request, urlopen


TOOL_MANIFEST = {
    "name": "web_search",
    "description": (
        "Search the web via DuckDuckGo and return structured results. "
        "Can optionally fetch top-result page text snippets."
    ),
    "permissions": ["network"],
    "entrypoint": "run",
}

DEFAULT_TIMEOUT_S = 16.0
DEFAULT_MAX_RESULTS = 5
DEFAULT_PAGE_FETCH_LIMIT = 2
DEFAULT_PAGE_TEXT_CHARS = 800
DEFAULT_MAX_BYTES = 1_500_000


def run(input: dict, ctx: dict) -> dict:
    del ctx
    payload = input if isinstance(input, dict) else {}
    query = _clean(str(payload.get("query") or ""))
    if not query:
        return {"ok": False, "error": "Missing input.query (string)."}

    timeout_s = _as_float(payload.get("timeout_s"), default=DEFAULT_TIMEOUT_S, min_value=3.0, max_value=90.0)
    max_results = _as_int(payload.get("max_results"), default=DEFAULT_MAX_RESULTS, min_value=1, max_value=10)
    include_page_text = _as_bool(payload.get("include_page_text"), default=False)
    page_fetch_limit = _as_int(
        payload.get("page_fetch_limit"),
        default=DEFAULT_PAGE_FETCH_LIMIT,
        min_value=0,
        max_value=5,
    )
    page_text_chars = _as_int(
        payload.get("page_text_chars"),
        default=DEFAULT_PAGE_TEXT_CHARS,
        min_value=200,
        max_value=2_000,
    )
    render_js = _as_bool(payload.get("render_js"), default=False)

    results = _search_duckduckgo_html(query, timeout_s=timeout_s, max_results=max_results)
    if not results:
        results = _search_duckduckgo_instant(query, timeout_s=timeout_s, max_results=max_results)
    if not results:
        return {"ok": True, "query": query, "results": [], "count": 0, "source": "duckduckgo"}

    if include_page_text and page_fetch_limit > 0:
        for item in results[:page_fetch_limit]:
            fetched = _fetch_page_preview(
                item["url"],
                timeout_s=timeout_s,
                max_chars=page_text_chars,
                render_js=render_js,
            )
            if fetched.get("ok"):
                preview = _clean(str(fetched.get("text") or ""))
                if preview:
                    item["page_text"] = preview
                title = _clean(str(fetched.get("title") or ""))
                if title and not item.get("title"):
                    item["title"] = title
            else:
                item["page_text_error"] = _clean(str(fetched.get("error") or ""))

    return {
        "ok": True,
        "query": query,
        "results": results,
        "count": len(results),
        "source": "duckduckgo",
    }


def _search_duckduckgo_html(query: str, *, timeout_s: float, max_results: int) -> list[dict]:
    url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
    request = Request(
        url,
        headers={
            "User-Agent": "takobot-web-search/1.0 (+https://tako.bot)",
            "Accept": "text/html,application/xhtml+xml;q=0.9,*/*;q=0.1",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(DEFAULT_MAX_BYTES + 1)
    except Exception:
        return []
    if len(raw) > DEFAULT_MAX_BYTES:
        return []

    parser = _DuckResultParser()
    parser.feed(raw.decode(charset, errors="replace"))
    out: list[dict] = []
    seen: set[str] = set()
    for item in parser.results:
        url_value = _clean(item.get("url", ""))
        if not url_value or url_value in seen:
            continue
        seen.add(url_value)
        out.append(
            {
                "title": _clean(item.get("title", "")),
                "url": url_value,
                "snippet": _clean(item.get("snippet", "")),
            }
        )
        if len(out) >= max_results:
            break
    return out


def _search_duckduckgo_instant(query: str, *, timeout_s: float, max_results: int) -> list[dict]:
    url = f"https://api.duckduckgo.com/?q={quote_plus(query)}&format=json&no_redirect=1&no_html=1&skip_disambig=0"
    request = Request(
        url,
        headers={
            "User-Agent": "takobot-web-search/1.0 (+https://tako.bot)",
            "Accept": "application/json,text/plain;q=0.4,*/*;q=0.1",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            payload = json.loads(response.read(DEFAULT_MAX_BYTES + 1).decode(charset, errors="replace"))
    except Exception:
        return []
    if not isinstance(payload, dict):
        return []

    out: list[dict] = []
    heading = _clean(str(payload.get("Heading") or ""))
    abstract_text = _clean(str(payload.get("AbstractText") or ""))
    abstract_url = _clean(str(payload.get("AbstractURL") or ""))
    if abstract_url:
        out.append({"title": heading or abstract_url, "url": abstract_url, "snippet": abstract_text})

    related = payload.get("RelatedTopics")
    if isinstance(related, list):
        for item in related:
            if not isinstance(item, dict):
                continue
            text = _clean(str(item.get("Text") or ""))
            first_url = _clean(str(item.get("FirstURL") or ""))
            if text and first_url:
                out.append({"title": text, "url": first_url, "snippet": ""})
            topics = item.get("Topics")
            if isinstance(topics, list):
                for nested in topics:
                    if not isinstance(nested, dict):
                        continue
                    nested_text = _clean(str(nested.get("Text") or ""))
                    nested_url = _clean(str(nested.get("FirstURL") or ""))
                    if nested_text and nested_url:
                        out.append({"title": nested_text, "url": nested_url, "snippet": ""})
            if len(out) >= max_results:
                break

    deduped: list[dict] = []
    seen: set[str] = set()
    for item in out:
        url_value = _clean(str(item.get("url") or ""))
        if not url_value or url_value in seen:
            continue
        seen.add(url_value)
        deduped.append(item)
        if len(deduped) >= max_results:
            break
    return deduped


def _fetch_page_preview(url: str, *, timeout_s: float, max_chars: int, render_js: bool) -> dict:
    if render_js:
        rendered = _fetch_with_playwright(url, timeout_s=timeout_s, max_chars=max_chars)
        if rendered.get("ok"):
            return rendered
    return _fetch_plain(url, timeout_s=timeout_s, max_chars=max_chars)


def _fetch_with_playwright(url: str, *, timeout_s: float, max_chars: int) -> dict:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _short(str(exc), 180)}

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=int(timeout_s * 1000))
            title = _clean(page.title() or "")
            text = _clean(page.inner_text("body") or "")
            browser.close()
    except PlaywrightError as exc:
        return {"ok": False, "error": _short(str(exc), 220)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _short(str(exc), 220)}

    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return {"ok": True, "url": url, "title": title, "text": text, "render_mode": "playwright"}


def _fetch_plain(url: str, *, timeout_s: float, max_chars: int) -> dict:
    request = Request(
        url,
        headers={
            "User-Agent": "takobot-web-search/1.0 (+https://tako.bot)",
            "Accept": "text/html,text/plain;q=0.9,*/*;q=0.2",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            content_type = (response.headers.get("Content-Type") or "").lower()
            raw = response.read(DEFAULT_MAX_BYTES + 1)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _short(str(exc), 220)}
    if len(raw) > DEFAULT_MAX_BYTES:
        return {"ok": False, "error": "response too large"}

    decoded = raw.decode(charset, errors="replace")
    if "html" in content_type or "<html" in decoded[:1024].lower():
        parser = _TextExtractor()
        parser.feed(decoded)
        title = _clean(parser.title)
        text = _clean(" ".join(parser.chunks))
    else:
        title = ""
        text = _clean(decoded)
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return {"ok": True, "url": url, "title": title, "text": text, "render_mode": "plain_http"}


def _unwrap_duckduckgo_href(href: str) -> str:
    raw = html.unescape(href)
    if raw.startswith("/l/?"):
        parsed = urlparse("https://duckduckgo.com" + raw)
    else:
        parsed = urlparse(raw)
    if "duckduckgo.com" in (parsed.netloc or "") and parsed.path.startswith("/l/"):
        query = parse_qs(parsed.query)
        uddg = query.get("uddg")
        if uddg and isinstance(uddg, list):
            value = _clean(unquote(uddg[0]))
            if value:
                return value
    return _clean(raw)


def _as_bool(value, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"1", "true", "yes", "y", "on"}:
            return True
        if lowered in {"0", "false", "no", "n", "off"}:
            return False
    return default


def _as_int(value, *, default: int, min_value: int, max_value: int) -> int:
    try:
        parsed = int(float(value))
    except Exception:
        parsed = default
    return max(min_value, min(max_value, parsed))


def _as_float(value, *, default: float, min_value: float, max_value: float) -> float:
    try:
        parsed = float(value)
    except Exception:
        parsed = default
    return max(min_value, min(max_value, parsed))


def _clean(value: str) -> str:
    return " ".join((value or "").strip().split())


def _short(value: str, limit: int) -> str:
    cleaned = _clean(value)
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


class _DuckResultParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.results: list[dict[str, str]] = []
        self._in_result_anchor = False
        self._in_snippet = False
        self._result_href = ""
        self._result_parts: list[str] = []
        self._snippet_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        attrs_map = {key.lower(): value for key, value in attrs if isinstance(key, str)}
        classes = (attrs_map.get("class") or "").lower()
        if tag.lower() == "a" and "result__a" in classes:
            self._in_result_anchor = True
            self._result_href = str(attrs_map.get("href") or "")
            self._result_parts = []
            return
        if "result__snippet" in classes:
            self._in_snippet = True
            self._snippet_parts = []

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        lowered = tag.lower()
        if lowered == "a" and self._in_result_anchor:
            title = _clean(html.unescape("".join(self._result_parts)))
            url = _unwrap_duckduckgo_href(self._result_href)
            if title and url:
                self.results.append({"title": title, "url": url, "snippet": ""})
            self._in_result_anchor = False
            self._result_href = ""
            self._result_parts = []
            return
        if self._in_snippet and lowered in {"a", "div", "span"}:
            snippet = _clean(html.unescape("".join(self._snippet_parts)))
            if snippet:
                for item in reversed(self.results):
                    if not item.get("snippet"):
                        item["snippet"] = snippet
                        break
            self._in_snippet = False
            self._snippet_parts = []

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._in_result_anchor:
            self._result_parts.append(data)
            return
        if self._in_snippet:
            self._snippet_parts.append(data)


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_script = False
        self._in_style = False
        self._in_title = False
        self.title = ""
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
        del attrs
        lowered = tag.lower()
        if lowered == "script":
            self._in_script = True
        elif lowered == "style":
            self._in_style = True
        elif lowered == "title":
            self._in_title = True

    def handle_endtag(self, tag: str) -> None:  # type: ignore[override]
        lowered = tag.lower()
        if lowered == "script":
            self._in_script = False
        elif lowered == "style":
            self._in_style = False
        elif lowered == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:  # type: ignore[override]
        if self._in_script or self._in_style:
            return
        text = _clean(html.unescape(data))
        if not text:
            return
        if self._in_title:
            self.title = _clean(f"{self.title} {text}")
            return
        self.chunks.append(text)
