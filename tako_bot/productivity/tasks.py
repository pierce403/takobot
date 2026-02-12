from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any


_FRONTMATTER_BOUNDARY = "---"
_TASK_FILENAME_SAFE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str, *, max_len: int = 42) -> str:
    text = value.strip().lower()
    text = _TASK_FILENAME_SAFE.sub("-", text).strip("-")
    if not text:
        return "task"
    if len(text) > max_len:
        text = text[:max_len].rstrip("-")
    return text or "task"


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    raw = value.strip()
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except Exception:
        return None


def _today() -> date:
    return date.today()


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _split_frontmatter(text: str) -> tuple[dict[str, Any], str] | None:
    lines = text.splitlines()
    if not lines or lines[0].strip() != _FRONTMATTER_BOUNDARY:
        return None
    try:
        end = lines.index(_FRONTMATTER_BOUNDARY, 1)
    except ValueError:
        return None
    fm_lines = lines[1:end]
    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    fm = _parse_frontmatter_minimal(fm_lines)
    return fm, body


def _parse_frontmatter_minimal(lines: list[str]) -> dict[str, Any]:
    """Parse a tiny YAML subset: key: value and key: + indented list items."""
    data: dict[str, Any] = {}
    key: str | None = None
    list_acc: list[str] | None = None

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            continue

        if re.match(r"^[A-Za-z0-9_-]+\\s*:", line):
            if key and list_acc is not None:
                data[key] = list(list_acc)
            list_acc = None

            k, v = line.split(":", 1)
            key = k.strip()
            v = v.strip()
            if v == "":
                list_acc = []
                continue
            data[key] = _strip_quotes(v)
            continue

        if key and list_acc is not None:
            stripped = line.lstrip()
            if stripped.startswith("- "):
                list_acc.append(_strip_quotes(stripped[2:].strip()))
                continue

    if key and list_acc is not None:
        data[key] = list(list_acc)
    return data


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and ((value[0] == value[-1] == '"') or (value[0] == value[-1] == "'")):
        return value[1:-1]
    return value


def _render_frontmatter(data: dict[str, Any]) -> str:
    lines = ["---"]
    for key in (
        "id",
        "title",
        "status",
        "project",
        "area",
        "created",
        "updated",
        "due",
        "tags",
        "energy",
    ):
        if key not in data:
            continue
        value = data[key]
        if value is None or value == "":
            continue
        if isinstance(value, list):
            lines.append(f"{key}:")
            for item in value:
                if not str(item).strip():
                    continue
                lines.append(f"  - {str(item).strip()}")
            continue
        lines.append(f"{key}: {value}")
    lines.append("---")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    status: str
    project: str | None
    area: str | None
    created: date
    updated: date
    due: date | None
    tags: list[str]
    energy: str | None
    path: Path

    @property
    def is_done(self) -> bool:
        return self.status == "done"

    @property
    def is_open(self) -> bool:
        return not self.is_done


def tasks_root(repo_root: Path) -> Path:
    return repo_root / "tasks"


def ensure_tasks_dir(repo_root: Path) -> Path:
    root = tasks_root(repo_root)
    root.mkdir(parents=True, exist_ok=True)
    return root


def read_task(path: Path) -> Task | None:
    if not path.exists() or not path.is_file():
        return None
    if path.name.lower() == "readme.md":
        return None
    payload = _split_frontmatter(_read_text(path))
    if payload is None:
        return None
    fm, _body = payload

    task_id = str(fm.get("id") or "").strip()
    title = str(fm.get("title") or "").strip()
    if not task_id or not title:
        return None

    status = str(fm.get("status") or "open").strip().lower()
    if status not in {"open", "done", "blocked", "someday"}:
        status = "open"

    project = str(fm.get("project")).strip() if isinstance(fm.get("project"), str) else None
    area = str(fm.get("area")).strip() if isinstance(fm.get("area"), str) else None

    created = _parse_iso_date(str(fm.get("created") or "")) or _today()
    updated = _parse_iso_date(str(fm.get("updated") or "")) or created
    due = _parse_iso_date(str(fm.get("due") or "")) if fm.get("due") else None

    tags: list[str] = []
    raw_tags = fm.get("tags")
    if isinstance(raw_tags, list):
        tags = [str(item).strip() for item in raw_tags if str(item).strip()]
    elif isinstance(raw_tags, str) and raw_tags.strip():
        tags = [raw_tags.strip()]

    energy = str(fm.get("energy")).strip().lower() if isinstance(fm.get("energy"), str) else None
    if energy and energy not in {"low", "medium", "high"}:
        energy = None

    return Task(
        id=task_id,
        title=title,
        status=status,
        project=project or None,
        area=area or None,
        created=created,
        updated=updated,
        due=due,
        tags=tags,
        energy=energy,
        path=path,
    )


def read_task_file(path: Path) -> tuple[dict[str, Any], str] | None:
    payload = _split_frontmatter(_read_text(path))
    if payload is None:
        return None
    return payload


def list_tasks(repo_root: Path) -> list[Task]:
    root = ensure_tasks_dir(repo_root)
    tasks: list[Task] = []
    for path in sorted(root.glob("*.md")):
        task = read_task(path)
        if task is None:
            continue
        tasks.append(task)
    return tasks


def list_open_tasks(repo_root: Path) -> list[Task]:
    return [task for task in list_tasks(repo_root) if task.is_open]


def _generate_task_id(now: datetime) -> str:
    return now.strftime("tsk-%Y%m%d-%H%M%S")


def create_task(
    repo_root: Path,
    *,
    title: str,
    project: str | None = None,
    area: str | None = None,
    due: date | None = None,
    tags: list[str] | None = None,
    energy: str | None = None,
) -> Task:
    clean_title = " ".join(title.strip().split())
    if not clean_title:
        raise ValueError("task title is empty")

    now = datetime.now()
    today = now.date()
    task_id_base = _generate_task_id(now)
    slug = _slugify(clean_title)
    root = ensure_tasks_dir(repo_root)

    task_id = task_id_base
    for attempt in range(1, 50):
        existing = any(root.glob(f"{task_id}-*.md")) or (root / f"{task_id}.md").exists()
        if not existing:
            break
        task_id = f"{task_id_base}-{attempt:02d}"

    path = root / f"{task_id}-{slug}.md"
    fm: dict[str, Any] = {
        "id": task_id,
        "title": clean_title,
        "status": "open",
        "project": project or None,
        "area": area or None,
        "created": today.isoformat(),
        "updated": today.isoformat(),
        "due": due.isoformat() if due else None,
        "tags": list(tags or []),
        "energy": (energy or "").strip().lower() or None,
    }
    body = f"\n# {clean_title}\n\n- \n"
    path.write_text(_render_frontmatter(fm) + body, encoding="utf-8")

    created = today
    updated = today
    return Task(
        id=task_id,
        title=clean_title,
        status="open",
        project=project,
        area=area,
        created=created,
        updated=updated,
        due=due,
        tags=list(tags or []),
        energy=fm["energy"],
        path=path,
    )


def update_task_frontmatter(path: Path, updates: dict[str, Any]) -> Task:
    payload = read_task_file(path)
    if payload is None:
        raise ValueError(f"task file missing frontmatter: {path}")
    fm, body = payload
    fm.update(updates)
    rendered = _render_frontmatter(fm) + ("\n" + body if body else "")
    path.write_text(rendered, encoding="utf-8")
    task = read_task(path)
    if task is None:
        raise ValueError(f"task update produced invalid task: {path}")
    return task


def mark_done(repo_root: Path, task_id: str) -> Task | None:
    task = find_task(repo_root, task_id)
    if task is None:
        return None
    if task.is_done:
        return task
    updates = {"status": "done", "updated": _today().isoformat()}
    return update_task_frontmatter(task.path, updates)


def find_task(repo_root: Path, task_id: str) -> Task | None:
    needle = task_id.strip()
    if not needle:
        return None
    for task in list_tasks(repo_root):
        if task.id == needle:
            return task
    return None


def filter_tasks(
    tasks: list[Task],
    *,
    status: str | None = None,
    project: str | None = None,
    area: str | None = None,
    due_on_or_before: date | None = None,
) -> list[Task]:
    wanted_status = status.strip().lower() if status else None
    wanted_project = project.strip().lower() if project else None
    wanted_area = area.strip().lower() if area else None

    filtered: list[Task] = []
    for task in tasks:
        if wanted_status and task.status != wanted_status:
            continue
        if wanted_project and (task.project or "").strip().lower() != wanted_project:
            continue
        if wanted_area and (task.area or "").strip().lower() != wanted_area:
            continue
        if due_on_or_before and (task.due is None or task.due > due_on_or_before):
            continue
        filtered.append(task)

    def sort_key(item: Task) -> tuple[int, str, str]:
        due_bucket = 0 if item.due else 1
        due_value = item.due.isoformat() if item.due else "9999-12-31"
        return (due_bucket, due_value, item.created.isoformat())

    return sorted(filtered, key=sort_key)


def format_task_line(task: Task, *, today: date | None = None) -> str:
    today = today or _today()
    due = ""
    if task.due:
        overdue = " (overdue)" if task.due < today and task.is_open else ""
        due = f" due={task.due.isoformat()}{overdue}"
    proj = f" project={task.project}" if task.project else ""
    area = f" area={task.area}" if task.area else ""
    return f"{task.id} [{task.status}] {task.title}{due}{proj}{area}"


