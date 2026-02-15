from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
import subprocess
from urllib.parse import urlparse
from urllib.request import Request, urlopen


WEB_FETCH_TIMEOUT_S = 20.0
WEB_FETCH_MAX_BYTES = 1_000_000
WEB_FETCH_TEXT_LIMIT = 2600

COMMAND_TIMEOUT_S = 25.0
COMMAND_OUTPUT_LIMIT = 2200


@dataclass(frozen=True)
class WebFetchResult:
    ok: bool
    url: str
    title: str
    text: str
    error: str = ""


@dataclass(frozen=True)
class CommandResult:
    ok: bool
    command: str
    exit_code: int
    output: str
    error: str = ""


def fetch_webpage(
    url: str,
    *,
    timeout_s: float = WEB_FETCH_TIMEOUT_S,
    max_bytes: int = WEB_FETCH_MAX_BYTES,
    text_limit: int = WEB_FETCH_TEXT_LIMIT,
) -> WebFetchResult:
    target = url.strip()
    parsed = urlparse(target)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return WebFetchResult(False, target, "", "", "URL must be http(s) with a host.")

    request = Request(
        target,
        headers={
            "User-Agent": "takobot/1.0 (+https://tako.bot)",
            "Accept": "text/html, text/plain;q=0.9, */*;q=0.2",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout_s) as response:
            final_url = response.geturl() or target
            content_type = (response.headers.get("Content-Type") or "").lower()
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read(max_bytes + 1)
    except Exception as exc:  # noqa: BLE001
        return WebFetchResult(False, target, "", "", _short(str(exc), 220))

    if len(raw) > max_bytes:
        return WebFetchResult(False, target, "", "", f"response too large (> {max_bytes} bytes)")

    decoded = raw.decode(charset, errors="replace")
    if "html" in content_type or "<html" in decoded[:1024].lower():
        parser = _HTMLTextParser()
        parser.feed(decoded)
        title = _normalize_text(parser.title)
        text = _normalize_text("\n".join(parser.chunks))
    else:
        title = ""
        text = _normalize_text(decoded)

    if not text:
        text = "(no readable text content)"
    if len(text) > text_limit:
        text = text[: text_limit - 3] + "..."
    return WebFetchResult(True, final_url, title, text, "")


def run_local_command(
    command: str,
    *,
    timeout_s: float = COMMAND_TIMEOUT_S,
    output_limit: int = COMMAND_OUTPUT_LIMIT,
    cwd: str | Path | None = None,
) -> CommandResult:
    cmd = command.strip()
    if not cmd:
        return CommandResult(False, cmd, -1, "", "missing command text")
    if "\n" in cmd:
        return CommandResult(False, cmd, -1, "", "multi-line command input is not allowed")

    try:
        run_cwd = str(cwd) if cwd is not None else None
        proc = subprocess.run(
            ["bash", "-lc", cmd],
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
            cwd=run_cwd,
        )
    except Exception as exc:  # noqa: BLE001
        return CommandResult(False, cmd, -1, "", _short(str(exc), 220))

    stdout = proc.stdout.strip()
    stderr = proc.stderr.strip()
    parts: list[str] = []
    if stdout:
        parts.append(stdout)
    if stderr:
        parts.append(f"[stderr]\n{stderr}")
    output = "\n\n".join(parts).strip()
    if not output:
        output = "(no output)"
    if len(output) > output_limit:
        output = output[: output_limit - 3] + "..."

    return CommandResult(proc.returncode == 0, cmd, int(proc.returncode), output, "")


def _normalize_text(value: str) -> str:
    # Preserve paragraph breaks but collapse noisy spacing.
    lines = [" ".join(line.split()) for line in value.replace("\r", "\n").split("\n")]
    chunks = [line for line in lines if line]
    return "\n".join(chunks)


def _short(text: str, limit: int) -> str:
    value = " ".join(text.strip().split())
    if not value:
        return "no details available"
    if len(value) <= limit:
        return value
    return value[: limit - 3] + "..."


class _HTMLTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self._in_script = False
        self._in_style = False
        self._in_title = False
        self.title = ""
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs) -> None:  # type: ignore[override]
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
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self.title = (self.title + " " + text).strip()
        else:
            self.chunks.append(text)
