#!/usr/bin/env python3
"""
config.py

Single source of truth for all pull-up detection parameters used by the
offline analysis pipeline (eval_pipeline.py, generate_inspection_gallery.py,
detect_pullups.py, plot_dataset_errors.py).

Every parameter here mirrors the validated "Golden Parameters" documented in
CONTEXT.md so that all offline tools agree with each other and can be compared
against the live Garmin Monkey C implementation.
"""

# ---------------------------------------------------------------------------
# Signal Processing
# ---------------------------------------------------------------------------
# Circular-buffer moving-average window for the |diff| envelope (samples).
# Matches WINDOW_SIZE in PullUpDetector.mc.
WINDOW_SIZE: int = 37

# ---------------------------------------------------------------------------
# Primary Detection Thresholds
# ---------------------------------------------------------------------------
# Starting envelope level (mG) required to arm the detector for a new rep.
REP_THRESHOLD: int = 105

# Starting envelope level (mG) that must be reached again after a peak
# before a rep candidate can be confirmed (valley clearance).
RESET_THRESHOLD: int = 60

# ---------------------------------------------------------------------------
# Adaptive Threshold Floors (kick in after rep >= 4)
# ---------------------------------------------------------------------------
# Dynamic rep threshold floor bounds [ADAPTIVE_REP_FLOOR_MIN, ADAPTIVE_REP_FLOOR_MAX].
# Tracks 60% of exponential peak average, scaling from 95 down to 80 mG in fatigue.
ADAPTIVE_REP_FLOOR: int = 95
ADAPTIVE_REP_FLOOR_MIN: int = 80
ADAPTIVE_REP_FLOOR_MAX: int = 95

# Dynamic reset threshold floor bounds [ADAPTIVE_RESET_FLOOR_MIN, ADAPTIVE_RESET_FLOOR_MAX].
# Tracks 55% of the dynamic rep floor, scaling from 55 down to 45 mG in fatigue.
ADAPTIVE_RESET_FLOOR: int = 55
ADAPTIVE_RESET_FLOOR_MIN: int = 45
ADAPTIVE_RESET_FLOOR_MAX: int = 55

# ---------------------------------------------------------------------------
# Timing Parameters (all in samples @ 100 Hz)
# ---------------------------------------------------------------------------
# Base cadence-adaptive debounce floor (samples).  For rep >= 2 this grows
# to min(DEBOUNCE_MAX, max(DEBOUNCE_MIN, int(0.55 * dt_prev))).
# Set to 95 samples (0.95 s) to align with human physical minimum cadence
# and eliminate 0.88s - 0.90s body drop rebound false triggers.
DEBOUNCE_MIN: int = 95          # 0.95 s

# Maximum ceiling on cadence-adaptive debounce (samples @ 100 Hz).
# Prevents long rest-pauses on the bar (> 2.5s) from locking out subsequent reps.
DEBOUNCE_MAX: int = 130         # 1.30 s

# Unused by the current full state-machine, kept for legacy / grid-search.
WARMUP_SAMPLES: int = 200       # 2.0 s

# Maximum cooldown duration before a pending rep is force-confirmed if the
# envelope has fallen below REP_THRESHOLD.
COOLDOWN_TIMEOUT_SAMPLES: int = 100   # 1.0 s

# Minimum width of the movement wave (samples) for a candidate to be
# confirmed as a true rep (rejects narrow twitches < 0.45 s).
MIN_WAVE_DURATION: int = 45     # 0.45 s

# ---------------------------------------------------------------------------
# X-Axis Orientation Guard (bar-hang detection & dismount latch)
# ---------------------------------------------------------------------------
# X-axis value above which the forearm is considered "not in hang".
# While X > X_RELEASE_THRESHOLD (-300 mG) the detector cannot arm or confirm.
X_RELEASE_THRESHOLD: int = -300   # mG

# Number of consecutive samples with X > X_RELEASE_THRESHOLD needed to
# permanently latch set termination (0.35 s at 100 Hz).
X_LATCH_STREAK_LEN: int = 35

# Look-back window (samples) before departure start inside which a freshly
# confirmed rep may be retroactively cancelled if its wave was marginal.
CANCEL_PRIOR_WINDOW: int = 25   # 0.25 s

# Number of consecutive samples with X in [-1300, -700] mG required to
# declare "user is hanging on the bar" (0.35 s at 100 Hz).
HANG_STREAK_REQ: int = 35

# ---------------------------------------------------------------------------
# Convenience dict for functions that accept **kwargs / CONFIG dicts
# ---------------------------------------------------------------------------
DETECTOR_CONFIG: dict = {
    "window_size":               WINDOW_SIZE,
    "rep_threshold":             REP_THRESHOLD,
    "reset_threshold":           RESET_THRESHOLD,
    "adaptive_rep_floor":        ADAPTIVE_REP_FLOOR,
    "adaptive_reset_floor":      ADAPTIVE_RESET_FLOOR,
    "debounce_min":              DEBOUNCE_MIN,
    "debounce_max":              DEBOUNCE_MAX,
    "warmup_samples":            WARMUP_SAMPLES,
    "cooldown_timeout_samples":  COOLDOWN_TIMEOUT_SAMPLES,
    "min_wave_duration":         MIN_WAVE_DURATION,
    "x_release_threshold":       X_RELEASE_THRESHOLD,
    "x_latch_streak_len":        X_LATCH_STREAK_LEN,
    "cancel_prior_window":       CANCEL_PRIOR_WINDOW,
    "hang_streak_req":           HANG_STREAK_REQ,
}
