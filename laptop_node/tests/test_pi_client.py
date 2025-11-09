"""Tests for the Pi OSC client buffer behaviour."""

from __future__ import annotations

import asyncio

import pytest

from laptop_node.pi_client import PiClient


@pytest.fixture
def event_loop() -> asyncio.AbstractEventLoop:
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


def test_consume_sensor_state_hit_consumed_once(event_loop: asyncio.AbstractEventLoop) -> None:
    client = PiClient(host="127.0.0.1", port=9000, loop=event_loop)
    client.inject_distance(25.0)
    client.inject_hit(64)

    first = client.consume_sensor_state()
    assert first.dist_cm == pytest.approx(25.0)
    assert first.hit_velocity == 64

    second = client.consume_sensor_state()
    assert second.hit_velocity is None
    assert second.dist_cm == pytest.approx(25.0)


def test_injected_hit_clamped(event_loop: asyncio.AbstractEventLoop) -> None:
    client = PiClient(host="127.0.0.1", port=9000, loop=event_loop)
    client.inject_hit(200)
    assert client.consume_sensor_state().hit_velocity == 127

