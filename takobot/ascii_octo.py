from __future__ import annotations

from dataclasses import dataclass

from .life_stage import LifeStage, life_stage_from_name


EYE_CENTER = "oo"
EYE_LEFT = "o."
EYE_RIGHT = ".o"
EYE_BLINK = "--"

EDGE_MARGIN = 2
GLANCE_HOLD_TICKS = 6
BOUNCE_HOLD_TICKS = 3


@dataclass(frozen=True)
class OctoStageSpec:
    width: int
    height: int
    head_top: str
    face_template: str
    mantle_lines: tuple[str, ...]
    tentacles_a: tuple[str, ...]
    tentacles_b: tuple[str, ...]
    tail_lines: tuple[str, ...]
    move_interval: int
    bob_interval: int
    blink_duration_ticks: int
    blink_cycle: tuple[int, ...]


@dataclass(frozen=True)
class OctoMotionState:
    x: int
    track: int
    direction: int
    ticks_since_bounce: int
    bounce_side: str


STAGE_SPECS: dict[LifeStage, OctoStageSpec] = {
    LifeStage.HATCHLING: OctoStageSpec(
        width=7,
        height=3,
        head_top="  ___",
        face_template="({L}_{R})",
        mantle_lines=(),
        tentacles_a=("_/v~v\\_",),
        tentacles_b=("_\\v~v/_",),
        tail_lines=(),
        move_interval=1,
        bob_interval=4,
        blink_duration_ticks=2,
        blink_cycle=(21, 34, 25, 30),
    ),
    LifeStage.CHILD: OctoStageSpec(
        width=9,
        height=3,
        head_top="  _____",
        face_template="({L}_w_{R})",
        mantle_lines=(),
        tentacles_a=("_/v~v~v\\_",),
        tentacles_b=("_\\v~v~v/_",),
        tail_lines=(),
        move_interval=2,
        bob_interval=5,
        blink_duration_ticks=1,
        blink_cycle=(24, 31, 27, 35),
    ),
    LifeStage.TEEN: OctoStageSpec(
        width=13,
        height=5,
        head_top="   _______",
        face_template="   ({L}_{R})",
        mantle_lines=("   /_____\\",),
        tentacles_a=("_/v~v~v~v\\_", "  \\~v~v~v~/"),
        tentacles_b=("_\\v~v~v~v/_", "  /~v~v~v~\\"),
        tail_lines=(),
        move_interval=2,
        bob_interval=8,
        blink_duration_ticks=1,
        blink_cycle=(28, 23, 34, 30),
    ),
    LifeStage.ADULT: OctoStageSpec(
        width=15,
        height=6,
        head_top="    _______",
        face_template="   ({L}___{R})",
        mantle_lines=("   /_______\\",),
        tentacles_a=("_/v~v~v~v~v\\_", "  \\~v~v~v~v~/"),
        tentacles_b=("_\\v~v~v~v~v/_", "  /~v~v~v~v~\\"),
        tail_lines=("   (o)(o)(o)",),
        move_interval=3,
        bob_interval=12,
        blink_duration_ticks=1,
        blink_cycle=(32, 25, 29, 34),
    ),
}


def octopus_ascii_for_stage(stage_name: str, *, frame: int = 0, canvas_cols: int | None = None) -> str:
    stage = life_stage_from_name(stage_name)
    spec = STAGE_SPECS.get(stage) or STAGE_SPECS[LifeStage.HATCHLING]
    tick = max(0, int(frame))
    cols = max(spec.width, int(canvas_cols) if canvas_cols is not None else spec.width)

    motion = _motion_state(spec=spec, tick=tick, cols=cols)
    blinking = _is_blinking(spec=spec, tick=tick, motion=motion)
    eyes = _eyes_for_tick(spec=spec, tick=tick, motion=motion, blinking=blinking)
    wiggle_phase = tick % 2
    bob_offset = _bob_offset(spec=spec, tick=tick)

    sprite = _compose_sprite(spec=spec, left_eye=eyes[0], right_eye=eyes[1], wiggle_phase=wiggle_phase)
    shifted = [(" " * motion.x) + line for line in sprite]
    if bob_offset > 0:
        shifted = ([""] * bob_offset) + shifted
    return "\n".join(shifted)


def stage_box(stage_name: str) -> tuple[int, int]:
    stage = life_stage_from_name(stage_name)
    spec = STAGE_SPECS.get(stage) or STAGE_SPECS[LifeStage.HATCHLING]
    return spec.width, spec.height


def _motion_state(*, spec: OctoStageSpec, tick: int, cols: int) -> OctoMotionState:
    track = max(0, int(cols) - int(spec.width))
    if track <= 0:
        return OctoMotionState(x=0, track=0, direction=1, ticks_since_bounce=tick, bounce_side="left")

    move_interval = max(1, int(spec.move_interval))
    moves = tick // move_interval
    period = max(1, 2 * track)
    phase = moves % period

    if phase < track:
        x = phase
        direction = 1
    elif phase > track:
        x = period - phase
        direction = -1
    else:
        x = track
        direction = -1

    cycle_start = moves - phase
    left_bounce_move = cycle_start
    right_bounce_move = cycle_start + track
    if phase == 0:
        last_bounce_move = moves
        bounce_side = "left"
    elif phase >= track:
        last_bounce_move = right_bounce_move
        bounce_side = "right"
    else:
        last_bounce_move = left_bounce_move
        bounce_side = "left"

    ticks_since_bounce = max(0, tick - (last_bounce_move * move_interval))
    return OctoMotionState(
        x=max(0, min(track, int(x))),
        track=track,
        direction=1 if direction >= 0 else -1,
        ticks_since_bounce=ticks_since_bounce,
        bounce_side=bounce_side,
    )


def _is_blinking(*, spec: OctoStageSpec, tick: int, motion: OctoMotionState) -> bool:
    if motion.track > 0 and motion.ticks_since_bounce < max(1, int(spec.blink_duration_ticks)):
        return True
    cycle = tuple(max(20, int(item)) for item in spec.blink_cycle) or (27,)
    total = sum(cycle)
    marker = tick % total
    cumulative = 0
    for gap in cycle:
        cumulative += gap
        if marker == ((cumulative - 1) % total):
            return True
    return False


def _eyes_for_tick(*, spec: OctoStageSpec, tick: int, motion: OctoMotionState, blinking: bool) -> tuple[str, str]:
    if blinking:
        return EYE_BLINK, EYE_BLINK
    if motion.track <= 0:
        return EYE_CENTER, EYE_CENTER

    if motion.ticks_since_bounce <= BOUNCE_HOLD_TICKS:
        gaze = motion.bounce_side
    else:
        hold_steps = max(1, GLANCE_HOLD_TICKS // max(1, spec.move_interval))
        near_left = motion.x <= EDGE_MARGIN
        near_right = motion.track - motion.x <= EDGE_MARGIN
        if near_left:
            gaze = "left"
        elif near_right:
            gaze = "right"
        elif motion.bounce_side == "left" and motion.x <= (EDGE_MARGIN + hold_steps):
            gaze = "left"
        elif motion.bounce_side == "right" and (motion.track - motion.x) <= (EDGE_MARGIN + hold_steps):
            gaze = "right"
        else:
            gaze = "center"

    if gaze == "left":
        return EYE_LEFT, EYE_LEFT
    if gaze == "right":
        return EYE_RIGHT, EYE_RIGHT

    if stage_is_teen(spec) and ((tick // 47) % 9 == 0) and (tick % 2 == 0):
        # Tiny occasional side-eye for teen attitude.
        return EYE_CENTER, EYE_RIGHT if motion.direction < 0 else EYE_LEFT
    return EYE_CENTER, EYE_CENTER


def _bob_offset(*, spec: OctoStageSpec, tick: int) -> int:
    interval = max(1, int(spec.bob_interval))
    return 1 if ((tick // interval) % 2) else 0


def _compose_sprite(*, spec: OctoStageSpec, left_eye: str, right_eye: str, wiggle_phase: int) -> list[str]:
    tentacles = spec.tentacles_a if wiggle_phase == 0 else spec.tentacles_b
    lines = [
        spec.head_top,
        spec.face_template.format(L=left_eye, R=right_eye),
        *spec.mantle_lines,
        *tentacles,
        *spec.tail_lines,
    ]
    lines = lines[: spec.height]
    if len(lines) < spec.height:
        lines.extend([""] * (spec.height - len(lines)))
    return [line[: spec.width].ljust(spec.width) for line in lines]


def stage_is_teen(spec: OctoStageSpec) -> bool:
    return spec.width == STAGE_SPECS[LifeStage.TEEN].width and spec.height == STAGE_SPECS[LifeStage.TEEN].height
