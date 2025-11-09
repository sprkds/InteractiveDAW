"""Unit tests for hit detection logic."""

from __future__ import annotations

from rasp_pi_node.hit_detect import HitState, detect_hit


def _make_state(**overrides):
    state = HitState(
        armed=True,
        last_hit_s=-1.0,
        last_cm=None,
        last_sample_s=None,
        velocity_min=30,
        velocity_max=120,
        min_speed_cm_s=5.0,
        max_speed_cm_s=100.0,
        fixed_velocity=90,
    )
    for key, value in overrides.items():
        setattr(state, key, value)
    return state


def test_hysteresis_single_hit() -> None:
    state = _make_state()
    thresh = 30.0
    hyst = 2.0
    refract = 0.2

    samples = [
        (35.0, 0.00),
        (28.0, 0.05),
        (27.0, 0.10),  # Should trigger
        (29.0, 0.15),
        (33.0, 0.25),  # Re-arm happens here
        (27.0, 0.30),  # Should trigger again
    ]

    hits = []
    for cm, t in samples:
        fired, vel, state = detect_hit(cm, t, state, thresh, hyst, refract)
        hits.append((fired, vel))

    assert hits[2][0] is True
    assert hits[5][0] is True
    assert sum(1 for fired, _ in hits if fired) == 2


def test_refractory_blocks_additional_hits() -> None:
    state = _make_state()
    thresh = 30.0
    hyst = 1.0
    refract = 0.5

    # First hit at t=0.1
    fired, vel, state = detect_hit(28.0, 0.10, state, thresh, hyst, refract)
    assert fired is True

    # Still below threshold but within refractory period
    fired, vel, state = detect_hit(27.0, 0.30, state, thresh, hyst, refract)
    assert fired is False

    # After refractory period and rearmed
    state.armed = True
    fired, vel, state = detect_hit(27.0, 0.70, state, thresh, hyst, refract)
    assert fired is True


def test_velocity_mapping_clamps_to_max() -> None:
    state = _make_state(last_cm=40.0, last_sample_s=0.0, last_hit_s=-1.0)
    thresh = 30.0
    hyst = 1.0
    refract = 0.1

    fired, velocity, state = detect_hit(20.0, 0.10, state, thresh, hyst, refract)
    assert fired is True
    assert velocity == state.velocity_max


def test_velocity_falls_back_without_history() -> None:
    state = _make_state()
    thresh = 30.0
    hyst = 1.0
    refract = 0.0

    fired, velocity, state = detect_hit(20.0, 0.10, state, thresh, hyst, refract)
    assert fired is True
    assert velocity == state.fixed_velocity

