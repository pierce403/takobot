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

    @classmethod
    def create(
        cls,
        *,
        state_dir: Path,
        user_agent: str,
        timeout_s: float,
    ) -> "SensorContext":
        return cls(
            state_dir=state_dir,
            now=datetime.now(tz=timezone.utc),
            user_agent=user_agent,
            timeout_s=max(1.0, float(timeout_s)),
        )


class Sensor(Protocol):
    name: str

    async def tick(self, ctx: SensorContext) -> list[dict[str, Any]]:
        ...
