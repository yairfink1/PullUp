"""
cand4_smoothed_y.py

Candidate 4: Smoothed Y-Axis Forearm-Tilt Wave Detector.
Inspired by the Garmin PushUp detector architecture (PushUp/detect_pushups.py).

Biomechanics:
  - In pull-ups (pronated grip) and chin-ups (supinated grip), the forearm tilts
    along the sagittal plane as the body ascends and descends.
  - Pull-ups produce negative dips in lateral Y-tilt; Chin-ups produce positive peaks.
  - An online classifier examines the first 50 samples (0.50s) in hang:
      if mean hang Y > +20 mG -> Chin-Up (sign = +1)
      else -> Pull-Up (sign = -1)
  - Detrending via slow running moving average (win_slow = 250-350 samples) extracts
    the periodic wave:
      y_wave = sign * (y_smooth - y_baseline)
  - Counting is executed via hysteresis on y_wave (rep_threshold and reset_threshold)
    gated by physical bar hang and debounce spacing.
"""

from typing import List, Optional
import numpy as np
import pandas as pd

from experiments.common import HangTracker


def detect(
    df: pd.DataFrame,
    win_fast: int = 25,
    win_slow: int = 250,
    rep_threshold: int = 100,
    reset_threshold: int = 40,
    debounce: int = 65,
    min_wave_dur: int = 20,
) -> List[int]:
    """
    Causal, online pull-up repetition detector using smoothed Y-axis tilt dynamics.
    Returns list of confirmed repetition sample indices.
    """
    x = df["x"].values
    y = df["y"].values
    n = len(y)

    # Causal O(1) circular buffers for fast smoothing and slow baseline tracking
    buf_f = [0] * win_fast
    buf_s = [0] * win_slow
    sum_f = 0
    sum_s = 0
    idx_f = 0
    idx_s = 0

    hang = HangTracker(
        hang_min_x=-1300,
        hang_max_x=-700,
        hang_streak_req=35,
        x_release_threshold=-300,
        x_latch_streak_len=35,
    )

    hang_samples = 0
    hang_y_sum = 0
    sign = 1.0  # +1 for chin-up, -1 for pull-up

    state = -1  # -1 = MOUNT_SETTLING & CLASSIFYING, 0 = READY_TO_ARM, 1 = ARMED
    reps: List[int] = []
    samples_since_last = debounce
    peak_val = 0
    peak_idx = 0
    wave_start = 0

    for i in range(n):
        cur_x = int(x[i])
        cur_y = int(y[i])

        # O(1) fast smoothed Y update
        sum_f += cur_y - buf_f[idx_f]
        buf_f[idx_f] = cur_y
        idx_f = (idx_f + 1) % win_fast
        count_f = min(i + 1, win_fast)
        y_fast = sum_f / count_f

        # O(1) slow baseline Y update
        sum_s += cur_y - buf_s[idx_s]
        buf_s[idx_s] = cur_y
        idx_s = (idx_s + 1) % win_slow
        count_s = min(i + 1, win_slow)
        y_slow = sum_s / count_s

        has_hung, in_hang, set_locked = hang.update(i, cur_x)
        if set_locked:
            break

        if not has_hung:
            continue

        # Classify exercise (Pull-Up vs Chin-Up) during the initial 50 samples of hang
        if hang_samples < 50:
            hang_samples += 1
            hang_y_sum += cur_y
            if hang_samples == 50:
                mean_y = hang_y_sum / 50.0
                sign = 1.0 if mean_y > 20 else -1.0

        samples_since_last += 1
        y_wave = sign * (y_fast - y_slow)

        # State -1: Mount settling & exercise classification period
        if state == -1:
            if (i - hang.hang_start_idx) >= 50 and in_hang:
                state = 0
                samples_since_last = debounce
            continue

        # State 0: READY_TO_ARM
        if state == 0:
            if in_hang and samples_since_last >= debounce and y_wave >= rep_threshold:
                state = 1
                wave_start = i
                peak_val = y_wave
                peak_idx = i

        # State 1: ARMED (inside wave, tracking peak)
        elif state == 1:
            if y_wave > peak_val:
                peak_val = y_wave
                peak_idx = i

            # Confirm rep when wave drops back below reset_threshold
            if (y_wave <= reset_threshold or not in_hang) and (i - wave_start) >= min_wave_dur:
                reps.append(peak_idx)
                samples_since_last = 0
                state = 0

    # Confirm trailing completed rep if set ends while in a valid wave
    if state == 1 and not hang.set_locked:
        if (n - wave_start) >= min_wave_dur and peak_val >= rep_threshold:
            reps.append(peak_idx)

    return reps


if __name__ == "__main__":
    from experiments.common import load_train_test, calculate_metrics, format_metrics
    train, test = load_train_test()
    m_train = calculate_metrics(train, detect)
    print(format_metrics("TRAIN (default)", m_train))
