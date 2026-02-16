from __future__ import annotations

from pathlib import Path

from .paths import repo_root


def load_memory_frontmatter_excerpt(*, root: Path | None = None, max_chars: int = 1400) -> str:
    target_root = root or repo_root()
    path = target_root / "MEMORY.md"
    if not path.exists():
        return "MEMORY.md is missing."
    try:
        text = path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        return f"MEMORY.md read failed: {exc}"

    lines = [line.rstrip() for line in text.splitlines()]
    if not lines:
        return "MEMORY.md is empty."

    joined = "\n".join(lines).strip()
    if not joined:
        return "MEMORY.md is empty."

    limit = max(200, int(max_chars))
    if len(joined) <= limit:
        return joined
    return joined[: limit - 3].rstrip() + "..."
