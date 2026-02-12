from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Callable

from .outcomes import Outcome, outcomes_completion
from .tasks import Task, format_task_line


SUMMARY_START = "<!-- tako:compress:start -->"
SUMMARY_END = "<!-- tako:compress:end -->"


@dataclass(frozen=True)
class CompressResult:
    ok: bool
    summary_md: str
    provider: str
    error: str


InferFn = Callable[[str, float], tuple[str, str]]


def _strip_block(text: str) -> str:
    return "\n".join(line.rstrip() for line in text.strip().splitlines()).strip()


def _upsert_block(text: str, block_md: str) -> str:
    block = f"{SUMMARY_START}\n{block_md.rstrip()}\n{SUMMARY_END}"
    if SUMMARY_START in text and SUMMARY_END in text:
        pattern = re.compile(
            re.escape(SUMMARY_START) + r".*?" + re.escape(SUMMARY_END),
            re.DOTALL,
        )
        return pattern.sub(block, text).rstrip() + "\n"
    return text.rstrip() + "\n\n" + block + "\n"


def _heuristic_summary(
    *,
    day: date,
    daily_text: str,
    tasks: list[Task],
    outcomes: list[Outcome],
) -> str:
    open_tasks = [t for t in tasks if t.is_open]
    done_outcomes, total_outcomes = outcomes_completion(outcomes)
    undecided = [o for o in outcomes if o.text.strip() and not o.done]

    decisions: list[str] = []
    notes: list[str] = []
    for line in daily_text.splitlines():
        if line.startswith("- "):
            notes.append(line[2:].strip())
    decisions = [item for item in notes if "decid" in item.lower()][:6]
    lessons = [item for item in notes if "lesson" in item.lower() or "learn" in item.lower()][:6]

    md_lines = [
        f"## Compressed Summary ({day.isoformat()})",
        "",
        "### Decisions",
        "- " + ("\n- ".join(decisions) if decisions else "(none captured)"),
        "",
        "### Open Loops",
    ]

    if undecided:
        for item in undecided[:6]:
            md_lines.append(f"- outcome: {item.text}")
    if open_tasks:
        for task in open_tasks[:10]:
            md_lines.append("- task: " + format_task_line(task, today=day))
    if not undecided and not open_tasks:
        md_lines.append("- (none)")

    md_lines.extend(
        [
            "",
            "### Lessons",
            "- " + ("\n- ".join(lessons) if lessons else "(none captured)"),
            "",
            "### Next Actions",
        ]
    )

    if open_tasks:
        for task in open_tasks[:8]:
            md_lines.append(f"- {task.title} ({task.id})")
    else:
        md_lines.append("- (none)")

    md_lines.extend(
        [
            "",
            "### Outcomes",
            f"- done: {done_outcomes}/{total_outcomes}",
        ]
    )

    return "\n".join(md_lines).rstrip()


def build_compress_prompt(
    *,
    day: date,
    daily_text: str,
    tasks: list[Task],
    outcomes: list[Outcome],
) -> str:
    open_tasks = [t for t in tasks if t.is_open]
    tasks_preview = "\n".join(format_task_line(t, today=day) for t in open_tasks[:25])
    outcomes_preview = "\n".join(
        f"- [{'x' if o.done else ' '}] {o.text}".rstrip() for o in outcomes[:10] if o.text.strip()
    )
    return (
        "You are Tako doing a Type2 progressive summarization pass.\n"
        "Summarize the daily log into exactly these sections, in plain Markdown:\n"
        "## Compressed Summary (YYYY-MM-DD)\n"
        "### Decisions\n"
        "### Open Loops\n"
        "### Lessons\n"
        "### Next Actions\n"
        "### Outcomes\n"
        "\n"
        "Rules:\n"
        "- Be concise.\n"
        "- Prefer bullets.\n"
        "- Never invent facts.\n"
        "- Never include secrets.\n"
        "- Keep it actionable: open loops and next actions should be concrete.\n"
        "\n"
        f"day={day.isoformat()}\n"
        f"open_tasks:\n{tasks_preview or '(none)'}\n"
        f"outcomes:\n{outcomes_preview or '(none)'}\n"
        "\n"
        "daily_log:\n"
        + daily_text
        + "\n"
    )


def compress_daily_log(
    daily_path: Path,
    *,
    day: date,
    tasks: list[Task],
    outcomes: list[Outcome],
    infer: InferFn | None = None,
    timeout_s: float = 85.0,
) -> CompressResult:
    daily_text = daily_path.read_text(encoding="utf-8")
    provider = "heuristic"
    error = ""
    summary_md = _heuristic_summary(day=day, daily_text=daily_text, tasks=tasks, outcomes=outcomes)

    if infer is not None:
        prompt = build_compress_prompt(day=day, daily_text=daily_text, tasks=tasks, outcomes=outcomes)
        try:
            provider, output = infer(prompt, timeout_s)
            cleaned = _strip_block(output)
            if cleaned:
                summary_md = cleaned
        except Exception as exc:  # noqa: BLE001
            provider = "heuristic"
            error = str(exc) or exc.__class__.__name__

    updated_text = _upsert_block(daily_text, summary_md)
    daily_path.write_text(updated_text, encoding="utf-8")

    return CompressResult(ok=True, summary_md=summary_md, provider=provider, error=error)


