"""Unit tests for conversion and clamping utilities."""

from __future__ import annotations

import math

import pytest

from rasp_pi_node.filters import clamp, us_to_cm


def test_us_to_cm_at_20C() -> None:
    # 20 cm roundtrip at 20°C corresponds to roughly 1165 µs.
    assert us_to_cm(1165, temp_C=20.0) == pytest.approx(20.0, rel=1e-2)


def test_us_to_cm_temperature_adjustment() -> None:
    base = us_to_cm(1165, temp_C=20.0)
    warmer = us_to_cm(1165, temp_C=30.0)
    assert warmer is not None and base is not None
    assert warmer > base  # Faster speed of sound yields greater distance.


def test_us_to_cm_invalid_values() -> None:
    assert us_to_cm(None) is None
    assert us_to_cm(0) is None
    assert us_to_cm(-10) is None


def test_clamp_bounds() -> None:
    assert clamp(5.0, 0.0, 10.0) == pytest.approx(5.0)
    assert clamp(-5.0, 0.0, 10.0) == pytest.approx(0.0)
    assert clamp(15.0, 0.0, 10.0) == pytest.approx(10.0)


def test_clamp_invalid_bounds() -> None:
    with pytest.raises(ValueError):
        clamp(1.0, 5.0, 2.0)

