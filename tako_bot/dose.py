from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def _clamp01(value: float) -> float:
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _safe_float(value: Any, *, default: float) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except Exception:
            return default
    return default


def _decay_toward(value: float, baseline: float, dt_s: float, *, half_life_s: float) -> float:
    """Exponential decay of (value-baseline) with a configurable half-life."""
    if dt_s <= 0.0:
        return value
    if half_life_s <= 0.0:
        return baseline
    # after half_life, delta is halved; after N half-lives, delta shrinks by 2^-N
    factor = 0.5 ** (dt_s / half_life_s)
    return baseline + (value - baseline) * factor


@dataclass
class DoseState:
    d: float
    o: float
    s: float
    e: float
    baseline_d: float
    baseline_o: float
    baseline_s: float
    baseline_e: float
    last_updated_ts: float

    def clamp(self) -> None:
        self.d = _clamp01(self.d)
        self.o = _clamp01(self.o)
        self.s = _clamp01(self.s)
        self.e = _clamp01(self.e)
        self.baseline_d = _clamp01(self.baseline_d)
        self.baseline_o = _clamp01(self.baseline_o)
        self.baseline_s = _clamp01(self.baseline_s)
        self.baseline_e = _clamp01(self.baseline_e)

    def tick(self, now: float, dt: float) -> None:
        """Decay toward baselines; deterministic and clamped."""
        dt_s = max(0.0, float(dt))

        # Cap extreme dt (e.g., sleeping laptop) to avoid surprising jumps.
        dt_s = min(dt_s, 12 * 60 * 60)

        # Dopamine is more "spiky" (faster), oxytocin slower, serotonin/endorphins moderate.
        self.d = _decay_toward(self.d, self.baseline_d, dt_s, half_life_s=4 * 60)
        self.o = _decay_toward(self.o, self.baseline_o, dt_s, half_life_s=12 * 60)
        self.s = _decay_toward(self.s, self.baseline_s, dt_s, half_life_s=9 * 60)
        self.e = _decay_toward(self.e, self.baseline_e, dt_s, half_life_s=7 * 60)

        self.clamp()
        self.last_updated_ts = float(now)

    def apply_event(
        self,
        event_type: str,
        severity: str,
        source: str,
        message: str,
        metadata: dict[str, Any] | None,
    ) -> dict[str, float]:
        """Apply deterministic deltas for the event and return the deltas used."""
        et = (event_type or "").strip().lower()
        sev = (severity or "info").strip().lower()
        src = (source or "").strip().lower()
        msg = (message or "").strip().lower()

        delta_d = 0.0
        delta_o = 0.0
        delta_s = 0.0
        delta_e = 0.0

        # Avoid self-feedback loops: the DOSE engine shouldn't "react to itself".
        if et.startswith("dose.started") or et.startswith("dose.mode.changed"):
            return {"d": 0.0, "o": 0.0, "s": 0.0, "e": 0.0}

        if et == "heartbeat.tick":
            # Small "alive and steady" reinforcement.
            delta_s += 0.002
            delta_e += 0.002
        elif et.startswith("pairing.completed"):
            delta_o += 0.16
            delta_d += 0.05
            delta_s += 0.08
            delta_e += 0.06
        elif et.startswith("pairing.outbound.sent"):
            delta_o += 0.04
            delta_d += 0.04
        elif et.startswith("pairing.outbound.send_failed") or et.startswith("pairing.outbound.resolve_failed"):
            scale = 1.0 if sev == "warn" else 1.6 if sev == "error" else 2.0
            delta_o -= 0.05 * scale
            delta_d -= 0.03 * scale
            delta_s -= 0.08 * scale
            delta_e -= 0.08 * scale
        elif et.startswith("inference.chat.reply") or et.startswith("inference.chat.reply".lower()):
            delta_d += 0.06
            delta_s += 0.02
            delta_e += 0.02
        elif et.startswith("inference.chat.error") or et.startswith("inference.error") or et.startswith("inference.runtime.error"):
            delta_d -= 0.02
            delta_s -= 0.06
            delta_e -= 0.05
        elif et.startswith("health.check.issue"):
            delta_s -= 0.04
            delta_e -= 0.02
        elif et.startswith("runtime.crash") or et.startswith("runtime.exit") or et.startswith("runtime.polling"):
            # Polling isn't a disaster, but it is "less calm".
            scale = 1.0 if sev in {"warn", "error", "critical"} else 0.6
            delta_s -= 0.06 * scale
            delta_e -= 0.05 * scale
        elif et.startswith("ui.error_card"):
            scale = 1.0 if sev == "warn" else 1.6 if sev in {"error", "critical"} else 0.8
            delta_s -= 0.05 * scale
            delta_e -= 0.04 * scale
        elif et.startswith("type1.escalation"):
            delta_s -= 0.01
            delta_e -= 0.01
        elif et.startswith("type2.result"):
            # Completing a deeper think is slightly rewarding, slightly tiring.
            delta_d += 0.02
            delta_s += 0.01
            delta_e -= 0.01
        elif et.startswith("identity.name.updated") or et.startswith("onboarding.identity.saved"):
            delta_o += 0.02
            delta_s += 0.01
        elif et.startswith("dose.operator.calm"):
            delta_s += 0.08
            delta_e += 0.08
            delta_o += 0.03
        elif et.startswith("dose.operator.explore"):
            delta_d += 0.10
            delta_s -= 0.02
        else:
            # Conservative default: only nudge on non-info severities.
            if sev == "warn":
                delta_s -= 0.015
                delta_e -= 0.01
            elif sev == "error":
                delta_d -= 0.02
                delta_s -= 0.05
                delta_e -= 0.05
            elif sev == "critical":
                delta_d -= 0.03
                delta_s -= 0.08
                delta_e -= 0.08

            # If an operator interaction is happening and it's not a failure, it tends to feel bonding.
            if src in {"xmtp", "operator", "terminal"} and sev == "info" and any(
                token in et for token in ("inbound", "chat", "message")
            ):
                delta_o += 0.005

            if "paired" in msg and sev == "info":
                delta_o += 0.01

        self.d = _clamp01(self.d + delta_d)
        self.o = _clamp01(self.o + delta_o)
        self.s = _clamp01(self.s + delta_s)
        self.e = _clamp01(self.e + delta_e)
        return {"d": delta_d, "o": delta_o, "s": delta_s, "e": delta_e}

    def label(self) -> str:
        if self.s < 0.35 or self.e < 0.35:
            return "stressed"
        if self.o >= 0.72 and self.s >= 0.45:
            return "bonded"
        if self.d >= 0.72 and self.s >= 0.45:
            return "curious"
        if self.s >= 0.74 and self.e >= 0.62:
            return "steady"
        return "steady"

    def behavior_bias(self) -> dict[str, float]:
        # Returned knobs are 0..1 and should bias UX without changing policy boundaries.
        verbosity = _clamp01(0.28 + (0.45 * self.d) + (0.15 * self.o) - (0.20 * self.s))
        confirm_level = _clamp01(0.18 + (0.50 * (1.0 - self.s)) + (0.28 * (1.0 - self.e)))
        explore_bias = _clamp01(0.15 + (0.70 * self.d) - (0.35 * self.s))
        patience = _clamp01(0.18 + (0.48 * self.e) + (0.22 * self.s))
        return {
            "verbosity": verbosity,
            "confirm_level": confirm_level,
            "explore_bias": explore_bias,
            "patience": patience,
        }


def default_state(*, now: float | None = None) -> DoseState:
    ts = float(now if now is not None else time.time())
    baseline = 0.55
    state = DoseState(
        d=baseline,
        o=baseline,
        s=baseline,
        e=baseline,
        baseline_d=baseline,
        baseline_o=baseline,
        baseline_s=baseline,
        baseline_e=baseline,
        last_updated_ts=ts,
    )
    state.clamp()
    return state


def load(path: Path) -> DoseState:
    if not path.exists():
        return default_state()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default_state()
    if not isinstance(payload, dict):
        return default_state()

    state = default_state(now=_safe_float(payload.get("last_updated_ts"), default=time.time()))
    state.d = _safe_float(payload.get("d"), default=state.d)
    state.o = _safe_float(payload.get("o"), default=state.o)
    state.s = _safe_float(payload.get("s"), default=state.s)
    state.e = _safe_float(payload.get("e"), default=state.e)
    state.baseline_d = _safe_float(payload.get("baseline_d"), default=state.baseline_d)
    state.baseline_o = _safe_float(payload.get("baseline_o"), default=state.baseline_o)
    state.baseline_s = _safe_float(payload.get("baseline_s"), default=state.baseline_s)
    state.baseline_e = _safe_float(payload.get("baseline_e"), default=state.baseline_e)
    state.last_updated_ts = _safe_float(payload.get("last_updated_ts"), default=state.last_updated_ts)
    state.clamp()
    return state


def save(path: Path, state: DoseState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    state.clamp()
    payload = asdict(state)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True) + "\n", encoding="utf-8")


def load_or_create(path: Path) -> DoseState:
    state = load(path)
    save(path, state)
    return state

