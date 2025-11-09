# Laptop Node

Async laptop-side gesture router for the low-latency musical instrument project. The process listens for ultrasonic sensor events from the Raspberry Pi over OSC, polls the camera classifier, and emits musical and transport MIDI to REAPER.

## Requirements
- Python 3.11 (developed against 3.10/3.11, 3.11 recommended)
- `mido`, `python-rtmidi`, `python-osc`, `PyYAML`, `pytest` (install with `pip install -r requirements.txt`)
- Two MIDI output ports available to the OS and named in `config.yaml` (defaults: `FromPi` for musical data, `PiCtrl` for transport CC)
- A callable `get_camera_state()` exposed via `--camera module:function`

## Quick Start
1. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
2. Ensure REAPER (or another DAW) exposes virtual MIDI ports named in the configuration, or edit `config.yaml` to match your setup.
3. Provide an import path to the camera/HUD API. Example stub module:
   ```python
   # camera_stub.py
   def get_camera_state():
       return {
           "instrument_state": "synth",
           "camera_state": "play",
           "recording": False,
           "is_note_being_played": False,
       }
   ```
4. Run the node:
   ```bash
   python -m laptop_node.main --camera camera_stub:get_camera_state
   ```
   Use `--config` to point to a custom YAML file if you need different ports or mapping.

## Configuration
`config.yaml` ships with sensible defaults for development. Key sections:
- `osc`: IP/port for incoming sensor events.
- `router`: tick rate (Hz) and watchdog timeout.
- `transport`: BPM and count-in beats for the mute window.
- `midi`: port names, channel assignments, drum note, lead velocity, record CC.
- `mapping`: distance-to-note bounds. The same structure is used to build the `NoteMapping` dataclass.

Any of these values can be overridden by providing a new YAML file and pointing `--config` at it.

## Testing
Run the Python unit tests with:
```bash
pytest laptop_node/tests
```
Tests include distance quantisation edges, OSC sensor buffering, and change-only note emission.

## Development Notes
- The core router loop runs at 100 Hz using a driftless `perf_counter` scheduler.
- OSC reception uses `python-osc`'s asyncio server; the router consumes snapshots each tick.
- MIDI output is abstracted through `mido` on top of `python-rtmidi`, so port selection happens once at startup.
- Recording control sends CC20 on both rising and falling edges of the camera `recording` flag, aligning with REAPER's toggle action.

See `DESIGN.md` for deeper details on timing assumptions and the mute window behaviour.

