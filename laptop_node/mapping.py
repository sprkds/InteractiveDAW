"""Distance-to-note mapping utilities for the laptop node."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional, Iterable, Set, Sequence


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

# ---------------- Scale helpers ----------------

# Map common note names to pitch classes (MIDI % 12). Support flats and sharps.
NOTE_NAME_TO_PC = {
    "C": 0,
    "C#": 1,
    "Db": 1,
    "D": 2,
    "D#": 3,
    "Eb": 3,
    "E": 4,
    "Fb": 4,
    "E#": 5,
    "F": 5,
    "F#": 6,
    "Gb": 6,
    "G": 7,
    "G#": 8,
    "Ab": 8,
    "A": 9,
    "A#": 10,
    "Bb": 10,
    "B": 11,
    "Cb": 11,
    "B#": 0,
}


def scale_fn_from_pitch_classes(allowed_pitch_classes: Iterable[int]) -> ScaleFn:
    """Return a function that maps a MIDI note to the nearest note within the given scale.

    allowed_pitch_classes is a collection of integers 0..11. The returned function
    will search up to +/- 6 semitones to find the nearest note whose pitch class
    is in the set (ties prefer the lower note).
    """
    pcs: Set[int] = {pc % 12 for pc in allowed_pitch_classes}

    def _map(note: int) -> int:
        base_pc = note % 12
        if base_pc in pcs:
            return note
        # Search outward for the nearest allowed pitch class
        for delta in range(1, 7):
            down = note - delta
            up = note + delta
            if down % 12 in pcs:
                return down
            if up % 12 in pcs:
                return up
        return note

    return _map


def scale_fn_from_names(names: Iterable[str]) -> ScaleFn:
    """Convenience wrapper: build a scale fn from note names like ['Db','Eb','F',...]."""
    pcs = []
    for name in names:
        key = str(name).strip()
        if key not in NOTE_NAME_TO_PC:
            raise ValueError(f"Unknown note name in scale: {name!r}")
        pcs.append(NOTE_NAME_TO_PC[key])
    return scale_fn_from_pitch_classes(pcs)


def absolute_scale_fn_from_notes(allowed_notes: Sequence[int]) -> ScaleFn:
    """Return a function that snaps any MIDI note to the nearest in allowed_notes.

    Ties prefer the lower note.
    """
    allowed: list[int] = sorted(int(n) for n in allowed_notes)
    if not allowed:
        raise ValueError("absolute_scale_fn_from_notes requires at least one note")

    def _map(note: int) -> int:
        # Binary search for nearest
        lo, hi = 0, len(allowed) - 1
        while lo <= hi:
            mid = (lo + hi) // 2
            if allowed[mid] < note:
                lo = mid + 1
            elif allowed[mid] > note:
                hi = mid - 1
            else:
                return note
        # lo is first greater element index; hi is last less-or-equal
        cand_hi = allowed[hi] if 0 <= hi < len(allowed) else None
        cand_lo = allowed[lo] if 0 <= lo < len(allowed) else None
        if cand_hi is None:
            return cand_lo  # type: ignore[return-value]
        if cand_lo is None:
            return cand_hi  # type: ignore[return-value]
        # pick nearest; tie => lower (cand_hi)
        if abs(cand_lo - note) < abs(note - cand_hi):
            return cand_lo
        return cand_hi

    return _map

