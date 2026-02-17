from __future__ import annotations

from dataclasses import dataclass
import importlib.resources
from pathlib import Path


STARTER_TOOL_SLUGS: tuple[str, ...] = ("web_search", "web_fetch")


@dataclass(frozen=True)
class StarterToolsResult:
    created: tuple[str, ...]
    existing: tuple[str, ...]
    warnings: tuple[str, ...]


def seed_starter_tools(workspace_root: Path) -> StarterToolsResult:
    created: list[str] = []
    existing: list[str] = []
    warnings: list[str] = []

    try:
        template_root = importlib.resources.files("takobot.templates").joinpath("workspace").joinpath("tools")
    except Exception as exc:  # noqa: BLE001
        return StarterToolsResult(created=(), existing=(), warnings=(f"starter tool templates unavailable: {exc}",))

    tools_root = workspace_root / "tools"
    tools_root.mkdir(parents=True, exist_ok=True)

    for slug in STARTER_TOOL_SLUGS:
        source_dir = template_root.joinpath(slug)
        target_dir = tools_root / slug
        if not source_dir.exists():
            warnings.append(f"missing starter tool template: {slug}")
            continue

        target_dir.mkdir(parents=True, exist_ok=True)
        wrote_any = False
        try:
            entries = list(source_dir.iterdir())
        except Exception as exc:  # noqa: BLE001
            warnings.append(f"failed reading starter tool template `{slug}`: {exc}")
            continue

        for item in entries:
            if item.is_dir():
                continue
            target_file = target_dir / item.name
            if target_file.exists():
                continue
            try:
                target_file.write_bytes(item.read_bytes())
                wrote_any = True
            except Exception as exc:  # noqa: BLE001
                warnings.append(f"failed writing `{target_file}`: {exc}")

        if wrote_any:
            created.append(slug)
        else:
            existing.append(slug)

    return StarterToolsResult(
        created=tuple(sorted(set(created))),
        existing=tuple(sorted(set(existing))),
        warnings=tuple(warnings),
    )
