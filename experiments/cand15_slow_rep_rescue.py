"""
cand15_slow_rep_rescue.py

Candidate 15: Base online detector with slow repetition arming rescue.

Rescues low-amplitude slow repetitions (envelope peaks 78-100 mG after long gaps)
by adding a causal slow-rep rescue condition in STATE_READY_TO_ARM (state == 0):
    slow_ok = (samples_since_last >= GAP) and (min_since_last <= VALLEY) and (cur_envelope >= ENV) and (abs(y_smooth - hang_y_base) >= YDEV)
where hang_y_base is the causal running mean of y_smooth over samples where x <= -650 while state != -1.
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np

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

def simulate_pullup_online(
    envelopes: np.ndarray,
    dismount_events: Optional[np.ndarray] = None,
    x_accel: Optional[np.ndarray] = None,
    y_accel: Optional[np.ndarray] = None,
    z_accel: Optional[np.ndarray] = None,
    rep_threshold: int = REP_THRESHOLD,
    reset_threshold: int = RESET_THRESHOLD,
    debounce_min: int = DEBOUNCE_MIN,
    debounce_max: int = DEBOUNCE_MAX,
    warmup_samples: int = WARMUP_SAMPLES,
    dismount_lockout_dur: int = 50,
    cancel_window: int = 35,
    cooldown_timeout_samples: int = COOLDOWN_TIMEOUT_SAMPLES,
    min_wave_duration: int = MIN_WAVE_DURATION,
    x_release_threshold: int = X_RELEASE_THRESHOLD,
    x_latch_streak_len: int = X_LATCH_STREAK_LEN,
    cancel_prior_window: int = CANCEL_PRIOR_WINDOW,
    hang_streak_req: int = HANG_STREAK_REQ,
    mount_exit_env: int = MOUNT_EXIT_ENV,
    gap: int = 180,
    valley: int = 50,
    env: int = 76,
    ydev: int = 120,
    **kwargs,
) -> List[int]:
    """
    Simulates the base online repetition detector with ONE added slow-rep arming rescue
    in STATE_READY_TO_ARM:
      slow_ok = (samples_since_last >= GAP) and (min_since_last <= VALLEY) and (cur_envelope >= ENV) and (abs(y_smooth - hang_y_base) >= YDEV)
    """
    # Allow kwargs with uppercase or lowercase names
    gap = kwargs.get("GAP", kwargs.get("gap", gap))
    valley = kwargs.get("VALLEY", kwargs.get("valley", valley))
    env = kwargs.get("ENV", kwargs.get("env", env))
    ydev = kwargs.get("YDEV", kwargs.get("ydev", ydev))

    state = -1  # Start in STATE_MOUNT_SETTLING
    debounce_cur = debounce_min
    samples_since_last = debounce_min
    dismount_lockout = 0
    prev_envelope = 0
    rep_indices: List[int] = []
    confirmed_meta: List[Tuple[int, int, bool]] = []
    pending_rep = None
    wave_start = 0

    # X-axis orientation guard state
    hang_streak = 0
    has_hung = False
    hang_start = 0
    x_streak = 0
    set_locked = False
    n_samples = len(envelopes)

    cur_rep_threshold = rep_threshold
    cur_reset_threshold = reset_threshold
    peak_avg = 140.0
    current_wave_peak = 0
    pending_wave_peak = 0
    last_rep_true_pk = 0
    wave_impulse = 0
    min_since_last = 0

    # O(1) circular buffers for 25-sample causal smoothing of Y and Z axes
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

    # Causal running mean of y_smooth over samples with x <= -650 while state != -1
    hang_y_sum = 0
    hang_y_count = 0

    for i in range(n_samples):
        if set_locked:
            break

        cur_x = int(x_accel[i]) if x_accel is not None else -1000
        cur_envelope = int(envelopes[i])

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

        # Causal accumulation of hang_y_base while state != -1 and cur_x <= -650
        if state != -1:
            if cur_x <= -650:
                hang_y_sum += y_smooth
                hang_y_count += 1

        # 1. Mount detection & hang stabilization: X in [-1300, -700] mG for at least 35 samples (0.35s)
        if not has_hung:
            if (-1300 <= cur_x <= -700) or (-1200 <= cur_x <= -750):
                hang_streak += 1
                if hang_streak >= hang_streak_req:
                    has_hung = True
                    hang_start = i
            else:
                hang_streak = 0
        else:
            # If still settling on mount and user drops arms, reset mount status
            if state == -1 and cur_x > x_release_threshold:
                has_hung = False
                hang_streak = 0

        # 2. Dismount detection: only once hanging is confirmed (35 samples = 0.35s)
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
                        rep_indices.pop()
                        confirmed_meta.pop()
                break

        samples_since_last += 1
        if dismount_lockout > 0:
            dismount_lockout -= 1

        if dismount_events is not None and dismount_events[i]:
            dismount_lockout = dismount_lockout_dur
            state = 2  # COOLDOWN
            pending_rep = None
            if rep_indices and (i - rep_indices[-1]) < cancel_window:
                rep_indices.pop()
                if confirmed_meta:
                    confirmed_meta.pop()

        is_safe_motion = (dismount_lockout == 0)
        x_in_hang = (cur_x <= x_release_threshold)

        # Pre-first-rep mount shockwave re-entry guard
        if state != -1 and len(rep_indices) == 0 and cur_envelope >= 355:
            state = -1
            pending_rep = None
            current_wave_peak = 0
            hang_y_sum = 0
            hang_y_count = 0

        # Track valley minimum, upward wave start, peak, impulse, and transverse tilt range
        if state != -1:
            if cur_envelope < min_since_last:
                min_since_last = cur_envelope
            if cur_envelope >= cur_reset_threshold and prev_envelope < cur_reset_threshold:
                wave_start = i
                current_wave_peak = cur_envelope
                wave_impulse = max(0, cur_envelope - cur_reset_threshold)
            else:
                if cur_envelope > current_wave_peak:
                    current_wave_peak = cur_envelope
                if cur_envelope > cur_reset_threshold:
                    wave_impulse += (cur_envelope - cur_reset_threshold)
            if y_smooth < wave_y_min:
                wave_y_min = y_smooth
            if y_smooth > wave_y_max:
                wave_y_max = y_smooth
            if z_smooth < wave_z_min:
                wave_z_min = z_smooth
            if z_smooth > wave_z_max:
                wave_z_max = z_smooth

        wave_tilt_ptp = (wave_y_max - wave_y_min) + (wave_z_max - wave_z_min) if has_yz else 700

        def record_confirmed_rep(rep_idx: int, wave_dur: int, in_hang: bool):
            nonlocal cur_rep_threshold, cur_reset_threshold, peak_avg, debounce_cur, last_rep_true_pk
            if rep_indices:
                dt_prev = rep_idx - rep_indices[-1]
                debounce_cur = min(debounce_max, max(debounce_min, int(0.55 * dt_prev)))
            else:
                debounce_cur = debounce_min
            rep_indices.append(rep_idx)
            confirmed_meta.append((i, wave_dur, in_hang))
            last_rep_true_pk = current_wave_peak
            if len(rep_indices) >= 4:
                peak_avg = 0.30 * pending_wave_peak + 0.70 * peak_avg
                # Dynamic physiological fatigue floor: decays for deep fatigue sets (reps >= 8)
                if len(rep_indices) >= 8:
                    dyn_rep_floor = max(83, min(95, int(0.60 * peak_avg)))
                else:
                    dyn_rep_floor = 95
                cur_rep_threshold = max(dyn_rep_floor, int(0.70 * peak_avg))
                dyn_reset_floor = max(45, min(55, int(0.55 * dyn_rep_floor)))
                cur_reset_threshold = max(dyn_reset_floor, int(0.55 * cur_rep_threshold))

        # State Machine Transitions
        if state == -1:  # STATE_MOUNT_SETTLING
            if has_hung:
                in_hang_time = i - hang_start
                settled_below = (cur_envelope < mount_exit_env)
                timed_out = (in_hang_time >= 130)
                if (settled_below or timed_out) and x_in_hang:
                    state = 0  # Transition to READY_TO_ARM
                    wave_start = i
                    current_wave_peak = 0
                    wave_impulse = 0
                    min_since_last = cur_envelope
                    wave_y_min = y_smooth
                    wave_y_max = y_smooth
                    wave_z_min = z_smooth
                    wave_z_max = z_smooth

        elif state == 2:  # COOLDOWN
            eff_timeout = 84 if (len(rep_indices) >= 13 and min_since_last <= 54) else cooldown_timeout_samples
            to_margin = 5 if (eff_timeout == 100 and cur_rep_threshold <= 98) else 0
            is_valley = (cur_envelope < cur_reset_threshold) or (pending_wave_peak > 0 and cur_envelope <= int(0.55 * pending_wave_peak))
            envelope_settled = (is_valley and cur_envelope < 160 and samples_since_last >= debounce_cur)
            timeout_fallback = (eff_timeout > 0 and samples_since_last >= eff_timeout and cur_envelope < (cur_rep_threshold - to_margin))

            if pending_rep is not None:
                dt_cand = (pending_rep - rep_indices[-1]) if rep_indices else 200
                tilt_ok = (dt_cand >= 95) or (wave_tilt_ptp >= 220)
                if cur_wave_peak_le_83 := (current_wave_peak <= 83):
                    if wave_tilt_ptp < 660:
                        tilt_ok = False
                is_bounce = (dt_cand < 155 and last_rep_true_pk >= 240 and current_wave_peak < int(0.45 * last_rep_true_pk))
                impulse_ok = (wave_impulse >= 550) and not is_bounce
                if is_valley:
                    wave_dur = i - wave_start
                    if wave_dur >= min_wave_duration and x_in_hang and tilt_ok and impulse_ok:
                        all_hang = bool(np.all(x_accel[wave_start:i+1] <= x_release_threshold)) if x_accel is not None else True
                        record_confirmed_rep(pending_rep, wave_dur, all_hang)
                    pending_rep = None
                    wave_y_min = y_smooth
                    wave_y_max = y_smooth
                    wave_z_min = z_smooth
                    wave_z_max = z_smooth
                elif timeout_fallback:
                    in_hang_len = np.sum(x_accel[wave_start:i] <= x_release_threshold) if x_accel is not None else samples_since_last
                    if x_in_hang and tilt_ok and impulse_ok:
                        all_hang = bool(np.all(x_accel[wave_start:i+1] <= x_release_threshold)) if x_accel is not None else True
                        record_confirmed_rep(pending_rep, samples_since_last, all_hang)
                    elif in_hang_len >= min_wave_duration and (pending_rep - wave_start) >= 20 and tilt_ok and impulse_ok:
                        record_confirmed_rep(pending_rep, in_hang_len, True)
                    pending_rep = None
                    wave_y_min = y_smooth
                    wave_y_max = y_smooth
                    wave_z_min = z_smooth
                    wave_z_max = z_smooth

            if (envelope_settled or timeout_fallback) and is_safe_motion:
                state = 0  # READY_TO_ARM
                if timeout_fallback and not is_valley:
                    min_since_last = cur_envelope

        elif state == 0:  # READY_TO_ARM
            req_th = cur_rep_threshold
            if samples_since_last < 155 and cur_rep_threshold <= 98 and last_rep_true_pk >= 240:
                req_th = max(cur_rep_threshold, min(105, int(0.45 * last_rep_true_pk)))
            long_gap = (samples_since_last >= 180) or (len(rep_indices) == 0 and (i - wave_start) >= 20 and (i - hang_start) >= 120)
            tilt_assisted = (long_gap and cur_envelope >= 88 and wave_tilt_ptp >= 260 and y_smooth >= 180)
            prom_ok = (samples_since_last >= 600 and min_since_last <= 36 and cur_envelope >= 97)
            mid_fatigue_ok = (len(rep_indices) >= 12 and samples_since_last >= 165 and min_since_last <= 47 and cur_envelope >= 95)
            late_pause_ok = (len(rep_indices) >= 12 and cur_rep_threshold >= 94 and samples_since_last >= 200 and min_since_last <= 58 and cur_envelope >= 78)
            
            # Added cand15 slow repetition rescue
            hang_y_base = (hang_y_sum / hang_y_count) if hang_y_count > 0 else 0.0
            slow_ok = (samples_since_last >= gap) and (min_since_last <= valley) and (cur_envelope >= env) and (abs(y_smooth - hang_y_base) >= ydev)

            valley_cleared = (samples_since_last < 110) or (min_since_last <= 98)
            if (cur_envelope >= req_th or tilt_assisted or prom_ok or mid_fatigue_ok or late_pause_ok or slow_ok) and valley_cleared and is_safe_motion and x_in_hang and samples_since_last >= debounce_cur:
                state = 1  # ARMED

        elif state == 1:  # ARMED
            if cur_envelope < prev_envelope and is_safe_motion and x_in_hang:
                pending_rep = i
                pending_wave_peak = current_wave_peak
                samples_since_last = 0
                min_since_last = cur_envelope
                state = 2  # COOLDOWN

        prev_envelope = cur_envelope

    # Confirm trailing pending rep if set ends while envelope is still above reset_threshold
    if pending_rep is not None and not set_locked:
        last_x = x_accel[-1] if x_accel is not None else -1000
        if (len(envelopes) - wave_start) >= min_wave_duration and last_x <= x_release_threshold:
            record_confirmed_rep(pending_rep, len(envelopes) - wave_start, True)
        pending_rep = None

    # End-of-Session Guard: If session ends and X departed above -300 mG in the final 1.0s,
    # retroactively discard any candidate that fired while X was departing or after departure
    if not set_locked and x_accel is not None:
        tail_start = max(0, n_samples - 100)
        dep_indices = np.where(x_accel[tail_start:] > x_release_threshold)[0]
        if len(dep_indices) > 0:
            first_dep_sample = tail_start + dep_indices[0]
            while rep_indices and rep_indices[-1] >= first_dep_sample:
                rep_indices.pop()
        elif x_accel[-1] > x_release_threshold:
            while rep_indices and (n_samples - rep_indices[-1]) <= 100:
                rep_indices.pop()

    return rep_indices
