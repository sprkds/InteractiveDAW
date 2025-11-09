"""Asynchronous OSC transmission utilities."""

from __future__ import annotations

import json
import logging
import threading
from collections import deque
from typing import Deque, Iterable, Tuple

from pythonosc.udp_client import SimpleUDPClient

LOGGER = logging.getLogger(__name__)


def _log_event(event: str, **fields: object) -> None:
    LOGGER.info(json.dumps({"event": event, **fields}))


class OscTx:
    """Non-blocking OSC transmitter with a bounded queue."""

    def __init__(self, ip: str, port: int, queue_size: int = 64) -> None:
        self._client = SimpleUDPClient(ip, port)
        self._queue_size = max(1, queue_size)
        self._queue: Deque[Tuple[str, Iterable[object]]] = deque()
        self._lock = threading.Lock()
        self._not_empty = threading.Condition(self._lock)
        self._closed = False
        self._thread = threading.Thread(target=self._run, name="osc-tx", daemon=True)
        self._thread.start()
        _log_event("osc_tx_started", ip=ip, port=port, queue_size=self._queue_size)

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._not_empty.notify_all()
        self._thread.join(timeout=1.0)
        _log_event("osc_tx_stopped")

    def send_dist(self, cm: float) -> None:
        self._enqueue("/dist", (float(cm),), drop_oldest=True)

    def send_hit(self, velocity: int) -> None:
        velocity = max(0, min(int(velocity), 127))
        if not self._enqueue("/hit", (velocity,)):
            _log_event("osc_drop_hit", velocity=velocity)

    def send_alive(self, seq: int) -> None:
        seq = int(seq)
        if not self._enqueue("/alive", (seq,)):
            _log_event("osc_drop_alive", seq=seq)

    # Internal -----------------------------------------------------------------

    def _enqueue(
        self,
        address: str,
        payload: Iterable[object],
        drop_oldest: bool = False,
    ) -> bool:
        with self._lock:
            if self._closed:
                return False
            if len(self._queue) >= self._queue_size:
                if drop_oldest and self._drop_oldest_dist_locked():
                    _log_event("osc_drop_oldest_dist")
                else:
                    return False
            self._queue.append((address, tuple(payload)))
            self._not_empty.notify()
            return True

    def _drop_oldest_dist_locked(self) -> bool:
        for idx, (address, _) in enumerate(self._queue):
            if address == "/dist":
                del self._queue[idx]
                return True
        return False

    def _run(self) -> None:
        while True:
            with self._lock:
                while not self._queue and not self._closed:
                    self._not_empty.wait()
                if self._closed and not self._queue:
                    return
                address, payload = self._queue.popleft()
            try:
                self._client.send_message(address, list(payload))
            except Exception as exc:  # pragma: no cover
                _log_event("osc_send_error", address=address, error=str(exc))

