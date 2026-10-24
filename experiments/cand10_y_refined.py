"""
cand10_y_refined.py

Candidate 10: Refined Standalone Y-Axis Wave Detector.
Suggestion 2 implementation for Round 4.

Key Enhancements over Candidate 7:
  1. Full Baseline Mount Settling & Guard:
     - Waits for dead-hang envelope settling (< mount_exit_env = 70 mG) or 130 samples ceiling.
     - Pre-rep-1 shockwave re-entry guard (cur_env >= 355 mG returns to settling).
  2. Directional Excursion State Machine:
     - Measures wrist lateral tilt excursion (peak-to-trough range).
     - Normalized repetition wave: y_wave = sign * (y_fast - y_slow).
     - Running amplitude estimation with decay toward amp_floor during pauses.
  3. Multi-Modal Confirmation & Safety Gates:
     - Confirms wave with envelope bump (max_env_in_wave >= min_env).
     - Strict wave duration check (wave_dur >= min_wave_dur).
     - Debounce spacing between consecutive repetition peaks.
  4. Dismount Departure Latch & Tail Purge:
     - Discards dismount arm-drop false triggers via departure latch and tail purge.
  5. 100% O(1) causal circular buffer arithmetic, fully portable to Garmin Monkey C.
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from config import (
    WINDOW_SIZE,
    DEBOUNCE_MIN,
    DEBOUNCE_MAX,
    X_RELEASE_THRESHOLD,
    X_LATCH_STREAK_LEN,
    CANCEL_PRIOR_WINDOW,
    HANG_STREAK_REQ,
    MOUNT_EXIT_ENV,
)
from eval_pipeline import precompute_envelopes
from experiments.common import compute_smoothed_axis, compute_envelope, HangTracker


def detect(
    df: pd.DataFrame,
    # Y-axis waveform parameters
    win_fast: int = 25,
    win_slow: int = 250,
    a_arm: float = 0.60,
    b_reset: float = 0.50,
    debounce: int = 75,
    min_env: int = 50,
    amp_floor: int = 120,
    amp_cap: int = 500,
    amp_decay_rate: float = 0.003,
    min_wave_dur: int = 20,
    # Mount and dismount parameters
    mount_exit_env: int = MOUNT_EXIT_ENV,
    mount_max_wait: int = 130,
    x_release_threshold: int = X_RELEASE_THRESHOLD,
    x_latch_streak_len: int = X_LATCH_STREAK_LEN,
    cancel_prior_window: int = CANCEL_PRIOR_WINDOW,
    hang_streak_req: int = HANG_STREAK_REQ,
) -> List[int]:
    """
    Refined standalone pull-up repetition detector using Y-axis tilt dynamics
    fused with baseline physical guards.
    """
    x = df["x"].values
    y = df["y"].values
    z = df["z"].values if "z" in df.columns else np.zeros_like(y)
    n = len(y)

    sq_sums = df["x"].values.astype(np.int64)**2 + df["y"].values.astype(np.int64)**2 + df["z"].values.astype(np.int64)**2
    mags = np.sqrt(sq_sums).astype(np.int32)
    diffs = np.abs(np.diff(mags, prepend=mags[0]))
    envs = compute_envelope(diffs, window_size=37)

    yf = compute_smoothed_axis(y, window_size=win_fast)
    ys = compute_smoothed_axis(y, window_size=win_slow)

    hang = HangTracker(
        hang_min_x=-1300,
        hang_max_x=-700,
        hang_streak_req=hang_streak_req,
        x_release_threshold=x_release_threshold,
        x_latch_streak_len=x_latch_streak_len,
    )

    reps: List[int] = []
    hang_samples = 0
    hang_y_sum = 0
    sign = 1.0

    state = -1  # -1 = MOUNT_SETTLING & CLASSIFYING, 0 = VALLEY_SEARCH, 1 = PEAK_SEARCH
    valley_val = 0.0
    valley_idx = 0
    peak_val = 0.0
    peak_idx = 0
    wave_start_idx = 0
    amp_est = 250.0
    last_rep_idx = -debounce
    max_env_in_wave = 0

    for i in range(n):
        cur_x = int(x[i])
        cur_env = int(envs[i])

        has_hung, in_hang, set_locked = hang.update(i, cur_x)
        if set_locked:
            departure_start = i - hang.x_latch_streak_len
            if reps and (departure_start - reps[-1]) < cancel_prior_window:
                reps.pop()
            break

        if not has_hung:
            continue

        # Classify exercise (Pull-Up vs Chin-Up)
        if hang_samples < 50:
            hang_samples += 1
            hang_y_sum += int(y[i])
            if hang_samples == 50:
                mean_y = hang_y_sum / 50.0
                sign = 1.0 if mean_y > 20 else -1.0

        # Pre-rep-1 shockwave re-entry guard
        if state != -1 and len(reps) == 0 and cur_env >= 355:
            state = -1

        # State -1: Mount Settling
        if state == -1:
            in_hang_time = i - hang.hang_start_idx
            settled = (cur_env < mount_exit_env) or (in_hang_time >= mount_max_wait)
            if in_hang_time >= 50 and settled and in_hang:
                state = 0
                y_wave = sign * (float(yf[i]) - float(ys[i]))
                valley_val = y_wave
                valley_idx = i
                peak_val = y_wave
                peak_idx = i
                wave_start_idx = i
                max_env_in_wave = cur_env
            continue

        y_wave = sign * (float(yf[i]) - float(ys[i]))
        amp_est += amp_decay_rate * (amp_floor - amp_est)
        arm_th = max(float(amp_floor) * a_arm, min(float(amp_cap) * a_arm, a_arm * amp_est))
        reset_th = max(float(amp_floor) * b_reset, min(float(amp_cap) * b_reset, b_reset * amp_est))

        if cur_env > max_env_in_wave:
            max_env_in_wave = cur_env

        # State 0: In valley / ascending, looking for crest
        if state == 0:
            if y_wave < valley_val:
                valley_val = y_wave
                valley_idx = i
                max_env_in_wave = cur_env
            elif (y_wave - valley_val) >= arm_th and in_hang:
                state = 1
                wave_start_idx = valley_idx
                peak_val = y_wave
                peak_idx = i

        # State 1: Inside crest, tracking peak and waiting for valley drop
        elif state == 1:
            if y_wave > peak_val:
                peak_val = y_wave
                peak_idx = i

            drop = peak_val - y_wave
            wave_dur = i - wave_start_idx

            if drop >= reset_th:
                if (
                    wave_dur >= min_wave_dur
                    and (peak_idx - last_rep_idx) >= debounce
                    and max_env_in_wave >= min_env
                ):
                    reps.append(peak_idx)
                    last_rep_idx = peak_idx
                    wave_amp = peak_val - valley_val
                    amp_est = 0.30 * wave_amp + 0.70 * amp_est

                valley_val = y_wave
                valley_idx = i
                max_env_in_wave = cur_env
                state = 0

    # End-of-Session Guard
    if not hang.set_locked and x is not None:
        tail_start = max(0, n - 100)
        dep_indices = np.where(x[tail_start:] > x_release_threshold)[0]
        if len(dep_indices) > 0:
            first_dep_sample = tail_start + dep_indices[0]
            while reps and reps[-1] >= first_dep_sample:
                reps.pop()
        elif x[-1] > x_release_threshold:
            while reps and (n - reps[-1]) <= 100:
                reps.pop()

    return reps
