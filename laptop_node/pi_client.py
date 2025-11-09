"""OSC client abstraction for receiving sensor data from the Pi."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from time import perf_counter
from typing import Optional, Tuple

from pythonosc import dispatcher
from pythonosc.osc_server import AsyncIOOSCUDPServer

from .state import SensorState

LOGGER = logging.getLogger(__name__)


@dataclass
class _SensorBuffer:
    dist_cm: Optional[float] = None
    pending_hit: Optional[int] = None
    last_rx_ts: float = field(default_factory=perf_counter)

    def update_distance(self, dist_cm: float) -> None:
        self.dist_cm = dist_cm
        self.last_rx_ts = perf_counter()

    def update_hit(self, velocity: int) -> None:
        self.pending_hit = velocity
        self.last_rx_ts = perf_counter()

    def consume(self) -> SensorState:
        hit = self.pending_hit
        self.pending_hit = None
        return SensorState(dist_cm=self.dist_cm, hit_velocity=hit, last_rx_ts=self.last_rx_ts)


class PiClient:
    """Receives OSC messages from the Pi and exposes sensor snapshots."""

    def __init__(
        self,
        host: str,
        port: int,
        loop: Optional[asyncio.AbstractEventLoop] = None,
    ) -> None:
        self._loop = loop or asyncio.get_event_loop()
        self._address = (host, port)
        self._buffer = _SensorBuffer()
        self._dispatcher = dispatcher.Dispatcher()
        self._dispatcher.map("/dist", self._on_dist)
        self._dispatcher.map("/hit", self._on_hit)
        self._server = AsyncIOOSCUDPServer(self._address, self._dispatcher, self._loop)
        self._transport: Optional[asyncio.BaseTransport] = None
        self._protocol = None

    async def start(self) -> None:
        """Start listening for OSC messages."""
        if self._transport is not None:
            return
        self._transport, self._protocol = await self._server.create_serve_endpoint()
        LOGGER.info("PiClient listening on %s:%s", *self.address)

    async def stop(self) -> None:
        """Stop the OSC server."""
        if self._transport is None:
            return
        self._transport.close()
        self._transport = None
        self._protocol = None

    @property
    def address(self) -> Tuple[str, int]:
        """Return the configured OSC address tuple."""
        return self._address

    def consume_sensor_state(self) -> SensorState:
        """Return the latest sensor state, consuming any pending hit."""
        return self._buffer.consume()

    def inject_distance(self, dist_cm: float) -> None:
        """Testing helper to inject a distance reading."""
        self._buffer.update_distance(dist_cm)

    def inject_hit(self, velocity: int) -> None:
        """Testing helper to inject a hit velocity."""
        velocity = max(0, min(int(velocity), 127))
        self._buffer.update_hit(velocity)

    # Handlers -----------------------------------------------------------------

    def _on_dist(self, _addr: str, value: float) -> None:
        try:
            dist = float(value)
        except (TypeError, ValueError):
            LOGGER.debug("Ignoring non-float distance payload: %s", value)
            return
        self._buffer.update_distance(dist)

    def _on_hit(self, _addr: str, value: int) -> None:
        try:
            velocity = int(value)
        except (TypeError, ValueError):
            LOGGER.debug("Ignoring non-int hit payload: %s", value)
            return
        velocity = max(0, min(velocity, 127))
        self._buffer.update_hit(velocity)


__all__ = ["PiClient"]

