# gesture_states_cam_fixed.py
# pip install opencv-python mediapipe==0.10.9 numpy
import time, math, json, os
import cv2, numpy as np
import mediapipe as mp

# ---------------- Config ----------------
IDLE_NAME = "Idle"
INSTRUMENT_MAP = {1:"Kick", 2:"Snare", 3:"HiHat", 4:"Tom", 5:IDLE_NAME}
PINCH_THRESH_PX = 40          # thumb–index "touch"
PINCH_HYST = 6
HUD_FONT = cv2.FONT_HERSHEY_SIMPLEX
SELECT_STABLE_MS = 400        # require finger-count to be stable this long before selection updates
SELECT_IGNORE_IDLE = True     # ignore Idle (5 fingers) as a candidate in BEGIN
SELECT_COMMIT_MS = 1000        # after this, candidate auto-commits to current_instr
ARM_COMBO_DWELL_MS = 250      # require thumb+middle+ring down to hold this long to arm
PINCH_HOLD_REPEAT_MS = 200    # repeat cadence while pinch held

# Ghost guidance overlay
SHOW_LIVE_RIG = True          # toggle drawing live hand skeleton
SHOW_GHOST = False            # toggle showing target ghost pose
DEBUG_HUD = False             # toggle extra debug text
GHOST_HIDE_PX = 45            # treat as "on top" threshold in pixels (looser match)
GHOST_HIDE_FRAMES = 2         # frames within threshold before we consider it matched (short)
GHOST_ALPHA = 0.50            # ghost overlay opacity (lower = more transparent)
GHOST_FILE = "ghost_pose.json"  # saved ghost pose (normalized coords)
GHOST_MATCH_ANCHORS = [0,5,9,13,17]  # wrist + MCPs for center/pose proximity
GHOST_SCALE_TOL_RATIO = 0.25   # allow ±25% hand scale vs ghost (prevents too far/too close from matching)

# If your thumb is counted "up" when it's actually folded (or vice versa), flip this:
THUMB_INVERT = True   # set True if thumb-up/down is inverted for you

# Mirror input before processing (fixes geometry/labels when camera feed is mirrored)
MIRROR_INPUT = True
# Mirror display for a selfie view (applied AFTER all overlays are drawn)
MIRROR_DISPLAY = False
# If your right/left is swapped by the camera/driver, flip handedness used for thumb logic
HANDEDNESS_INVERT = False

# ---------------- Helpers ----------------
def count_fingers(lm, handed):
    """
    Return number of extended fingers (thumb+4). Thumb uses x-axis test;
    flip rule with THUMB_INVERT if needed.
    """
    TIP = [4,8,12,16,20]; PIP=[3,6,10,14,18]
    arr = np.array([(p.x, p.y) for p in lm])
    fingers = 0

    # Thumb: compare tip.x vs pip.x; depends on handedness & camera orientation.
    # If your result is inverted, set THUMB_INVERT=True above.
    is_right = (handed == "Right")
    if HANDEDNESS_INVERT:
        is_right = not is_right
    if is_right:
        thumb_up = arr[TIP[0],0] > arr[PIP[0],0] + 0.02
    else:  # left
        thumb_up = arr[TIP[0],0] < arr[PIP[0],0] - 0.02
    if THUMB_INVERT:
        thumb_up = not thumb_up
    fingers += 1 if thumb_up else 0

    # Other four: tip above PIP (smaller y)
    for i in range(1,5):
        fingers += 1 if arr[TIP[i],1] < arr[PIP[i],1] - 0.02 else 0
    return fingers

def get_fingers_up(lm, handed):
    """
    Return a dict for each finger up/down:
    { 'thumb': bool, 'index': bool, 'middle': bool, 'ring': bool, 'pinky': bool }
    """
    TIP = [4,8,12,16,20]; PIP=[3,6,10,14,18]
    arr = np.array([(p.x, p.y) for p in lm])
    # thumb
    is_right = (handed == "Right")
    if HANDEDNESS_INVERT:
        is_right = not is_right
    if is_right:
        thumb_up = arr[TIP[0],0] > arr[PIP[0],0] + 0.02
    else:
        thumb_up = arr[TIP[0],0] < arr[PIP[0],0] - 0.02
    if THUMB_INVERT:
        thumb_up = not thumb_up
    # others use y
    index_up  = arr[TIP[1],1] < arr[PIP[1],1] - 0.02
    middle_up = arr[TIP[2],1] < arr[PIP[2],1] - 0.02
    ring_up   = arr[TIP[3],1] < arr[PIP[3],1] - 0.02
    pinky_up  = arr[TIP[4],1] < arr[PIP[4],1] - 0.02
    return {'thumb': thumb_up, 'index': index_up, 'middle': middle_up, 'ring': ring_up, 'pinky': pinky_up}

def dist_px(a, b, w, h):
    dx = (a.x - b.x) * w
    dy = (a.y - b.y) * h
    return math.hypot(dx, dy)

def mean_pose_error_px(live_landmarks, ghost_points_xy, w, h, indices=None):
    """
    Compute mean pixel error between live landmarks and ghost normalized (x,y) list.
    If indices is provided, use only those landmark indices.
    """
    if live_landmarks is None or ghost_points_xy is None:
        return None
    if indices is None:
        n = min(len(ghost_points_xy), len(live_landmarks))
        if n == 0:
            return None
        err_sum = 0.0
        for i in range(n):
            gx, gy = ghost_points_xy[i]
            lx, ly = live_landmarks[i].x, live_landmarks[i].y
            dx = (lx - gx) * w
            dy = (ly - gy) * h
            err_sum += math.hypot(dx, dy)
        return err_sum / n
    # subset mode
    n = 0
    if n == 0:
        err_sum = 0.0
        for i in indices:
            if i < len(ghost_points_xy) and i < len(live_landmarks):
                gx, gy = ghost_points_xy[i]
                lx, ly = live_landmarks[i].x, live_landmarks[i].y
                dx = (lx - gx) * w
                dy = (ly - gy) * h
                err_sum += math.hypot(dx, dy)
                n += 1
        if n == 0:
            return None
        return err_sum / n

def draw_ghost(display, ghost_points_xy, color, alpha):
    """
    Draw ghost hand connections using normalized (x,y) points.
    """
    if ghost_points_xy is None:
        return display
    overlay = display.copy()
    # Draw connections
    def px(pt): return (int(pt[0] * display.shape[1]), int(pt[1] * display.shape[0]))
    pts = [px(p) for p in ghost_points_xy]
    for conn in mp_hands.HAND_CONNECTIONS:
        i, j = conn
        if i < len(pts) and j < len(pts):
            cv2.line(overlay, pts[i], pts[j], color, 2, cv2.LINE_AA)
    # Also draw small joints
    for p in pts:
        cv2.circle(overlay, p, 2, color, -1, lineType=cv2.LINE_AA)
    return cv2.addWeighted(overlay, alpha, display, 1 - alpha, 0)
 
def palm_scale_from_landmarks(landmarks):
    """
    Simple hand scale proxy: distance between index_mcp (5) and pinky_mcp (17) in normalized coords.
    """
    if landmarks is None or len(landmarks) <= 17:
        return None
    ix, iy = landmarks[5].x, landmarks[5].y
    px, py = landmarks[17].x, landmarks[17].y
    return math.hypot(ix - px, iy - py)

def palm_scale_from_xy(points_xy):
    """
    Same as above but for saved ghost normalized points list.
    """
    if points_xy is None or len(points_xy) <= 17:
        return None
    ix, iy = points_xy[5]
    px, py = points_xy[17]
    return math.hypot(ix - px, iy - py)
def is_fist(fcount):  # no fingers up
    return fcount == 0

# ---------------- States ----------------
class CamState:
    INSTR_SELECT = "instrument select"  # BEGIN
    PLAY = "play"                       # test mode until armed
    RECORD_ON = "record on"

state = CamState.INSTR_SELECT         # <-- start here
recording = False
armed = False
current_instr = IDLE_NAME
prev_pinch = False
prev_arm_touch = False
candidate_instr = IDLE_NAME
_last_fc = None
_last_fc_change = 0.0
prev_is_fist = False
prev_state = state
pinch_hold_active = False
pinch_hold_last_ms = 0.0
arm_start_ms = 0.0
prev_arm_combo = False
arm_ready = False
ghost_pose = None            # list[(x,y)]
ghost_good_frames = 0
ghost_prev_good = False

def save_ghost_pose_to_file(path, pose):
    try:
        with open(path, "w") as f:
            json.dump(pose, f)
        print(f"Saved ghost pose to {path}")
    except Exception as e:
        print(f"Failed to save ghost pose: {e}")

def load_ghost_pose_from_file(path):
    try:
        if os.path.exists(path):
            with open(path, "r") as f:
                data = json.load(f)
            if isinstance(data, list) and len(data) >= 21 and isinstance(data[0], (list, tuple)) and len(data[0]) >= 2:
                print(f"Loaded ghost pose from {path}")
                return [(float(x), float(y)) for x, y in data]
    except Exception as e:
        print(f"Failed to load ghost pose: {e}")
    return None

# ---------------- MediaPipe ----------------
mp_hands, mp_draw = mp.solutions.hands, mp.solutions.drawing_utils
cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
cap.set(cv2.CAP_PROP_FPS, 30)

print("Flow: BEGIN (finger-count selects instrument) → FIST → PLAY (pinch=audition) → index+pinky=ARM → 3-2-1 → RECORDING → FIST=stop → BEGIN")
print("ESC/Q to quit. Tip: set THUMB_INVERT=True if thumb up/down is inverted.")

# Load persisted ghost pose if available; otherwise show ghost and auto-capture first seen hand
ghost_loaded = load_ghost_pose_from_file(GHOST_FILE)
if ghost_loaded:
    ghost_pose = ghost_loaded
SHOW_GHOST = True

with mp_hands.Hands(
    static_image_mode=False,
    max_num_hands=1,
    model_complexity=0,
    min_detection_confidence=0.5,
    min_tracking_confidence=0.5,
) as hands:
    while True:
        ok, frame = cap.read()
        if not ok:
            continue
        # Choose working frame (mirror input if configured)
        work = cv2.flip(frame, 1) if MIRROR_INPUT else frame
        h, w = work.shape[:2]

        # Process working frame for correct coordinates
        rgb = cv2.cvtColor(work, cv2.COLOR_BGR2RGB)
        res = hands.process(rgb)

        fcount, handed = 0, "?"
        pinch_px = 9999
        fingers_up = None

        if res.multi_hand_landmarks and res.multi_handedness:
            lm = res.multi_hand_landmarks[0]
            handed = res.multi_handedness[0].classification[0].label
            # draw later on the display frame (mirrored if enabled)
            fingers_up = get_fingers_up(lm.landmark, handed)
            fcount = int(fingers_up['thumb']) + int(fingers_up['index']) + int(fingers_up['middle']) + int(fingers_up['ring']) + int(fingers_up['pinky'])
            pinch_px = dist_px(lm.landmark[4], lm.landmark[8], w, h)  # thumb–index

        # ----- Keys -----
        key = cv2.waitKey(1) & 0xFF
        if key in (27, ord('q')):
            break
        # Runtime toggles to help calibrate quickly
        if key in (ord('m'), ord('M')):
            MIRROR_DISPLAY = not MIRROR_DISPLAY
        if key in (ord('i'), ord('I')):
            MIRROR_INPUT = not MIRROR_INPUT
        if key in (ord('h'), ord('H')):
            HANDEDNESS_INVERT = not HANDEDNESS_INVERT
        if key in (ord('t'), ord('T')):
            THUMB_INVERT = not THUMB_INVERT
        if key in (ord('l'), ord('L')):
            SHOW_LIVE_RIG = not SHOW_LIVE_RIG
        if key in (ord('g'), ord('G')):
            SHOW_GHOST = not SHOW_GHOST
        if key in (ord('d'), ord('D')):
            DEBUG_HUD = not DEBUG_HUD
        if key in (ord('c'), ord('C')):
            # Capture current pose as ghost (if available)
            if res.multi_hand_landmarks:
                ghost_pose = [(p.x, p.y) for p in res.multi_hand_landmarks[0].landmark]
                SHOW_GHOST = True
                ghost_good_frames = 0
                save_ghost_pose_to_file(GHOST_FILE, ghost_pose)
        if key in (ord('o'), ord('O')):
            # Reload saved ghost
            g = load_ghost_pose_from_file(GHOST_FILE)
            if g:
                ghost_pose = g
                SHOW_GHOST = True
                ghost_good_frames = 0
        if key in (ord('k'), ord('K')):
            # Clear ghost
            ghost_pose = None
            SHOW_GHOST = False

        # ----- FSM -----
        if state == CamState.INSTR_SELECT:
            # Debounce finger-count: update candidate only after dwell time
            now = time.time()
            if fcount != _last_fc:
                _last_fc = fcount
                _last_fc_change = now
            stable = (now - _last_fc_change) * 1000.0 >= SELECT_STABLE_MS
            if stable:
                cand = INSTRUMENT_MAP.get(_last_fc, IDLE_NAME)
                if SELECT_IGNORE_IDLE and cand == IDLE_NAME:
                    pass
                else:
                    candidate_instr = cand
                # Auto-commit to current after a higher confidence dwell
                if (now - _last_fc_change) * 1000.0 >= SELECT_COMMIT_MS and cand != current_instr and cand != IDLE_NAME:
                    current_instr = cand

            # Ignore pinch here—ONLY fist moves to PLAY
            is_f = is_fist(fcount)
            if res.multi_hand_landmarks and is_f and not prev_is_fist:
                # Commit candidate when entering PLAY (fall back to current if None)
                if candidate_instr != IDLE_NAME:
                    current_instr = candidate_instr
                state = CamState.PLAY
                prev_pinch = False  # reset to avoid immediate triggers
                # Inhibit arming until combo goes false once after entering PLAY
                arm_ready = False
                prev_arm_combo = True
                arm_start_ms = 0.0
                pinch_hold_active = False
                pinch_hold_last_ms = 0.0
            prev_is_fist = is_f

        elif state == CamState.PLAY and not recording:
            # Audition only when an instrument is actually selected (not "None")
            on_th, off_th = PINCH_THRESH_PX, PINCH_THRESH_PX + PINCH_HYST
            is_pinch = pinch_px < (off_th if prev_pinch else on_th)
            # Arm combo: thumb + middle + ring all down (mutual exclusion: suppress pinch while combo holds)
            arm_combo = False
            if fingers_up is not None:
                arm_combo = (not fingers_up['thumb']) and (not fingers_up['middle']) and (not fingers_up['ring'])
            now_ms = time.time() * 1000.0
            now_ms = time.time() * 1000.0
            if current_instr != IDLE_NAME and not arm_combo:
                if is_pinch and not prev_pinch:
                    pinch_hold_active = True
                    pinch_hold_last_ms = now_ms
                    print(f"[TEST_DOWN] {current_instr}")
                    # TODO: audition note-on
                elif is_pinch and pinch_hold_active:
                    if now_ms - pinch_hold_last_ms >= PINCH_HOLD_REPEAT_MS:
                        pinch_hold_last_ms = now_ms
                        print(f"[TEST_HOLD] {current_instr}")
                        # TODO: sustain/aftertouch or retrigger audition
                elif (not is_pinch) and pinch_hold_active:
                    pinch_hold_active = False
                    print(f"[TEST_UP] {current_instr}")
                    # TODO: audition note-off
            prev_pinch = is_pinch

            # Allow exit back to INSTR_SELECT with a fist (edge)
            is_f = is_fist(fcount)
            if is_f and not prev_is_fist:
                state = CamState.INSTR_SELECT
            prev_is_fist = is_f

            # ARM recording when thumb+middle+ring are down for a dwell period (edge + inhibit after fist)
            if fingers_up is not None:
                # arm_ready becomes True only after we observe combo false at least once
                if not arm_ready and not arm_combo:
                    arm_ready = True
                # start dwell only on combo rising edge and when arm_ready
                if arm_ready and arm_combo and not prev_arm_combo:
                    arm_start_ms = now_ms
                # complete dwell
                if arm_ready and arm_combo and prev_arm_combo and arm_start_ms > 0.0:
                    if now_ms - arm_start_ms >= ARM_COMBO_DWELL_MS:
                        armed = True
                        state = CamState.RECORD_ON
                        recording = True
                        arm_start_ms = 0.0
                # reset when combo false
                if not arm_combo:
                    arm_start_ms = 0.0
                prev_arm_combo = arm_combo

        if state == CamState.RECORD_ON:
            # Live recording: pinch to produce; fist to stop
            on_th, off_th = PINCH_THRESH_PX, PINCH_THRESH_PX + PINCH_HYST
            is_pinch = pinch_px < (off_th if prev_pinch else on_th)
            now_ms = time.time() * 1000.0
            if current_instr != IDLE_NAME:
                if is_pinch and not prev_pinch:
                    pinch_hold_active = True
                    pinch_hold_last_ms = now_ms
                    print(f"[REC_DOWN] {current_instr}")
                    # TODO: trigger note-on
                elif is_pinch and pinch_hold_active:
                    if now_ms - pinch_hold_last_ms >= PINCH_HOLD_REPEAT_MS:
                        pinch_hold_last_ms = now_ms
                        print(f"[REC_HOLD] {current_instr}")
                        # TODO: sustain/aftertouch or retrigger
                elif (not is_pinch) and pinch_hold_active:
                    pinch_hold_active = False
                    print(f"[REC_UP] {current_instr}")
                    # TODO: trigger note-off
            prev_pinch = is_pinch

            is_f = is_fist(fcount)
            if is_f and not prev_is_fist:
                print(">>> RECORDING OFF → BEGIN")
                recording = False
                armed = False
                state = CamState.INSTR_SELECT
            prev_is_fist = is_f

        # Print camera state changes
        if state != prev_state:
            print(f"camera state: {state}")
            prev_state = state

        # ----- HUD & Overlays -----
        cam_state_text = CamState.PLAY if state != CamState.INSTR_SELECT else CamState.INSTR_SELECT
        rec_text = "on" if recording else "off"

        # Draw on working frame; mirror to display at the end
        display = work.copy()

        # Show effective handedness for debugging orientation
        eff_right = None
        if res.multi_hand_landmarks and res.multi_handedness:
            eff_right = (res.multi_handedness[0].classification[0].label == "Right")
            if HANDEDNESS_INVERT:
                eff_right = not eff_right
        handed_text = f"hand: {'Right' if eff_right else 'Left' if eff_right is not None else '?'}"

        # Final minimal HUD (3 lines): state, instrument, recording
        base_y = 26
        step = 26
        y = base_y
        # Always show 'play' while in PLAY or RECORD_ON
        hud_state_label = CamState.PLAY if state != CamState.INSTR_SELECT else CamState.INSTR_SELECT
        cv2.putText(display, f"state: {hud_state_label}", (10, y), HUD_FONT, 0.8, (255,255,255), 2)
        y += step
        cv2.putText(display, f"instrument: {current_instr}", (10, y), HUD_FONT, 0.8, (255,255,255), 2)
        y += step
        cv2.putText(display, f"recording: {'on' if recording else 'off'}", (10, y),
                    HUD_FONT, 0.8, (0,0,255) if recording else (255,255,255), 2)

        # Footer: finger map + context options (commented out for now)
        # y_bottom = display.shape[0] - 10
        # map_text = "finger map: " + " ".join([f"{k}={v}" for k,v in INSTRUMENT_MAP.items()])
        # if state == CamState.INSTR_SELECT:
        #     opts_text = "options: fist to play"
        # elif state == CamState.PLAY:
        #     opts_text = "options: pinch trigger | record: thumb+middle+ring down | fist to select"
        # else:
        #     opts_text = "options: pinch trigger | fist to select"
        # cv2.putText(display, opts_text, (10, y_bottom-2), HUD_FONT, 0.55, (255,255,255), 1)
        # cv2.putText(display, map_text, (10, y_bottom-2-22), HUD_FONT, 0.55, (255,255,255), 1)

        # No countdown overlay (removed)

        # Draw live rig (optional)
        live_lm = None
        if res.multi_hand_landmarks:
            live_lm = res.multi_hand_landmarks[0]
            if SHOW_LIVE_RIG:
                mp_draw.draw_landmarks(display, live_lm, mp_hands.HAND_CONNECTIONS)

        # Draw ghost (optional), with error-based color and auto-hide
        if SHOW_GHOST:
            # If no ghost saved yet, auto-capture first seen pose
            if ghost_pose is None and live_lm is not None:
                ghost_pose = [(p.x, p.y) for p in live_lm.landmark]
                save_ghost_pose_to_file(GHOST_FILE, ghost_pose)
            # Draw ghost if we have one
            if ghost_pose is not None:
                err = mean_pose_error_px(live_lm.landmark if live_lm is not None else None,
                                         ghost_pose, display.shape[1], display.shape[0],
                                         GHOST_MATCH_ANCHORS)
                # Also enforce scale window so users aren't too far/too close
                live_scale = palm_scale_from_landmarks(live_lm.landmark) if live_lm is not None else None
                ghost_scale = palm_scale_from_xy(ghost_pose)
                scale_ok = None
                if live_scale is not None and ghost_scale is not None and ghost_scale > 0.0:
                    low = ghost_scale * (1.0 - GHOST_SCALE_TOL_RATIO)
                    high = ghost_scale * (1.0 + GHOST_SCALE_TOL_RATIO)
                    scale_ok = (low <= live_scale <= high)
                if err is not None:
                    good_now = (err <= GHOST_HIDE_PX) and (scale_ok is True)
                    # color: red if not matching, green if matching
                    color = (0, 0, 255) if not good_now else (0, 255, 0)
                    # keep ghost visible when not matching; hide (alpha=0) when matching
                    alpha = 0.0 if good_now else GHOST_ALPHA
                    if alpha > 0.0:
                        display = draw_ghost(display, ghost_pose, color, alpha)
                    ghost_prev_good = good_now
                else:
                    # No live hand; show red ghost to guide placement
                    display = draw_ghost(display, ghost_pose, (0, 0, 255), GHOST_ALPHA)

        # Apply display mirror last so landmarks/HUD match
        if MIRROR_DISPLAY:
            display = cv2.flip(display, 1)

        cv2.imshow("Gesture HUD (camera-only)", display)
