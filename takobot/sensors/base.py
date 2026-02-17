from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class SensorContext:
    state_dir: Path
    now: datetime
    user_agent: str
    timeout_s: float
    mission_objectives: tuple[str, ...]
    trigger: str
    topic_focus: str

    @classmethod
    def create(
        cls,
        *,
        state_dir: Path,
        user_agent: str,
        timeout_s: float,
        mission_objectives: list[str] | tuple[str, ...] | None = None,
        trigger: str = "cadence",
        topic_focus: str = "",
    ) -> "SensorContext":
        cleaned_objectives: list[str] = []
        for item in mission_objectives or ():
            value = " ".join(str(item or "").split()).strip()
            if value:
                cleaned_objectives.append(value)
        cleaned_trigger = " ".join(str(trigger or "").split()).strip().lower() or "cadence"
        cleaned_topic = " ".join(str(topic_focus or "").split()).strip()
        return cls(
            state_dir=state_dir,
            now=datetime.now(tz=timezone.utc),
            user_agent=user_agent,
            timeout_s=max(1.0, float(timeout_s)),
            mission_objectives=tuple(cleaned_objectives),
            trigger=cleaned_trigger,
            topic_focus=cleaned_topic,
        )


class Sensor(Protocol):
    name: str

    async def tick(self, ctx: SensorContext) -> list[dict[str, Any]]:
        ...
