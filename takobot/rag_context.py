from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any


RAGREP_TIMEOUT_S = 18.0
RAGREP_DB_FILENAME = "ragrep-memory.db"
RAGREP_SNIPPET_LIMIT = 420


@dataclass(frozen=True)
class FocusProfile:
    score: float
    level: str
    rag_limit: int
    rag_char_budget: int


@dataclass(frozen=True)
class RagContextResult:
    context: str
    status: str
    hits: int
    limit: int
    error: str = ""


def focus_profile_from_dose(dose_state: Any | None) -> FocusProfile:
    if dose_state is None:
        return FocusProfile(score=0.50, level="balanced", rag_limit=8, rag_char_budget=1700)

    d = _clamp01(_safe_float(getattr(dose_state, "d", 0.5), default=0.5))
    o = _clamp01(_safe_float(getattr(dose_state, "o", 0.5), default=0.5))
    s = _clamp01(_safe_float(getattr(dose_state, "s", 0.5), default=0.5))
    e = _clamp01(_safe_float(getattr(dose_state, "e", 0.5), default=0.5))

    # High serotonin/endorphins generally map to better concentration and less context thrash.
    d_center_bonus = max(0.0, 1.0 - (abs(d - 0.58) * 1.9))
    score = _clamp01((0.43 * s) + (0.39 * e) + (0.10 * o) + (0.08 * d_center_bonus))

    if score >= 0.68:
        return FocusProfile(score=score, level="focused", rag_limit=4, rag_char_budget=900)
    if score >= 0.40:
        return FocusProfile(score=score, level="balanced", rag_limit=8, rag_char_budget=1700)
    return FocusProfile(score=score, level="diffuse", rag_limit=16, rag_char_budget=3600)


def format_focus_summary(profile: FocusProfile) -> str:
    return f"{profile.level} ({profile.score:.2f})"


def query_memory_with_ragrep(
    *,
    query: str,
    workspace_root: Path,
    memory_root: Path,
    state_dir: Path,
    focus_profile: FocusProfile,
    timeout_s: float = RAGREP_TIMEOUT_S,
) -> RagContextResult:
    cleaned_query = _clean_text(query)
    if not cleaned_query:
        return RagContextResult(
            context="No semantic query available for memory lookup.",
            status="query-empty",
            hits=0,
            limit=focus_profile.rag_limit,
        )
    if not memory_root.exists():
        return RagContextResult(
            context="`memory/` directory is missing; semantic recall skipped.",
            status="memory-missing",
            hits=0,
            limit=focus_profile.rag_limit,
        )

    ragrep_bin = shutil.which("ragrep")
    if ragrep_bin is None:
        return RagContextResult(
            context="`ragrep` is unavailable; semantic recall skipped.",
            status="ragrep-missing",
            hits=0,
            limit=focus_profile.rag_limit,
        )

    state_dir.mkdir(parents=True, exist_ok=True)
    db_path = state_dir / RAGREP_DB_FILENAME
    cmd = [
        ragrep_bin,
        cleaned_query,
        "--path",
        str(memory_root),
        "--limit",
        str(max(1, int(focus_profile.rag_limit))),
        "--db-path",
        str(db_path),
        "--json",
    ]
    try:
        proc = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=max(3.0, float(timeout_s)),
            cwd=str(workspace_root),
        )
    except Exception as exc:  # noqa: BLE001
        detail = _short(str(exc), 240)
        return RagContextResult(
            context=f"`ragrep` failed before completion: {detail}",
            status="ragrep-error",
            hits=0,
            limit=focus_profile.rag_limit,
            error=detail,
        )

    if proc.returncode != 0:
        detail = _short(proc.stderr or proc.stdout or f"exit={proc.returncode}", 240)
        return RagContextResult(
            context=f"`ragrep` returned an error: {detail}",
            status="ragrep-error",
            hits=0,
            limit=focus_profile.rag_limit,
            error=detail,
        )

    try:
        payload = json.loads(proc.stdout or "{}")
    except Exception as exc:  # noqa: BLE001
        detail = _short(str(exc), 180)
        return RagContextResult(
            context=f"`ragrep` JSON parse failed: {detail}",
            status="ragrep-parse-error",
            hits=0,
            limit=focus_profile.rag_limit,
            error=detail,
        )

    matches = payload.get("matches")
    if not isinstance(matches, list):
        matches = []

    rendered = _render_matches(
        matches=matches,
        workspace_root=workspace_root,
        char_budget=max(300, int(focus_profile.rag_char_budget)),
    )
    if not rendered:
        rendered = "No semantic memory matches found."
        return RagContextResult(
            context=rendered,
            status="ok",
            hits=0,
            limit=focus_profile.rag_limit,
        )

    return RagContextResult(
        context=rendered,
        status="ok",
        hits=len(matches),
        limit=focus_profile.rag_limit,
    )


def _render_matches(*, matches: list[Any], workspace_root: Path, char_budget: int) -> str:
    lines: list[str] = []
    for idx, raw in enumerate(matches, start=1):
        if not isinstance(raw, dict):
            continue
        metadata = raw.get("metadata")
        metadata_dict = metadata if isinstance(metadata, dict) else {}
        source = _render_source(metadata_dict.get("source"), workspace_root=workspace_root)
        score = _safe_float(raw.get("score"), default=0.0)
        snippet = _clean_text(str(raw.get("text") or ""))
        if not snippet:
            continue
        snippet = _short(snippet, RAGREP_SNIPPET_LIMIT)
        lines.append(f"{idx}. score={score:.4f} source={source}")
        lines.append(f"   {snippet}")
        text = "\n".join(lines)
        if len(text) > char_budget:
            trimmed = text[: max(0, char_budget - 3)].rstrip()
            return trimmed + "..."
    return "\n".join(lines)


def _render_source(source: Any, *, workspace_root: Path) -> str:
    raw = _clean_text(str(source or ""))
    if not raw:
        return "unknown"
    try:
        path = Path(raw)
    except Exception:
        return raw
    if not path.is_absolute():
        return raw
    try:
        return str(path.relative_to(workspace_root))
    except Exception:
        return raw


def _safe_float(value: Any, *, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except Exception:
            return default
    return default


def _clean_text(value: str) -> str:
    return " ".join((value or "").split()).strip()


def _short(value: str, limit: int) -> str:
    text = _clean_text(value)
    if not text:
        return "(no details)"
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value
