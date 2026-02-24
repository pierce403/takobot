from __future__ import annotations

import json
import re


def _normalize_text(text: str) -> str:
    return " ".join(text.strip().split())


def looks_like_role_change_request(text: str) -> bool:
    """Heuristic gate for purpose/mission updates."""
    lowered = _normalize_text(text).lower()
    if not lowered:
        return False
    if not any(token in lowered for token in ("purpose", "mission", "role")):
        return False

    # Informational questions should not trigger a write path.
    if looks_like_role_info_query(lowered):
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


def looks_like_role_info_query(text: str) -> bool:
    lowered = _normalize_text(text).lower()
    if not lowered:
        return False
    if not any(token in lowered for token in ("purpose", "mission", "role")):
        return False

    question_only_patterns = (
        r"\bwhat(?:'s| is)\s+your\s+(?:purpose|mission|role)\b",
        r"\bwhat\s+your\s+(?:purpose|mission|role)\s+is\b",
        r"\btell\s+me\s+what\s+your\s+(?:purpose|mission|role)\s+is\b",
        r"\bcan\s+you\s+tell\s+me\s+what\s+your\s+(?:purpose|mission|role)\s+is\b",
        r"\bremind\s+me\s+what\s+your\s+(?:purpose|mission|role)\s+is\b",
        r"\bshare\s+your\s+(?:purpose|mission|role)\b",
    )
    if any(re.search(pattern, lowered) for pattern in question_only_patterns):
        return True

    question_starters = ("what", "who", "why", "how", "can you tell", "could you tell", "tell me", "remind me")
    if lowered.endswith("?") and any(lowered.startswith(prefix) for prefix in question_starters):
        return True
    return False


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


def extract_name_from_text(text: str, *, allow_plain_name: bool = False) -> str:
    cleaned = _normalize_text(text)
    if not cleaned:
        return ""

    patterns = (
        r"(?:call|name|rename)\s+(?:yourself|you)\s*(?:to|as|:|=)?\s*(.+)",
        r"(?:set|change|update)\s+(?:your\s+)?name\s*(?:to|as|:|=)\s*(.+)",
        r"(?:your|you)\s+name\s*(?:can|should)\s*be\s+(.+)",
        r"(?:your|you)\s+name\s+is\s+(.+)",
    )
    for pattern in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if not match:
            continue
        candidate = _sanitize_name_candidate(match.group(1))
        if candidate:
            return candidate

    if not allow_plain_name:
        return ""

    candidate = _sanitize_name_candidate(cleaned)
    if _is_plain_name_candidate(candidate):
        return candidate
    return ""


def looks_like_name_change_hint(text: str) -> bool:
    lowered = _normalize_text(text).lower()
    if not lowered:
        return False

    if extract_name_from_text(text):
        return True

    direct_phrases = (
        "your name",
        "set name",
        "set your name",
        "change name",
        "change your name",
        "update name",
        "update your name",
        "rename",
        "call yourself",
        "call you",
        "display name",
        "identity name",
        "alias",
        "profile name",
        "xmtp name",
        "xmtp profile",
    )
    if any(phrase in lowered for phrase in direct_phrases):
        return True

    action_words = ("set", "change", "update", "rename", "fix", "correct")
    if "profile" in lowered and any(word in lowered for word in action_words):
        if "xmtp" in lowered or "display" in lowered or "name" in lowered:
            return True

    return False


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


def build_identity_name_intent_prompt(*, text: str, current_name: str) -> str:
    return (
        "Classify whether the user is asking you to change your identity/display name.\n"
        "Return exactly one JSON object with this schema: {\"intent\":\"rename|none\",\"name\":\"...\"}\n"
        "Rules:\n"
        "- Set intent=rename only when the user is requesting a name change (including XMTP profile name requests).\n"
        "- If intent=rename and a concrete replacement name is provided, put that in `name`.\n"
        "- If intent=rename but no concrete replacement name is present, set `name` to an empty string.\n"
        "- For informational questions or unrelated chat, set intent=none and name=\"\".\n"
        "- No prose, no markdown, no extra keys.\n"
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

    return _sanitize_name_candidate(candidate)


def extract_name_intent_from_model_output(value: str) -> tuple[bool, str]:
    raw = value.strip()
    if not raw:
        return False, ""

    if raw.startswith("```"):
        lines = raw.splitlines()
        if len(lines) >= 3 and lines[-1].strip().startswith("```"):
            raw = "\n".join(lines[1:-1]).strip()

    requested = False
    candidate = ""
    parsed_payload = False

    if raw.startswith("{") and raw.endswith("}"):
        try:
            parsed = json.loads(raw)
        except Exception:  # noqa: BLE001
            parsed = None
        if isinstance(parsed, dict):
            parsed_payload = True
            intent_raw = " ".join(str(parsed.get("intent") or "").split()).strip().lower().replace("-", "_")
            requested_raw = parsed.get("requested")
            if isinstance(requested_raw, bool):
                requested = requested_raw
            if intent_raw in {"rename", "set_name", "change_name", "update_name", "name_change"}:
                requested = True
            elif intent_raw in {"none", "no_change", "ignore", "chat"} and not isinstance(requested_raw, bool):
                requested = False

            maybe_name = parsed.get("name")
            if isinstance(maybe_name, str):
                candidate = maybe_name

    if not parsed_payload:
        first_line = raw.splitlines()[0].strip().lower()
        if first_line in {"rename", "rename requested", "intent: rename", "intent=rename"}:
            requested = True
        elif first_line in {"none", "intent: none", "intent=none"}:
            requested = False
        else:
            fallback_name = extract_name_from_model_output(raw)
            if fallback_name:
                requested = True
                candidate = fallback_name

    return requested, _sanitize_name_candidate(candidate)


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


def _sanitize_name_candidate(value: str) -> str:
    candidate = _normalize_text(value)
    if not candidate:
        return ""
    candidate = candidate.strip().strip("`\"' ")
    candidate = re.sub(r"^(?:name|candidate)\s*(?::|=)\s*", "", candidate, flags=re.IGNORECASE)
    candidate = re.sub(r"^(?:your\s+name\s+is|name\s+is)\s+", "", candidate, flags=re.IGNORECASE)
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
        "you",
        "me",
        "it",
        "myself",
        "yourself",
        "yes",
        "no",
        "ok",
        "okay",
        "keep",
        "same",
        "default",
        "skip",
        "later",
    }
    if lowered in blocked:
        return ""

    if len(candidate) > 48:
        candidate = candidate[:48].rstrip()
    return candidate


def _is_plain_name_candidate(candidate: str) -> bool:
    if not candidate:
        return False
    if len(candidate) > 48:
        return False
    if any(char in candidate for char in ",:;!?/\\()[]{}<>"):
        return False
    words = candidate.split()
    if not words or len(words) > 3:
        return False
    lowered_words = {word.casefold() for word in words}
    blocked_words = {
        "your",
        "name",
        "call",
        "rename",
        "set",
        "change",
        "update",
        "purpose",
        "mission",
        "role",
    }
    return not bool(lowered_words & blocked_words)
