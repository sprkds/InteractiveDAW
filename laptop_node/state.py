"""Dataclasses modelling application, sensor, and router state."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AppState:
    """Camera-derived state snapshot provided to the router."""

    instrument_state: str
    camera_state: str
    recording: bool
    is_note_being_played: bool


@dataclass
class SensorState:
    """Latest sensor readings received from the Pi."""

    dist_cm: Optional[float]
    hit_velocity: Optional[int]
    last_rx_ts: float


@dataclass
class RouterState:
    """Mutable state maintained by the musical router."""

    held_note: Optional[int] = None
    last_note_sent: Optional[int] = None
    mute_until: float = 0.0
    was_recording: bool = field(default=False, repr=False)
    was_note_playing: bool = field(default=False, repr=False)

