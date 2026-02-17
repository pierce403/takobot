from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
import time
from urllib.parse import urlparse, urlunparse


PROFILE_STATE_FILENAME = "operator_profile.json"
URL_RE = re.compile(r"\bhttps?://[^\s<>()\[\],;]+", re.IGNORECASE)
DOMAIN_RE = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}(?:/[^\s<>()\[\],;]*)?\b",
    re.IGNORECASE,
)
FOLLOWUP_COOLDOWN_S = 20 * 60


@dataclass
class OperatorProfileState:
    name: str = ""
    location: str = ""
    what_they_do: str = ""
    current_focus: str = ""
    preferred_sites: list[str] = field(default_factory=list)
    asked_intro: bool = False
    asked_focus: bool = False
    asked_websites: bool = False
    last_followup_topic: str = ""
    last_followup_at: float = 0.0
    updated_at: float = 0.0

    def to_json(self) -> dict[str, object]:
        return {
            "name": self.name,
            "location": self.location,
            "what_they_do": self.what_they_do,
            "current_focus": self.current_focus,
            "preferred_sites": list(self.preferred_sites),
            "asked_intro": bool(self.asked_intro),
            "asked_focus": bool(self.asked_focus),
            "asked_websites": bool(self.asked_websites),
            "last_followup_topic": self.last_followup_topic,
            "last_followup_at": float(self.last_followup_at),
            "updated_at": float(self.updated_at),
        }


@dataclass(frozen=True)
class OperatorProfileUpdate:
    name: str = ""
    location: str = ""
    what_they_do: str = ""
    current_focus: str = ""
    sites: tuple[str, ...] = ()


def load_operator_profile(state_dir: Path) -> OperatorProfileState:
    path = state_dir / PROFILE_STATE_FILENAME
    if not path.exists():
        return OperatorProfileState()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return OperatorProfileState()
    if not isinstance(payload, dict):
        return OperatorProfileState()
    return OperatorProfileState(
        name=_clean_text(str(payload.get("name") or "")),
        location=_clean_text(str(payload.get("location") or "")),
        what_they_do=_clean_text(str(payload.get("what_they_do") or "")),
        current_focus=_clean_text(str(payload.get("current_focus") or "")),
        preferred_sites=_normalize_sites(payload.get("preferred_sites") if isinstance(payload.get("preferred_sites"), list) else []),
        asked_intro=bool(payload.get("asked_intro")),
        asked_focus=bool(payload.get("asked_focus")),
        asked_websites=bool(payload.get("asked_websites")),
        last_followup_topic=_clean_text(str(payload.get("last_followup_topic") or "")),
        last_followup_at=_as_float(payload.get("last_followup_at")),
        updated_at=_as_float(payload.get("updated_at")),
    )


def save_operator_profile(state_dir: Path, profile: OperatorProfileState) -> None:
    path = state_dir / PROFILE_STATE_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile.to_json(), sort_keys=True, ensure_ascii=True, indent=2) + "\n", encoding="utf-8")


def extract_operator_profile_update(text: str) -> OperatorProfileUpdate:
    cleaned = _clean_text(text)
    if not cleaned:
        return OperatorProfileUpdate()

    return OperatorProfileUpdate(
        name=_extract_name(cleaned),
        location=_extract_location(cleaned),
        what_they_do=_extract_what_they_do(cleaned),
        current_focus=_extract_current_focus(cleaned),
        sites=tuple(extract_site_urls(cleaned)),
    )


def extract_site_urls(text: str) -> list[str]:
    cleaned = _clean_text(text)
    if not cleaned:
        return []
    found: list[str] = []
    for match in URL_RE.findall(cleaned):
        found.append(match)
    for match in DOMAIN_RE.findall(cleaned):
        if match.lower().startswith("http://") or match.lower().startswith("https://"):
            continue
        found.append(match)
    return _normalize_sites(found)


def apply_operator_profile_update(
    profile: OperatorProfileState,
    update: OperatorProfileUpdate,
) -> tuple[list[str], list[str]]:
    changed: list[str] = []
    if update.name and update.name != profile.name:
        profile.name = update.name
        changed.append(f"name={update.name}")
    if update.location and update.location != profile.location:
        profile.location = update.location
        changed.append(f"location={update.location}")
    if update.what_they_do and update.what_they_do != profile.what_they_do:
        profile.what_they_do = update.what_they_do
        changed.append(f"work={update.what_they_do}")
    if update.current_focus and update.current_focus != profile.current_focus:
        profile.current_focus = update.current_focus
        changed.append(f"focus={update.current_focus}")

    added_sites: list[str] = []
    for site in update.sites:
        if site in profile.preferred_sites:
            continue
        profile.preferred_sites.append(site)
        added_sites.append(site)

    if changed or added_sites:
        profile.updated_at = time.time()
    return changed, added_sites


def write_operator_profile_note(memory_root: Path, profile: OperatorProfileState) -> Path:
    people_dir = memory_root / "people"
    people_dir.mkdir(parents=True, exist_ok=True)
    path = people_dir / "operator.md"
    path.write_text(_render_operator_profile(profile), encoding="utf-8")
    return path


def next_child_followup_question(profile: OperatorProfileState) -> str:
    now = time.time()
    if profile.last_followup_at > 0 and (now - profile.last_followup_at) < FOLLOWUP_COOLDOWN_S:
        return ""
    if not profile.asked_intro and not (profile.location and profile.what_they_do):
        profile.asked_intro = True
        profile.last_followup_topic = "intro"
        profile.last_followup_at = now
        profile.updated_at = now
        return "tiny curiosity bubble: where are you working from lately, and what do your days usually involve?"
    if not profile.asked_focus and not profile.current_focus:
        profile.asked_focus = True
        profile.last_followup_topic = "focus"
        profile.last_followup_at = now
        profile.updated_at = now
        return "what are you most interested in right now? I can tie my exploring to that."
    if not profile.asked_websites and not profile.preferred_sites:
        profile.asked_websites = True
        profile.last_followup_topic = "websites"
        profile.last_followup_at = now
        profile.updated_at = now
        return "where do you like browsing online? share links and I will add them to my watch list."
    return ""


def child_profile_prompt_context(profile: OperatorProfileState) -> str:
    known: list[str] = []
    missing: list[str] = []

    if profile.name:
        known.append(f"name={profile.name}")
    else:
        missing.append("name")
    if profile.location:
        known.append(f"location={profile.location}")
    else:
        missing.append("location")
    if profile.what_they_do:
        known.append(f"what_they_do={profile.what_they_do}")
    else:
        missing.append("what_they_do")
    if profile.current_focus:
        known.append(f"current_focus={profile.current_focus}")
    else:
        missing.append("current_focus")

    if profile.preferred_sites:
        known.append(f"preferred_sites={len(profile.preferred_sites)}")
    else:
        missing.append("preferred_sites")

    asked = (
        f"asked_intro={_yes_no(profile.asked_intro)} "
        f"asked_focus={_yes_no(profile.asked_focus)} "
        f"asked_websites={_yes_no(profile.asked_websites)}"
    )
    cooldown = "followup_cooldown=active" if (time.time() - profile.last_followup_at) < FOLLOWUP_COOLDOWN_S else "followup_cooldown=clear"
    parts = [
        "known: " + (", ".join(known) if known else "(none)"),
        "missing: " + (", ".join(missing) if missing else "(none)"),
        asked,
        cooldown,
    ]
    if profile.last_followup_topic:
        parts.append(f"last_followup_topic={profile.last_followup_topic}")
    return " | ".join(parts)


def _render_operator_profile(profile: OperatorProfileState) -> str:
    name = profile.name or "(unknown)"
    location = profile.location or "(unknown)"
    what_they_do = profile.what_they_do or "(unknown)"
    current_focus = profile.current_focus or "(not captured yet)"
    lines = [
        "# Operator Profile",
        "",
        "## Identity",
        f"- Name: {name}",
        f"- Location: {location}",
        "",
        "## What They Do",
        f"- {what_they_do}",
        "",
        "## Current Focus",
        f"- {current_focus}",
        "",
        "## Preferred Websites",
    ]
    if profile.preferred_sites:
        for site in profile.preferred_sites:
            lines.append(f"- {site}")
    else:
        lines.append("- (none captured yet)")
    lines.append("")
    return "\n".join(lines)


def _extract_name(text: str) -> str:
    patterns = (
        r"\bmy name is ([a-z][a-z0-9 _'-]{1,40})\b",
        r"\bi am ([a-z][a-z0-9 _'-]{1,40})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        value = _clean_phrase(match.group(1))
        if _looks_like_name(value):
            return value
    return ""


def _extract_location(text: str) -> str:
    match = re.search(r"\b(?:i am|i'm)\s+(?:in|at|from)\s+([^.,;!?]{2,80})", text, flags=re.IGNORECASE)
    if not match:
        return ""
    return _clean_phrase(match.group(1))


def _extract_what_they_do(text: str) -> str:
    patterns = (
        r"\bi work as\s+([^.,;!?]{2,100})",
        r"\bi am\s+(?:a|an)\s+([^.,;!?]{2,100})",
        r"\bi build\s+([^.,;!?]{2,100})",
        r"\bi work on\s+([^.,;!?]{2,100})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = _clean_phrase(match.group(1))
            if value:
                return value
    return ""


def _extract_current_focus(text: str) -> str:
    patterns = (
        r"\b(?:right now|currently)\s+(?:i am|i'm)?\s*(?:focused on|working on)\s+([^.,;!?]{2,120})",
        r"\b(?:today|this week)\s+(?:i am|i'm)?\s*(?:working on|focused on)\s+([^.,;!?]{2,120})",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            value = _clean_phrase(match.group(1))
            if value:
                return value
    return ""


def _normalize_sites(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in values:
        candidate = _clean_text(str(raw))
        if not candidate:
            continue
        if "://" not in candidate and "." in candidate:
            candidate = "https://" + candidate
        parsed = urlparse(candidate)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            continue
        normalized = urlunparse(
            (
                parsed.scheme.lower(),
                parsed.netloc.lower(),
                parsed.path or "",
                "",
                parsed.query or "",
                "",
            )
        ).rstrip("/")
        if normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _looks_like_name(value: str) -> bool:
    lowered = value.lower()
    if any(token in lowered for token in ("working", "focused", "build", "developer", "engineer", "from", "in ")):
        return False
    return bool(value)


def _clean_phrase(value: str) -> str:
    cleaned = _clean_text(value).strip(" .,:;!?-")
    return cleaned


def _clean_text(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _as_float(value: object) -> float:
    try:
        return float(value)
    except Exception:
        return 0.0


def _yes_no(value: bool) -> str:
    return "yes" if value else "no"
