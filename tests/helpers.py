from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import threading


@dataclass(frozen=True)
class FeatureCriterion:
    section: str
    checked: bool
    text: str


_SECTION_RE = re.compile(r"^###\s+(?P<section>.+?)\s*$")
_CRITERION_RE = re.compile(r"^\s*-\s+\[(?P<state>[xX ])\]\s+(?P<text>.+?)\s*$")


def parse_feature_criteria(path: Path) -> list[FeatureCriterion]:
    criteria: list[FeatureCriterion] = []
    section = ""
    for raw in path.read_text(encoding="utf-8").splitlines():
        section_match = _SECTION_RE.match(raw)
        if section_match:
            section = section_match.group("section").strip()
            continue
        criterion_match = _CRITERION_RE.match(raw)
        if not criterion_match:
            continue
        if not section:
            raise RuntimeError("Found feature criterion before first section heading.")
        criteria.append(
            FeatureCriterion(
                section=section,
                checked=criterion_match.group("state").lower() == "x",
                text=criterion_match.group("text").strip(),
            )
        )
    return criteria


@contextmanager
def local_html_server(*, title: str = "Takobot Test Page", body: str = "hello from takobot tests"):
    html = (
        "<!doctype html>"
        "<html><head>"
        f"<title>{title}</title>"
        "</head><body>"
        f"<h1>{body}</h1>"
        "<p>Deterministic local response.</p>"
        "</body></html>"
    ).encode("utf-8")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, _format, *_args):  # noqa: A003
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/"
    finally:
        server.shutdown()
        thread.join(timeout=5.0)
        server.server_close()
