from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .daily import append_daily_note, ensure_daily_log
from .paths import daily_root
from .tool_ops import fetch_webpage


@dataclass(frozen=True)
class ResearchSourceNote:
    requested_url: str
    resolved_url: str
    ok: bool
    title: str
    summary: str
    error: str = ""


@dataclass(frozen=True)
class ResearchNotesResult:
    topic: str
    notes_path: Path
    sources: tuple[ResearchSourceNote, ...]
    sources_ok: int
    sources_failed: int


def take_research_notes(
    topic: str,
    urls: list[str],
    *,
    notes_root: Path | None = None,
    day: date | None = None,
    max_summary_chars: int = 240,
) -> ResearchNotesResult:
    cleaned_topic = " ".join((topic or "").split()).strip()
    if not cleaned_topic:
        raise ValueError("topic is required")

    cleaned_urls = [value.strip() for value in urls if isinstance(value, str) and value.strip()]
    if not cleaned_urls:
        raise ValueError("at least one URL is required")

    notes_dir = notes_root or daily_root()
    target_day = day or date.today()
    notes_path = ensure_daily_log(notes_dir, target_day)
    append_daily_note(notes_dir, target_day, f"Research topic: {cleaned_topic}")
    append_daily_note(notes_dir, target_day, f"Research plan: review {len(cleaned_urls)} source(s).")

    results: list[ResearchSourceNote] = []
    ok_count = 0
    fail_count = 0

    for requested in cleaned_urls:
        fetched = fetch_webpage(requested)
        if fetched.ok:
            ok_count += 1
            title = fetched.title or "(untitled)"
            summary = _summarize_text(fetched.text, max_chars=max_summary_chars)
            append_daily_note(
                notes_dir,
                target_day,
                f"Research note: topic={cleaned_topic}; source={fetched.url}; title={title}; summary={summary}",
            )
            results.append(
                ResearchSourceNote(
                    requested_url=requested,
                    resolved_url=fetched.url,
                    ok=True,
                    title=title,
                    summary=summary,
                )
            )
            continue

        fail_count += 1
        append_daily_note(
            notes_dir,
            target_day,
            f"Research source failed: topic={cleaned_topic}; source={requested}; error={fetched.error}",
        )
        results.append(
            ResearchSourceNote(
                requested_url=requested,
                resolved_url=requested,
                ok=False,
                title="",
                summary="",
                error=fetched.error,
            )
        )

    append_daily_note(
        notes_dir,
        target_day,
        f"Research summary: topic={cleaned_topic}; sources_ok={ok_count}/{len(cleaned_urls)}",
    )
    return ResearchNotesResult(
        topic=cleaned_topic,
        notes_path=notes_path,
        sources=tuple(results),
        sources_ok=ok_count,
        sources_failed=fail_count,
    )


def _summarize_text(text: str, *, max_chars: int) -> str:
    compact = " ".join((text or "").split())
    if not compact:
        return "(no readable text)"
    if len(compact) <= max_chars:
        return compact
    return compact[: max_chars - 3].rstrip() + "..."
