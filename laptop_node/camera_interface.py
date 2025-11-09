"""Threaded camera HUD that exposes get_camera_state() for the laptop node."""

from __future__ import annotations

import atexit
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import math

try:
    import cv2  # type: ignore[import]
except ImportError as exc:  # pragma: no cover - dependency missing
    raise RuntimeError(
        "OpenCV (cv2) is required for laptop_node.camera_interface"
    ) from exc

from .configuration import AppConfig, load_default_config

try:
    import mediapipe as mp  # type: ignore[import]
except ImportError:  # pragma: no cover
    mp = None  # type: ignore[assignment]

LOGGER = logging.getLogger(__name__)

# FSM timing constants (ms)
SELECT_STABLE_MS = 400
SELECT_COMMIT_MS = 1000
ARM_COMBO_DWELL_MS = 250
SELECT_IGNORE_IDLE = True
FIST_STABLE_MS = 150
FIST_MAX_UP = 0  # require exactly 0 fingers up (true fist)
HAND_PRESENT_GRACE_MS = 200
PINCH_THRESH_PX = 40
PINCH_HYST = 6

_DEBUG_MODE = False


@dataclass(frozen=True)
class CameraSettings:
    """Runtime settings for the camera HUD."""

    index: int = 0
    hud_enabled: bool = True
    flip: bool = False
    instruments: Tuple[str, ...] = field(default_factory=tuple)


class CameraController:
    """Background thread that renders the camera HUD and tracks state."""

    WINDOW_NAME = "InteractiveDAW Camera"

    def __init__(self, settings: CameraSettings) -> None:
        self._settings = settings
        self._state_lock = threading.Lock()
        instruments = settings.instruments or ("lead",)
        self._instruments: Tuple[str, ...] = instruments
        self._instrument_idx = -1  # none selected at startup
        self._candidate_idx: Optional[int] = None
        self._last_fc: Optional[int] = None
        self._last_fc_change: float = time.time()
        self._prev_is_fist: bool = False
        self._prev_arm_combo: bool = False
        self._arm_ready: bool = False
        self._arm_start_ms: float = 0.0

        # Calibration flags (match original defaults)
        self._thumb_invert: bool = True
        self._handedness_invert: bool = False
        # Fist stability
        self._last_fist_raw: bool = False
        self._last_fist_change: float = time.time()
        self._last_hand_seen: float = time.time()
        self._prev_pinch: bool = False
        self._pinch_hold_active: bool = False
        self._pinch_last_ms: float = 0.0

        self._camera_state = "instrument select"
        self._recording = False
        self._note_on = False
        self._running = threading.Event()
        self._running.set()
        self._thread = threading.Thread(target=self._run, name="camera-hud", daemon=True)
        self._fps = 0.0
        self._last_frame_ts = time.perf_counter()
        self._controller_lock = threading.Lock()
        self._cap: Optional[cv2.VideoCapture] = None
        self._window_created = False
        self._hands = None
        self._flip = settings.flip
        self._thread.start()
        atexit.register(self.shutdown)
        LOGGER.info(
            "CameraController started (index=%s, hud_enabled=%s, flip=%s)",
            settings.index,
            settings.hud_enabled,
            settings.flip,
        )

    # ------------------------------------------------------------------ #
    # Public API                                                         #
    # ------------------------------------------------------------------ #
    def snapshot(self) -> Dict[str, object]:
        """Return the latest camera state snapshot."""
        with self._state_lock:
            instrument = self._current_instrument_label()
            return {
                "instrument_state": instrument,
                "camera_state": self._camera_state,
                "recording": self._recording,
                "is_note_being_played": self._note_on,
            }

    def shutdown(self) -> None:
        """Request the controller to stop and release resources."""
        if not self._running.is_set():
            return
        self._running.clear()
        self._thread.join(timeout=1.5)
        with self._controller_lock:
            if self._cap is not None:
                self._cap.release()
                self._cap = None
        if self._window_created:
            try:
                cv2.destroyWindow(self.WINDOW_NAME)
            except Exception:  # pragma: no cover
                pass
        self._window_created = False
        LOGGER.info("CameraController stopped")

    # ------------------------------------------------------------------ #
    # Internal helpers                                                   #
    # ------------------------------------------------------------------ #
    def _run(self) -> None:
        capture = self._open_capture()
        hands_ctx = self._open_hands()
        while self._running.is_set():
            frame = self._read_frame(capture)
            if frame is not None and self._flip:
                frame = cv2.flip(frame, 1)

            if frame is not None and self._settings.hud_enabled:
                display = frame.copy()
                now_ts = time.time()
                landmarks, handedness, fcount, fingers_up, pinch_px = self._infer(display, hands_ctx)
                present = landmarks is not None
                if present:
                    self._last_hand_seen = now_ts
                present_smoothed = present or ((now_ts - self._last_hand_seen) * 1000.0 <= HAND_PRESENT_GRACE_MS)
                if present:
                    self._draw_landmarks(display, landmarks)
                    self._run_fsm(
                        fcount,
                        fingers_up is not None and not fingers_up["thumb"] and not fingers_up["middle"] and not fingers_up["ring"],
                        hand_present=present_smoothed,
                    )
                    self._handle_pinch(pinch_px, arm_combo=(fingers_up is not None and not fingers_up["thumb"] and not fingers_up["middle"] and not fingers_up["ring"]))
                else:
                    # No hand detected: run FSM with smoothed presence and display '-' for fingers
                    self._run_fsm(0, False, hand_present=present_smoothed)
                    self._handle_pinch(None, arm_combo=False)
                self._draw_hud(display, fcount if present else -1, present_smoothed)
                if not self._window_created:
                    cv2.namedWindow(self.WINDOW_NAME, cv2.WINDOW_NORMAL)
                    self._window_created = True
                cv2.imshow(self.WINDOW_NAME, display)
                key = cv2.waitKey(1) & 0xFF
            else:
                key = -1
                time.sleep(0.016)

            self._handle_key(key)
            self._maybe_close_window()

        if capture is not None:
            capture.release()
        self._close_hands(hands_ctx)

    def _open_capture(self) -> Optional[cv2.VideoCapture]:
        if not self._settings.hud_enabled:
            LOGGER.info("Camera HUD disabled; running in headless mode")
            return None

        index = self._settings.index

        # On Windows, try DirectShow first, then MSMF, then default
        tried = []
        for api in (getattr(cv2, "CAP_DSHOW", 0), getattr(cv2, "CAP_MSMF", 0), getattr(cv2, "CAP_ANY", 0)):
            try:
                cap = cv2.VideoCapture(index, api)
                tried.append((api, bool(cap.isOpened())))
                if cap.isOpened():
                    with self._controller_lock:
                        self._cap = cap
                    LOGGER.info("Camera opened at index=%s with API=%s", index, api)
                    return cap
                cap.release()
            except Exception:
                tried.append((api, False))
                continue

        LOGGER.warning("Unable to open camera index %s; tried apis=%s; running headless", index, tried)
        return None

    def _open_hands(self):
        if mp is None:
            return None
        try:
            hands = mp.solutions.hands.Hands(  # type: ignore[attr-defined]
                static_image_mode=False,
                max_num_hands=1,
                model_complexity=0,
                min_detection_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            return hands
        except Exception:  # pragma: no cover
            return None

    def _close_hands(self, hands) -> None:
        try:
            if hands is not None:
                hands.close()
        except Exception:  # pragma: no cover
            pass

    def _read_frame(self, cap: Optional[cv2.VideoCapture]) -> Optional[cv2.Mat]:
        if cap is None:
            return None
        ok, frame = cap.read()
        if not ok:
            # Give the camera a moment before retrying
            time.sleep(0.05)
            return None
        self._update_fps()
        return frame

    def _update_fps(self) -> None:
        now = time.perf_counter()
        delta = now - self._last_frame_ts
        self._last_frame_ts = now
        if delta > 0:
            self._fps = 0.9 * self._fps + 0.1 * (1.0 / delta)

    def _infer(self, frame, hands_ctx):
        if hands_ctx is None:
            return None, None, 0, None, None
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        res = hands_ctx.process(rgb)
        if not res.multi_hand_landmarks or not res.multi_handedness:
            return None, None, 0, None, None
        lm = res.multi_hand_landmarks[0]
        handed = res.multi_handedness[0].classification[0].label
        fingers_up = self._fingers_up(lm, handed)
        fcount = int(fingers_up["thumb"]) + int(fingers_up["index"]) + int(fingers_up["middle"]) + int(fingers_up["ring"]) + int(fingers_up["pinky"])
        # Pinch distance in pixels (thumb tip 4 to index tip 8)
        h, w = frame.shape[0], frame.shape[1]
        pt4 = lm.landmark[4]
        pt8 = lm.landmark[8]
        dx = (pt4.x - pt8.x) * w
        dy = (pt4.y - pt8.y) * h
        pinch_px = math.hypot(dx, dy)
        return lm, handed, fcount, fingers_up, pinch_px

    def _draw_landmarks(self, frame, landmarks) -> None:
        try:
            drawer = mp.solutions.drawing_utils  # type: ignore[attr-defined]
            conn = mp.solutions.hands.HAND_CONNECTIONS  # type: ignore[attr-defined]
            drawer.draw_landmarks(frame, landmarks, conn)
        except Exception:  # pragma: no cover
            pass

    def _draw_hud(self, frame, fcount: int, hand_present: bool) -> None:
        with self._state_lock:
            instrument = self._current_instrument_label()
            recording = self._recording
            note_on = self._note_on
            cam_state = self._camera_state
            fps = self._fps

        font = cv2.FONT_HERSHEY_SIMPLEX
        color = (255, 255, 255)
        line1 = f"state: {cam_state}"
        line2 = f"instrument: {instrument or 'none'}"
        line3 = f"recording: {'on' if recording else 'off'}"
        lines = [line1, line2, line3]
        if _DEBUG_MODE:
            line4 = f"note: {'on' if note_on else 'off'}"
            line5 = f"fps: {fps:.1f}"
            fc_text = "-" if fcount < 0 else str(fcount)
            line6 = f"fingers: {fc_text}  hand:{'yes' if hand_present else 'no'}  flip:{self._flip} hand_inv:{self._handedness_invert} thumb_inv:{self._thumb_invert}"
            lines.extend([line4, line5, line6])

        y = 28
        for idx, text in enumerate(lines):
            col = color
            if idx == 2 and recording:
                col = (0, 0, 255)
            if _DEBUG_MODE and idx == 3 and note_on:
                col = (0, 255, 0)
            cv2.putText(frame, text, (10, y), font, 0.7, col, 2, cv2.LINE_AA)
            y += 28

        if _DEBUG_MODE:
            help_text = "keys: [p]lay [r]ec [space]=note [i]nstr [m]irror [h]and [t]humb [q]/ESC"
            cv2.putText(
                frame,
                help_text,
                (10, frame.shape[0] - 12),
                font,
                0.55,
                (200, 200, 200),
                1,
                cv2.LINE_AA,
            )

    def _fingers_up(self, lm, handed_label: str) -> Dict[str, bool]:
        pts = lm.landmark
        tip = [4, 8, 12, 16, 20]
        pip = [3, 6, 10, 14, 18]
        # Thumb: horizontal test depends on handedness
        is_right = handed_label == "Right"
        if self._handedness_invert:
            is_right = not is_right
        thumb_up = (pts[tip[0]].x > pts[pip[0]].x + 0.02) if is_right else (pts[tip[0]].x < pts[pip[0]].x - 0.02)
        if self._thumb_invert:
            thumb_up = not thumb_up
        # Other four: tip above PIP (smaller y)
        index_up = pts[tip[1]].y < pts[pip[1]].y - 0.02
        middle_up = pts[tip[2]].y < pts[pip[2]].y - 0.02
        ring_up = pts[tip[3]].y < pts[pip[3]].y - 0.02
        pinky_up = pts[tip[4]].y < pts[pip[4]].y - 0.02
        return {"thumb": thumb_up, "index": index_up, "middle": middle_up, "ring": ring_up, "pinky": pinky_up}

    def _run_fsm(self, fcount: int, arm_combo: bool, *, hand_present: bool) -> None:
        now = time.time()
        # Consider <=1 fingers up as fist to handle occasional thumb miscounts
        is_fist_raw = fcount <= FIST_MAX_UP
        if is_fist_raw != self._last_fist_raw:
            self._last_fist_raw = is_fist_raw
            self._last_fist_change = now
        is_fist_stable = (now - self._last_fist_change) * 1000.0 >= FIST_STABLE_MS
        is_fist = is_fist_raw and is_fist_stable

        start_state = self._camera_state

        # Update candidate in instrument_select with dwell debounce
        if start_state == "instrument select":
            if fcount != self._last_fc:
                self._last_fc = fcount
                self._last_fc_change = now
            stable_ms = (now - self._last_fc_change) * 1000.0
            if stable_ms >= SELECT_STABLE_MS:
                cand_idx = self._map_fingers_to_instrument_idx(self._last_fc or 0)
                # Optionally ignore "idle" (5) as candidate
                if not (SELECT_IGNORE_IDLE and (self._last_fc == 5)):
                    self._candidate_idx = cand_idx
                # Auto-commit after a longer dwell
                if (
                    stable_ms >= SELECT_COMMIT_MS
                    and cand_idx is not None
                    and cand_idx != self._instrument_idx
                ):
                    self._instrument_idx = cand_idx
                    LOGGER.info("Instrument committed by dwell -> %s", self._current_instrument_label())

            # Fist edge enters play and commits candidate if available
            # Allow transition based on stabilized fist irrespective of brief hand-present glitches
            if is_fist and not self._prev_is_fist:
                if self._candidate_idx is not None and self._candidate_idx >= 0:
                    self._instrument_idx = self._candidate_idx
                self._camera_state = "play"
                LOGGER.info("FSM: instrument_select -> play (fist)")
                # Reset arm gating
                self._arm_ready = False
                self._prev_arm_combo = True
                self._arm_start_ms = 0.0

        # PLAY (not recording): handle arm combo and exit by fist
        if start_state == "play" and not self._recording:
            if hand_present and is_fist and not self._prev_is_fist:
                self._camera_state = "instrument select"

            # arm gating
            now_ms = now * 1000.0
            if not self._arm_ready and not arm_combo:
                self._arm_ready = True
            if self._arm_ready and arm_combo and not self._prev_arm_combo:
                self._arm_start_ms = now_ms
            if self._arm_ready and arm_combo and self._prev_arm_combo and self._arm_start_ms > 0.0:
                if now_ms - self._arm_start_ms >= ARM_COMBO_DWELL_MS:
                    self._recording = True
                    self._arm_start_ms = 0.0
            if not arm_combo:
                self._arm_start_ms = 0.0
            self._prev_arm_combo = arm_combo

        # RECORDING: fist edge exits back to instrument_select and stops recording
        if start_state == "play" and self._recording:
            if hand_present and is_fist and not self._prev_is_fist:
                self._recording = False
                self._camera_state = "instrument select"

        self._prev_is_fist = is_fist

    def _map_fingers_to_instrument_idx(self, fcount: int) -> Optional[int]:
        # Map 1..N fingers to 0..N-1 instrument indices; others None
        if 1 <= fcount <= len(self._instruments):
            return fcount - 1
        return None

    def _current_instrument_label(self) -> str:
        if self._instrument_idx is None or self._instrument_idx < 0:
            return ""
        return self._instruments[self._instrument_idx]

    def _handle_pinch(self, pinch_px: Optional[float], *, arm_combo: bool) -> None:
        """Update note_on based on pinch with hysteresis, mirroring the original behavior.

        Only active in PLAY/RECORD, suppressed during arm_combo. Rising edge sets note_on,
        falling edge clears note_on.
        """
        if self._camera_state != "play":
            # In instrument_select, ensure note is off
            if self._note_on:
                self._note_on = False
            self._prev_pinch = False
            return
        if self._instrument_idx is None or self._instrument_idx < 0:
            # No instrument selected: do nothing
            self._note_on = False
            self._prev_pinch = False
            return
        if pinch_px is None:
            # No measurement; be conservative but don't toggle spuriously
            return
        on_th = PINCH_THRESH_PX
        off_th = PINCH_THRESH_PX + PINCH_HYST
        is_pinch = (pinch_px < (off_th if self._prev_pinch else on_th)) and (not arm_combo)

        if is_pinch and not self._prev_pinch:
            # Rising edge
            self._note_on = True
        elif (not is_pinch) and self._prev_pinch:
            # Falling edge
            self._note_on = False
        self._prev_pinch = is_pinch

    def _handle_key(self, key: int) -> None:
        if key == -1:
            return

        if key in (ord("q"), 27):
            LOGGER.info("Camera HUD exit requested by user")
            self._running.clear()
            return
        if key in (ord("p"), ord("P")):
            self._toggle_camera_state()
        elif key in (ord("r"), ord("R")):
            self._toggle_recording()
        elif key == ord(" "):
            self._toggle_note()
        elif key in (ord("i"), ord("I")):
            self._advance_instrument()
        elif key in (ord("m"), ord("M")):
            self._flip = not self._flip
            LOGGER.info("Mirror (flip) set to %s", self._flip)
        elif key in (ord("h"), ord("H")):
            self._handedness_invert = not self._handedness_invert
            LOGGER.info("Handedness invert set to %s", self._handedness_invert)
        elif key in (ord("t"), ord("T")):
            self._thumb_invert = not self._thumb_invert
            LOGGER.info("Thumb invert set to %s", self._thumb_invert)

    def _toggle_camera_state(self) -> None:
        with self._state_lock:
            self._camera_state = "play" if self._camera_state != "play" else "instrument select"
            LOGGER.info("Camera state toggled to %s", self._camera_state)

    def _toggle_recording(self) -> None:
        with self._state_lock:
            self._recording = not self._recording
            LOGGER.info("Recording toggled to %s", self._recording)

    def _toggle_note(self) -> None:
        with self._state_lock:
            self._note_on = not self._note_on

    def _advance_instrument(self) -> None:
        with self._state_lock:
            self._instrument_idx = (self._instrument_idx + 1) % len(self._instruments)
            LOGGER.info(
                "Instrument switched to %s", self._instruments[self._instrument_idx]
            )

    def _maybe_close_window(self) -> None:
        if not self._window_created:
            return
        try:
            visible = cv2.getWindowProperty(self.WINDOW_NAME, cv2.WND_PROP_VISIBLE)
        except Exception:
            visible = 0
        if visible < 1:
            LOGGER.info("Camera HUD window closed by user")
            self._running.clear()


# ---------------------------------------------------------------------- #
# Module-level helpers                                                   #
# ---------------------------------------------------------------------- #
_controller: Optional[CameraController] = None
_controller_lock = threading.Lock()
_settings: Optional[CameraSettings] = None


def configure_from_app_config(config: AppConfig) -> None:
    """Supply configuration from the loaded AppConfig."""
    instruments: List[str] = []
    if config.instrument_map:
        instruments = list(config.instrument_map.keys())
    else:
        instruments = ["lead"]

    camera_cfg = getattr(config, "camera", None)
    if camera_cfg is not None:
        settings = CameraSettings(
            index=camera_cfg.index,
            hud_enabled=camera_cfg.hud_enabled,
            flip=camera_cfg.flip,
            instruments=tuple(instruments),
        )
    else:
        settings = CameraSettings(instruments=tuple(instruments))

    global _settings
    _settings = settings
    LOGGER.debug("Camera settings configured: %s", settings)


def _ensure_controller() -> CameraController:
    global _controller
    with _controller_lock:
        if _controller is not None:
            return _controller

        settings = _settings
        if settings is None:
            defaults = load_default_config()
            configure_from_app_config(defaults)
            settings = _settings
        assert settings is not None
        _controller = CameraController(settings)
        return _controller


def get_camera_state() -> Dict[str, object]:
    """Return the latest camera state snapshot (lazy-starting the controller)."""
    controller = _ensure_controller()
    return controller.snapshot()


def set_debug_mode(enabled: bool) -> None:
    global _DEBUG_MODE
    _DEBUG_MODE = bool(enabled)


__all__ = ["get_camera_state", "configure_from_app_config", "CameraSettings", "set_debug_mode"]