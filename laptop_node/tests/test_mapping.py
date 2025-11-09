"""Unit tests for distance-to-note mapping utilities."""

from __future__ import annotations

import math

import pytest

from laptop_node.mapping import NoteMapping, clamp_distance, interpolate_note, quantize_note


@pytest.fixture
def default_mapping() -> NoteMapping:
    return NoteMapping(d_min_cm=15.0, d_max_cm=60.0, note_lo=48, note_hi=72)


def test_clamp_distance_low_high(default_mapping: NoteMapping) -> None:
    assert clamp_distance(10.0, default_mapping) == pytest.approx(default_mapping.d_min_cm)
    assert clamp_distance(75.0, default_mapping) == pytest.approx(default_mapping.d_max_cm)


def test_interpolate_note_linear(default_mapping: NoteMapping) -> None:
    mid_dist = (default_mapping.d_min_cm + default_mapping.d_max_cm) / 2.0
    interpolated = interpolate_note(mid_dist, default_mapping)
    assert math.isclose(interpolated, (default_mapping.note_lo + default_mapping.note_hi) / 2.0)


def test_quantize_note_clamps_and_rounds(default_mapping: NoteMapping) -> None:
    assert quantize_note(5.0, default_mapping) == default_mapping.note_lo
    assert quantize_note(95.0, default_mapping) == default_mapping.note_hi

    # 0.5 should round up.
    target_note = 53.5
    ratio = (target_note - default_mapping.note_lo) / (default_mapping.note_hi - default_mapping.note_lo)
    dist = default_mapping.d_min_cm + ratio * (default_mapping.d_max_cm - default_mapping.d_min_cm)
    assert quantize_note(dist, default_mapping) == 54


def test_quantize_note_monotonic(default_mapping: NoteMapping) -> None:
    distances = [15.0, 22.0, 30.0, 45.0, 60.0]
    notes = [quantize_note(d, default_mapping) for d in distances]
    assert notes == sorted(notes)


def test_quantize_note_scale_fn(default_mapping: NoteMapping) -> None:
    def transpose_octave(note: int) -> int:
        return note + 12

    base_note = quantize_note(20.0, default_mapping)
    assert quantize_note(20.0, default_mapping, scale_fn=transpose_octave) == base_note + 12

