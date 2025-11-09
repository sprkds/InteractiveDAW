"""Signal conditioning utilities for the Raspberry Pi node."""

from __future__ import annotations

from statistics import median
from typing import List, Optional


def us_to_cm(echo_us: Optional[int], temp_C: float = 20.0) -> Optional[float]:
    """Convert an ultrasonic echo duration (µs) to centimetres.

    Args:
        echo_us: Pulse width in microseconds. If ``None`` or non-positive the
            function returns ``None``.
        temp_C: Ambient temperature in Celsius used to estimate the speed of
            sound.

    Returns:
        Distance measurement in centimetres, or ``None`` if the input is
        invalid.
    """
    if echo_us is None or echo_us <= 0:
        return None
    speed_m_s = 331.3 + 0.606 * temp_C
    # Divide by 2 because the pulse travels to the target and back.
    distance_cm = (echo_us * speed_m_s / 2.0) / 1e4
    return distance_cm


def median_filter(window: List[float], size: int) -> float:
    """Return the median of the latest ``size`` samples in ``window``.

    The function mutates ``window`` in-place, keeping only the most recent
    ``size`` entries.
    """
    if size <= 0:
        raise ValueError("Median window size must be greater than zero")
    if not window:
        raise ValueError("Median window is empty")
    # Retain only the most recent ``size`` samples.
    if len(window) > size:
        del window[: len(window) - size]
    return float(median(window))


def ema(prev: Optional[float], x: float, alpha: float) -> float:
    """Compute the exponential moving average."""
    if not 0.0 <= alpha <= 1.0:
        raise ValueError("alpha must be between 0 and 1")
    if prev is None:
        return x
    return (alpha * x) + ((1.0 - alpha) * prev)


def clamp(x: float, lower: float, upper: float) -> float:
    """Clamp ``x`` into the inclusive range [``lower``, ``upper``]."""
    if lower > upper:
        raise ValueError("lower bound must be <= upper bound")
    if x < lower:
        return lower
    if x > upper:
        return upper
    return x


__all__ = ["us_to_cm", "median_filter", "ema", "clamp"]

