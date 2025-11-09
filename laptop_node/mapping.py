"""Distance-to-note mapping utilities for the laptop node."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


ScaleFn = Callable[[int], int]


@dataclass(frozen=True)
class NoteMapping:
    """Parameters describing a linear distance-to-note mapping."""

    d_min_cm: float
    d_max_cm: float
    note_lo: int
    note_hi: int

    def __post_init__(self) -> None:
        if self.d_min_cm >= self.d_max_cm:
            raise ValueError("d_min_cm must be less than d_max_cm")
        if self.note_lo > self.note_hi:
            raise ValueError("note_lo must be less than or equal to note_hi")


def clamp_distance(dist_cm: float, mapping: NoteMapping) -> float:
    """Clamp a distance reading into the configured range."""
    if dist_cm < mapping.d_min_cm:
        return mapping.d_min_cm
    if dist_cm > mapping.d_max_cm:
        return mapping.d_max_cm
    return dist_cm


def interpolate_note(dist_cm: float, mapping: NoteMapping) -> float:
    """Interpolate a floating-point MIDI note from the distance."""
    distance_span = mapping.d_max_cm - mapping.d_min_cm
    note_span = mapping.note_hi - mapping.note_lo
    if distance_span == 0 or note_span == 0:
        return float(mapping.note_lo)
    ratio = (dist_cm - mapping.d_min_cm) / distance_span
    return mapping.note_lo + ratio * note_span


def quantize_note(
    dist_cm: float,
    mapping: NoteMapping,
    scale_fn: Optional[ScaleFn] = None,
) -> int:
    """Map a distance in centimetres to an integer MIDI note number.

    The mapping is linear between the configured boundaries, rounded to the
    nearest semitone, and optionally remapped through a scale function.
    """
    clamped = clamp_distance(dist_cm, mapping)
    note_float = interpolate_note(clamped, mapping)
    quantized = int(note_float + 0.5)
    if quantized < mapping.note_lo:
        quantized = mapping.note_lo
    elif quantized > mapping.note_hi:
        quantized = mapping.note_hi
    if scale_fn is None:
        return quantized
    return scale_fn(quantized)


__all__ = [
    "NoteMapping",
    "ScaleFn",
    "clamp_distance",
    "interpolate_note",
    "quantize_note",
]

