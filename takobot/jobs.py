from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import re
import secrets
from pathlib import Path
from typing import Any


JOBS_VERSION = 1
JOBS_DIRNAME = "cron"
JOBS_FILENAME = "jobs.json"
MAX_JOBS = 256
MAX_ACTION_CHARS = 700

_WEEKDAY_TO_INDEX = {
    "monday": 0,
    "tuesday": 1,
    "wednesday": 2,
    "thursday": 3,
    "friday": 4,
    "saturday": 5,
    "sunday": 6,
}
_INDEX_TO_WEEKDAY = {value: key for key, value in _WEEKDAY_TO_INDEX.items()}
_SCHEDULE_FRAGMENT = r"(?:every day|daily|every weekday|every weekdays|every monday|every tuesday|every wednesday|every thursday|every friday|every saturday|every sunday)"
_TIME_FRAGMENT = r"(?:[01]?\d|2[0-3])(?::[0-5]\d)?\s*(?:a\.?m?\.?|p\.?m?\.?)?"
_PATTERNS = (
    re.compile(
        rf"^(?:please\s+)?(?P<schedule>{_SCHEDULE_FRAGMENT})\s+at\s+(?P<time>{_TIME_FRAGMENT})(?:\s+(?:to\s+)?)?(?P<action>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:please\s+)?at\s+(?P<time>{_TIME_FRAGMENT})\s+(?P<schedule>{_SCHEDULE_FRAGMENT})(?:\s+(?:to\s+)?)?(?P<action>.+)$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:please\s+)?(?P<action>.+?)\s+(?P<schedule>{_SCHEDULE_FRAGMENT})\s+at\s+(?P<time>{_TIME_FRAGMENT})$",
        re.IGNORECASE,
    ),
    re.compile(
        rf"^(?:please\s+)?(?P<action>.+?)\s+at\s+(?P<time>{_TIME_FRAGMENT})\s+(?P<schedule>{_SCHEDULE_FRAGMENT})$",
        re.IGNORECASE,
    ),
)
_TIME_RE = re.compile(
    r"^\s*(?P<hour>\d{1,2})(?::(?P<minute>[0-5]\d))?\s*(?P<ampm>a\.?m?\.?|p\.?m?\.?)?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class JobSchedule:
    kind: str
    hour: int
    minute: int
    weekdays: tuple[int, ...]


@dataclass(frozen=True)
class ScheduledJob:
    job_id: str
    natural: str
    action: str
    schedule: JobSchedule
    enabled: bool
    created_at: str
    updated_at: str
    last_run_at: str
    last_run_key: str
    run_count: int
    last_error: str


@dataclass(frozen=True)
class JobDraft:
    natural: str
    action: str
    schedule: JobSchedule


def jobs_store_path(state_dir: Path) -> Path:
    return state_dir / JOBS_DIRNAME / JOBS_FILENAME


def list_jobs(state_dir: Path) -> list[ScheduledJob]:
    payload = _load_payload(jobs_store_path(state_dir))
    jobs = [_job_from_record(record) for record in payload.get("jobs", []) if isinstance(record, dict)]
    return [job for job in jobs if job is not None]


def get_job(state_dir: Path, job_id: str) -> ScheduledJob | None:
    cleaned = " ".join((job_id or "").split()).strip()
    if not cleaned:
        return None
    for job in list_jobs(state_dir):
        if job.job_id == cleaned:
            return job
    return None


def remove_job(state_dir: Path, job_id: str) -> bool:
    cleaned = " ".join((job_id or "").split()).strip()
    if not cleaned:
        return False
    path = jobs_store_path(state_dir)
    payload = _load_payload(path)
    records = payload.get("jobs", [])
    if not isinstance(records, list):
        return False
    kept: list[dict[str, Any]] = []
    removed = False
    for item in records:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip() == cleaned:
            removed = True
            continue
        kept.append(item)
    if not removed:
        return False
    payload["jobs"] = kept
    _save_payload(path, payload)
    return True


def format_jobs_report(jobs: list[ScheduledJob], *, now: datetime | None = None) -> str:
    local_now = _local_now(now)
    if not jobs:
        return "jobs: none scheduled."
    ordered = sorted(
        jobs,
        key=lambda job: (
            _next_run_at(job, local_now) or (local_now + timedelta(days=3660)),
            job.job_id,
        ),
    )
    lines = [f"jobs: {len(ordered)} scheduled"]
    for job in ordered[:50]:
        status = "enabled" if job.enabled else "disabled"
        schedule = _schedule_label(job.schedule)
        next_run = _next_run_at(job, local_now)
        next_run_text = next_run.strftime("%Y-%m-%d %H:%M %Z") if next_run is not None else "n/a"
        lines.append(
            f"- {job.job_id} [{status}] {schedule} -> {job.action} (next: {next_run_text}, runs: {job.run_count})"
        )
    if len(ordered) > 50:
        lines.append(f"... and {len(ordered) - 50} more")
    return "\n".join(lines)


def looks_like_natural_job_request(text: str) -> bool:
    parsed = parse_natural_job_request(text)
    if parsed is None:
        return False
    lowered = " ".join((text or "").strip().lower().split())
    if lowered.startswith(("every ", "daily ", "at ")):
        return True
    tokens = ("schedule", "cron", "remind me", "set a job", "create job", "new job")
    return any(token in lowered for token in tokens)


def parse_natural_job_request(text: str) -> JobDraft | None:
    cleaned = " ".join((text or "").strip().split())
    if not cleaned:
        return None

    for pattern in _PATTERNS:
        match = pattern.match(cleaned)
        if not match:
            continue
        schedule_raw = str(match.group("schedule") or "")
        time_raw = str(match.group("time") or "")
        action_raw = str(match.group("action") or "")

        schedule = _parse_schedule(schedule_raw, time_raw)
        if schedule is None:
            continue
        action = _clean_action(action_raw)
        if not action:
            continue
        if len(action) > MAX_ACTION_CHARS:
            action = action[:MAX_ACTION_CHARS].rstrip()
        return JobDraft(natural=cleaned, action=action, schedule=schedule)
    return None


def add_job_from_natural_text(state_dir: Path, text: str) -> tuple[bool, str, ScheduledJob | None]:
    draft = parse_natural_job_request(text)
    if draft is None:
        return (
            False,
            (
                "couldn't parse schedule. try forms like:\n"
                "- `every day at 3pm explore ai news`\n"
                "- `at 09:30 every weekday run doctor`\n"
                "- `every monday at 14:00 run git pull`"
            ),
            None,
        )

    path = jobs_store_path(state_dir)
    payload = _load_payload(path)
    records = payload.get("jobs", [])
    if not isinstance(records, list):
        records = []
    if len(records) >= MAX_JOBS:
        return False, f"job limit reached ({MAX_JOBS}). remove old jobs before adding new ones.", None

    now = _local_now()
    now_iso = _to_iso(now)
    job = ScheduledJob(
        job_id=_new_job_id(now),
        natural=draft.natural,
        action=draft.action,
        schedule=draft.schedule,
        enabled=True,
        created_at=now_iso,
        updated_at=now_iso,
        last_run_at="",
        last_run_key="",
        run_count=0,
        last_error="",
    )
    records.append(_record_from_job(job))
    payload["jobs"] = records
    _save_payload(path, payload)
    next_run = _next_run_at(job, now)
    next_run_text = next_run.strftime("%Y-%m-%d %H:%M %Z") if next_run is not None else "n/a"
    summary = f"job created: {job.job_id}\n- schedule: {_schedule_label(job.schedule)}\n- action: {job.action}\n- next: {next_run_text}"
    return True, summary, job


def claim_due_jobs(state_dir: Path, *, now: datetime | None = None) -> list[ScheduledJob]:
    local_now = _local_now(now)
    path = jobs_store_path(state_dir)
    payload = _load_payload(path)
    records = payload.get("jobs", [])
    if not isinstance(records, list):
        return []

    due_jobs: list[ScheduledJob] = []
    changed = False
    for item in records:
        if not isinstance(item, dict):
            continue
        job = _job_from_record(item)
        if job is None or not job.enabled:
            continue
        due, run_key = _is_due(job, local_now)
        if not due:
            continue
        item["last_run_key"] = run_key
        item["last_run_at"] = _to_iso(local_now)
        item["run_count"] = int(item.get("run_count") or 0) + 1
        item["updated_at"] = _to_iso(local_now)
        item["last_error"] = ""
        changed = True
        updated = _job_from_record(item)
        if updated is not None:
            due_jobs.append(updated)

    if changed:
        payload["jobs"] = records
        _save_payload(path, payload)
    return due_jobs


def record_job_error(state_dir: Path, job_id: str, error: str) -> bool:
    cleaned_id = " ".join((job_id or "").split()).strip()
    if not cleaned_id:
        return False
    cleaned_error = " ".join((error or "").split()).strip()
    path = jobs_store_path(state_dir)
    payload = _load_payload(path)
    records = payload.get("jobs", [])
    if not isinstance(records, list):
        return False
    changed = False
    now_iso = _to_iso(_local_now())
    for item in records:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip() != cleaned_id:
            continue
        item["last_error"] = cleaned_error[:300]
        item["updated_at"] = now_iso
        changed = True
        break
    if changed:
        payload["jobs"] = records
        _save_payload(path, payload)
    return changed


def mark_job_manual_trigger(state_dir: Path, job_id: str, *, now: datetime | None = None) -> ScheduledJob | None:
    cleaned_id = " ".join((job_id or "").split()).strip()
    if not cleaned_id:
        return None
    local_now = _local_now(now)
    path = jobs_store_path(state_dir)
    payload = _load_payload(path)
    records = payload.get("jobs", [])
    if not isinstance(records, list):
        return None

    updated: ScheduledJob | None = None
    now_iso = _to_iso(local_now)
    manual_key = f"manual:{now_iso}"
    for item in records:
        if not isinstance(item, dict):
            continue
        if str(item.get("id") or "").strip() != cleaned_id:
            continue
        item["last_run_key"] = manual_key
        item["last_run_at"] = now_iso
        item["run_count"] = int(item.get("run_count") or 0) + 1
        item["updated_at"] = now_iso
        item["last_error"] = ""
        updated = _job_from_record(item)
        break
    if updated is None:
        return None
    payload["jobs"] = records
    _save_payload(path, payload)
    return updated


def _new_job_id(now: datetime) -> str:
    stamp = now.strftime("%Y%m%d%H%M%S")
    return f"job-{stamp}-{secrets.token_hex(2)}"


def _parse_schedule(schedule_text: str, time_text: str) -> JobSchedule | None:
    parsed_time = _parse_time(time_text)
    if parsed_time is None:
        return None
    hour, minute = parsed_time
    lowered = " ".join(schedule_text.strip().lower().split())
    if lowered in {"every day", "daily"}:
        return JobSchedule(kind="daily", hour=hour, minute=minute, weekdays=())
    if lowered in {"every weekday", "every weekdays"}:
        return JobSchedule(kind="weekly", hour=hour, minute=minute, weekdays=(0, 1, 2, 3, 4))
    if lowered.startswith("every "):
        day_name = lowered.replace("every ", "", 1).strip()
        index = _WEEKDAY_TO_INDEX.get(day_name)
        if index is not None:
            return JobSchedule(kind="weekly", hour=hour, minute=minute, weekdays=(index,))
    return None


def _parse_time(raw: str) -> tuple[int, int] | None:
    match = _TIME_RE.match(raw or "")
    if not match:
        return None
    hour = int(match.group("hour") or 0)
    minute = int(match.group("minute") or 0)
    ampm = str(match.group("ampm") or "").strip().lower().replace(".", "")
    if ampm:
        if hour < 1 or hour > 12:
            return None
        if ampm.startswith("p") and hour != 12:
            hour += 12
        if ampm.startswith("a") and hour == 12:
            hour = 0
    if hour < 0 or hour > 23:
        return None
    if minute < 0 or minute > 59:
        return None
    return hour, minute


def _clean_action(raw: str) -> str:
    cleaned = " ".join((raw or "").strip().split())
    if not cleaned:
        return ""
    cleaned = re.sub(r"^(?:please\s+)?to\s+", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _schedule_label(schedule: JobSchedule) -> str:
    if schedule.kind == "daily":
        return f"daily @ {schedule.hour:02d}:{schedule.minute:02d}"
    if schedule.kind == "weekly":
        names = [_INDEX_TO_WEEKDAY.get(idx, str(idx)) for idx in schedule.weekdays]
        joined = ",".join(names) if names else "weekdays"
        return f"weekly ({joined}) @ {schedule.hour:02d}:{schedule.minute:02d}"
    return f"{schedule.kind} @ {schedule.hour:02d}:{schedule.minute:02d}"


def _next_run_at(job: ScheduledJob, now: datetime) -> datetime | None:
    local_now = _local_now(now)
    for day_offset in range(0, 14):
        candidate_date = (local_now + timedelta(days=day_offset)).date()
        if not _runs_on_date(job.schedule, candidate_date.weekday()):
            continue
        candidate = local_now.replace(
            year=candidate_date.year,
            month=candidate_date.month,
            day=candidate_date.day,
            hour=job.schedule.hour,
            minute=job.schedule.minute,
            second=0,
            microsecond=0,
        )
        run_key = _run_key(candidate_date, job.schedule)
        if day_offset == 0:
            if candidate < local_now:
                if job.last_run_key != run_key:
                    return local_now
                continue
            if job.last_run_key == run_key and candidate <= local_now:
                continue
            return candidate
        return candidate
    return None


def _is_due(job: ScheduledJob, now: datetime) -> tuple[bool, str]:
    local_now = _local_now(now)
    if not _runs_on_date(job.schedule, local_now.weekday()):
        return False, ""
    scheduled = local_now.replace(hour=job.schedule.hour, minute=job.schedule.minute, second=0, microsecond=0)
    if local_now < scheduled:
        return False, ""
    run_key = _run_key(local_now.date(), job.schedule)
    if job.last_run_key == run_key:
        return False, ""
    return True, run_key


def _runs_on_date(schedule: JobSchedule, weekday: int) -> bool:
    if schedule.kind == "daily":
        return True
    if schedule.kind == "weekly":
        return weekday in set(schedule.weekdays)
    return False


def _run_key(day, schedule: JobSchedule) -> str:
    return f"{day.isoformat()}@{schedule.hour:02d}:{schedule.minute:02d}"


def _load_payload(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": JOBS_VERSION, "jobs": []}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {"version": JOBS_VERSION, "jobs": []}
    if not isinstance(raw, dict):
        return {"version": JOBS_VERSION, "jobs": []}
    version = int(raw.get("version") or 0)
    if version != JOBS_VERSION:
        return {"version": JOBS_VERSION, "jobs": []}
    records = raw.get("jobs")
    if not isinstance(records, list):
        records = []
    return {"version": JOBS_VERSION, "jobs": records}


def _save_payload(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    serializable = {
        "version": JOBS_VERSION,
        "jobs": payload.get("jobs", []),
    }
    path.write_text(json.dumps(serializable, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def _job_from_record(record: dict[str, Any]) -> ScheduledJob | None:
    job_id = " ".join(str(record.get("id") or "").split()).strip()
    action = " ".join(str(record.get("action") or "").split()).strip()
    natural = " ".join(str(record.get("natural") or "").split()).strip()
    if not job_id or not action:
        return None
    schedule_raw = record.get("schedule")
    if not isinstance(schedule_raw, dict):
        return None
    kind = str(schedule_raw.get("kind") or "").strip().lower()
    try:
        hour = int(schedule_raw.get("hour") or 0)
        minute = int(schedule_raw.get("minute") or 0)
    except Exception:
        return None
    weekdays_raw = schedule_raw.get("weekdays")
    weekdays: tuple[int, ...] = ()
    if isinstance(weekdays_raw, list):
        parsed: list[int] = []
        for item in weekdays_raw:
            try:
                value = int(item)
            except Exception:
                continue
            if 0 <= value <= 6:
                parsed.append(value)
        weekdays = tuple(sorted(set(parsed)))
    schedule = JobSchedule(kind=kind, hour=hour, minute=minute, weekdays=weekdays)
    if schedule.kind not in {"daily", "weekly"}:
        return None
    if schedule.hour < 0 or schedule.hour > 23 or schedule.minute < 0 or schedule.minute > 59:
        return None
    if schedule.kind == "weekly" and not schedule.weekdays:
        return None
    try:
        run_count = max(0, int(record.get("run_count") or 0))
    except Exception:
        run_count = 0
    return ScheduledJob(
        job_id=job_id,
        natural=natural or action,
        action=action,
        schedule=schedule,
        enabled=bool(record.get("enabled", True)),
        created_at=str(record.get("created_at") or ""),
        updated_at=str(record.get("updated_at") or ""),
        last_run_at=str(record.get("last_run_at") or ""),
        last_run_key=str(record.get("last_run_key") or ""),
        run_count=run_count,
        last_error=" ".join(str(record.get("last_error") or "").split()),
    )


def _record_from_job(job: ScheduledJob) -> dict[str, Any]:
    return {
        "id": job.job_id,
        "natural": job.natural,
        "action": job.action,
        "enabled": bool(job.enabled),
        "schedule": {
            "kind": job.schedule.kind,
            "hour": int(job.schedule.hour),
            "minute": int(job.schedule.minute),
            "weekdays": list(job.schedule.weekdays),
        },
        "created_at": job.created_at,
        "updated_at": job.updated_at,
        "last_run_at": job.last_run_at,
        "last_run_key": job.last_run_key,
        "run_count": int(job.run_count),
        "last_error": job.last_error,
    }


def _to_iso(value: datetime) -> str:
    return value.astimezone().replace(microsecond=0).isoformat()


def _local_now(value: datetime | None = None) -> datetime:
    if value is None:
        return datetime.now().astimezone()
    if value.tzinfo is None:
        return value.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return value.astimezone()
