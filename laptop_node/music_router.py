"""Core 100 Hz router logic for translating gestures to MIDI."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from time import perf_counter
from typing import Optional

from .mapping import NoteMapping, quantize_note
from .midi_io import (
    MidiOutputs,
    send_control_change,
    send_note_off,
    send_note_on,
    send_program_change,
)
from .state import AppState, RouterState, SensorState

LOGGER = logging.getLogger(__name__)

DIST_STEP_CM = 5.0  # Snap distance to 1.0 cm buckets to reduce note flutter


@dataclass(frozen=True)
class RouterConfig:
    """Immutable configuration for the music router."""

    mapping: NoteMapping
    instrument_map: dict
    drum_channel: int
    drum_note: int
    lead_channel: int
    lead_velocity: int
    control_channel: int
    record_cc: int
    insert_track_cc: int
    drum_velocity_default: int
    bpm: float
    countin_beats: int
    watchdog_s: float
    auto_insert_on_instrument_change: bool = False
    insert_on_record_start: bool = False

    @property
    def countin_duration(self) -> float:
        return self.countin_beats * 60.0 / self.bpm


class MusicRouter:
    """Applies play logic, quantization, and transport control each tick."""

    def __init__(self, midi: MidiOutputs, config: RouterConfig) -> None:
        self._midi = midi
        self._config = config
        self._state = RouterState()
        self._last_camera_state: Optional[str] = None
        self._last_instrument_state: Optional[str] = None
        self._instrument_changed = False
        self._watchdog_tripped = False
        self._current_is_drum = False
        self._current_drum_note = config.drum_note

    @property
    def state(self) -> RouterState:
        return self._state

    def process_tick(self, app_state: AppState, sensor_state: SensorState, now: float) -> None:
        """Process a single router tick."""
        self._instrument_changed = False
        self._log_mode_changes(app_state)
        if self._instrument_changed:
            self._release_note()
            if self._config.auto_insert_on_instrument_change and app_state.recording:
                self._insert_new_track()
        self._check_watchdog(sensor_state, now)

        self._handle_recording_edge(app_state, now)
        muted = now < self._state.mute_until

        if app_state.camera_state != "play":
            self._release_note()
            self._state.was_note_playing = False
            return

        if muted:
            self._release_note()
            self._state.was_note_playing = False
            return

        if self._current_is_drum:
            self._release_note()
            # Fire on rising edge of camera is_note_being_played
            if not self._state.was_note_playing and app_state.is_note_being_played:
                self._trigger_drum(self._config.drum_velocity_default)
            self._state.was_note_playing = app_state.is_note_being_played
            return

        # Non-drum instruments
        if not app_state.is_note_being_played or sensor_state.dist_cm is None:
            self._release_note()
            self._state.was_note_playing = False
            return

        snapped_dist = round(sensor_state.dist_cm / DIST_STEP_CM) * DIST_STEP_CM
        note = quantize_note(snapped_dist, self._config.mapping)
        if self._state.held_note == note:
            return

        self._release_note()
        # Print the pitch decision at INFO level for visibility during runs
        LOGGER.info("Pitch from distance: dist_cm=%.1f -> note=%d", sensor_state.dist_cm, note)
        send_note_on(
            self._midi,
            channel=self._config.lead_channel,
            note=note,
            velocity=self._config.lead_velocity,
        )
        LOGGER.debug("NoteOn sent note=%s", note)
        self._state.held_note = note
        self._state.last_note_sent = note
        self._state.was_note_playing = True

    # Internal helpers -----------------------------------------------------

    def _trigger_drum(self, velocity: int) -> None:
        send_note_on(
            self._midi,
            channel=self._config.drum_channel,
            note=self._current_drum_note,
            velocity=velocity,
        )
        send_note_off(
            self._midi,
            channel=self._config.drum_channel,
            note=self._current_drum_note,
            velocity=0,
        )
        LOGGER.debug("Drum hit velocity=%s", velocity)


    def _release_note(self) -> None:
        if self._state.held_note is None:
            return
        send_note_off(
            self._midi,
            channel=self._config.lead_channel,
            note=self._state.held_note,
            velocity=0,
        )
        LOGGER.debug("NoteOff sent note=%s", self._state.held_note)
        self._state.held_note = None
        self._state.last_note_sent = None

    def _handle_recording_edge(self, app_state: AppState, now: float) -> None:
        if not self._state.was_recording and app_state.recording:
            LOGGER.info("Recording started via camera")
            send_control_change(
                self._midi,
                channel=self._config.control_channel,
                cc=self._config.record_cc,
                value=127,
            )
            if self._config.insert_on_record_start:
                LOGGER.info("Requesting DAW to insert new track (on record start)")
                send_control_change(
                    self._midi,
                    channel=self._config.control_channel,
                    cc=self._config.insert_track_cc,
                    value=127,
                )
            self._state.mute_until = now + self._config.countin_duration
            self._state.was_recording = True
            self._release_note()
        elif self._state.was_recording and not app_state.recording:
            LOGGER.info("Recording stopped via camera")
            send_control_change(
                self._midi,
                channel=self._config.control_channel,
                cc=self._config.record_cc,
                value=127,
            )
            self._state.was_recording = False

    def _check_watchdog(self, sensor_state: SensorState, now: float) -> None:
        elapsed = now - sensor_state.last_rx_ts
        if elapsed >= self._config.watchdog_s:
            if not self._watchdog_tripped:
                LOGGER.warning("Watchdog timeout triggered after %.3fs", elapsed)
            self._watchdog_tripped = True
            self._release_note()
            return
        if self._watchdog_tripped:
            LOGGER.info("Watchdog recovered after sensor update")
        self._watchdog_tripped = False

    def _log_mode_changes(self, app_state: AppState) -> None:
        if app_state.camera_state != self._last_camera_state:
            LOGGER.info("Camera mode changed to %s", app_state.camera_state)
            self._last_camera_state = app_state.camera_state
        if app_state.instrument_state != self._last_instrument_state:
            LOGGER.info("Instrument changed to %s", app_state.instrument_state)
            self._last_instrument_state = app_state.instrument_state
            self._instrument_changed = True
            self._apply_instrument(app_state.instrument_state)

    def _apply_instrument(self, label: str) -> None:
        entry = self._config.instrument_map.get(label, {"type": "lead"})
        if entry.get("type") == "drum":
            self._current_is_drum = True
            self._current_drum_note = int(entry.get("note", self._config.drum_note))
        else:
            self._current_is_drum = False
            program = entry.get("program")
            if program is not None:
                try:
                    send_program_change(self._midi, self._config.lead_channel, int(program))
                    LOGGER.info("Program change sent: program=%s on ch %s", program, self._config.lead_channel)
                except Exception as exc:  # pragma: no cover
                    LOGGER.debug("Program change failed: %s", exc)

    def _insert_new_track(self) -> None:
        """Emit CC to insert a new track in the DAW."""
        LOGGER.info("Requesting DAW to insert a new track (instrument change during recording)")
        send_control_change(
            self._midi,
            channel=self._config.control_channel,
            cc=self._config.insert_track_cc,
            value=127,
        )


def perf_counter_now() -> float:
    """Helper for injection/mocking in tests."""
    return perf_counter()


__all__ = ["MusicRouter", "RouterConfig", "perf_counter_now"]

