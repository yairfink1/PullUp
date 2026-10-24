"""
cand5_baseline_lite.py

Candidate 5: Regularized Baseline (Baseline-Lite).
Exact copy of eval_pipeline.simulate_pullup_online architecture with toggleable rules:
  1. enable_tilt_assisted
  2. enable_prom_ok
  3. enable_mid_fatigue_ok
  4. enable_late_pause_ok
  5. enable_post_explosive_raise
  6. enable_impulse_gate
  7. enable_tilt_gate
  8. enable_deep_fatigue_timeout
  9. enable_mount_reentry_guard
  10. cap_and_decay (fixes the unbounded threshold ratchet)
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


def detect(
    df: pd.DataFrame,
    # Threshold parameters
    rep_threshold: int = REP_THRESHOLD,
    reset_threshold: int = RESET_THRESHOLD,
    lo: int = 95,
    hi: int = 135,
    k: float = 0.70,
    decay_rate: float = 0.005,
    cap_and_decay: bool = False,
    # Rule ablation toggles
    enable_tilt_assisted: bool = True,
    enable_prom_ok: bool = True,
    enable_mid_fatigue_ok: bool = True,
    enable_late_pause_ok: bool = True,
    enable_post_explosive_raise: bool = True,
    enable_impulse_gate: bool = True,
    enable_tilt_gate: bool = True,
    enable_deep_fatigue_timeout: bool = True,
    enable_mount_reentry_guard: bool = True,
    # Timing and guards
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
) -> List[int]:
    """
    Simulates the online repetition detector with toggleable rules and optional threshold cap+decay.
    When cap_and_decay=False and all rules=True, identically reproduces simulate_pullup_online.
    """
    x_accel = df["x"].values if "x" in df.columns else None
    y_accel = df["y"].values if "y" in df.columns else None
    z_accel = df["z"].values if "z" in df.columns else None

    sq_sums = df["x"].values.astype(np.int64)**2 + df["y"].values.astype(np.int64)**2 + df["z"].values.astype(np.int64)**2
    mags = np.sqrt(sq_sums).astype(np.int32)
    diffs = np.abs(np.diff(mags, prepend=mags[0]))
    envelopes, dismount_events = precompute_envelopes(mags, diffs)
    n_samples = len(envelopes)

    state = -1  # STATE_MOUNT_SETTLING
    debounce_cur = debounce_min
    samples_since_last = debounce_min
    dismount_lockout = 0
    prev_envelope = 0
    rep_indices: List[int] = []
    confirmed_meta: List[Tuple[int, int, bool]] = []
    pending_rep = None
    wave_start = 0

    hang_streak = 0
    has_hung = False
    hang_start = 0
    x_streak = 0
    set_locked = False

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

        # 1. Mount detection & hang stabilization: X in [-1300, -700] mG for >= 35 samples
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
                        rep_indices.pop()
                        confirmed_meta.pop()
                break

        samples_since_last += 1
        if dismount_lockout > 0:
            dismount_lockout -= 1

        is_safe_motion = (dismount_lockout == 0)
        x_in_hang = (cur_x <= x_release_threshold)

        # Causal threshold decay towards lo during pauses
        if cap_and_decay:
            cur_rep_threshold += decay_rate * (lo - cur_rep_threshold)
            cur_reset_threshold = max(45, min(65, int(0.55 * cur_rep_threshold)))

        # Rule 9: Pre-first-rep mount shockwave re-entry guard
        if enable_mount_reentry_guard and state != -1 and len(rep_indices) == 0 and cur_envelope >= 355:
            state = -1
            pending_rep = None
            current_wave_peak = 0

        # Track valley minimum, upward wave start, peak, impulse, and transverse tilt range
        if state != -1:
            if cur_envelope < min_since_last:
                min_since_last = cur_envelope
            if cur_envelope >= cur_reset_threshold and prev_envelope < cur_reset_threshold:
                wave_start = i
                current_wave_peak = cur_envelope
                wave_impulse = max(0, cur_envelope - int(cur_reset_threshold))
            else:
                if cur_envelope > current_wave_peak:
                    current_wave_peak = cur_envelope
                if cur_envelope > cur_reset_threshold:
                    wave_impulse += (cur_envelope - int(cur_reset_threshold))

            if y_smooth < wave_y_min: wave_y_min = y_smooth
            if y_smooth > wave_y_max: wave_y_max = y_smooth
            if z_smooth < wave_z_min: wave_z_min = z_smooth
            if z_smooth > wave_z_max: wave_z_max = z_smooth

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
                if cap_and_decay:
                    cur_rep_threshold = max(float(lo), min(float(hi), k * peak_avg))
                    cur_reset_threshold = max(45, min(65, int(0.55 * cur_rep_threshold)))
                else:
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
                    state = 0
                    wave_start = i
                    current_wave_peak = 0
                    wave_impulse = 0
                    min_since_last = cur_envelope
                    wave_y_min = y_smooth
                    wave_y_max = y_smooth
                    wave_z_min = z_smooth
                    wave_z_max = z_smooth

        elif state == 2:  # COOLDOWN
            if enable_deep_fatigue_timeout and (len(rep_indices) >= 13 and min_since_last <= 54):
                eff_timeout = 84
            else:
                eff_timeout = cooldown_timeout_samples

            to_margin = 5 if (eff_timeout == 100 and cur_rep_threshold <= 98) else 0
            is_valley = (cur_envelope < cur_reset_threshold) or (
                pending_wave_peak > 0 and cur_envelope <= int(0.55 * pending_wave_peak)
            )
            envelope_settled = (is_valley and cur_envelope < 160 and samples_since_last >= debounce_cur)
            timeout_fallback = (eff_timeout > 0 and samples_since_last >= eff_timeout and cur_envelope < (cur_rep_threshold - to_margin))

            if pending_rep is not None:
                dt_cand = (pending_rep - rep_indices[-1]) if rep_indices else 200

                if enable_tilt_gate:
                    tilt_ok = (dt_cand >= 95) or (wave_tilt_ptp >= 220)
                    if current_wave_peak <= 83 and wave_tilt_ptp < 660:
                        tilt_ok = False
                else:
                    tilt_ok = True

                if enable_impulse_gate:
                    is_bounce = (dt_cand < 155 and last_rep_true_pk >= 240 and current_wave_peak < int(0.45 * last_rep_true_pk))
                    impulse_ok = (wave_impulse >= 550) and not is_bounce
                else:
                    impulse_ok = True

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
                state = 0
                if timeout_fallback and not is_valley:
                    min_since_last = cur_envelope

        elif state == 0:  # READY_TO_ARM
            req_th = cur_rep_threshold
            if enable_post_explosive_raise and samples_since_last < 155 and cur_rep_threshold <= 98 and last_rep_true_pk >= 240:
                req_th = max(cur_rep_threshold, min(105, int(0.45 * last_rep_true_pk)))

            long_gap = (samples_since_last >= 180) or (len(rep_indices) == 0 and (i - wave_start) >= 20 and (i - hang_start) >= 120)
            tilt_assisted = enable_tilt_assisted and (long_gap and cur_envelope >= 88 and wave_tilt_ptp >= 260 and y_smooth >= 180)
            prom_ok = enable_prom_ok and (samples_since_last >= 600 and min_since_last <= 36 and cur_envelope >= 97)
            mid_fatigue_ok = enable_mid_fatigue_ok and (len(rep_indices) >= 12 and samples_since_last >= 165 and min_since_last <= 47 and cur_envelope >= 95)
            late_pause_ok = enable_late_pause_ok and (len(rep_indices) >= 12 and cur_rep_threshold >= 94 and samples_since_last >= 200 and min_since_last <= 58 and cur_envelope >= 78)
            valley_cleared = (samples_since_last < 110) or (min_since_last <= 98)

            if (cur_envelope >= req_th or tilt_assisted or prom_ok or mid_fatigue_ok or late_pause_ok) and valley_cleared and is_safe_motion and x_in_hang and samples_since_last >= debounce_cur:
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
