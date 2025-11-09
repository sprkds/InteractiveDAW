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
3. (Optional) Update `config.yaml`:
   - confirm your OSC host/port and MIDI port names
   - tweak the distance→note mapping bounds
   - adjust the `camera` section if you need a different webcam index or want to disable the HUD
4. Run the node with the bundled camera HUD:
   ```bash
   python -m laptop_node.main
   ```
   Use `--config` to point to a custom YAML file or `--camera other_module:get_camera_state` if you provide a different implementation.

## Configuration
`config.yaml` ships with sensible defaults for development. Key sections:
- `osc`: IP/port for incoming sensor events.
- `router`: tick rate (Hz) and watchdog timeout.
- `transport`: BPM and count-in beats for the mute window.
- `midi`: port names, channel assignments, drum note, lead velocity, record CC.
- `mapping`: distance-to-note bounds. The same structure is used to build the `NoteMapping` dataclass.
- `camera`: webcam index, HUD toggle, and optional horizontal flip for the built-in camera interface.

Any of these values can be overridden by providing a new YAML file and pointing `--config` at it.

## Camera HUD
The default `camera_interface` launches a lightweight OpenCV window that mirrors the controller state consumed by the router. Key bindings (window focus required):

- `p` – toggle camera mode between `idle` and `play`
- `r` – toggle `recording`
- `space` – toggle `is_note_being_played`
- `i` – cycle through instruments defined in `instrument_map`
- `q` or `Esc` – close the HUD (the laptop node continues with the last state)

Set `camera.hud_enabled` to `false` in the config to run headless while still supplying state snapshots.

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

