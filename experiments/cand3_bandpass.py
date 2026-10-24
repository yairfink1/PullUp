"""
cand3_bandpass.py

Candidate 3: Band-Pass Peak Counting.
Features:
  - Band-pass filtering across the natural human pull-up cadence (~0.4 - 1.5 Hz).
  - Causal IIR filter (scipy.signal.lfilter with Butterworth coefficients), portable
    to Monkey C as cascaded biquad (Direct Form II) filter sections running in O(1).
  - Gated by physical forearm vertical hang (mount sustained streak, dismount latch).
  - Online causal peak detection with minimum prominence hysteresis and minimum spacing (debounce).
"""

from typing import List, Optional
import numpy as np
import pandas as pd
from scipy.signal import butter, lfilter

from experiments.common import HangTracker, compute_envelope


def detect(
    df: pd.DataFrame,
    f_low: float = 0.4,
    f_high: float = 1.5,
    order: int = 2,
    prominence: float = 55.0,
    min_spacing: int = 70,
    signal_source: str = "envelope",
) -> List[int]:
    """
    Causal, online pull-up repetition detector using band-pass filtering and prominence peak counting.
    Returns list of confirmed repetition sample indices.
    """
    x = df["x"].values
    y = df["y"].values
    z = df["z"].values

    if "magnitude" in df.columns:
        mags = df["magnitude"].values.astype(np.int32)
    else:
        mags = np.sqrt(x.astype(np.float64)**2 + y.astype(np.float64)**2 + z.astype(np.float64)**2).astype(np.int32)

    diffs = np.abs(np.diff(mags, prepend=mags[0]))

    if signal_source == "envelope":
        raw_sig = compute_envelope(diffs, window_size=37).astype(np.float64)
    else:
        raw_sig = mags.astype(np.float64)

    # Design causal IIR bandpass filter (fs = 100 Hz)
    nyquist = 50.0
    low = f_low / nyquist
    high = f_high / nyquist
    b, a = butter(order, [low, high], btype="bandpass")

    # Strictly causal filtering via lfilter (O(1) Direct Form II)
    filtered = lfilter(b, a, raw_sig)
    n = len(filtered)

    hang = HangTracker(
        hang_min_x=-1300,
        hang_max_x=-700,
        hang_streak_req=35,
        x_release_threshold=-300,
        x_latch_streak_len=35,
    )

    reps: List[int] = []
    last_rep_idx = -min_spacing

    # Online peak tracking state
    peak_val = -1e9
    peak_idx = 0
    in_descent = False

    for i in range(n):
        cur_x = int(x[i])
        val = filtered[i]

        has_hung, in_hang, set_locked = hang.update(i, cur_x)
        if set_locked:
            break

        if not has_hung:
            continue

        if not in_descent:
            if val > peak_val:
                peak_val = val
                peak_idx = i
            elif val < peak_val - 1.0:
                in_descent = True
        else:
            if val > peak_val:
                # Upward reversal before reaching prominence -> update higher peak
                peak_val = val
                peak_idx = i
            elif val <= (peak_val - prominence):
                # Valley reached: prominence condition satisfied
                if in_hang and (peak_idx - last_rep_idx) >= min_spacing and peak_val > 0:
                    reps.append(peak_idx)
                    last_rep_idx = peak_idx
                peak_val = val
                in_descent = False

    return reps


if __name__ == "__main__":
    from experiments.common import load_train_test, calculate_metrics, format_metrics
    train, test = load_train_test()
    m_train = calculate_metrics(train, detect)
    print(format_metrics("TRAIN (default)", m_train))
