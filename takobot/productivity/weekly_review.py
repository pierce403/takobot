from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from .tasks import Task, list_tasks


@dataclass(frozen=True)
class WeeklyReview:
    report: str
    stale_tasks: list[Task]
    projects_missing_next: list[str]
    areas_touched: list[str]


InferFn = Callable[[str, float], tuple[str, str]]


def _norm(value: str) -> str:
    return " ".join(value.strip().lower().split())


def _project_files(repo_root: Path) -> list[Path]:
    root = repo_root / "projects"
    if not root.exists():
        return []
    return sorted([p for p in root.glob("*.md") if p.is_file() and p.name.lower() != "readme.md"])


def _area_files(repo_root: Path) -> list[Path]:
    root = repo_root / "areas"
    if not root.exists():
        return []
    return sorted([p for p in root.glob("*.md") if p.is_file() and p.name.lower() != "readme.md"])


def _project_names(repo_root: Path) -> list[str]:
    return [p.stem for p in _project_files(repo_root)]


def _area_names(repo_root: Path) -> list[str]:
    return [p.stem for p in _area_files(repo_root)]


def build_weekly_review(
    repo_root: Path,
    *,
    today: date,
    stale_after_days: int = 7,
) -> WeeklyReview:
    tasks = list_tasks(repo_root)
    open_tasks = [t for t in tasks if t.is_open]
    stale: list[Task] = []
    for task in open_tasks:
        age = (today - task.updated).days
        if age >= stale_after_days:
            stale.append(task)

    projects = _project_names(repo_root)
    projects_missing_next: list[str] = []
    for proj in projects:
        key = _norm(proj)
        has_next = any(_norm(t.project or "") == key and t.is_open for t in tasks)
        if not has_next:
            projects_missing_next.append(proj)

    areas = _area_names(repo_root)
    areas_touched: list[str] = []
    for area in areas:
        key = _norm(area)
        if any(_norm(t.area or "") == key for t in tasks):
            areas_touched.append(area)

    lines: list[str] = []
    lines.append(f"weekly review ({today.isoformat()})")
    lines.append("")
    lines.append("Open tasks:")
    lines.append(f"- count: {len(open_tasks)}")
    lines.append("")

    lines.append("Stale tasks (>= 7 days untouched):")
    if stale:
        for task in sorted(stale, key=lambda t: t.updated.isoformat())[:20]:
            lines.append(f"- {task.id} (updated {task.updated.isoformat()}): {task.title}")
    else:
        lines.append("- none")
    lines.append("")

    lines.append("Projects missing a next action:")
    if projects_missing_next:
        for proj in projects_missing_next[:20]:
            lines.append(f"- {proj} (no open task references this project)")
    else:
        lines.append("- none (or no projects yet)")
    lines.append("")

    lines.append("Areas touched (tasks reference these areas):")
    if areas_touched:
        for area in areas_touched[:20]:
            lines.append(f"- {area}")
    else:
        lines.append("- none (or no areas yet)")
    lines.append("")

    lines.append("Prompts:")
    lines.append("- Archive completed projects into `archives/` (move files/folders; don’t delete).")
    lines.append("- Promote durable lessons/decisions into `MEMORY.md` (operator-approved).")
    lines.append("- For each stale task: clarify the next action, change scope, or mark `someday`/`done`.")

    return WeeklyReview(
        report="\n".join(lines).rstrip(),
        stale_tasks=stale,
        projects_missing_next=projects_missing_next,
        areas_touched=areas_touched,
    )


def build_weekly_review_prompt(review: WeeklyReview) -> str:
    return (
        "You are Tako doing a Type2 weekly review.\n"
        "Given the weekly review facts, produce a short operator-facing plan.\n"
        "Constraints:\n"
        "- No markdown.\n"
        "- Max 10 lines.\n"
        "- Include 1-3 concrete next actions.\n"
        "- Never invent facts.\n"
        "\n"
        "weekly_review_facts:\n"
        + review.report
        + "\n"
    )


def weekly_review_with_inference(
    review: WeeklyReview,
    *,
    infer: InferFn | None,
    timeout_s: float = 85.0,
) -> tuple[str, str, str]:
    if infer is None:
        return review.report, "heuristic", ""
    prompt = build_weekly_review_prompt(review)
    try:
        provider, output = infer(prompt, timeout_s)
        cleaned = " ".join(output.strip().split())
        if cleaned:
            return review.report + "\n\nType2 suggestion (" + provider + "):\n" + cleaned, provider, ""
    except Exception as exc:  # noqa: BLE001
        return review.report, "heuristic", str(exc) or exc.__class__.__name__
    return review.report, "heuristic", ""

