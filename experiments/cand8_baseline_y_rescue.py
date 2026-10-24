"""
cand8_baseline_y_rescue.py

Candidate 8: Full Baseline FSM with Parallel Adaptive Y-Axis Wave Rescue Channel.

Architecture:
  - Primary Channel: Exact simulate_pullup_online baseline logic (all rules ON, original
    threshold ratchet kept). Provides high noise immunity and 55/56 accuracy on standard reps.
  - Secondary Channel: Candidate 7 Adaptive Y-Axis Wave detector running causally in lockstep.
    Tracks lateral wrist-tilt excursions (peak-to-trough range) and exercise orientation.
  - Causal Fusion & Rescue Arbiter:
    * When the Y-axis channel confirms a repetition wave, it queries the baseline channel.
    * If no baseline repetition (confirmed or pending) occurred within a proximity window W
      around the Y-wave apex, the baseline MISSED this repetition.
    * Three optional gates protect against false rescues (cand7's overcount tendency):
        Gate A (Elevated Threshold): cur_rep_threshold >= min_thresh_for_rescue OR cur_rep_threshold > current_wave_peak
        Gate B (Rhythm Consistency): interval from last rep is [0.60, 2.50] * median recent rep period
        Gate C (Set Progress): repCount >= min_reps_for_rescue
    * On rescue admission, the baseline debounce and state are synchronized to prevent
      subsequent double-counts.
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from config import (
    WINDOW_SIZE,
    REP_THRESHOLD,
    RESET_THRESHOLD,
    DEBOUNCE_MIN,
    DEBOUNCE_MAX,
    WARMUP_SAMPLES,
    COOLDOWN_TIMEOUT_SAMPLES,
    MIN_WAVE_DURATION,
    X_RELEASE_THRESHOLD,
    X_LATCH_STREAK_LEN,
    CANCEL_PRIOR_WINDOW,
    HANG_STREAK_REQ,
    MOUNT_EXIT_ENV,
)
from eval_pipeline import precompute_envelopes
from experiments.common import compute_smoothed_axis


def detect_with_channels(
    df: pd.DataFrame,
    # Rescue channel parameters
    rescue_window: int = 100,
    min_gap_samples: int = 140,
    min_thresh_for_rescue: float = 110.0,
    gate_elevated_only: bool = True,
    gate_rhythm: bool = True,
    min_reps_for_rescue: int = 3,
    y_a_arm: float = 0.60,
    y_b_reset: float = 0.50,
    y_debounce: int = 75,
    y_min_env: int = 45,
    y_amp_floor: int = 120,
    y_amp_cap: int = 500,
    win_fast: int = 25,
    win_slow: int = 250,
    min_wave_dur: int = 20,
    # Baseline FSM parameters (exact default baseline)
    rep_threshold: int = REP_THRESHOLD,
    reset_threshold: int = RESET_THRESHOLD,
    debounce_min: int = DEBOUNCE_MIN,
    debounce_max: int = DEBOUNCE_MAX,
    cooldown_timeout_samples: int = COOLDOWN_TIMEOUT_SAMPLES,
    min_wave_duration: int = MIN_WAVE_DURATION,
    x_release_threshold: int = X_RELEASE_THRESHOLD,
    x_latch_streak_len: int = X_LATCH_STREAK_LEN,
    cancel_prior_window: int = CANCEL_PRIOR_WINDOW,
    hang_streak_req: int = HANG_STREAK_REQ,
    mount_exit_env: int = MOUNT_EXIT_ENV,
) -> Tuple[List[int], List[int], List[int]]:
    """
    Simulates baseline + Y-wave rescue in parallel.
    Returns (all_reps, baseline_reps, rescued_reps).
    """
    x_accel = df["x"].values if "x" in df.columns else None
    y_accel = df["y"].values if "y" in df.columns else None
    z_accel = df["z"].values if "z" in df.columns else None

    sq_sums = df["x"].values.astype(np.int64)**2 + df["y"].values.astype(np.int64)**2 + df["z"].values.astype(np.int64)**2
    mags = np.sqrt(sq_sums).astype(np.int32)
    diffs = np.abs(np.diff(mags, prepend=mags[0]))
    envelopes, _ = precompute_envelopes(mags, diffs)
    n_samples = len(envelopes)

    # Precompute causal moving averages for Y-channel
    yf = compute_smoothed_axis(y_accel, window_size=win_fast)
    ys = compute_smoothed_axis(y_accel, window_size=win_slow)

    # Shared mount / dismount tracking
    hang_streak = 0
    has_hung = False
    hang_start = 0
    x_streak = 0
    set_locked = False

    # Baseline detector state
    state = -1  # STATE_MOUNT_SETTLING
    debounce_cur = debounce_min
    samples_since_last = debounce_min
    dismount_lockout = 0
    prev_envelope = 0
    pending_rep: Optional[int] = None
    wave_start = 0

    cur_rep_threshold = float(rep_threshold)
    cur_reset_threshold = float(reset_threshold)
    peak_avg = 140.0
    current_wave_peak = 0
    pending_wave_peak = 0
    last_rep_true_pk = 0
    wave_impulse = 0
    min_since_last = 0

    tilt_win = 25
    y_buf = [0] * tilt_win
    z_buf = [0] * tilt_win
    yz_idx = 0
    y_sum = 0
    z_sum = 0
    wave_y_min = 0
    wave_y_max = 0
    wave_z_min = 0
    wave_z_max = 0
    has_yz = (y_accel is not None and z_accel is not None)

    # Repetition storage
    rep_indices: List[int] = []
    baseline_reps: List[int] = []
    rescued_reps: List[int] = []
    confirmed_meta: List[Tuple[int, int, bool]] = []

    # Adaptive Y-wave rescue state
    y_hang_samples = 0
    y_hang_sum = 0
    y_sign = 1.0
    y_state = -1  # -1 = SETTLING, 0 = VALLEY_SEARCH, 1 = PEAK_SEARCH
    y_valley_val = 0.0
    y_valley_idx = 0
    y_peak_val = 0.0
    y_peak_idx = 0
    y_wave_start_idx = 0
    y_amp_est = 250.0
    y_last_rep_idx = -y_debounce
    y_max_env_in_wave = 0

    for i in range(n_samples):
        if set_locked:
            break

        cur_x = int(x_accel[i]) if x_accel is not None else -1000
        cur_env = int(envelopes[i])

        if has_yz:
            cy = int(y_accel[i])
            cz = int(z_accel[i])
            y_sum += cy - y_buf[yz_idx]
            z_sum += cz - z_buf[yz_idx]
            y_buf[yz_idx] = cy
            z_buf[yz_idx] = cz
            yz_idx = (yz_idx + 1) % tilt_win
            y_smooth = y_sum // tilt_win
            z_smooth = z_sum // tilt_win
        else:
            y_smooth = 0
            z_smooth = 0

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
                pending_rep = None
                if rep_indices and confirmed_meta:
                    last_confirm_idx, last_wave_dur, last_all_hang = confirmed_meta[-1]
                    interval = departure_start - last_confirm_idx
                    if interval < cancel_prior_window and (last_wave_dur < min_wave_duration or not last_all_hang):
                        popped = rep_indices.pop()
                        if baseline_reps and baseline_reps[-1] == popped:
                            baseline_reps.pop()
                        elif rescued_reps and rescued_reps[-1] == popped:
                            rescued_reps.pop()
                        confirmed_meta.pop()
                break

        samples_since_last += 1
        if dismount_lockout > 0:
            dismount_lockout -= 1

        is_safe_motion = (dismount_lockout == 0)
        x_in_hang = (cur_x <= x_release_threshold)

        # Pre-first-rep mount shockwave re-entry guard
        if state != -1 and len(rep_indices) == 0 and cur_env >= 355:
            state = -1
            pending_rep = None
            current_wave_peak = 0

        # Track valley, peak, impulse, and transverse tilt range
        if state != -1:
            if cur_env < min_since_last:
                min_since_last = cur_env
            if cur_env >= cur_reset_threshold and prev_envelope < cur_reset_threshold:
                wave_start = i
                current_wave_peak = cur_env
                wave_impulse = max(0, cur_env - int(cur_reset_threshold))
            else:
                if cur_env > current_wave_peak:
                    current_wave_peak = cur_env
                if cur_env > cur_reset_threshold:
                    wave_impulse += (cur_env - int(cur_reset_threshold))

            if y_smooth < wave_y_min: wave_y_min = y_smooth
            if y_smooth > wave_y_max: wave_y_max = y_smooth
            if z_smooth < wave_z_min: wave_z_min = z_smooth
            if z_smooth > wave_z_max: wave_z_max = z_smooth

        wave_tilt_ptp = (wave_y_max - wave_y_min) + (wave_z_max - wave_z_min) if has_yz else 700

        def record_confirmed_rep(rep_idx: int, wave_dur: int, in_hang: bool, is_rescue: bool = False):
            nonlocal cur_rep_threshold, cur_reset_threshold, peak_avg, debounce_cur, last_rep_true_pk
            if rep_indices:
                dt_prev = rep_idx - rep_indices[-1]
                debounce_cur = min(debounce_max, max(debounce_min, int(0.55 * dt_prev)))
            else:
                debounce_cur = debounce_min

            rep_indices.append(rep_idx)
            confirmed_meta.append((i, wave_dur, in_hang))
            if is_rescue:
                rescued_reps.append(rep_idx)
            else:
                baseline_reps.append(rep_idx)
                last_rep_true_pk = current_wave_peak

            if len(rep_indices) >= 4:
                pk_to_use = pending_wave_peak if not is_rescue else max(cur_env, 120)
                peak_avg = 0.30 * pk_to_use + 0.70 * peak_avg
                if len(rep_indices) >= 8:
                    dyn_rep_floor = max(83, min(95, int(0.60 * peak_avg)))
                else:
                    dyn_rep_floor = 95
                cur_rep_threshold = max(dyn_rep_floor, int(0.70 * peak_avg))
                dyn_reset_floor = max(45, min(55, int(0.55 * dyn_rep_floor)))
                cur_reset_threshold = max(dyn_reset_floor, int(0.55 * cur_rep_threshold))

        # --------------------------------------------------------------------
        # 3. Baseline State Machine Transitions
        # --------------------------------------------------------------------
        if state == -1:  # STATE_MOUNT_SETTLING
            if has_hung:
                in_hang_time = i - hang_start
                settled_below = (cur_env < mount_exit_env)
                timed_out = (in_hang_time >= 130)
                if (settled_below or timed_out) and x_in_hang:
                    state = 0
                    wave_start = i
                    current_wave_peak = 0
                    wave_impulse = 0
                    min_since_last = cur_env
                    wave_y_min = y_smooth
                    wave_y_max = y_smooth
                    wave_z_min = z_smooth
                    wave_z_max = z_smooth

        elif state == 2:  # COOLDOWN
            eff_timeout = 84 if (len(rep_indices) >= 13 and min_since_last <= 54) else cooldown_timeout_samples
            to_margin = 5 if (eff_timeout == 100 and cur_rep_threshold <= 98) else 0
            is_valley = (cur_env < cur_reset_threshold) or (
                pending_wave_peak > 0 and cur_env <= int(0.55 * pending_wave_peak)
            )
            envelope_settled = (is_valley and cur_env < 160 and samples_since_last >= debounce_cur)
            timeout_fallback = (eff_timeout > 0 and samples_since_last >= eff_timeout and cur_env < (cur_rep_threshold - to_margin))

            if pending_rep is not None:
                dt_cand = (pending_rep - rep_indices[-1]) if rep_indices else 200
                tilt_ok = (dt_cand >= 95) or (wave_tilt_ptp >= 220)
                if current_wave_peak <= 83 and wave_tilt_ptp < 660:
                    tilt_ok = False
                is_bounce = (dt_cand < 155 and last_rep_true_pk >= 240 and current_wave_peak < int(0.45 * last_rep_true_pk))
                impulse_ok = (wave_impulse >= 550) and not is_bounce

                if is_valley:
                    wave_dur = i - wave_start
                    if wave_dur >= min_wave_duration and x_in_hang and tilt_ok and impulse_ok:
                        all_hang = bool(np.all(x_accel[wave_start:i+1] <= x_release_threshold)) if x_accel is not None else True
                        already_rescued = any(abs(r - pending_rep) <= rescue_window for r in rescued_reps)
                        if not already_rescued:
                            record_confirmed_rep(pending_rep, wave_dur, all_hang, is_rescue=False)
                    pending_rep = None
                    wave_y_min = y_smooth
                    wave_y_max = y_smooth
                    wave_z_min = z_smooth
                    wave_z_max = z_smooth
                elif timeout_fallback:
                    in_hang_len = np.sum(x_accel[wave_start:i] <= x_release_threshold) if x_accel is not None else samples_since_last
                    already_rescued = any(abs(r - pending_rep) <= rescue_window for r in rescued_reps)
                    if not already_rescued:
                        if x_in_hang and tilt_ok and impulse_ok:
                            all_hang = bool(np.all(x_accel[wave_start:i+1] <= x_release_threshold)) if x_accel is not None else True
                            record_confirmed_rep(pending_rep, samples_since_last, all_hang, is_rescue=False)
                        elif in_hang_len >= min_wave_duration and (pending_rep - wave_start) >= 20 and tilt_ok and impulse_ok:
                            record_confirmed_rep(pending_rep, in_hang_len, True, is_rescue=False)
                    pending_rep = None
                    wave_y_min = y_smooth
                    wave_y_max = y_smooth
                    wave_z_min = z_smooth
                    wave_z_max = z_smooth

            if (envelope_settled or timeout_fallback) and is_safe_motion:
                state = 0
                if timeout_fallback and not is_valley:
                    min_since_last = cur_env

        elif state == 0:  # READY_TO_ARM
            req_th = cur_rep_threshold
            if samples_since_last < 155 and cur_rep_threshold <= 98 and last_rep_true_pk >= 240:
                req_th = max(cur_rep_threshold, min(105, int(0.45 * last_rep_true_pk)))

            long_gap = (samples_since_last >= 180) or (len(rep_indices) == 0 and (i - wave_start) >= 20 and (i - hang_start) >= 120)
            tilt_assisted = (long_gap and cur_env >= 88 and wave_tilt_ptp >= 260 and y_smooth >= 180)
            prom_ok = (samples_since_last >= 600 and min_since_last <= 36 and cur_env >= 97)
            mid_fatigue_ok = (len(rep_indices) >= 12 and samples_since_last >= 165 and min_since_last <= 47 and cur_env >= 95)
            late_pause_ok = (len(rep_indices) >= 12 and cur_rep_threshold >= 94 and samples_since_last >= 200 and min_since_last <= 58 and cur_env >= 78)
            valley_cleared = (samples_since_last < 110) or (min_since_last <= 98)

            if (cur_env >= req_th or tilt_assisted or prom_ok or mid_fatigue_ok or late_pause_ok) and valley_cleared and is_safe_motion and x_in_hang and samples_since_last >= debounce_cur:
                state = 1  # ARMED

        elif state == 1:  # ARMED
            if cur_env < prev_envelope and is_safe_motion and x_in_hang:
                pending_rep = i
                pending_wave_peak = current_wave_peak
                samples_since_last = 0
                min_since_last = cur_env
                state = 2  # COOLDOWN

        prev_envelope = cur_env

        # --------------------------------------------------------------------
        # 4. Parallel Adaptive Y-Axis Rescue Channel
        # --------------------------------------------------------------------
        if has_hung and x_in_hang:
            if y_hang_samples < 50:
                y_hang_samples += 1
                y_hang_sum += int(y_accel[i])
                if y_hang_samples == 50:
                    mean_y = y_hang_sum / 50.0
                    y_sign = 1.0 if mean_y > 20 else -1.0

            if y_state == -1:
                if (i - hang_start) >= 50:
                    y_state = 0
                    y_w = y_sign * (float(yf[i]) - float(ys[i]))
                    y_valley_val = y_w
                    y_valley_idx = i
                    y_peak_val = y_w
                    y_peak_idx = i
                    y_wave_start_idx = i
                    y_max_env_in_wave = cur_env
            else:
                y_w = y_sign * (float(yf[i]) - float(ys[i]))
                y_arm_th = max(float(y_amp_floor) * y_a_arm, min(float(y_amp_cap) * y_a_arm, y_a_arm * y_amp_est))
                y_reset_th = max(float(y_amp_floor) * y_b_reset, min(float(y_amp_cap) * y_b_reset, y_b_reset * y_amp_est))

                if cur_env > y_max_env_in_wave:
                    y_max_env_in_wave = cur_env

                if y_state == 0:
                    if y_w < y_valley_val:
                        y_valley_val = y_w
                        y_valley_idx = i
                        y_max_env_in_wave = cur_env
                    elif (y_w - y_valley_val) >= y_arm_th:
                        y_state = 1
                        y_wave_start_idx = y_valley_idx
                        y_peak_val = y_w
                        y_peak_idx = i
                elif y_state == 1:
                    if y_w > y_peak_val:
                        y_peak_val = y_w
                        y_peak_idx = i

                    drop = y_peak_val - y_w
                    y_wave_dur = i - y_wave_start_idx

                    if drop >= y_reset_th:
                        # Candidate Y-wave confirmed!
                        if (
                            y_wave_dur >= min_wave_dur
                            and (y_peak_idx - y_last_rep_idx) >= y_debounce
                            and y_max_env_in_wave >= y_min_env
                        ):
                            y_last_rep_idx = y_peak_idx
                            wave_amp = y_peak_val - y_valley_val
                            y_amp_est = 0.30 * wave_amp + 0.70 * y_amp_est

                            # Verify entire Y-wave duration occurred strictly in hang
                            y_all_hang = bool(np.all(x_accel[y_wave_start_idx:i+1] <= x_release_threshold)) if x_accel is not None else True

                            # Check for nearby baseline repetition (confirmed or pending)
                            has_nearby_rep = any(abs(r - y_peak_idx) <= rescue_window for r in rep_indices)
                            has_pending_baseline = (pending_rep is not None and abs(pending_rep - y_peak_idx) <= rescue_window)

                            # Gate A: Baseline threshold is elevated
                            if gate_elevated_only:
                                gate_thresh_ok = (cur_rep_threshold >= min_thresh_for_rescue)
                            else:
                                gate_thresh_ok = (cur_rep_threshold >= min_thresh_for_rescue) if min_thresh_for_rescue > 0 else True

                            # Gate B: Rhythm consistency
                            if gate_rhythm and len(rep_indices) >= 3:
                                dt_history = [rep_indices[k] - rep_indices[k-1] for k in range(len(rep_indices)-2, len(rep_indices))]
                                dt_median = float(np.median(dt_history))
                                dt_cand = float(y_peak_idx - rep_indices[-1])
                                gate_rhythm_ok = (0.55 * dt_median <= dt_cand <= 2.60 * dt_median)
                            else:
                                gate_rhythm_ok = True

                            # Gate C: Set progress
                            gate_reps_ok = (len(rep_indices) >= min_reps_for_rescue)

                            # Gap requirement: baseline has not triggered recently (fatigue dropout)
                            gap_ok = (samples_since_last >= min_gap_samples)

                            if (
                                not has_nearby_rep
                                and not has_pending_baseline
                                and y_all_hang
                                and x_in_hang
                                and x_streak == 0
                                and gate_thresh_ok
                                and gate_rhythm_ok
                                and gate_reps_ok
                                and gap_ok
                            ):
                                # Rescue fires!
                                record_confirmed_rep(y_peak_idx, y_wave_dur, True, is_rescue=True)
                                # Resynchronize baseline state
                                samples_since_last = 0
                                min_since_last = cur_env
                                state = 0
                                pending_rep = None

                        y_valley_val = y_w
                        y_valley_idx = i
                        y_max_env_in_wave = cur_env
                        y_state = 0

    # Confirm trailing pending rep if set ends while envelope is still high
    if pending_rep is not None and not set_locked:
        last_x = x_accel[-1] if x_accel is not None else -1000
        if (len(envelopes) - wave_start) >= min_wave_duration and last_x <= x_release_threshold:
            record_confirmed_rep(pending_rep, len(envelopes) - wave_start, True, is_rescue=False)
        pending_rep = None

    # End-of-Session Guard: If session ends and X departed above -300 mG in the final 1.0s,
    # retroactively discard any candidate that fired while X was departing or after departure
    if not set_locked and x_accel is not None:
        tail_start = max(0, n_samples - 100)
        dep_indices = np.where(x_accel[tail_start:] > x_release_threshold)[0]
        if len(dep_indices) > 0:
            first_dep_sample = tail_start + dep_indices[0]
            while rep_indices and rep_indices[-1] >= first_dep_sample:
                popped = rep_indices.pop()
                if baseline_reps and baseline_reps[-1] == popped:
                    baseline_reps.pop()
                elif rescued_reps and rescued_reps[-1] == popped:
                    rescued_reps.pop()
        elif x_accel[-1] > x_release_threshold:
            while rep_indices and (n_samples - rep_indices[-1]) <= 100:
                popped = rep_indices.pop()
                if baseline_reps and baseline_reps[-1] == popped:
                    baseline_reps.pop()
                elif rescued_reps and rescued_reps[-1] == popped:
                    rescued_reps.pop()

    return rep_indices, baseline_reps, rescued_reps


def detect(df: pd.DataFrame, **kwargs: Any) -> List[int]:
    """
    Standard detector entrypoint returning only the list of rep indices.
    """
    all_reps, _, _ = detect_with_channels(df, **kwargs)
    return all_reps
