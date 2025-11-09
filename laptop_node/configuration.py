"""Configuration loading and dataclasses for the laptop node."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .mapping import NoteMapping


@dataclass(frozen=True)
class OscConfig:
    host: str
    port: int


@dataclass(frozen=True)
class RouterSettings:
    tick_hz: float
    watchdog_s: float
    auto_insert_track_on_instrument_change: bool = False
    auto_insert_track_on_record_start: bool = False


@dataclass(frozen=True)
class TransportConfig:
    bpm: float
    countin_beats: int


@dataclass(frozen=True)
class MidiConfig:
    musical_port: str
    control_port: str
    drum_channel: int
    lead_channel: int
    control_channel: int
    drum_note: int
    drum_velocity_default: int
    lead_velocity: int
    record_cc: int
    insert_track_cc: int


@dataclass(frozen=True)
class LoggingConfig:
    level: str


@dataclass(frozen=True)
class CameraConfig:
    index: int = 0
    hud_enabled: bool = True
    flip: bool = False


@dataclass(frozen=True)
class AppConfig:
    osc: OscConfig
    router: RouterSettings
    transport: TransportConfig
    midi: MidiConfig
    mapping: NoteMapping
    logging: LoggingConfig
    instrument_map: dict
    camera: CameraConfig


def load_config(path: Path) -> AppConfig:
    """Load configuration from a YAML file."""
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    mapping_cfg = raw["mapping"]
    mapping = NoteMapping(
        d_min_cm=float(mapping_cfg["d_min_cm"]),
        d_max_cm=float(mapping_cfg["d_max_cm"]),
        note_lo=int(mapping_cfg["note_lo"]),
        note_hi=int(mapping_cfg["note_hi"]),
    )

    return AppConfig(
        osc=OscConfig(host=str(raw["osc"]["host"]), port=int(raw["osc"]["port"])),
        router=RouterSettings(
            tick_hz=float(raw["router"]["tick_hz"]),
            watchdog_s=float(raw["router"]["watchdog_s"]),
            auto_insert_track_on_instrument_change=bool(
                raw["router"].get("auto_insert_track_on_instrument_change", False)
            ),
            auto_insert_track_on_record_start=bool(
                raw["router"].get("auto_insert_track_on_record_start", False)
            ),
        ),
        transport=TransportConfig(
            bpm=float(raw["transport"]["bpm"]),
            countin_beats=int(raw["transport"]["countin_beats"]),
        ),
        midi=_parse_midi(raw["midi"]),
        mapping=mapping,
        logging=LoggingConfig(level=str(raw.get("logging", {}).get("level", "INFO"))),
        instrument_map=dict(raw.get("instrument_map", {})),
        camera=_parse_camera(raw.get("camera", {})),
    )


def _parse_midi(raw: Any) -> MidiConfig:
    return MidiConfig(
        musical_port=str(raw["musical_port"]),
        control_port=str(raw["control_port"]),
        drum_channel=int(raw["drum_channel"]),
        lead_channel=int(raw["lead_channel"]),
        control_channel=int(raw.get("control_channel", 1)),
        drum_note=int(raw["drum_note"]),
        drum_velocity_default=int(raw.get("drum_velocity_default", 100)),
        lead_velocity=int(raw["lead_velocity"]),
        record_cc=int(raw.get("record_cc", 20)),
        insert_track_cc=int(raw.get("insert_track_cc", 21)),
    )


def _parse_camera(raw: Any) -> CameraConfig:
    if not isinstance(raw, dict):
        raw = {}
    return CameraConfig(
        index=int(raw.get("index", 0)),
        hud_enabled=bool(raw.get("hud_enabled", True)),
        flip=bool(raw.get("flip", False)),
    )


def load_default_config() -> AppConfig:
    """Load the default config.yaml shipped with the package."""
    path = Path(__file__).resolve().parent / "config.yaml"
    return load_config(path)


__all__ = [
    "AppConfig",
    "CameraConfig",
    "LoggingConfig",
    "MidiConfig",
    "OscConfig",
    "RouterSettings",
    "TransportConfig",
    "load_config",
    "load_default_config",
]

