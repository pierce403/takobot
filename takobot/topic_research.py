from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any
from urllib.parse import quote, quote_plus
from urllib.request import Request, urlopen

TOPIC_RESEARCH_MAX_BYTES = 2_000_000


@dataclass(frozen=True)
class TopicResearchNote:
    source: str
    title: str
    link: str
    summary: str
    mission_relevance: str
    question: str


@dataclass(frozen=True)
class TopicResearchResult:
    topic: str
    notes: tuple[TopicResearchNote, ...]
    highlight: str


def collect_topic_research(
    topic: str,
    *,
    mission_objectives: list[str] | tuple[str, ...] | None = None,
    timeout_s: float = 12.0,
    user_agent: str = "takobot/1.0 (+https://tako.bot; topic-research)",
    max_notes: int = 8,
) -> TopicResearchResult:
    cleaned_topic = _clean_text(topic)
    if not cleaned_topic:
        return TopicResearchResult(topic="", notes=(), highlight="")

    mission = ""
    for item in mission_objectives or ():
        value = _clean_text(str(item))
        if value:
            mission = value
            break

    notes: list[TopicResearchNote] = []
    for fetcher in (
        _fetch_wikipedia_notes,
        _fetch_hackernews_notes,
        _fetch_reddit_notes,
        _fetch_duckduckgo_note,
    ):
        with _suppress_exceptions():
            notes.extend(
                fetcher(
                    cleaned_topic,
                    mission=mission,
                    timeout_s=timeout_s,
                    user_agent=user_agent,
                )
            )

    deduped: list[TopicResearchNote] = []
    seen: set[tuple[str, str]] = set()
    for note in notes:
        key = (_clean_text(note.title).casefold(), _clean_text(note.link).casefold())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(note)
        if len(deduped) >= max(1, int(max_notes)):
            break

    highlight = _pick_highlight(cleaned_topic, deduped)
    return TopicResearchResult(topic=cleaned_topic, notes=tuple(deduped), highlight=highlight)


def _fetch_wikipedia_notes(topic: str, *, mission: str, timeout_s: float, user_agent: str) -> list[TopicResearchNote]:
    slug = quote(topic.replace(" ", "_"), safe="")
    payload = _fetch_json(
        f"https://en.wikipedia.org/api/rest_v1/page/summary/{slug}",
        timeout_s=timeout_s,
        user_agent=user_agent,
    )
    if not isinstance(payload, dict):
        return []
    title = _clean_text(str(payload.get("title") or "")) or topic.title()
    extract = _clean_text(str(payload.get("extract") or ""))
    if not extract:
        return []
    urls = payload.get("content_urls")
    desktop = urls.get("desktop") if isinstance(urls, dict) else None
    link = _clean_text(str(desktop.get("page") if isinstance(desktop, dict) else ""))
    if not link:
        link = f"https://en.wikipedia.org/wiki/{slug}"
    summary = _trim_sentence(extract, limit=260)
    return [
        TopicResearchNote(
            source="Wikipedia",
            title=title,
            link=link,
            summary=summary,
            mission_relevance=_mission_relevance(topic, mission, source="Wikipedia"),
            question=_follow_up_question(title, topic),
        )
    ]


def _fetch_hackernews_notes(topic: str, *, mission: str, timeout_s: float, user_agent: str) -> list[TopicResearchNote]:
    payload = _fetch_json(
        "https://hn.algolia.com/api/v1/search?"
        f"query={quote_plus(topic)}&tags=story&hitsPerPage=4",
        timeout_s=timeout_s,
        user_agent=user_agent,
    )
    hits = payload.get("hits") if isinstance(payload, dict) else None
    if not isinstance(hits, list):
        return []
    notes: list[TopicResearchNote] = []
    for hit in hits:
        if not isinstance(hit, dict):
            continue
        title = _clean_text(str(hit.get("title") or ""))
        if not title:
            continue
        object_id = _clean_text(str(hit.get("objectID") or ""))
        link = _clean_text(str(hit.get("url") or ""))
        if not link and object_id:
            link = f"https://news.ycombinator.com/item?id={object_id}"
        if not link:
            continue
        points = _safe_int(hit.get("points"))
        comments = _safe_int(hit.get("num_comments"))
        summary = f"HN discussion traction: {points} points and {comments} comments."
        notes.append(
            TopicResearchNote(
                source="Hacker News",
                title=title,
                link=link,
                summary=summary,
                mission_relevance=_mission_relevance(topic, mission, source="Hacker News"),
                question=_follow_up_question(title, topic),
            )
        )
        if len(notes) >= 3:
            break
    return notes


def _fetch_reddit_notes(topic: str, *, mission: str, timeout_s: float, user_agent: str) -> list[TopicResearchNote]:
    payload = _fetch_json(
        "https://www.reddit.com/search.json?"
        f"q={quote_plus(topic)}&sort=top&t=month&limit=4&raw_json=1",
        timeout_s=timeout_s,
        user_agent=user_agent,
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    children = data.get("children") if isinstance(data, dict) else None
    if not isinstance(children, list):
        return []
    notes: list[TopicResearchNote] = []
    for child in children:
        node = child.get("data") if isinstance(child, dict) else None
        if not isinstance(node, dict):
            continue
        if bool(node.get("stickied")):
            continue
        title = _clean_text(str(node.get("title") or ""))
        if not title:
            continue
        permalink = _clean_text(str(node.get("permalink") or ""))
        link = f"https://www.reddit.com{permalink}" if permalink else ""
        if not link:
            continue
        subreddit = _clean_text(str(node.get("subreddit") or ""))
        score = _safe_int(node.get("score"))
        comments = _safe_int(node.get("num_comments"))
        summary = f"Community traction: {score} upvotes and {comments} comments."
        selftext = _safe_summary(str(node.get("selftext") or ""), limit=160)
        if selftext:
            summary = f"{summary} Notes mention: {selftext}"
        notes.append(
            TopicResearchNote(
                source=f"Reddit r/{subreddit}" if subreddit else "Reddit",
                title=title,
                link=link,
                summary=summary,
                mission_relevance=_mission_relevance(topic, mission, source="Reddit"),
                question=_follow_up_question(title, topic),
            )
        )
        if len(notes) >= 3:
            break
    return notes


def _fetch_duckduckgo_note(topic: str, *, mission: str, timeout_s: float, user_agent: str) -> list[TopicResearchNote]:
    payload = _fetch_json(
        f"https://api.duckduckgo.com/?q={quote_plus(topic)}&format=json&no_html=1&skip_disambig=1",
        timeout_s=timeout_s,
        user_agent=user_agent,
    )
    if not isinstance(payload, dict):
        return []
    abstract = _safe_summary(str(payload.get("AbstractText") or ""), limit=220)
    if not abstract:
        return []
    title = _clean_text(str(payload.get("Heading") or "")) or f"{topic.title()} quick brief"
    link = _clean_text(str(payload.get("AbstractURL") or "")) or f"https://duckduckgo.com/?q={quote_plus(topic)}"
    summary = _trim_sentence(abstract, limit=220)
    return [
        TopicResearchNote(
            source="DuckDuckGo",
            title=title,
            link=link,
            summary=summary,
            mission_relevance=_mission_relevance(topic, mission, source="DuckDuckGo"),
            question=_follow_up_question(title, topic),
        )
    ]


def _fetch_json(url: str, *, timeout_s: float, user_agent: str) -> Any:
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            "Accept": "application/json, text/plain;q=0.5, */*;q=0.2",
        },
        method="GET",
    )
    with urlopen(request, timeout=max(1.0, float(timeout_s))) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        raw = response.read(TOPIC_RESEARCH_MAX_BYTES + 1)
        if len(raw) > TOPIC_RESEARCH_MAX_BYTES:
            raise ValueError(f"response too large (> {TOPIC_RESEARCH_MAX_BYTES} bytes)")
    return json.loads(raw.decode(charset, errors="replace"))


def _clean_text(value: str) -> str:
    return " ".join((value or "").strip().split())


def _trim_sentence(value: str, *, limit: int) -> str:
    cleaned = _clean_text(value)
    if not cleaned:
        return ""
    first = re.split(r"(?<=[.!?])\s+", cleaned, maxsplit=1)[0]
    if len(first) < 30 and len(cleaned) > len(first):
        first = cleaned
    if len(first) <= limit:
        return first
    return first[: limit - 3].rstrip() + "..."


def _safe_summary(value: str, *, limit: int) -> str:
    candidate = _trim_sentence(value, limit=limit)
    if not candidate:
        return ""
    if _looks_low_signal_text(candidate):
        return ""
    return candidate


def _looks_low_signal_text(value: str) -> bool:
    cleaned = _clean_text(value)
    if not cleaned:
        return True
    lowered = cleaned.lower()
    if lowered.startswith(("source:", "sources:", "by the way", "http://", "https://")):
        return True
    if " long ass " in f" {lowered} ":
        return True
    url_count = len(re.findall(r"https?://", lowered))
    if url_count >= 2:
        return True
    words = lowered.split()
    if len(words) < 6:
        return True
    return False


def _safe_int(value: Any) -> int:
    try:
        return int(float(value))
    except Exception:
        return 0


def _mission_relevance(topic: str, mission: str, *, source: str) -> str:
    if mission:
        return f"Could influence `{mission}` by changing what matters about {topic} (signal via {source})."
    return f"May affect active priorities around {topic} (signal via {source})."


def _follow_up_question(title: str, topic: str) -> str:
    clean_title = _clean_text(title) or topic
    return f"What action should we take if `{clean_title}` keeps gaining momentum?"


def _pick_highlight(topic: str, notes: list[TopicResearchNote]) -> str:
    if not notes:
        return ""
    ranked = sorted(notes, key=_highlight_score, reverse=True)
    top = ranked[0]
    summary = _safe_summary(top.summary, limit=200)
    if summary:
        return f"{top.title} ({top.source}) stood out: {summary}"
    title = _clean_text(top.title)
    source = _clean_text(top.source)
    if title:
        return f"{title} from {source or 'a tracked source'} looks like a high-signal thread for {topic}."
    return f"I found fresh signals about {topic} worth tracking."


def _highlight_score(note: TopicResearchNote) -> tuple[int, int, int, int]:
    source = _clean_text(note.source).lower()
    source_priority = 0
    if "wikipedia" in source:
        source_priority = 5
    elif "hacker news" in source:
        source_priority = 4
    elif "reddit" in source:
        source_priority = 3
    elif "duckduckgo" in source:
        source_priority = 2
    summary = _safe_summary(note.summary, limit=220)
    summary_quality = len(summary)
    title_quality = len(_clean_text(note.title))
    relevance_quality = len(_clean_text(note.mission_relevance))
    return (source_priority, summary_quality, relevance_quality, title_quality)


class _suppress_exceptions:
    def __enter__(self) -> None:
        return None

    def __exit__(self, _exc_type, _exc, _tb) -> bool:
        return True
