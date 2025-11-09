"""Entrypoint for the laptop node asyncio application."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib
import logging
from pathlib import Path
from time import perf_counter
from typing import Callable, Dict

from .configuration import AppConfig, load_config, load_default_config
from .midi_io import open_outputs
from .music_router import MusicRouter, RouterConfig
from .pi_client import PiClient
from .state import AppState

LOGGER = logging.getLogger(__name__)

CameraCallable = Callable[[], Dict[str, object]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Laptop node for gestural instrument routing.")
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to configuration YAML. Defaults to bundled config.yaml if omitted.",
    )
    parser.add_argument(
        "--camera",
        default="camera_interface:get_camera_state",
        help="Import path for get_camera_state callable (module:function).",
    )
    return parser.parse_args()


async def router_loop(
    router: MusicRouter,
    pi_client: PiClient,
    camera_fn: CameraCallable,
    app_config: AppConfig,
) -> None:
    """Run the fixed-rate router loop until cancelled."""
    tick_hz = app_config.router.tick_hz
    if tick_hz <= 0:
        raise ValueError("router.tick_hz must be greater than zero")
    tick_interval = 1.0 / tick_hz
    next_tick = perf_counter()
    try:
        while True:
            next_tick += tick_interval
            camera_snapshot = _app_state_from_camera(camera_fn())
            sensor_snapshot = pi_client.consume_sensor_state()
            router.process_tick(camera_snapshot, sensor_snapshot, perf_counter())
            sleep_time = max(0.0, next_tick - perf_counter())
            if sleep_time:
                await asyncio.sleep(sleep_time)
    except asyncio.CancelledError:
        LOGGER.info("Router loop cancelled")
        raise


def _app_state_from_camera(raw: Dict[str, object]) -> AppState:
    try:
        return AppState(
            instrument_state=str(raw["instrument_state"]),
            camera_state=str(raw["camera_state"]),
            recording=bool(raw["recording"]),
            is_note_being_played=bool(raw["is_note_being_played"]),
        )
    except KeyError as exc:
        raise KeyError(f"Camera payload missing key: {exc}") from exc


def resolve_camera_callable(spec: str) -> CameraCallable:
    if ":" not in spec:
        raise ValueError("Camera callable spec must be module:function")
    module_name, func_name = spec.split(":", 1)
    module = importlib.import_module(module_name)
    try:
        func = getattr(module, func_name)
    except AttributeError as exc:
        raise AttributeError(f"{module_name} has no attribute {func_name}") from exc
    if not callable(func):
        raise TypeError(f"{func!r} is not callable")
    return func  # type: ignore[return-value]


def _build_router_config(app_config: AppConfig) -> RouterConfig:
    midi = app_config.midi
    transport = app_config.transport
    router = app_config.router
    return RouterConfig(
        mapping=app_config.mapping,
        instrument_map=app_config.instrument_map,
        drum_channel=midi.drum_channel,
        drum_note=midi.drum_note,
        lead_channel=midi.lead_channel,
        lead_velocity=midi.lead_velocity,
        control_channel=midi.control_channel,
        record_cc=midi.record_cc,
        insert_track_cc=midi.insert_track_cc,
        drum_velocity_default=midi.drum_velocity_default,
        bpm=transport.bpm,
        countin_beats=transport.countin_beats,
        watchdog_s=router.watchdog_s,
        auto_insert_on_instrument_change=router.auto_insert_track_on_instrument_change,
        insert_on_record_start=router.auto_insert_track_on_record_start,
    )


async def async_main(args: argparse.Namespace) -> None:
    config = load_config(args.config) if args.config else load_default_config()
    logging.basicConfig(level=getattr(logging, config.logging.level.upper(), logging.INFO))

    midi_outputs = open_outputs(config.midi.musical_port, config.midi.control_port)
    pi_client = PiClient(config.osc.host, config.osc.port)
    camera_fn = resolve_camera_callable(args.camera)
    router = MusicRouter(
        midi_outputs,
        _build_router_config(config),
    )

    loop_task: asyncio.Task[None] | None = None
    try:
        await pi_client.start()
        LOGGER.info("OSC receiver started on %s:%s", config.osc.host, config.osc.port)
        loop_task = asyncio.create_task(router_loop(router, pi_client, camera_fn, config))
        await loop_task
    except asyncio.CancelledError:
        if loop_task is not None:
            loop_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await loop_task
        raise
    finally:
        await pi_client.stop()
        midi_outputs.close()


def main() -> None:
    args = parse_args()
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        LOGGER.info("Interrupted by user")


if __name__ == "__main__":
    main()

