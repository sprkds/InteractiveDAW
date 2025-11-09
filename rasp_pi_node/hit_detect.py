"""Edge detection and velocity estimation for percussion hits."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class HitState:
    """Mutable hit detection state."""

    armed: bool = True
    last_hit_s: float = 0.0
    last_cm: Optional[float] = None
    last_sample_s: Optional[float] = None
    velocity_min: int = 30
    velocity_max: int = 127
    min_speed_cm_s: float = 5.0
    max_speed_cm_s: float = 120.0
    fixed_velocity: int = 100


def detect_hit(
    cm: float,
    t_s: float,
    st: HitState,
    thresh: float,
    hyst: float,
    refract_s: float,
) -> Tuple[bool, int, HitState]:
    """Detect threshold crossings with hysteresis and refractory guard."""

    fired = False
    velocity = 0
    elapsed_since_hit = t_s - st.last_hit_s
    epsilon = 1e-6

    if st.armed and cm < (thresh - hyst) and elapsed_since_hit + epsilon >= refract_s:
        fired = True
        velocity = _compute_velocity(cm, t_s, st)
        st.armed = False
        st.last_hit_s = t_s

    if not st.armed and cm > (thresh + hyst):
        st.armed = True

    st.last_cm = cm
    st.last_sample_s = t_s
    return fired, velocity, st


def _compute_velocity(cm: float, t_s: float, st: HitState) -> int:
    """Estimate a MIDI velocity from the approach speed."""
    if st.last_cm is None or st.last_sample_s is None:
        return st.fixed_velocity

    dt = t_s - st.last_sample_s
    if dt <= 0.0:
        return st.fixed_velocity

    approach_speed = max(0.0, (st.last_cm - cm) / dt)
    if approach_speed <= st.min_speed_cm_s:
        return st.velocity_min
    if approach_speed >= st.max_speed_cm_s:
        return st.velocity_max

    ratio = (approach_speed - st.min_speed_cm_s) / (
        st.max_speed_cm_s - st.min_speed_cm_s
    )
    velocity = st.velocity_min + ratio * (st.velocity_max - st.velocity_min)
    return int(round(velocity))


__all__ = ["HitState", "detect_hit"]

