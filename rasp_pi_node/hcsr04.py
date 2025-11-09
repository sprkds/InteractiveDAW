"""HC-SR04 ultrasonic sensor driver using pigpio."""

from __future__ import annotations

import json
import logging
import math
import threading
from itertools import cycle
from typing import Iterable, Optional

try:
    import pigpio  # type: ignore
except ImportError:  # pragma: no cover - pigpio unavailable on non-Pi hosts
    pigpio = None  # type: ignore

LOGGER = logging.getLogger(__name__)


def _log_event(event: str, **fields: object) -> None:
    LOGGER.info(json.dumps({"event": event, **fields}))


class HCSR04:
    """HC-SR04 distance sensor driver powered by pigpio callbacks."""

    def __init__(self, trig: int, echo: int, timeout_us: int) -> None:
        if pigpio is None:
            raise RuntimeError("pigpio library is not available on this host")

        self._trig = trig
        self._echo = echo
        self._timeout_us = max(1, int(timeout_us))
        self._watchdog_ms = max(1, int(math.ceil(self._timeout_us / 1000.0)))

        self._pi = pigpio.pi()  # type: ignore[assignment]
        if not self._pi.connected:  # pragma: no cover - requires hardware fault
            raise RuntimeError("Unable to establish connection to pigpio daemon")
        self._owns_pi = True

        self._pi.set_mode(self._trig, pigpio.OUTPUT)
        self._pi.write(self._trig, 0)
        self._pi.set_mode(self._echo, pigpio.INPUT)
        self._pi.set_pull_up_down(self._echo, pigpio.PUD_DOWN)

        self._lock = threading.Lock()
        self._start_tick: Optional[int] = None
        self._in_flight = False
        self._last_echo_us: Optional[int] = None

        self._callback = self._pi.callback(
            self._echo, pigpio.EITHER_EDGE, self._handle_echo
        )
        _log_event(
            "hcsr04_started",
            trig=self._trig,
            echo=self._echo,
            timeout_us=self._timeout_us,
        )

    def trigger(self) -> bool:
        """Emit the 10 µs trigger pulse if no reading is in-flight."""
        with self._lock:
            if self._in_flight:
                return False
        self._pi.gpio_trigger(self._trig, 10, 1)
        return True

    def read_last_echo_us(self) -> Optional[int]:
        """Consume the last completed echo duration in microseconds."""
        with self._lock:
            value = self._last_echo_us
            self._last_echo_us = None
        return value

    def close(self) -> None:
        """Release pigpio resources."""
        if pigpio is None:
            return
        with self._lock:
            if self._callback is not None:
                self._callback.cancel()
                self._callback = None
            self._pi.set_watchdog(self._echo, 0)
            self._pi.write(self._trig, 0)
        if self._owns_pi:
            self._pi.stop()
        _log_event("hcsr04_stopped")

    # Internal -----------------------------------------------------------------

    def _handle_echo(self, gpio: int, level: int, tick: int) -> None:
        if pigpio is None:
            return

        with self._lock:
            if level == pigpio.TIMEOUT:
                if self._in_flight:
                    _log_event("hcsr04_timeout", timeout_us=self._timeout_us)
                self._in_flight = False
                self._start_tick = None
                self._pi.set_watchdog(self._echo, 0)
                return

            if level == 1:
                self._start_tick = tick
                self._in_flight = True
                self._pi.set_watchdog(self._echo, self._watchdog_ms)
                return

            if level == 0 and self._start_tick is not None:
                pulse_us = pigpio.tickDiff(self._start_tick, tick)
                if 0 < pulse_us <= self._timeout_us:
                    self._last_echo_us = pulse_us
                self._in_flight = False
                self._start_tick = None
                self._pi.set_watchdog(self._echo, 0)


class SimHCSR04:
    """Software stand-in for the HC-SR04 driver."""

    def __init__(
        self,
        distances_cm: Optional[Iterable[float]] = None,
        temp_C: float = 20.0,
    ) -> None:
        if distances_cm is None:
            distances_cm = [40.0]
        self._source = cycle(tuple(distances_cm))
        self._temp_C = temp_C
        self._last_echo_us: Optional[int] = None
        _log_event("hcsr04_sim_started", temp_C=temp_C)

    def trigger(self) -> bool:
        distance_cm = float(next(self._source))
        self._last_echo_us = self._cm_to_us(distance_cm)
        return True

    def read_last_echo_us(self) -> Optional[int]:
        value = self._last_echo_us
        self._last_echo_us = None
        return value

    def close(self) -> None:
        _log_event("hcsr04_sim_stopped")

    def _cm_to_us(self, cm: float) -> int:
        speed_m_s = 331.3 + 0.606 * self._temp_C
        return int(round((cm * 2.0 * 1e4) / speed_m_s))


__all__ = ["HCSR04", "SimHCSR04"]

