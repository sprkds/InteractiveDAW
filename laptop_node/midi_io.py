"""Convenience wrappers for opening and sending MIDI messages."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import mido


class MidiPort(Protocol):
    """Subset of the mido output port API used by the laptop node."""

    def send(self, message: mido.Message) -> None:
        ...

    def close(self) -> None:
        ...


@dataclass
class MidiOutputs:
    """Container for the musical and control MIDI output ports."""

    musical: MidiPort
    control: MidiPort

    def close(self) -> None:
        """Close both MIDI output ports."""
        self.musical.close()
        self.control.close()


def _open_output(port_name: str) -> MidiPort:
    """Open a single MIDI output port with user-friendly errors."""
    try:
        return mido.open_output(port_name)
    except IOError as exc:  # pragma: no cover - depends on system ports
        available = ", ".join(mido.get_output_names())
        raise RuntimeError(
            f"Failed to open MIDI output '{port_name}'. Available ports: {available}"
        ) from exc


def open_outputs(musical_port: str, control_port: str) -> MidiOutputs:
    """Open both required MIDI outputs."""
    musical = _open_output(musical_port)
    control = _open_output(control_port)
    return MidiOutputs(musical=musical, control=control)


def _zero_based_channel(channel: int) -> int:
    """Convert 1-based user channel numbers to 0-based MIDI channels."""
    if not 1 <= channel <= 16:
        raise ValueError(f"MIDI channel must be 1-16, got {channel}")
    return channel - 1


def send_note_on(outputs: MidiOutputs, channel: int, note: int, velocity: int) -> None:
    """Send a NoteOn message via the musical port."""
    message = mido.Message(
        "note_on", channel=_zero_based_channel(channel), note=note, velocity=velocity
    )
    outputs.musical.send(message)


def send_note_off(outputs: MidiOutputs, channel: int, note: int, velocity: int = 0) -> None:
    """Send a NoteOff message via the musical port."""
    message = mido.Message(
        "note_off", channel=_zero_based_channel(channel), note=note, velocity=velocity
    )
    outputs.musical.send(message)


def send_control_change(outputs: MidiOutputs, channel: int, cc: int, value: int) -> None:
    """Send a control change message via the control port."""
    message = mido.Message(
        "control_change",
        channel=_zero_based_channel(channel),
        control=cc,
        value=value,
    )
    outputs.control.send(message)


def send_program_change(outputs: MidiOutputs, channel: int, program: int) -> None:
    """Send a Program Change on the musical port to select a sound (GM-compatible)."""
    message = mido.Message(
        "program_change", channel=_zero_based_channel(channel), program=int(program)
    )
    outputs.musical.send(message)


__all__ = [
    "MidiOutputs",
    "open_outputs",
    "send_control_change",
    "send_program_change",
    "send_note_off",
    "send_note_on",
]

