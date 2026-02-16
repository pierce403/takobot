from __future__ import annotations

import asyncio
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import random
import time
from typing import Any, Callable, Mapping
from urllib.parse import quote
from urllib.request import Request, urlopen

from .base import SensorContext

CURIOSITY_MAX_BYTES = 1_500_000
DEFAULT_CURIOSITY_SOURCES = ("reddit", "hackernews", "wikipedia")
DEFAULT_REDDIT_SUBREDDITS = (
    "technology",
    "science",
    "futurology",
    "worldnews",
    "machinelearning",
    "programming",
)
HN_TOP_STORIES_URL = "https://hacker-news.firebaseio.com/v0/topstories.json"
HN_ITEM_URL_TEMPLATE = "https://hacker-news.firebaseio.com/v0/item/{story_id}.json"
WIKIPEDIA_RANDOM_SUMMARY_URL = "https://en.wikipedia.org/api/rest_v1/page/random/summary"
REDDIT_HOT_TEMPLATE = "https://www.reddit.com/r/{subreddit}/hot.json?raw_json=1&limit=25"

SourceFetcher = Callable[[SensorContext, random.Random], dict[str, Any] | None]


class CuriositySensor:
    name = "curiosity"

    def __init__(
        self,
        *,
        sources: list[str] | None = None,
        poll_minutes: int = 30,
        seen_path: Path | None = None,
        max_seen_ids: int = 20_000,
        max_events_per_tick: int = 1,
        rng: random.Random | None = None,
        source_fetchers: Mapping[str, SourceFetcher] | None = None,
    ) -> None:
        self._source_fetchers: dict[str, SourceFetcher] = {
            "reddit": _fetch_reddit_item,
            "hackernews": _fetch_hackernews_item,
            "wikipedia": _fetch_wikipedia_item,
        }
        if source_fetchers:
            self._source_fetchers.update(source_fetchers)
        self.sources = tuple(
            source
            for source in _normalize_sources(sources or list(DEFAULT_CURIOSITY_SOURCES))
            if source in self._source_fetchers
        )
        self.poll_interval_s = max(300, int(poll_minutes) * 60)
        self._next_poll_at = 0.0
        self._seen_path = seen_path
        self._seen_ids: set[str] = set()
        self._seen_order: deque[str] = deque()
        self._seen_loaded = False
        self._max_seen_ids = max(1_000, int(max_seen_ids))
        self._max_events_per_tick = max(1, int(max_events_per_tick))
        self._rng = rng if rng is not None else random.Random()

    async def tick(self, ctx: SensorContext) -> list[dict[str, Any]]:
        if not self.sources:
            return []

        now = time.monotonic()
        if self._next_poll_at and now < self._next_poll_at:
            return []
        self._next_poll_at = now + float(self.poll_interval_s)
        self._ensure_seen_loaded(ctx.state_dir)

        sources = list(self.sources)
        self._rng.shuffle(sources)

        changed = False
        events: list[dict[str, Any]] = []
        for source_name in sources:
            fetcher = self._source_fetchers.get(source_name)
            if fetcher is None:
                continue
            try:
                raw_item = await asyncio.to_thread(fetcher, ctx, self._rng)
            except Exception:
                continue
            prepared = _prepare_item(raw_item, source_name=source_name, mission_objectives=ctx.mission_objectives)
            if prepared is None:
                continue
            item_id = prepared["item_id"]
            if item_id in self._seen_ids:
                continue
            self._remember_item_id(item_id)
            changed = True
            events.append(_item_event(prepared))
            if len(events) >= self._max_events_per_tick:
                break

        if changed:
            self._persist_seen()
        return events

    def _ensure_seen_loaded(self, state_dir: Path) -> None:
        if self._seen_loaded:
            return
        self._seen_loaded = True
        if self._seen_path is None:
            self._seen_path = state_dir / "curiosity_seen.json"
        path = self._seen_path
        if not path.exists():
            return
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            return
        seen_ids = payload.get("seen_ids")
        if not isinstance(seen_ids, list):
            return
        for raw in seen_ids:
            item_id = _clean_text(str(raw))
            if not item_id or item_id in self._seen_ids:
                continue
            self._seen_ids.add(item_id)
            self._seen_order.append(item_id)
        self._truncate_seen()

    def _remember_item_id(self, item_id: str) -> None:
        clean = _clean_text(item_id)
        if not clean or clean in self._seen_ids:
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
            self._seen_path.write_text(
                json.dumps(payload, sort_keys=True, ensure_ascii=True, indent=2) + "\n",
                encoding="utf-8",
            )
        except Exception:
            return


def _normalize_sources(values: list[str]) -> list[str]:
    aliases = {
        "hn": "hackernews",
        "hacker-news": "hackernews",
        "news.ycombinator": "hackernews",
        "wiki": "wikipedia",
        "wikipedia.org": "wikipedia",
        "reddit.com": "reddit",
    }
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        candidate = _clean_text(str(raw)).lower()
        if not candidate:
            continue
        normalized = aliases.get(candidate, candidate)
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _item_event(item: dict[str, str]) -> dict[str, Any]:
    return {
        "type": "world.news.item",
        "severity": "info",
        "source": "sensor:curiosity",
        "message": f"{item['title']} ({item['source']})",
        "metadata": {
            "sensor": "curiosity",
            "item_id": item["item_id"],
            "title": item["title"],
            "link": item["link"],
            "source": item["source"],
            "published": item["published"],
            "why_it_matters": item["why_it_matters"],
            "mission_relevance": item["mission_relevance"],
            "question": item["question"],
            "origin_source": item["origin_source"],
            "discovery_mode": "random_explore",
        },
    }


def _prepare_item(
    raw_item: dict[str, Any] | None,
    *,
    source_name: str,
    mission_objectives: tuple[str, ...],
) -> dict[str, str] | None:
    if not isinstance(raw_item, dict):
        return None
    title = _clean_text(str(raw_item.get("title") or ""))
    if not title:
        return None
    link = _clean_text(str(raw_item.get("link") or ""))
    source = _clean_text(str(raw_item.get("source") or "")) or _source_label(source_name)
    published = _clean_text(str(raw_item.get("published") or ""))
    item_id = _clean_text(str(raw_item.get("item_id") or ""))
    if not item_id:
        if link:
            item_id = f"{source_name}:{link}"
        else:
            item_id = f"{source_name}:{title.lower()}"

    mission = mission_objectives[0] if mission_objectives else ""
    why_it_matters = _clean_text(str(raw_item.get("why_it_matters") or "")) or _default_why(source_name)
    mission_relevance = _clean_text(str(raw_item.get("mission_relevance") or "")) or _default_mission_relevance(
        mission,
        source,
    )
    question = _clean_text(str(raw_item.get("question") or "")) or _default_question(mission, title)

    return {
        "item_id": item_id,
        "title": title,
        "link": link,
        "source": source,
        "published": published,
        "why_it_matters": why_it_matters,
        "mission_relevance": mission_relevance,
        "question": question,
        "origin_source": source_name,
    }


def _default_why(source_name: str) -> str:
    if source_name == "reddit":
        return "Shows active community discussion momentum worth monitoring."
    if source_name == "hackernews":
        return "Signals what technical builders are prioritizing right now."
    if source_name == "wikipedia":
        return "Adds background context that can sharpen current decisions."
    return "Represents a fresh external signal worth reviewing."


def _default_mission_relevance(mission: str, source: str) -> str:
    if mission:
        return f"Potentially affects mission objective: {mission} (signal from {source})."
    return f"Potentially relevant to active priorities (signal from {source})."


def _default_question(mission: str, title: str) -> str:
    if mission:
        return f"How might {title} change our approach to {mission}?"
    return f"What should we verify next about {title} before acting on it?"


def _source_label(source_name: str) -> str:
    if source_name == "reddit":
        return "Reddit"
    if source_name == "hackernews":
        return "Hacker News"
    if source_name == "wikipedia":
        return "Wikipedia"
    return source_name


def _fetch_reddit_item(ctx: SensorContext, rng: random.Random) -> dict[str, Any] | None:
    subreddit = rng.choice(DEFAULT_REDDIT_SUBREDDITS)
    url = REDDIT_HOT_TEMPLATE.format(subreddit=quote(subreddit))
    payload = _fetch_json(url, timeout_s=ctx.timeout_s, user_agent=ctx.user_agent)
    data = payload.get("data")
    if not isinstance(data, dict):
        return None
    children = data.get("children")
    if not isinstance(children, list):
        return None
    for child in children:
        node = child.get("data") if isinstance(child, dict) else None
        if not isinstance(node, dict):
            continue
        if bool(node.get("stickied")):
            continue
        title = _clean_text(str(node.get("title") or ""))
        if not title:
            continue
        item_id = _clean_text(str(node.get("id") or node.get("name") or ""))
        permalink = _clean_text(str(node.get("permalink") or ""))
        link = f"https://www.reddit.com{permalink}" if permalink else _clean_text(str(node.get("url") or ""))
        published = _epoch_to_iso(node.get("created_utc"))
        return {
            "item_id": f"reddit:{subreddit}:{item_id or title.lower()}",
            "title": title,
            "link": link,
            "source": f"Reddit r/{subreddit}",
            "published": published,
        }
    return None


def _fetch_hackernews_item(ctx: SensorContext, rng: random.Random) -> dict[str, Any] | None:
    top_stories = _fetch_json(HN_TOP_STORIES_URL, timeout_s=ctx.timeout_s, user_agent=ctx.user_agent)
    if not isinstance(top_stories, list) or not top_stories:
        return None
    story_id = int(rng.choice(top_stories[:120]))
    payload = _fetch_json(
        HN_ITEM_URL_TEMPLATE.format(story_id=story_id),
        timeout_s=ctx.timeout_s,
        user_agent=ctx.user_agent,
    )
    if not isinstance(payload, dict):
        return None
    title = _clean_text(str(payload.get("title") or ""))
    if not title:
        return None
    link = _clean_text(str(payload.get("url") or f"https://news.ycombinator.com/item?id={story_id}"))
    published = _epoch_to_iso(payload.get("time"))
    return {
        "item_id": f"hackernews:{story_id}",
        "title": title,
        "link": link,
        "source": "Hacker News",
        "published": published,
    }


def _fetch_wikipedia_item(ctx: SensorContext, _rng: random.Random) -> dict[str, Any] | None:
    payload = _fetch_json(WIKIPEDIA_RANDOM_SUMMARY_URL, timeout_s=ctx.timeout_s, user_agent=ctx.user_agent)
    if not isinstance(payload, dict):
        return None
    title = _clean_text(str(payload.get("title") or ""))
    if not title:
        return None
    page_id = _clean_text(str(payload.get("pageid") or ""))
    links = payload.get("content_urls") if isinstance(payload.get("content_urls"), dict) else {}
    desktop = links.get("desktop") if isinstance(links, dict) else {}
    mobile = links.get("mobile") if isinstance(links, dict) else {}
    desktop_page = desktop.get("page") if isinstance(desktop, dict) else ""
    mobile_page = mobile.get("page") if isinstance(mobile, dict) else ""
    link = _clean_text(str(desktop_page or mobile_page))
    extract = _clean_text(str(payload.get("extract") or ""))
    why = ""
    if extract:
        first_sentence = extract.split(".", 1)[0].strip()
        if first_sentence:
            why = first_sentence + "."
    published = _clean_text(str(payload.get("timestamp") or ""))
    return {
        "item_id": f"wikipedia:{page_id or title.lower()}",
        "title": title,
        "link": link,
        "source": "Wikipedia",
        "published": published,
        "why_it_matters": why,
    }


def _fetch_json(url: str, *, timeout_s: float, user_agent: str) -> Any:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json, text/plain;q=0.2, */*;q=0.1",
        },
        method="GET",
    )
    with urlopen(request, timeout=max(1.0, float(timeout_s))) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        raw = response.read(CURIOSITY_MAX_BYTES + 1)
        if len(raw) > CURIOSITY_MAX_BYTES:
            raise ValueError(f"curiosity payload too large (> {CURIOSITY_MAX_BYTES} bytes)")
    return json.loads(raw.decode(charset, errors="replace"))


def _epoch_to_iso(value: Any) -> str:
    try:
        timestamp = float(value)
    except Exception:
        return ""
    if timestamp <= 0:
        return ""
    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat()


def _clean_text(value: str) -> str:
    return " ".join((value or "").strip().split())
