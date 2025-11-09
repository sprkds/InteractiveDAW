"""Main entry-point for the Raspberry Pi sensor node."""

from __future__ import annotations

import argparse
import json
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Optional

import yaml

from .filters import clamp, ema, median_filter, us_to_cm
from .hcsr04 import HCSR04, SimHCSR04
from .hit_detect import HitState, detect_hit
from .osc_sender import OscTx

LOGGER = logging.getLogger(__name__)
DEFAULT_CONFIG = Path(__file__).resolve().with_name("config.yaml")


def _log_event(event: str, **fields: object) -> None:
    LOGGER.info(json.dumps({"event": event, **fields}))


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Raspberry Pi node for InteractiveDAW distance sensing."
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Path to configuration YAML (defaults to rasp_pi_node/config.yaml).",
    )
    return parser.parse_args(list(argv) if argv is not None else None)


def load_config(path: Optional[Path]) -> Dict[str, Any]:
    config_path = path or DEFAULT_CONFIG
    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle) or {}
    return raw


def _deep_update(base: Dict[str, Any], updates: Dict[str, Any]) -> Dict[str, Any]:
    for key, value in updates.items():
        if (
            isinstance(value, dict)
            and key in base
            and isinstance(base[key], dict)
        ):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def _with_defaults(raw: Dict[str, Any]) -> Dict[str, Any]:
    defaults: Dict[str, Any] = {
        "pins": {"trig": 23, "echo": 24},
        "cycle_hz": 100.0,
        "timeout_us": 30000,
        "distance": {
            "min_cm": 15.0,
            "max_cm": 60.0,
            "temp_C": 20.0,
        },
        "filters": {"median_window": 5, "ema_alpha": 0.25},
        "osc": {"laptop_ip": "127.0.0.1", "port": 9000, "queue_size": 64},
        "hit": {
            "enabled": False,
            "threshold_cm": 25.0,
            "hysteresis_cm": 2.0,
            "refractory_s": 0.2,
            "velocity_min": 30,
            "velocity_max": 127,
            "min_speed_cm_s": 5.0,
            "max_speed_cm_s": 120.0,
            "fixed_velocity": 100,
        },
        "simulator": {"enabled": False, "waveform_cm": [40.0]},
        "logging": {"level": "INFO"},
        "print_dist": True,
    }
    return _deep_update(defaults, raw)


def _install_signal_handlers(stop_flag: Dict[str, bool]) -> None:
    def handler(signum: int, _frame: object) -> None:
        _log_event("signal_received", signal=signum)
        stop_flag["stop"] = True

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, handler)
        except ValueError:  # pragma: no cover - not available on all platforms
            continue


def run(config: Dict[str, Any]) -> None:
    stop_flag = {"stop": False}
    _install_signal_handlers(stop_flag)

    pins = config["pins"]
    distance_cfg = config["distance"]
    filters_cfg = config["filters"]
    osc_cfg = config["osc"]
    hit_cfg = config["hit"]
    sim_cfg = config["simulator"]

    osc = OscTx(osc_cfg["laptop_ip"], int(osc_cfg["port"]), osc_cfg.get("queue_size", 64))

    temp_C = float(distance_cfg.get("temp_C", 20.0))
    sensor = (
        SimHCSR04(sim_cfg.get("waveform_cm"), temp_C=temp_C)
        if sim_cfg.get("enabled", False)
        else HCSR04(int(pins["trig"]), int(pins["echo"]), int(config["timeout_us"]))
    )

    cycle_hz = float(config["cycle_hz"])
    if cycle_hz <= 0.0:
        raise ValueError("cycle_hz must be greater than zero")

    median_window_size = int(filters_cfg.get("median_window", 5))
    ema_alpha = float(filters_cfg.get("ema_alpha", 0.0))
    print_dist = bool(config.get("print_dist", False))

    hit_state = HitState(
        armed=True,
        last_hit_s=time.monotonic() - float(hit_cfg.get("refractory_s", 0.0)),
        last_cm=None,
        last_sample_s=None,
        velocity_min=int(hit_cfg.get("velocity_min", 30)),
        velocity_max=int(hit_cfg.get("velocity_max", 127)),
        min_speed_cm_s=float(hit_cfg.get("min_speed_cm_s", 5.0)),
        max_speed_cm_s=float(hit_cfg.get("max_speed_cm_s", 120.0)),
        fixed_velocity=int(hit_cfg.get("fixed_velocity", 100)),
    )

    _log_event(
        "pi_node_started",
        cycle_hz=cycle_hz,
        trig=pins["trig"],
        echo=pins["echo"],
        simulator=bool(sim_cfg.get("enabled", False)),
    )

    try:
        _run_loop(
            osc=osc,
            sensor=sensor,
            temp_C=temp_C,
            cycle_hz=cycle_hz,
            median_window_size=median_window_size,
            ema_alpha=ema_alpha,
            d_min=float(distance_cfg["min_cm"]),
            d_max=float(distance_cfg["max_cm"]),
            hit_cfg=hit_cfg,
            hit_state=hit_state,
            print_dist=print_dist,
            stop_flag=stop_flag,
        )
    finally:
        sensor.close()
        osc.close()
        _log_event("pi_node_stopped")


def _run_loop(
    *,
    osc: OscTx,
    sensor: Any,
    temp_C: float,
    cycle_hz: float,
    median_window_size: int,
    ema_alpha: float,
    d_min: float,
    d_max: float,
    hit_cfg: Dict[str, Any],
    hit_state: HitState,
    print_dist: bool,
    stop_flag: Dict[str, bool],
) -> None:
    period = 1.0 / cycle_hz
    next_tick = time.monotonic()
    next_alive = next_tick + 1.0
    alive_seq = 0

    median_window: list[float] = []
    ema_value: Optional[float] = None
    last_cm: Optional[float] = None

    hit_enabled = bool(hit_cfg.get("enabled", False))
    thresh = float(hit_cfg.get("threshold_cm", 0.0))
    hyst = float(hit_cfg.get("hysteresis_cm", 0.0))
    refract_s = float(hit_cfg.get("refractory_s", 0.0))

    sensor.trigger()

    while not stop_flag["stop"]:
        now = time.monotonic()
        sleep_time = next_tick - now
        if sleep_time > 0:
            time.sleep(sleep_time)
        now = time.monotonic()
        next_tick += period

        echo_us = sensor.read_last_echo_us()
        if echo_us is not None:
            cm_raw = us_to_cm(echo_us, temp_C=temp_C)
            if cm_raw is not None:
                median_window.append(cm_raw)
                try:
                    cm_filtered = median_filter(median_window, median_window_size)
                except ValueError:
                    cm_filtered = cm_raw

                if 0.0 < ema_alpha <= 1.0:
                    ema_value = ema(ema_value, cm_filtered, ema_alpha)
                    cm_filtered = ema_value

                cm_filtered = clamp(cm_filtered, d_min, d_max)
                last_cm = cm_filtered

        if last_cm is not None:
            osc.send_dist(last_cm)
            if print_dist:
                print(f"dist_cm={last_cm:.2f}")

            if hit_enabled:
                fired, velocity, hit_state = detect_hit(
                    last_cm, now, hit_state, thresh, hyst, refract_s
                )
                if fired:
                    osc.send_hit(velocity)
                    _log_event("hit", cm=last_cm, velocity=velocity)

        while now >= next_alive:
            alive_seq += 1
            osc.send_alive(alive_seq)
            _log_event("alive", seq=alive_seq)
            next_alive += 1.0

        sensor.trigger()


def main(argv: Optional[Iterable[str]] = None) -> None:
    args = parse_args(argv)
    raw_config = load_config(args.config)
    config = _with_defaults(raw_config)

    logging_level = getattr(
        logging, str(config["logging"].get("level", "INFO")).upper(), logging.INFO
    )
    logging.basicConfig(level=logging_level, format="%(message)s")

    try:
        run(config)
    except KeyboardInterrupt:
        _log_event("keyboard_interrupt")
    except Exception as exc:  # pragma: no cover - top-level guard
        _log_event("fatal_error", error=str(exc))
        raise


if __name__ == "__main__":
    main(sys.argv[1:])

