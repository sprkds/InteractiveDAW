# Design Notes

## Overview
The laptop node integrates three real-time data sources: the Pi's ultrasonic sensor stream (OSC), the camera classifier (Python callable), and the DAW (MIDI). All processing happens inside a single asyncio event loop. A 100 Hz router coroutine fuses the latest camera snapshot with the most recent sensor reading and emits MIDI per instrument mode. Transport control uses a separate MIDI port so that musical data can be muted without interrupting record toggles.

## Timing & Scheduler
- **Tick cadence**: The router loop targets 100 Hz. Each iteration increments `next_tick += dt` (with `dt = 0.01`) and sleeps the residual, ensuring driftless timing even under minor jitter.
- **Clock source**: `time.perf_counter()` backs both tick scheduling and watchdog checks, providing monotonic, high-resolution timing on Windows.
- **Camera polling**: The camera callable is executed synchronously at the start of each tick. It is assumed to be fast; if it ever blocks, the callable can be moved to a thread and its latest snapshot injected before calling `router.process_tick`.
- **Watchdog**: If no OSC `/dist` or `/hit` arrives for ≥ `router.watchdog_s` seconds (default 0.5 s), the router sends `NoteOff` for any held note, logs a “watchdog timeout”, and suppresses further duplicates until fresh data arrives.

## MIDI Mapping Choices
- **Port split**: Musical data flows through `midi.musical_port` (`FromPi` by default). Transport CCs travel via `midi.control_port` (`PiCtrl`). This keeps REAPER’s action mappings isolated from melodic notes.
- **Channels**: Lead instruments use channel 1, drums use channel 10 (General MIDI percussion). Transport CCs default to channel 1 but can be overridden in the config.
- **Notes & velocities**:
  - Drum hits map `/hit` velocities to note 36 (kick) with channel 10.
  - Lead voices quantise distance (15–60 cm) to chromatic notes 48–72 (C3–C5) and emit `NoteOn` at fixed velocity 90. Velocity curves per instrument can be added later within `music_router`.
- **Change-only policy**: Consecutive ticks with stable distance don’t re-trigger `NoteOn`. When the quantised pitch shifts, the router sends `NoteOff` for the held note before issuing the new `NoteOn`. When `is_note_being_played` becomes false, the held note is released and the last note tracker resets so a subsequent gesture re-triggers correctly.

## Count-In Mute Window
- **Recording edges**: Rising and falling transitions of the camera `recording` flag emit CC20 (value 127) on the control port, matching REAPER’s “Transport: Record” toggle action.
- **Mute window**: On a rising edge, `mute_until` is set to `now + countin_beats * 60 / bpm`. During this window the router suppresses all musical MIDI (no NoteOn/NoteOff/CC), but transport CCs continue to flow. Any held note is released immediately when the mute starts to prevent sustain under the count-in click.
- **Configurable length**: `transport.bpm` and `transport.countin_beats` live in `config.yaml`. Setting `countin_beats` to 0 effectively disables the mute window.

## Structured Logging
- Mode changes (`camera_state`), instrument changes, recording edges, and watchdog events log via `logging`. The default formatter is simple text; replace with JSON logging if deeper telemetry is required.
- `MusicRouter` only logs in the control path to keep the 100 Hz loop lightweight.

## Extensibility Hooks
- `NoteMapping` already supports swapping the scale function, enabling pentatonic or modal mappings later without reworking the router.
- The OSC client exposes `inject_distance` and `inject_hit` helpers, which feed the same buffer used by real OSC handlers. Integration tests can use these to mimic Pi behaviour without sockets.
- Future additions (e.g., CC21 track creation or multi-voice layers) can piggyback on the existing MIDI abstractions without touching the 100 Hz scheduler.

