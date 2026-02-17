from __future__ import annotations

import html
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.request import Request, urlopen


TOOL_MANIFEST = {
    "name": "web_fetch",
    "description": (
        "Fetch and extract readable text from a web page. "
        "Supports optional Playwright rendering for JS-heavy pages."
    ),
    "permissions": ["network"],
    "entrypoint": "run",
}

DEFAULT_TIMEOUT_S = 20.0
DEFAULT_MAX_BYTES = 1_500_000
DEFAULT_MAX_CHARS = 4_000


def run(input: dict, ctx: dict) -> dict:
    del ctx
    payload = input if isinstance(input, dict) else {}
    url = _clean(str(payload.get("url") or ""))
    if not _is_http_url(url):
        return {"ok": False, "error": "Missing or invalid input.url (http/https required)."}

    timeout_s = _as_float(payload.get("timeout_s"), default=DEFAULT_TIMEOUT_S, min_value=3.0, max_value=90.0)
    max_bytes = _as_int(payload.get("max_bytes"), default=DEFAULT_MAX_BYTES, min_value=50_000, max_value=5_000_000)
    max_chars = _as_int(payload.get("max_chars"), default=DEFAULT_MAX_CHARS, min_value=300, max_value=20_000)
    render_js = _as_bool(payload.get("render_js"), default=False)

    render_error = ""
    if render_js:
        rendered = _fetch_with_playwright(url, timeout_s=timeout_s, max_chars=max_chars)
        if rendered.get("ok"):
            return rendered
        render_error = _clean(str(rendered.get("error") or ""))

    plain = _fetch_plain(url, timeout_s=timeout_s, max_bytes=max_bytes, max_chars=max_chars)
    if plain.get("ok") and render_error:
        plain["note"] = f"playwright render unavailable; fallback to plain fetch ({render_error})"
    return plain


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

    if not text:
        text = "(no readable body text)"
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."
    return {
        "ok": True,
        "url": url,
        "title": title,
        "text": text,
        "render_mode": "playwright",
    }


def _fetch_plain(url: str, *, timeout_s: float, max_bytes: int, max_chars: int) -> dict:
    request = Request(
        url,
        headers={
            "User-Agent": "takobot-web-fetch/1.0 (+https://tako.bot)",
            "Accept": "text/html, text/plain;q=0.9, */*;q=0.2",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            final_url = response.geturl() or url
            content_type = (response.headers.get("Content-Type") or "").lower()
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(max_bytes + 1)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": _short(str(exc), 220)}

    if len(raw) > max_bytes:
        return {"ok": False, "error": f"response too large (> {max_bytes} bytes)"}

    decoded = raw.decode(charset, errors="replace")
    if "html" in content_type or "<html" in decoded[:1024].lower():
        parser = _TextExtractor()
        parser.feed(decoded)
        title = _clean(parser.title)
        text = _clean(" ".join(parser.chunks))
    else:
        title = ""
        text = _clean(decoded)

    if not text:
        text = "(no readable text content)"
    if len(text) > max_chars:
        text = text[: max_chars - 3].rstrip() + "..."

    return {
        "ok": True,
        "url": final_url,
        "title": title,
        "text": text,
        "render_mode": "plain_http",
    }


def _is_http_url(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


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
