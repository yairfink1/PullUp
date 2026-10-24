"""
cand2_decay_fsm.py

Candidate 2: Current-style FSM with Capped & Decaying Adaptive Threshold.
Features:
  - Envelope: 37-sample causal moving average of |diff(magnitude)| via O(1) circular buffer.
  - Same robust hang gates (sustained vertical lock to mount, latch on dismount).
  - Capped & decaying adaptive threshold:
      threshold = clamp(k * EMA(recent peak heights), lo, hi)
      During pauses/gaps, threshold exponentially decays back towards lo:
        threshold += decay_rate * (lo - threshold)
  - Prevents threshold ratcheting during explosive early reps, eliminating the failure
    mode seen on test sets (e.g. 2026-10-17-09-44-55.fit) where fatigue reps were missed.
  - Cleansed of brittle hand-crafted rescue rules.
"""

from typing import List, Optional
import numpy as np
import pandas as pd

from experiments.common import HangTracker, compute_envelope


def detect(
    df: pd.DataFrame,
    lo: int = 95,
    hi: int = 125,
    k: float = 0.65,
    alpha: float = 0.30,
    decay_rate: float = 0.005,
    reset_ratio: float = 0.55,
    debounce_min: int = 75,
    debounce_max: int = 130,
    min_wave_duration: int = 35,
    cooldown_timeout: int = 100,
    mount_exit_env: int = 70,
    mount_max_wait: int = 130,
) -> List[int]:
    """
    Causal, online pull-up repetition detector using capped and decaying adaptive threshold FSM.
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

    state = -1  # -1 = MOUNT_SETTLING, 0 = READY_TO_ARM, 1 = ARMED, 2 = COOLDOWN
    debounce_cur = debounce_min
    samples_since_last = debounce_min
    prev_envelope = 0
    rep_indices: List[int] = []
    pending_rep: Optional[int] = None
    wave_start = 0

    cur_rep_threshold = float(lo)
    peak_ema = 140.0
    current_wave_peak = 0
    pending_wave_peak = 0
    wave_impulse = 0

    for i in range(n):
        cur_x = int(x[i])
        cur_env = int(envelopes[i])

        has_hung, in_hang, set_locked = hang.update(i, cur_x)
        if set_locked:
            break

        if not has_hung:
            continue

        samples_since_last += 1

        # Causal threshold decay towards lo during pauses / gaps
        cur_rep_threshold += decay_rate * (lo - cur_rep_threshold)
        cur_reset_threshold = max(45, min(70, int(reset_ratio * cur_rep_threshold)))

        # State -1: Mount Settling
        if state == -1:
            in_hang_time = i - hang.hang_start_idx
            if (cur_env < mount_exit_env or in_hang_time >= mount_max_wait) and in_hang:
                state = 0
                samples_since_last = debounce_cur
                current_wave_peak = 0
                wave_impulse = 0
            continue

        # Track wave envelope peak and impulse while active
        if cur_env > current_wave_peak:
            current_wave_peak = cur_env
        if cur_env > cur_reset_threshold:
            wave_impulse += (cur_env - cur_reset_threshold)

        # State 0: READY_TO_ARM
        if state == 0:
            if in_hang and samples_since_last >= debounce_cur and cur_env >= cur_rep_threshold:
                state = 1
                wave_start = i
                current_wave_peak = cur_env
                wave_impulse = max(0, cur_env - cur_reset_threshold)

        # State 1: ARMED (looking for falling edge)
        elif state == 1:
            if cur_env < prev_envelope and in_hang:
                pending_rep = i
                pending_wave_peak = current_wave_peak
                samples_since_last = 0
                state = 2  # Transition to COOLDOWN

        # State 2: COOLDOWN (wait for valley clearance or cooldown timeout)
        elif state == 2:
            is_valley = (cur_env <= cur_reset_threshold) or (
                pending_wave_peak > 0 and cur_env <= int(0.55 * pending_wave_peak)
            )
            settled = is_valley and cur_env < 160 and samples_since_last >= debounce_cur
            timeout = (cooldown_timeout > 0 and samples_since_last >= cooldown_timeout and cur_env < cur_rep_threshold)

            if pending_rep is not None:
                wave_dur = i - wave_start
                if (is_valley or timeout) and wave_dur >= min_wave_duration and in_hang:
                    # Confirmed repetition!
                    if rep_indices:
                        dt_prev = pending_rep - rep_indices[-1]
                        debounce_cur = min(debounce_max, max(debounce_min, int(0.55 * dt_prev)))
                    else:
                        debounce_cur = debounce_min

                    rep_indices.append(pending_rep)

                    # Update adaptive threshold with capping
                    peak_ema = alpha * pending_wave_peak + (1.0 - alpha) * peak_ema
                    cur_rep_threshold = max(float(lo), min(float(hi), k * peak_ema))
                    pending_rep = None

            if settled or timeout:
                state = 0
                samples_since_last = 0
                current_wave_peak = 0
                wave_impulse = 0

        prev_envelope = cur_env

    # Confirm trailing pending rep if set ends while in hang
    if pending_rep is not None and not hang.set_locked:
        if (n - wave_start) >= min_wave_duration and in_hang:
            rep_indices.append(pending_rep)

    return rep_indices


if __name__ == "__main__":
    from experiments.common import load_train_test, calculate_metrics, format_metrics
    train, test = load_train_test()
    m_train = calculate_metrics(train, detect)
    print(format_metrics("TRAIN (default)", m_train))
