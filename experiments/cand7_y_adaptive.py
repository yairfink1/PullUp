"""
cand7_y_adaptive.py

Candidate 7: Adaptive Smoothed Y-Axis Wave Detector.
Primary focus for production pull-up / chin-up repetition counting.

Biomechanics & Signal Architecture:
  1. Directional Wrist-Tilt Physics:
     - Pull-ups (pronated grip) tilt the lateral Y-axis downward (negative excursion).
     - Chin-ups (supinated grip) tilt the lateral Y-axis upward (positive excursion).
     - An online hang classifier measures the first 50 samples (0.50s) in bar hang:
         if mean hang Y > +20 mG -> Chin-Up (sign = +1)
         else -> Pull-Up (sign = -1)
  2. Causal Detrending:
     - 25-sample fast moving average (y_fast) tracks instantaneous forearm tilt.
     - 250-sample slow moving average (y_slow) tracks the static orientation baseline.
     - Detrended repetition wave: y_wave = sign * (y_fast - y_slow).
  3. Dynamic Peak-to-Trough Amplitude Tracking:
     - Does not assume a static amplitude across different users and grip widths.
     - Maintains a running estimate of wave amplitude: amp_est.
     - Arm threshold: a_arm * amp_est (clamped).
     - Reset threshold: b_reset * amp_est (clamped).
     - amp_est decays toward amp_floor during long pauses.
  4. Multi-Modal Confirmation & Guards:
     - Wave duration guard: wave duration >= min_wave_dur (rejects high-frequency spikes).
     - Envelope bump confirmation: maximum envelope during the wave >= min_env (confirms movement).
     - Debounce spacing between consecutive repetition peaks.
  5. 100% O(1) causal circular buffer arithmetic, fully portable to Garmin Monkey C.
"""

from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd

from experiments.common import HangTracker, compute_envelope, compute_smoothed_axis


def detect(
    df: pd.DataFrame,
    a_arm: float = 0.55,
    b_reset: float = 0.50,
    debounce: int = 75,
    min_env: int = 50,
    amp_floor: int = 120,
    amp_cap: int = 500,
    amp_decay_rate: float = 0.003,
    win_fast: int = 25,
    win_slow: int = 250,
    min_wave_dur: int = 20,
    use_transverse_fusion: bool = False,
) -> List[int]:
    """
    Causal, online pull-up repetition detector using adaptive Y-axis tilt dynamics.
    Returns list of confirmed repetition sample indices.
    """
    x = df["x"].values
    y = df["y"].values
    z = df["z"].values if "z" in df.columns else np.zeros_like(y)
    n = len(y)

    sq_sums = df["x"].values.astype(np.int64)**2 + df["y"].values.astype(np.int64)**2 + df["z"].values.astype(np.int64)**2
    mags = np.sqrt(sq_sums).astype(np.int32)
    diffs = np.abs(np.diff(mags, prepend=mags[0]))
    envs = compute_envelope(diffs, window_size=37)

    # Causal O(1) moving averages
    yf = compute_smoothed_axis(y, window_size=win_fast)
    ys = compute_smoothed_axis(y, window_size=win_slow)

    if use_transverse_fusion:
        zf = compute_smoothed_axis(z, window_size=win_fast)
        zs = compute_smoothed_axis(z, window_size=win_slow)

    hang = HangTracker(
        hang_min_x=-1300,
        hang_max_x=-700,
        hang_streak_req=35,
        x_release_threshold=-300,
        x_latch_streak_len=35,
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
            # Dismount departure rollback: purge trigger if it happened during departure
            departure_start = i - hang.x_latch_streak_len
            if reps and (departure_start - reps[-1]) < 35:
                reps.pop()
            break

        if not has_hung:
            continue

        # Classify exercise (Pull-Up vs Chin-Up) during the initial 50 samples of hang
        if hang_samples < 50:
            hang_samples += 1
            hang_y_sum += int(y[i])
            if hang_samples == 50:
                mean_y = hang_y_sum / 50.0
                sign = 1.0 if mean_y > 20 else -1.0

        # State -1: Wait for 50 samples of bar hang to establish initial baseline
        if state == -1:
            if (i - hang.hang_start_idx) >= 50 and in_hang:
                state = 0
                y_wave = sign * (float(yf[i]) - float(ys[i]))
                valley_val = y_wave
                valley_idx = i
                peak_val = y_wave
                peak_idx = i
                wave_start_idx = i
                max_env_in_wave = cur_env
            continue

        # Compute instantaneous repetition wave
        if use_transverse_fusion:
            dy = float(yf[i]) - float(ys[i])
            dz = float(zf[i]) - float(zs[i])
            # Project onto sign-oriented transverse displacement
            y_wave = sign * dy + 0.3 * np.abs(dz)
        else:
            y_wave = sign * (float(yf[i]) - float(ys[i]))

        # Decay amplitude estimate toward amp_floor during gaps
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

        # State 1: At or near peak, tracking apex and looking for valley descent
        elif state == 1:
            if y_wave > peak_val:
                peak_val = y_wave
                peak_idx = i

            drop = peak_val - y_wave
            wave_dur = i - wave_start_idx

            if drop >= reset_th:
                # Validate wave duration, debounce spacing, and envelope bump
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

    # End-of-Session Guard: If session ends and arms departed, discard triggers during departure
    if not hang.set_locked and x is not None:
        tail_start = max(0, n - 100)
        dep_indices = np.where(x[tail_start:] > -300)[0]
        if len(dep_indices) > 0:
            first_dep_sample = tail_start + dep_indices[0]
            while reps and reps[-1] >= first_dep_sample:
                reps.pop()
        elif x[-1] > -300:
            while reps and (n - reps[-1]) <= 100:
                reps.pop()

    return reps
