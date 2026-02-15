from __future__ import annotations

import re


_WORD_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_-]*")
_STOP = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "into",
    "while",
    "when",
    "then",
    "your",
    "you",
    "our",
    "are",
    "was",
    "were",
    "have",
    "has",
    "had",
    "will",
    "shall",
    "would",
    "could",
    "should",
    "operator",
    "help",
    "safe",
}


def mission_keywords(text: str) -> set[str]:
    lowered = (text or "").lower()
    tokens = {token for token in _WORD_RE.findall(lowered) if len(token) >= 4}
    return {token for token in tokens if token not in _STOP}


def activity_alignment_score(activity: str, mission: str) -> float:
    mission_tokens = mission_keywords(mission)
    if not mission_tokens:
        return 1.0
    activity_tokens = mission_keywords(activity)
    if not activity_tokens:
        return 0.0
    overlap = mission_tokens & activity_tokens
    return len(overlap) / float(len(mission_tokens))


def is_activity_mission_aligned(activity: str, mission: str, *, min_score: float = 0.2) -> bool:
    if activity_alignment_score(activity, mission) >= min_score:
        return True
    lowered = (activity or "").lower()
    if "operator" in lowered and any(token in lowered for token in {"safe", "safely", "reliable", "quality"}):
        return True
    return False
