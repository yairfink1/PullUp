"""
cand6_hybrid.py

Candidate 6: Hybrid Detector.
Combines:
  1. The battle-tested physical orientation mount, settling, and dismount guards
     from the baseline (mount lock in [-1300, -700] mG, dead-hang settling < 70 mG,
     post-settle warmup exclusion window, and dismount departure latch).
  2. The high-generalization causal 2nd-order IIR Butterworth band-pass peak detector
     (from Candidate 3) executing strictly within the validated hang window.
"""

from typing import Any, Dict, List, Optional
import numpy as np
import pandas as pd
from scipy.signal import butter, lfilter

from eval_pipeline import precompute_envelopes


def detect(
    df: pd.DataFrame,
    f_low: float = 0.35,
    f_high: float = 1.7,
    order: int = 2,
    prominence: float = 50.0,
    min_spacing: int = 70,
    warmup_after_settle: int = 60,
    hang_streak_req: int = 35,
    mount_exit_env: int = 70,
    mount_max_wait: int = 130,
    x_release_threshold: int = -300,
    x_latch_streak_len: int = 35,
    cancel_prior_window: int = 25,
) -> List[int]:
    """
    Causal online hybrid detector: Baseline mount/dismount guards + band-pass peak counting.
    """
    x_accel = df["x"].values if "x" in df.columns else None
    y_accel = df["y"].values if "y" in df.columns else None
    z_accel = df["z"].values if "z" in df.columns else None

    sq_sums = df["x"].values.astype(np.int64)**2 + df["y"].values.astype(np.int64)**2 + df["z"].values.astype(np.int64)**2
    mags = np.sqrt(sq_sums).astype(np.int32)
    diffs = np.abs(np.diff(mags, prepend=mags[0]))
    envelopes, _ = precompute_envelopes(mags, diffs)
    n_samples = len(envelopes)

    # Design causal IIR bandpass filter (fs = 100 Hz)
    nyquist = 50.0
    low = f_low / nyquist
    high = f_high / nyquist
    b, a = butter(order, [low, high], btype="bandpass")
    filtered = lfilter(b, a, envelopes.astype(np.float64))

    # Mount / dismount tracking
    hang_streak = 0
    has_hung = False
    hang_start = 0
    settle_idx: Optional[int] = None
    x_streak = 0
    set_locked = False
    state = -1  # -1 = MOUNT_SETTLING, 0 = ACTIVE_HANG

    reps: List[int] = []
    last_rep_idx = -min_spacing

    peak_val = -1e9
    peak_idx = 0
    in_descent = False

    for i in range(n_samples):
        if set_locked:
            break

        cur_x = int(x_accel[i]) if x_accel is not None else -1000
        cur_env = int(envelopes[i])
        val = filtered[i]

        # 1. Mount confirmation: X in [-1300, -700] mG for >= 35 samples
        if not has_hung:
            if (-1300 <= cur_x <= -700) or (-1200 <= cur_x <= -750):
                hang_streak += 1
                if hang_streak >= hang_streak_req:
                    has_hung = True
                    hang_start = i
            else:
                hang_streak = 0
        else:
            if state == -1 and cur_x > x_release_threshold:
                has_hung = False
                hang_streak = 0

        # 2. Dismount detection
        if has_hung:
            if cur_x > x_release_threshold:
                x_streak += 1
            else:
                x_streak = 0

            if x_streak >= x_latch_streak_len:
                set_locked = True
                departure_start = i - x_latch_streak_len
                # Rollback if last rep occurred right as departing
                if reps and (departure_start - reps[-1]) < cancel_prior_window:
                    reps.pop()
                break

        x_in_hang = (cur_x <= x_release_threshold)

        # 3. Mount settling state
        if state == -1:
            if has_hung:
                in_hang_time = i - hang_start
                settled_below = (cur_env < mount_exit_env)
                timed_out = (in_hang_time >= mount_max_wait)
                if (settled_below or timed_out) and x_in_hang:
                    state = 0  # ACTIVE_HANG
                    settle_idx = i
                    peak_val = val
                    peak_idx = i
                    in_descent = False
            continue

        # 4. Post-settling warmup guard: ignore first warmup_after_settle samples
        if settle_idx is not None and (i - settle_idx) < warmup_after_settle:
            peak_val = val
            peak_idx = i
            continue

        # 5. Causal peak detection with prominence hysteresis inside hang
        if x_in_hang:
            if not in_descent:
                if val > peak_val:
                    peak_val = val
                    peak_idx = i
                elif val < peak_val - 1.0:
                    in_descent = True
            else:
                if val > peak_val:
                    peak_val = val
                    peak_idx = i
                elif val <= (peak_val - prominence):
                    # Prominence drop confirmed
                    if (peak_idx - last_rep_idx) >= min_spacing and peak_val > 0:
                        reps.append(peak_idx)
                        last_rep_idx = peak_idx
                    peak_val = val
                    in_descent = False
        else:
            # Not in hang -> reset peak search
            peak_val = val
            in_descent = False

    return reps
