# Raspberry Pi Node Design

## Overview
The Pi node reads the HC-SR04 ultrasonic sensor, filters the distance, and streams
telemetry to the laptop node via OSC/UDP. The laptop already maps distance to
pitch, so the Pi focuses on high-rate distance data, optional hit edges, and a
heartbeat.

## Timing and Scheduler
- Fixed-rate loop at `cycle_hz` (default 100 Hz).
- Driftless scheduling: `next_tick += 1 / cycle_hz`, `sleep(max(0, next_tick - now))`.
- `/alive <int seq>` published every second (`seq` is a monotonic counter).

## Sensor Driver (pigpio)
- TRIG emits a 10 µs pulse via `pigpio.gpio_trigger()`.
- ECHO monitored with a single `pigpio.callback` on both edges.
- Rising edge starts the measurement and arms a watchdog (`timeout_us`).
- Falling edge captures `tickDiff` in microseconds and stores the sample.
- Watchdog expiry clears the in-flight measurement and logs a timeout event.
- `SimHCSR04` offers a waveform-driven software sensor for development.

## Filtering Pipeline
1. Convert microseconds to centimetres:
   - `speed = 331.3 + 0.606 * temp_C` (m/s).
   - `cm = (echo_us * speed / 2) / 1e4`.
2. Median filter over the most recent `median_window` samples.
3. Optional EMA smoothing (`ema_alpha`).
4. Clamp to `[min_cm, max_cm]` before publishing.

## Hit Detection (Optional)
- Configurable hysteresis and refractory window.
- Fires once per crossing (`cm < threshold - hysteresis`).
- Re-arms when `cm > threshold + hysteresis`.
- Velocity estimated from approach speed and mapped into `[velocity_min, velocity_max]`.
- Default configuration disables hit reporting; when enabled it sends `/hit <int vel>`.

## OSC Transport
- Non-blocking sender with a bounded queue (default 64 entries).
- `/dist <float cm>` transmitted every loop iteration.
- `/alive <int seq>` emitted once per second.
- `/hit <int vel>` sent only when hit detection triggers.
- If the queue fills, the oldest `/dist` sample is discarded to protect control
  messages.

## Logging and Telemetry
- JSON-line structured logging for startup, hits, alive ticks, timeouts, and send
  drops.
- Optional console output of every distance sample (`print_dist`).

## Configuration Surface (`config.yaml`)
- Pins (`trig`, `echo`), timing (`cycle_hz`, `timeout_us`).
- Distance limits and temperature.
- Filter parameters (median window, EMA alpha).
- OSC endpoint (`laptop_ip`, `port`, `queue_size`).
- Hit detection tuning and velocity mapping.
- Simulator section for waveform-driven development.
- Logging level and whether to print each distance.

