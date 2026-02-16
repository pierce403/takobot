from __future__ import annotations

import json
import re


def _normalize_text(text: str) -> str:
    return " ".join(text.strip().split())


def looks_like_name_change_request(text: str) -> bool:
    """Heuristic gate before we spend inference calls extracting a name."""
    lowered = _normalize_text(text).lower()
    if not lowered:
        return False

    # Strong/direct phrasing
    if "call yourself" in lowered:
        return True
    if "name yourself" in lowered or "rename yourself" in lowered:
        return True
    if "set your name" in lowered or "change your name" in lowered:
        return True

    # Common/typo variants: "your name can be X" / "you name can be X"
    if ("your name" in lowered or "you name" in lowered) and ("can be" in lowered or "should be" in lowered or " is " in f" {lowered} "):
        return True

    # Broader "name can be X" but require it to be about the agent ("you/your/tako") to avoid false positives.
    if "name can be" in lowered and any(token in lowered for token in (" you ", " your ", " tako ")):
        return True

    return False


def looks_like_role_change_request(text: str) -> bool:
    """Heuristic gate for purpose/mission updates."""
    lowered = _normalize_text(text).lower()
    if not lowered:
        return False
    if not any(token in lowered for token in ("purpose", "mission", "role")):
        return False

    # Informational questions should not trigger a write path.
    question_only_patterns = (
        "what is your purpose",
        "what's your purpose",
        "what is your mission",
        "what's your mission",
        "what is your role",
        "what's your role",
    )
    if any(pattern in lowered for pattern in question_only_patterns):
        return False

    direct_phrases = (
        "your purpose is",
        "your mission is",
        "your role is",
        "my purpose for you is",
        "set your purpose",
        "set your mission",
        "set your role",
        "change your purpose",
        "change your mission",
        "change your role",
        "update your purpose",
        "update your mission",
        "update your role",
        "fix your purpose",
        "fix your mission",
        "fix your role",
        "correct your purpose",
        "correct your mission",
        "correct your role",
    )
    if any(phrase in lowered for phrase in direct_phrases):
        return True

    action_words = ("set", "change", "update", "fix", "correct", "rewrite", "adjust")
    mentions_agent = ("your" in lowered) or (" you " in f" {lowered} ")
    return mentions_agent and any(word in lowered for word in action_words)


def extract_role_from_text(text: str) -> str:
    cleaned = _normalize_text(text)
    if not cleaned:
        return ""

    patterns = (
        r"(?:my\s+(?:purpose|mission)\s+for\s+you|your\s+(?:purpose|mission|role)|(?:purpose|mission|role))\s*(?:is|should\s+be|needs\s+to\s+be|can\s+be|:|=)\s*(.+)",
        r"(?:set|change|update|fix|correct|rewrite|adjust)\s+(?:your\s+)?(?:purpose|mission|role)\s*(?:to|as|:|=)\s*(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if not match:
            continue
        candidate = _sanitize_role_candidate(match.group(1))
        if candidate:
            return candidate
    return ""


def build_identity_name_prompt(*, text: str, current_name: str) -> str:
    return (
        "Extract the intended display name from the user message.\n"
        "Return exactly one JSON object with one key: {\"name\":\"...\"}\n"
        "If no clear name is provided, return {\"name\":\"\"}.\n"
        "Do not include any prose, markdown, or extra keys.\n"
        "Prefer concise names and ignore unrelated clauses.\n"
        f"current_name={current_name}\n"
        f"user_message={text}\n"
    )


def extract_name_from_model_output(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""

    # Accept fenced output while still preferring strict JSON.
    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            raw = "\n".join(lines[1:-1]).strip()

    candidate = ""
    parsed_name_found = False
    if raw.startswith("{") and raw.endswith("}"):
        try:
            parsed = json.loads(raw)
        except Exception:  # noqa: BLE001
            parsed = None
        if isinstance(parsed, dict):
            maybe = parsed.get("name")
            if isinstance(maybe, str):
                candidate = maybe
                parsed_name_found = True

    if not candidate and not parsed_name_found:
        line = raw.splitlines()[0].strip()
        lowered = line.lower()
        prefixes = ["name:", "candidate:", "- name:", "\"name\":"]
        for prefix in prefixes:
            if lowered.startswith(prefix):
                line = line[len(prefix) :].strip()
                break
        candidate = line

    candidate = candidate.strip().strip("`\"' ")
    candidate = candidate.strip(" .,:;!?-_")
    candidate = " ".join(candidate.split())
    if not candidate:
        return ""

    lowered = candidate.lower()
    blocked = {"none", "null", "n/a", "unknown", "you", "me", "it", "myself", "yourself"}
    if lowered in blocked:
        return ""

    if len(candidate) > 48:
        candidate = candidate[:48].rstrip()
    return candidate


def build_identity_role_prompt(*, text: str, current_role: str) -> str:
    return (
        "Extract the intended identity purpose/mission statement from the user message.\n"
        "Return exactly one JSON object with one key: {\"role\":\"...\"}\n"
        "If no clear replacement statement is provided, return {\"role\":\"\"}.\n"
        "Do not include prose, markdown, or extra keys.\n"
        "Preserve the user's wording but remove unrelated clauses.\n"
        f"current_role={current_role}\n"
        f"user_message={text}\n"
    )


def extract_role_from_model_output(value: str) -> str:
    raw = value.strip()
    if not raw:
        return ""

    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            raw = "\n".join(lines[1:-1]).strip()

    candidate = ""
    parsed_role_found = False
    if raw.startswith("{") and raw.endswith("}"):
        try:
            parsed = json.loads(raw)
        except Exception:  # noqa: BLE001
            parsed = None
        if isinstance(parsed, dict):
            for key in ("role", "purpose", "mission"):
                maybe = parsed.get(key)
                if isinstance(maybe, str):
                    candidate = maybe
                    parsed_role_found = True
                    break

    if not candidate and not parsed_role_found:
        line = raw.splitlines()[0].strip()
        lowered = line.lower()
        prefixes = ["role:", "purpose:", "mission:", "- role:", "\"role\":"]
        for prefix in prefixes:
            if lowered.startswith(prefix):
                line = line[len(prefix) :].strip()
                break
        candidate = line

    return _sanitize_role_candidate(candidate)


def _sanitize_role_candidate(value: str) -> str:
    candidate = _normalize_text(value)
    if not candidate:
        return ""
    candidate = candidate.strip().strip("`\"' ")
    candidate = re.sub(r"(?:\s+)?(?:please|thanks|thank you)\.?$", "", candidate, flags=re.IGNORECASE).strip()
    candidate = candidate.strip(" .,:;!?-_")
    if not candidate:
        return ""

    lowered = candidate.casefold()
    blocked = {
        "none",
        "null",
        "n/a",
        "unknown",
        "that",
        "this",
        "it",
        "same",
        "same as before",
        "typo",
        "spelling",
        "spelling mistake",
    }
    if lowered in blocked:
        return ""
    if len(candidate) > 280:
        candidate = candidate[:280].rstrip()
    return candidate
