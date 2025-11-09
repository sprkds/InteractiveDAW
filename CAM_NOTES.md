## cam overview (what it does and how to explain it simply)

This script turns a webcam into a gesture controller for a simple DAW workflow with three states: instrument select, play, and recording on. It uses MediaPipe hands to track one hand and OpenCV for video and the on‑screen HUD.

### Components
- Video + HUD
  - Captures frames from the default camera with OpenCV.
  - Draws a minimal HUD (three lines): state, instrument, recording.
  - “Ghost hand” overlay helps users position their hand (red until matched, green when matched, then hides).

- Model used
  - MediaPipe Hands (single-hand mode), which is a TensorFlow Lite graph bundled by Google. It returns 21 hand landmarks and a handedness label (Left/Right). We did not train a model.
  
- Gesture logic at a high level
  1) Finger counting (instrument select)
     - Converts landmarks into “fingers up” booleans (thumb, index, middle, ring, pinky).
     - Maps “fingers up” count (1..4) to an instrument (Kick/Snare/HiHat/Tom). 5 fingers = Idle.
     - Debounces selection with time-based stability and auto-commit thresholds.
     - Transition to PLAY happens on a fist “edge” (open→closed).

  2) Play (not recording)
     - Pinch (thumb–index close) auditions the current instrument and supports hold (DOWN/HOLD/UP).
     - Fist edge returns to instrument select (escape hatch).
     - “Arm” gesture for recording requires thumb+middle+ring down (with a short dwell and edge detection to avoid false triggers right after a fist).

  3) Recording on
     - Same pinch hold behavior triggers the instrument while recording.
     - Fist edge stops recording and returns to instrument select.

- Ghost hand (guidance)
  - A saved target pose (21 normalized points). Shows in red until the live hand is near it; turns green and hides when matched; reappears red if the hand moves away.
  - Anchors for matching are the wrist and MCP joints to judge “general placement,” not exact fingertips.
  - Hotkeys let you capture the current hand as the ghost and save it to disk; it auto-loads on startup.

### Key thresholds and why
- SELECT_STABLE_MS / SELECT_COMMIT_MS
  - Time dwell to stabilize finger-count (candidate) and then auto-commit to the instrument. Reduces flicker and accidental picks.
- PINCH_THRESH_PX (+ hysteresis)
  - Distance threshold (pixels) for pinch detection with hysteresis to avoid chattering.
- ARM_COMBO_DWELL_MS
  - Short dwell so thumb+middle+ring down must persist briefly to arm. Also requires an edge after a fist to prevent instant arming.
- GHOST_HIDE_PX (+ anchors)
  - Loose match on wrist + MCPs so a user only needs to be “near” the ghost rather than exact. Keeps guidance helpful without being frustrating.

### Handedness and mirroring
- MIRROR_INPUT ensures MediaPipe sees a “selfie-like” image so Left/Right align with the user’s perspective.
- HANDEDNESS_INVERT and THUMB_INVERT are safety toggles in case camera feed or handedness feels reversed.

### Hotkeys (for live calibration/testing)
- C: capture and save current pose as ghost (persists to `ghost_pose.json`).
- O: reload saved ghost. K: clear ghost. G: toggle ghost visibility.
- L: toggle live landmark rig. D: toggle debug HUD (extra diagnostics).
- M / I: toggle display/input mirroring. H / T: invert handedness / thumb rule.

### State summary (for demos)
- Instrument select (BEGIN): choose instrument by finger count; fist edge → PLAY.
- PLAY (recording off): pinch audition; fist edge → select; arm when thumb+middle+ring down (dwell + edge).
- RECORDING ON: pinch to trigger; fist edge → select.

### Integration notes
- The app is a single Python script with no external server. MediaPipe is imported as a Python package and runs locally via TFLite.
- All timing and debouncing are local (no threads required). HUD and overlays are drawn with OpenCV.
- Persistence: ghost pose is saved as normalized coordinates in `ghost_pose.json` next to the script.

This framing (“three states,” “pinch audition/trigger,” “arm combo to record”) is usually enough to explain the system clearly to users and collaborators.

