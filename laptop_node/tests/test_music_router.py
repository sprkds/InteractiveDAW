"""Tests for the change-only note policy in the music router."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest

from laptop_node.mapping import NoteMapping
from laptop_node.midi_io import MidiOutputs
from laptop_node.music_router import MusicRouter, RouterConfig
from laptop_node.state import AppState, SensorState


@dataclass
class FakePort:
    messages: list = field(default_factory=list)

    def send(self, message) -> None:
        self.messages.append(message)

    def close(self) -> None:
        pass


def make_router() -> tuple[MusicRouter, FakePort]:
    mapping = NoteMapping(d_min_cm=15, d_max_cm=60, note_lo=48, note_hi=72)
    midi_port = FakePort()
    control_port = FakePort()
    outputs = MidiOutputs(musical=midi_port, control=control_port)
    config = RouterConfig(
        instrument_map={},
        mapping=mapping,
        drum_channel=10,
        drum_note=36,
        lead_channel=1,
        lead_velocity=90,
        control_channel=1,
        record_cc=20,
        insert_track_cc=21,
        drum_velocity_default=100,
        bpm=120,
        countin_beats=4,
        watchdog_s=5.0,
        auto_insert_on_instrument_change=False,
        insert_on_record_start=False,
    )
    router = MusicRouter(outputs, config)
    return router, midi_port


def base_app_state() -> AppState:
    return AppState(
        instrument_state="synth",
        camera_state="play",
        recording=False,
        is_note_being_played=True,
    )


def test_change_only_emits_single_note_on() -> None:
    router, port = make_router()
    app_state = base_app_state()
    sensor = SensorState(dist_cm=30.0, hit_velocity=None, last_rx_ts=0.0)

    router.process_tick(app_state, sensor, now=0.0)
    assert len(port.messages) == 1
    assert port.messages[0].type == "note_on"

    router.process_tick(app_state, SensorState(dist_cm=30.0, hit_velocity=None, last_rx_ts=0.01), now=0.01)
    assert len(port.messages) == 1, "No duplicate NoteOn should be emitted while note is held"


def test_note_change_sends_note_off_then_note_on() -> None:
    router, port = make_router()
    app_state = base_app_state()

    router.process_tick(app_state, SensorState(dist_cm=30.0, hit_velocity=None, last_rx_ts=0.0), now=0.0)
    router.process_tick(app_state, SensorState(dist_cm=45.0, hit_velocity=None, last_rx_ts=0.01), now=0.01)

    # We expect NoteOn then NoteOff + NoteOn for the new note (total 3 messages).
    assert len(port.messages) == 3
    assert port.messages[1].type == "note_off"
    assert port.messages[2].type == "note_on"

