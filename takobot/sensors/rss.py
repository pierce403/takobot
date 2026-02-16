from __future__ import annotations

import asyncio
from collections import deque
import json
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

from .base import SensorContext

RSS_MAX_BYTES = 2_500_000


class RSSSensor:
    name = "rss"

    def __init__(
        self,
        feeds: list[str],
        *,
        poll_minutes: int = 15,
        seen_path: Path | None = None,
        per_host_min_interval_s: float = 2.0,
        max_items_per_feed: int = 20,
        max_seen_ids: int = 20_000,
    ) -> None:
        self.feeds = tuple(_clean_feed_urls(feeds))
        self.poll_interval_s = max(60, int(poll_minutes) * 60)
        self._next_poll_at = 0.0
        self._per_host_min_interval_s = max(0.1, float(per_host_min_interval_s))
        self._max_items_per_feed = max(1, int(max_items_per_feed))
        self._max_seen_ids = max(1_000, int(max_seen_ids))
        self._last_fetch_by_host: dict[str, float] = {}
        self._seen_path = seen_path
        self._seen_ids: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._seen_loaded = False

    async def tick(self, ctx: SensorContext) -> list[dict[str, Any]]:
        if not self.feeds:
            return []

        now = time.monotonic()
        if self._next_poll_at and now < self._next_poll_at:
            return []
        self._next_poll_at = now + float(self.poll_interval_s)

        self._ensure_seen_loaded(ctx.state_dir)

        events: list[dict[str, Any]] = []
        changed = False
        for feed_url in self.feeds:
            host = urlparse(feed_url).netloc.lower()
            last_fetch = self._last_fetch_by_host.get(host, 0.0)
            if host and now - last_fetch < self._per_host_min_interval_s:
                continue
            self._last_fetch_by_host[host] = now

            try:
                final_url, payload = await asyncio.to_thread(
                    _fetch_feed,
                    feed_url,
                    timeout_s=ctx.timeout_s,
                    user_agent=ctx.user_agent,
                )
            except Exception:
                continue

            items = _parse_feed_items(payload, feed_url=final_url)
            for item in items[: self._max_items_per_feed]:
                item_id = item.get("item_id", "")
                if not item_id or item_id in self._seen_ids:
                    continue
                changed = True
                self._remember_item_id(item_id)
                title = item.get("title") or "(untitled)"
                source = item.get("source") or urlparse(final_url).netloc or "unknown source"
                events.append(
                    {
                        "type": "world.news.item",
                        "severity": "info",
                        "source": "sensor:rss",
                        "message": f"{title} ({source})",
                        "metadata": {
                            "sensor": self.name,
                            "feed_url": final_url,
                            "feed_title": item.get("feed_title", ""),
                            "item_id": item_id,
                            "title": title,
                            "link": item.get("link", ""),
                            "source": source,
                            "published": item.get("published", ""),
                        },
                    }
                )

        if changed:
            self._persist_seen()
        return events

    def _ensure_seen_loaded(self, state_dir: Path) -> None:
        if self._seen_loaded:
            return
        self._seen_loaded = True
        if self._seen_path is None:
            self._seen_path = state_dir / "rss_seen.json"
        path = self._seen_path
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        ids = payload.get("seen_ids")
        if not isinstance(ids, list):
            return
        for value in ids:
            item_id = _clean_text(str(value))
            if not item_id or item_id in self._seen_ids:
                continue
            self._seen_ids.add(item_id)
            self._seen_order.append(item_id)
        self._truncate_seen()

    def _remember_item_id(self, item_id: str) -> None:
        clean = _clean_text(item_id)
        if not clean:
            return
        if clean in self._seen_ids:
            return
        self._seen_ids.add(clean)
        self._seen_order.append(clean)
        self._truncate_seen()

    def _truncate_seen(self) -> None:
        while len(self._seen_order) > self._max_seen_ids:
            dropped = self._seen_order.popleft()
            self._seen_ids.discard(dropped)

    def _persist_seen(self) -> None:
        if self._seen_path is None:
            return
        payload = {
            "updated_at": time.time(),
            "seen_ids": list(self._seen_order),
        }
        try:
            self._seen_path.parent.mkdir(parents=True, exist_ok=True)
            self._seen_path.write_text(json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")
        except Exception:
            return


def _fetch_feed(url: str, *, timeout_s: float, user_agent: str) -> tuple[str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/atom+xml, application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.2",
        },
        method="GET",
    )
    with urlopen(request, timeout=max(1.0, float(timeout_s))) as response:
        final_url = response.geturl() or url
        charset = response.headers.get_content_charset() or "utf-8"
        raw = response.read(RSS_MAX_BYTES + 1)
        if len(raw) > RSS_MAX_BYTES:
            raise ValueError(f"feed payload too large (> {RSS_MAX_BYTES} bytes)")
    return final_url, raw.decode(charset, errors="replace")


def _parse_feed_items(xml_text: str, *, feed_url: str) -> list[dict[str, str]]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    root_name = _local_name(root.tag)
    if root_name == "feed":
        return _parse_atom_items(root, feed_url=feed_url)
    return _parse_rss_items(root, feed_url=feed_url)


def _parse_atom_items(root: ET.Element, *, feed_url: str) -> list[dict[str, str]]:
    feed_title = _find_text(root, "title") or urlparse(feed_url).netloc or "unknown source"
    out: list[dict[str, str]] = []
    for entry in root.findall("./{*}entry"):
        title = _find_text(entry, "title") or "(untitled)"
        link = _atom_link(entry)
        item_id = _find_text(entry, "id") or link
        published = _find_text(entry, "updated") or _find_text(entry, "published")
        if not item_id:
            continue
        out.append(
            {
                "item_id": _clean_text(item_id),
                "title": _clean_text(title),
                "link": _clean_text(link),
                "source": _clean_text(feed_title),
                "feed_title": _clean_text(feed_title),
                "published": _clean_text(published),
            }
        )
    return out


def _parse_rss_items(root: ET.Element, *, feed_url: str) -> list[dict[str, str]]:
    channel = root.find("./channel")
    if channel is None:
        channel = root.find("./{*}channel")
    if channel is None:
        channel = root
    feed_title = _find_text(channel, "title") or urlparse(feed_url).netloc or "unknown source"

    entries = list(channel.findall("./item")) + list(channel.findall("./{*}item"))
    if not entries and _local_name(root.tag) == "rdf":
        entries = list(root.findall("./{*}item"))

    out: list[dict[str, str]] = []
    for entry in entries:
        title = _find_text(entry, "title") or "(untitled)"
        link = _find_text(entry, "link")
        item_id = _find_text(entry, "guid") or link
        published = _find_text(entry, "pubDate") or _find_text(entry, "updated")
        if not item_id:
            continue
        out.append(
            {
                "item_id": _clean_text(item_id),
                "title": _clean_text(title),
                "link": _clean_text(link),
                "source": _clean_text(feed_title),
                "feed_title": _clean_text(feed_title),
                "published": _clean_text(published),
            }
        )
    return out


def _find_text(node: ET.Element, name: str) -> str:
    for child in list(node):
        if _local_name(child.tag) != name:
            continue
        if child.text:
            return child.text
    return ""


def _atom_link(entry: ET.Element) -> str:
    for link in entry.findall("./{*}link"):
        href = _clean_text(str(link.attrib.get("href") or ""))
        if not href:
            continue
        rel = _clean_text(str(link.attrib.get("rel") or "alternate")).lower()
        if rel in {"alternate", ""}:
            return href
    fallback = entry.find("./{*}link")
    if fallback is None:
        return ""
    return _clean_text(str(fallback.attrib.get("href") or fallback.text or ""))


def _clean_feed_urls(feeds: list[str]) -> list[str]:
    out: list[str] = []
    for raw in feeds:
        candidate = _clean_text(str(raw))
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        out.append(candidate)
    return out


def _local_name(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[1].lower()
    return tag.lower()


def _clean_text(value: str) -> str:
    return " ".join((value or "").strip().split())
