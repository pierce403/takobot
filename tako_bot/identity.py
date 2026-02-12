from __future__ import annotations

import json


def looks_like_name_change_request(text: str) -> bool:
    """Heuristic gate before we spend inference calls extracting a name."""
    lowered = " ".join(text.strip().lower().split())
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
