from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class LifeStage(str, Enum):
    HATCHLING = "hatchling"
    CHILD = "child"
    TEEN = "teen"
    ADULT = "adult"


DEFAULT_LIFE_STAGE = LifeStage.HATCHLING.value


@dataclass(frozen=True)
class DoseBaselineMultipliers:
    d: float = 1.0
    o: float = 1.0
    s: float = 1.0
    e: float = 1.0


@dataclass(frozen=True)
class StagePolicy:
    stage: LifeStage
    title: str
    tone: str
    routines_active: tuple[str, ...]
    explore_interval_minutes: int
    type2_budget_per_day: int
    dose_baseline_multipliers: DoseBaselineMultipliers
    world_watch_enabled: bool
    world_watch_poll_multiplier: float = 1.0


STAGE_POLICIES: dict[LifeStage, StagePolicy] = {
    LifeStage.HATCHLING: StagePolicy(
        stage=LifeStage.HATCHLING,
        title="Hatchling",
        tone="curious, small, gentle",
        routines_active=(
            "identity_imprint",
            "purpose_capture",
            "operator_pairing",
            "safety_checks",
        ),
        explore_interval_minutes=30,
        type2_budget_per_day=24,
        dose_baseline_multipliers=DoseBaselineMultipliers(d=0.95, o=1.10, s=1.10, e=1.05),
        world_watch_enabled=False,
        world_watch_poll_multiplier=2.0,
    ),
    LifeStage.CHILD: StagePolicy(
        stage=LifeStage.CHILD,
        title="Child",
        tone="curious, observant, notebooky",
        routines_active=(
            "world_watch",
            "world_notebook",
            "bounded_briefings",
            "mission_review_lite",
        ),
        explore_interval_minutes=5,
        type2_budget_per_day=48,
        dose_baseline_multipliers=DoseBaselineMultipliers(d=1.05, o=1.05, s=1.00, e=1.00),
        world_watch_enabled=True,
        world_watch_poll_multiplier=1.0,
    ),
    LifeStage.TEEN: StagePolicy(
        stage=LifeStage.TEEN,
        title="Teen",
        tone="skeptical, careful, prove-it",
        routines_active=(
            "world_watch",
            "assumption_tracking",
            "contradiction_tracking",
            "bounded_briefings",
            "mission_review_lite",
        ),
        explore_interval_minutes=4,
        type2_budget_per_day=64,
        dose_baseline_multipliers=DoseBaselineMultipliers(d=1.10, o=0.95, s=0.95, e=1.00),
        world_watch_enabled=True,
        world_watch_poll_multiplier=0.9,
    ),
    LifeStage.ADULT: StagePolicy(
        stage=LifeStage.ADULT,
        title="Adult",
        tone="steady, strategic, output-focused",
        routines_active=(
            "world_watch",
            "mission_review_lite",
            "execution_planning",
            "weekly_review",
            "bounded_briefings",
        ),
        explore_interval_minutes=6,
        type2_budget_per_day=56,
        dose_baseline_multipliers=DoseBaselineMultipliers(d=1.00, o=1.00, s=1.10, e=1.05),
        world_watch_enabled=True,
        world_watch_poll_multiplier=1.1,
    ),
}


def normalize_life_stage_name(value: str | None, *, default: str = DEFAULT_LIFE_STAGE) -> str:
    candidate = str(value or "").strip().lower()
    if candidate in {stage.value for stage in LifeStage}:
        return candidate
    return default


def life_stage_from_name(value: str | None, *, default: LifeStage = LifeStage.HATCHLING) -> LifeStage:
    normalized = normalize_life_stage_name(value, default=default.value)
    try:
        return LifeStage(normalized)
    except Exception:
        return default


def stage_policy_for_name(value: str | None, *, default: LifeStage = LifeStage.HATCHLING) -> StagePolicy:
    stage = life_stage_from_name(value, default=default)
    return STAGE_POLICIES[stage]


def stage_titles_csv() -> str:
    return ", ".join(stage.value for stage in LifeStage)
