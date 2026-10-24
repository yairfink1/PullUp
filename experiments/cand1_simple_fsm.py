"""
cand1_simple_fsm.py

Candidate 1: Simplified Finite State Machine (FSM).
Features:
  - Envelope: 37-sample causal moving average of |diff(magnitude)| via O(1) circular buffer.
  - Hang gate: Forearm vertical lock X in [-1300, -700] mG for >= 35 samples (0.35s) to mount.
    Dismount latch when X > -300 mG for >= 35 samples locks set termination.
  - Fixed rep threshold + fixed reset threshold hysteresis + minimum debounce.
  - Strictly NO rescue rules, NO cadence/fatigue floor ratcheting, NO brittle timeouts.
"""

from typing import List, Optional
import numpy as np
import pandas as pd

from experiments.common import HangTracker, compute_envelope


def detect(
    df: pd.DataFrame,
    rep_threshold: int = 100,
    reset_threshold: int = 65,
    debounce: int = 75,
    min_wave_duration: int = 30,
    mount_exit_env: int = 70,
    mount_max_wait: int = 130,
) -> List[int]:
    """
    Causal, online pull-up repetition detector using simplified fixed-threshold FSM.
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
    envelopes = compute_envelope(diffs, window_size=37)

    n = len(envelopes)
    hang = HangTracker(
        hang_min_x=-1300,
        hang_max_x=-700,
        hang_streak_req=35,
        x_release_threshold=-300,
        x_latch_streak_len=35,
    )

    state = -1  # -1 = MOUNT_SETTLING, 0 = READY_TO_ARM, 1 = ARMED (in rep)
    samples_since_last = debounce
    rep_indices: List[int] = []
    peak_val = 0
    peak_idx = 0
    wave_start = 0

    for i in range(n):
        cur_x = int(x[i])
        cur_env = int(envelopes[i])

        has_hung, in_hang, set_locked = hang.update(i, cur_x)
        if set_locked:
            break

        if not has_hung:
            continue

        samples_since_last += 1

        # State -1: Wait for dead-hang envelope settling or timeout ceiling
        if state == -1:
            in_hang_time = i - hang.hang_start_idx
            if (cur_env < mount_exit_env or in_hang_time >= mount_max_wait) and in_hang:
                state = 0
                samples_since_last = debounce
            continue

        # State 0: Ready to arm on rising edge above fixed rep_threshold
        if state == 0:
            if in_hang and samples_since_last >= debounce and cur_env >= rep_threshold:
                state = 1
                wave_start = i
                peak_val = cur_env
                peak_idx = i

        # State 1: In wave, tracking peak and waiting for valley drop below reset_threshold
        elif state == 1:
            if cur_env > peak_val:
                peak_val = cur_env
                peak_idx = i

            # Confirm rep on valley clearance below reset_threshold
            if in_hang and cur_env <= reset_threshold:
                wave_dur = i - wave_start
                if wave_dur >= min_wave_duration:
                    rep_indices.append(peak_idx)
                    samples_since_last = 0
                state = 0

    # Confirm trailing completed rep if set ended / latched after a valid wave
    if state == 1 and not hang.set_locked:
        if (n - wave_start) >= min_wave_duration and peak_val >= rep_threshold:
            rep_indices.append(peak_idx)

    return rep_indices


if __name__ == "__main__":
    from experiments.common import load_train_test, calculate_metrics, format_metrics
    train, test = load_train_test()
    m_train = calculate_metrics(train, detect)
    print(format_metrics("TRAIN (default)", m_train))
