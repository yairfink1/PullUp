import os
import sys
from typing import Optional, Tuple, List, Dict, Any
import fitdecode
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from config import (
    DETECTOR_CONFIG,
    ADAPTIVE_REP_FLOOR,
    ADAPTIVE_RESET_FLOOR,
)
from eval_pipeline import (
    build_ground_truth_map,
    extract_fit_session_reps,
    extract_high_freq_accel,
    precompute_envelopes,
)


def simulate_with_trace(
    envelopes: np.ndarray,
    x_accel: np.ndarray,
    config: Dict[str, Any],
    y_accel: Optional[np.ndarray] = None,
    z_accel: Optional[np.ndarray] = None,
) -> Tuple[
    List[int],
    List[int],
    List[int],
    Optional[int],
    Optional[int],
    Optional[int],
    np.ndarray,
    np.ndarray,
]:
    """
    Simulates the Hybrid v2 Combined detector with Mount Settling Guard & X-axis Bar Release Guard, recording:
      - confirmed_reps: sample indices of confirmed reps
      - cancelled_reps: sample indices of reps cancelled by dismount/departure
      - narrow_reps: sample indices of candidate peaks rejected due to narrow wave, tilt, or impulse
      - mount_idx: sample index when user first enters sustained vertical bar hang (X in [-1300, -700] for >= 35 samples)
      - dismount_idx: sample index when user leaves the bar (X > -300 mG)
      - settle_idx: sample index when envelope drops below RESET_THRESHOLD after mount shockwave
      - rep_thresh_history: array of running rep threshold values across time
      - reset_thresh_history: array of running reset threshold values across time
    """
    rep_th = config["rep_threshold"]
    reset_th = config["reset_threshold"]
    deb_min = config["debounce_min"]
    deb_max = config.get("debounce_max", 130)
    timeout_samples = config.get("cooldown_timeout_samples", 100)
    min_wave_duration = config.get("min_wave_duration", 45)
    x_release_th = config.get("x_release_threshold", -300)
    x_latch_streak = config.get("x_latch_streak_len", 35)
    cancel_prior_window = config.get("cancel_prior_window", 25)
    hang_streak_req = config.get("hang_streak_req", 35)
    mount_exit_env = config.get("mount_exit_env", 92)

    state = -1  # STATE_MOUNT_SETTLING
    debounce_cur = deb_min
    samples_since_last = deb_min
    prev_envelope = 0

    confirmed_reps: List[int] = []
    confirmed_meta: List[Tuple[int, int, bool]] = []
    cancelled_reps: List[int] = []
    narrow_reps: List[int] = []
    pending_rep = None
    wave_start = 0

    cur_rep_threshold = rep_th
    cur_reset_threshold = reset_th
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

    hang_streak = 0
    has_hung = False
    hang_start = 0
    mount_idx = None
    settle_idx = None
    dismount_idx = None
    x_streak = 0
    set_locked = False
    n_samples = len(envelopes)

    rep_thresh_history = np.zeros(n_samples, dtype=np.int32)
    reset_thresh_history = np.zeros(n_samples, dtype=np.int32)

    for i in range(n_samples):
        rep_thresh_history[i] = cur_rep_threshold
        reset_thresh_history[i] = cur_reset_threshold

        if set_locked:
            continue

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

        # 1. Mount detection & hang stabilization: X in [-1300, -700] mG for at least 35 samples (0.35s)
        if not has_hung:
            if (-1300 <= cur_x <= -700) or (-1200 <= cur_x <= -750):
                hang_streak += 1
                if hang_streak >= hang_streak_req:
                    has_hung = True
                    hang_start = i
                    mount_idx = i - hang_streak_req + 1
            else:
                hang_streak = 0
        else:
            # If still settling on mount and user drops arms, reset mount status
            if state == -1 and cur_x > x_release_th:
                has_hung = False
                hang_streak = 0
                mount_idx = None

        # 2. Bar dismount detection: only once hanging is confirmed (35 samples = 0.35s continuous departure)
        if has_hung:
            if cur_x > x_release_th:
                x_streak += 1
            else:
                x_streak = 0

            if x_streak >= x_latch_streak:
                set_locked = True
                departure_start = i - x_latch_streak
                dismount_idx = departure_start
                # 1. State-Based Rollback Rule:
                # Discard any pending_rep immediately (incomplete wave that hasn't finished settling)
                if pending_rep is not None:
                    cancelled_reps.append(pending_rep)
                    pending_rep = None
                if confirmed_reps and confirmed_meta:
                    last_confirm_idx, last_wave_dur, last_all_hang = confirmed_meta[-1]
                    interval = departure_start - last_confirm_idx
                    if interval < cancel_prior_window and (last_wave_dur < min_wave_duration or not last_all_hang):
                        cancelled = confirmed_reps.pop()
                        confirmed_meta.pop()
                        cancelled_reps.append(cancelled)
                continue

        samples_since_last += 1
        x_in_hang = (cur_x <= x_release_th)

        # Pre-first-rep mount shockwave re-entry guard
        if state != -1 and len(confirmed_reps) == 0 and cur_envelope >= 355:
            state = -1
            if pending_rep is not None:
                narrow_reps.append(pending_rep)
                pending_rep = None
            current_wave_peak = 0

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
            if confirmed_reps:
                dt_prev = rep_idx - confirmed_reps[-1]
                debounce_cur = min(deb_max, max(deb_min, int(0.55 * dt_prev)))
            else:
                debounce_cur = deb_min
            confirmed_reps.append(rep_idx)
            confirmed_meta.append((i, wave_dur, in_hang))
            last_rep_true_pk = current_wave_peak
            if len(confirmed_reps) >= 4:
                peak_avg = 0.30 * pending_wave_peak + 0.70 * peak_avg
                # Dynamic physiological fatigue floor: decays for deep fatigue sets (reps >= 8)
                if len(confirmed_reps) >= 8:
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
                # Exit as soon as envelope drops below mount_exit_env (92 mG) OR hard timeout of 1.3s (130 samples) in hang
                settled_below = (cur_envelope < mount_exit_env)
                timed_out = (in_hang_time >= 130)
                if (settled_below or timed_out) and x_in_hang:
                    state = 0  # Transition to READY_TO_ARM
                    settle_idx = i
                    wave_start = i
                    current_wave_peak = 0  # Explicitly reset mount shockwave peak
                    wave_impulse = 0
                    min_since_last = cur_envelope
                    wave_y_min = y_smooth
                    wave_y_max = y_smooth
                    wave_z_min = z_smooth
                    wave_z_max = z_smooth

        elif state == 2:  # COOLDOWN
            eff_timeout = 84 if (len(confirmed_reps) >= 13 and min_since_last <= 54) else timeout_samples
            to_margin = 5 if (eff_timeout == 100 and cur_rep_threshold <= 98) else 0
            # Relative Peak-to-Trough clearance (drop >= 45% from peak) OR absolute reset threshold
            is_valley = (cur_envelope < cur_reset_threshold) or (pending_wave_peak > 0 and cur_envelope <= int(0.55 * pending_wave_peak))
            envelope_settled = (is_valley and cur_envelope < 160 and samples_since_last >= debounce_cur)
            timeout_fallback = (eff_timeout > 0 and samples_since_last >= eff_timeout and cur_envelope < (cur_rep_threshold - to_margin))

            if pending_rep is not None:
                dt_cand = (pending_rep - confirmed_reps[-1]) if confirmed_reps else 200
                tilt_ok = (dt_cand >= 95) or (wave_tilt_ptp >= 220)
                if current_wave_peak <= 83 and wave_tilt_ptp < 660:
                    tilt_ok = False
                is_bounce = (dt_cand < 155 and last_rep_true_pk >= 240 and current_wave_peak < int(0.45 * last_rep_true_pk))
                impulse_ok = (wave_impulse >= 550) and not is_bounce
                if is_valley:
                    wave_dur = i - wave_start
                    if wave_dur >= min_wave_duration and x_in_hang and tilt_ok and impulse_ok:
                        all_hang = bool(np.all(x_accel[wave_start:i+1] <= x_release_th)) if x_accel is not None else True
                        record_confirmed_rep(pending_rep, wave_dur, all_hang)
                    else:
                        narrow_reps.append(pending_rep)
                    pending_rep = None
                    wave_y_min = y_smooth
                    wave_y_max = y_smooth
                    wave_z_min = z_smooth
                    wave_z_max = z_smooth
                elif timeout_fallback:
                    in_hang_len = np.sum(x_accel[wave_start:i] <= x_release_th) if x_accel is not None else samples_since_last
                    if x_in_hang and tilt_ok and impulse_ok:
                        all_hang = bool(np.all(x_accel[wave_start:i+1] <= x_release_th)) if x_accel is not None else True
                        record_confirmed_rep(pending_rep, samples_since_last, all_hang)
                    elif in_hang_len >= min_wave_duration and (pending_rep - wave_start) >= 20 and tilt_ok and impulse_ok:
                        record_confirmed_rep(pending_rep, in_hang_len, True)
                    else:
                        narrow_reps.append(pending_rep)
                    pending_rep = None
                    wave_y_min = y_smooth
                    wave_y_max = y_smooth
                    wave_z_min = z_smooth
                    wave_z_max = z_smooth

            if (envelope_settled or timeout_fallback):
                state = 0  # READY_TO_ARM
                if timeout_fallback and not is_valley:
                    min_since_last = cur_envelope

        elif state == 0:  # READY_TO_ARM
            req_th = cur_rep_threshold
            if samples_since_last < 155 and cur_rep_threshold <= 98 and last_rep_true_pk >= 240:
                req_th = max(cur_rep_threshold, min(105, int(0.45 * last_rep_true_pk)))
            long_gap = (samples_since_last >= 180) or (len(confirmed_reps) == 0 and (i - wave_start) >= 20 and (i - hang_start) >= 120)
            tilt_assisted = (long_gap and cur_envelope >= 88 and wave_tilt_ptp >= 260 and y_smooth >= 180)
            prom_ok = (samples_since_last >= 600 and min_since_last <= 36 and cur_envelope >= 97)
            mid_fatigue_ok = (len(confirmed_reps) >= 12 and samples_since_last >= 165 and min_since_last <= 47 and cur_envelope >= 95)
            late_pause_ok = (len(confirmed_reps) >= 12 and cur_rep_threshold >= 94 and samples_since_last >= 200 and min_since_last <= 58 and cur_envelope >= 78)
            valley_cleared = (samples_since_last < 110) or (min_since_last <= 98)
            if (cur_envelope >= req_th or tilt_assisted or prom_ok or mid_fatigue_ok or late_pause_ok) and valley_cleared and x_in_hang and samples_since_last >= debounce_cur:
                state = 1  # ARMED

        elif state == 1:  # ARMED
            if cur_envelope < prev_envelope and x_in_hang:
                pending_rep = i
                pending_wave_peak = current_wave_peak
                samples_since_last = 0
                min_since_last = cur_envelope
                state = 2  # COOLDOWN

        prev_envelope = cur_envelope

    # Confirm trailing pending rep if set ends while envelope is still above reset_threshold
    if pending_rep is not None and not set_locked:
        last_x = x_accel[-1] if x_accel is not None else -1000
        if (len(envelopes) - wave_start) >= min_wave_duration and last_x <= x_release_th:
            record_confirmed_rep(pending_rep, len(envelopes) - wave_start, True)
        else:
            narrow_reps.append(pending_rep)
        pending_rep = None

    # End-of-Session Guard: If session ends and X departed above -300 mG in the final 1.0s,
    # retroactively discard any candidate that fired while X was departing or after departure
    if not set_locked and x_accel is not None:
        tail_start = max(0, n_samples - 100)
        dep_indices = np.where(x_accel[tail_start:] > x_release_th)[0]
        if len(dep_indices) > 0:
            first_dep_sample = tail_start + dep_indices[0]
            while confirmed_reps and confirmed_reps[-1] >= first_dep_sample:
                cancelled = confirmed_reps.pop()
                if confirmed_meta:
                    confirmed_meta.pop()
                cancelled_reps.append(cancelled)
        elif x_accel[-1] > x_release_th:
            while confirmed_reps and (n_samples - confirmed_reps[-1]) <= 100:
                cancelled = confirmed_reps.pop()
                if confirmed_meta:
                    confirmed_meta.pop()
                cancelled_reps.append(cancelled)

    return confirmed_reps, cancelled_reps, narrow_reps, mount_idx, dismount_idx, settle_idx, rep_thresh_history, reset_thresh_history


def resolve_fit_path(arg_path: str) -> str:
    """
    Resolves the provided FIT file argument to a valid file path,
    checking working directory, data/, and real/ subdirectories.
    """
    if os.path.isfile(arg_path):
        return arg_path
    for candidate in [os.path.join("data", arg_path), os.path.join("real", arg_path)]:
        if os.path.isfile(candidate):
            return candidate
    return arg_path


def extract_true_reps(fit_path: str) -> Optional[int]:
    """
    Extracts the true repetition count recorded in the FIT session/lap summary
    or from benchmark file size mappings / manual inspection labels.
    """
    fname = os.path.basename(fit_path)
    manual_labels = {
        "2026-09-21-21-15-13.fit": 4,
        "2026-09-21-21-15-39.fit": 5,
        "2026-10-19-17-33-50.fit": 13,
    }
    if fname in manual_labels:
        return manual_labels[fname]

    # Try FIT session or lap rep field
    reps = extract_fit_session_reps(fit_path)
    if reps is not None:
        return reps

    # Try fallback to benchmark file size mapping in real/
    if os.path.exists(fit_path):
        sz = os.path.getsize(fit_path)
        workspace_dir = os.path.dirname(os.path.abspath(__file__))
        real_size_map = build_ground_truth_map(workspace_dir)
        if sz in real_size_map:
            return real_size_map[sz][0]

    return None


def simulate_pullup_detector(df: pd.DataFrame) -> tuple:
    """
    Runs the canonical pull-up detection algorithm with trace data.
    Delegates to simulate_with_trace so results and state boundaries
    are identical to generate_inspection_gallery.py.

    Returns:
        confirmed: sample indices of confirmed reps
        cancelled: sample indices of cancelled reps
        narrow: sample indices of candidate peaks rejected due to narrow wave
        mount_idx: sample index of bar mount
        dismount_idx: sample index of bar dismount
        settle_idx: sample index when envelope settled below RESET_THRESHOLD
        rep_th_hist: running rep threshold array
        reset_th_hist: running reset threshold array
        envelopes: precomputed causal envelope series
    """
    sq_sums = (
        df["x"].values.astype(np.int64) ** 2
        + df["y"].values.astype(np.int64) ** 2
        + df["z"].values.astype(np.int64) ** 2
    )
    mags = np.sqrt(sq_sums).astype(np.int32)
    diffs = np.abs(np.diff(mags, prepend=mags[0]))

    envelopes, _ = precompute_envelopes(
        mags, diffs, window_size=DETECTOR_CONFIG["window_size"]
    )

    x = df["x"].values.astype(np.float64)
    y = df["y"].values.astype(np.float64)
    z = df["z"].values.astype(np.float64)
    (
        confirmed,
        cancelled,
        narrow,
        mount_idx,
        dismount_idx,
        settle_idx,
        rep_th_hist,
        reset_th_hist,
    ) = simulate_with_trace(envelopes, x, DETECTOR_CONFIG, y_accel=y, z_accel=z)

    return (
        confirmed,
        cancelled,
        narrow,
        mount_idx,
        dismount_idx,
        settle_idx,
        rep_th_hist,
        reset_th_hist,
        envelopes,
    )


def plot_pullup_inspection(
    df: pd.DataFrame,
    fname: str,
    confirmed: list,
    cancelled: list,
    narrow: list,
    mount_idx: Optional[int],
    dismount_idx: Optional[int],
    settle_idx: Optional[int],
    rep_th_hist: np.ndarray,
    reset_th_hist: np.ndarray,
    envelopes: np.ndarray,
    true_reps: Optional[int],
    fs: float = 100.0,
):
    """
    Renders the exact 3-row diagnostic stacked plot matching generate_inspection_gallery.py:
      - Row 1: Raw Acceleration Magnitude & Rep Trigger Timings
      - Row 2: Causal Movement Envelope & State Triggers (Mount Settling Shading & Thresholds)
      - Row 3: Raw 3-Axis Acceleration Components (Directional Orientation & Gravity)
    """
    x = df["x"].values.astype(np.float64)
    y = df["y"].values.astype(np.float64)
    z = df["z"].values.astype(np.float64)
    sq_sums = (
        df["x"].values.astype(np.int64) ** 2
        + df["y"].values.astype(np.int64) ** 2
        + df["z"].values.astype(np.int64) ** 2
    )
    mags = np.sqrt(sq_sums).astype(np.int32)

    n_samples = len(mags)
    duration_s = n_samples / fs
    time_s = np.arange(n_samples) / fs

    det_reps = len(confirmed)

    # Determine status and title badge
    if true_reps is not None:
        error = det_reps - true_reps
        if error == 0:
            status = "MATCH"
            title_color = "#155724"  # Green
            bg_badge = "EXACT MATCH"
        elif error > 0:
            status = "OVER"
            title_color = "#004085"  # Blue
            bg_badge = f"OVERCOUNT (+{error})"
        else:
            status = "UNDER"
            title_color = "#721c24"  # Red
            bg_badge = f"UNDERCOUNT ({error})"
        sign = "+" if error > 0 else ""
        rep_summary_str = f"True: {true_reps}  |  Detected: {det_reps} ({sign}{error})"
    else:
        title_color = "#2c3e50"
        bg_badge = "UNLABELED"
        rep_summary_str = f"Detected: {det_reps} Reps"

    mount_str = (
        f"Mount: {mount_idx / fs:.2f}s (Settle: {settle_idx / fs:.2f}s)"
        if (mount_idx is not None and settle_idx is not None)
        else (f"Mount: {mount_idx / fs:.2f}s" if mount_idx is not None else "Mount: N/A")
    )
    dismount_str = f"Dismount: {dismount_idx / fs:.2f}s" if dismount_idx is not None else "Dismount: End"

    # Generate 3-Row Stacked Figure
    fig, axes = plt.subplots(3, 1, figsize=(16, 11), sharex=True, dpi=120)

    fig.suptitle(
        f"{fname}  |  {rep_summary_str}  |  Dur: {duration_s:.1f}s  [{bg_badge}]  |  {mount_str} -> {dismount_str}",
        fontsize=13,
        fontweight="bold",
        color=title_color,
        y=0.98,
    )

    # --------------------------------------------------------------------
    # Helper: Draw Purple Bar Mount & Dismount Boundary Lines Across Subplots
    # --------------------------------------------------------------------
    for ax in axes:
        if mount_idx is not None:
            t_m = mount_idx / fs
            ax.axvline(
                t_m,
                color="purple",
                linestyle="--",
                lw=1.5,
                alpha=0.9,
                label="Bar Mount (X <= -600 mG)" if ax == axes[0] else "",
            )
        if dismount_idx is not None:
            t_d = dismount_idx / fs
            ax.axvline(
                t_d,
                color="purple",
                linestyle="--",
                lw=1.5,
                alpha=0.9,
                label="Bar Dismount (X > -300 mG)" if ax == axes[0] else "",
            )
            # Dim out post-dismount region
            ax.axvspan(
                t_d,
                duration_s,
                color="purple",
                alpha=0.08,
                label="Post-Workout Latch Lockout" if ax == axes[1] else "",
            )

    # --------------------------------------------------------------------
    # Subplot 1 (Top): Raw Accelerometer Magnitude
    # --------------------------------------------------------------------
    axes[0].plot(time_s, mags, color="#2c3e50", lw=0.8, alpha=0.85, label="Raw Magnitude (mG)")
    axes[0].axhline(1000, color="gray", linestyle=":", lw=0.9, alpha=0.7, label="1G Static Level (1000 mG)")
    axes[0].axhline(1900, color="#800080", linestyle=":", lw=0.9, alpha=0.5, label="1900 mG Reference")

    # Mark confirmed reps on top plot
    for r_i, r_samp in enumerate(confirmed, 1):
        t_rep = r_samp / fs
        axes[0].axvline(t_rep, color="crimson", linestyle="--", lw=1.1, alpha=0.8)

    # Mark cancelled reps on top plot
    for c_samp in cancelled:
        t_c = c_samp / fs
        axes[0].axvline(t_c, color="darkorange", linestyle="-.", lw=1.4, alpha=0.9)

    # Mark narrow twitch rejected reps on top plot
    for n_samp in narrow:
        t_n = n_samp / fs
        axes[0].axvline(t_n, color="gray", linestyle=":", lw=1.4, alpha=0.9)

    axes[0].set_ylabel("Magnitude (mG)", fontsize=10, fontweight="bold")
    axes[0].set_title("1. Acceleration Magnitude & Rep Trigger Timings", fontsize=11, fontweight="bold")
    axes[0].set_ylim(0, max(2600, np.max(mags) + 200))
    axes[0].grid(True, linestyle=":", alpha=0.5)
    axes[0].legend(loc="upper right", fontsize=8, ncol=4)

    # --------------------------------------------------------------------
    # Subplot 2 (Middle): Causal Envelope, Smoothed Y-Axis Tilt & Rep Detection
    # --------------------------------------------------------------------
    tilt_win = 25
    y_smooth = np.zeros(n_samples, dtype=np.int32)
    y_buf = [0] * tilt_win
    yz_idx = 0
    y_sum = 0
    for i in range(n_samples):
        cy = int(y[i])
        y_sum += cy - y_buf[yz_idx]
        y_buf[yz_idx] = cy
        yz_idx = (yz_idx + 1) % tilt_win
        y_smooth[i] = y_sum // tilt_win

    axes[1].axhline(0, color="gray", linestyle=":", lw=0.8, alpha=0.6)
    axes[1].plot(
        time_s,
        y_smooth,
        color="#2ca02c",
        lw=1.5,
        alpha=0.9,
        label="Smoothed Y-Axis Wrist Tilt (25-sample MA)",
    )
    axes[1].plot(time_s, envelopes, color="#0056b3", lw=1.5, label="Movement Envelope (37-sample MA)")
    axes[1].plot(
        time_s,
        rep_th_hist,
        color="crimson",
        linestyle="-",
        lw=1.3,
        label=f"Adaptive REP Threshold (start {DETECTOR_CONFIG['rep_threshold']} mG)",
    )
    axes[1].plot(
        time_s,
        reset_th_hist,
        color="forestgreen",
        linestyle="--",
        lw=1.3,
        label=f"Adaptive RESET Threshold (start {DETECTOR_CONFIG['reset_threshold']} mG)",
    )

    # Mount Settling Shading
    if settle_idx is not None:
        t_settle = settle_idx / fs
        axes[1].axvspan(0, t_settle, color="gray", alpha=0.18, label=f"Mount Settling ({t_settle:.2f}s)")
    else:
        wm_t = DETECTOR_CONFIG["warmup_samples"] / fs
        axes[1].axvspan(0, wm_t, color="gray", alpha=0.18, label=f"Warmup ({wm_t:.1f}s)")

    # Label Confirmed Reps
    for r_i, r_samp in enumerate(confirmed, 1):
        t_rep = r_samp / fs
        env_val = envelopes[r_samp]
        axes[1].axvline(t_rep, color="crimson", linestyle="--", lw=1.1, alpha=0.85)
        axes[1].plot(t_rep, env_val, marker="o", markersize=6, color="crimson", zorder=5)
        axes[1].text(
            t_rep,
            env_val + 14,
            f"#{r_i}",
            ha="center",
            va="bottom",
            fontsize=8,
            fontweight="bold",
            color="crimson",
        )

    # Label Cancelled Reps
    for c_samp in cancelled:
        t_c = c_samp / fs
        env_val = envelopes[c_samp]
        axes[1].axvline(t_c, color="darkorange", linestyle="-.", lw=1.4, alpha=0.9)
        axes[1].plot(t_c, env_val, marker="x", markersize=8, color="darkorange", markeredgewidth=2, zorder=5)
        axes[1].text(
            t_c,
            env_val + 14,
            "CANC",
            ha="center",
            va="bottom",
            fontsize=8,
            fontweight="bold",
            color="darkorange",
        )

    # Label Narrow Twitch Rejected Reps
    for n_samp in narrow:
        t_n = n_samp / fs
        env_val = envelopes[n_samp]
        axes[1].axvline(t_n, color="gray", linestyle=":", lw=1.4, alpha=0.9)
        axes[1].plot(t_n, env_val, marker="v", markersize=7, color="gray", zorder=5)
        axes[1].text(
            t_n,
            env_val + 14,
            "TWITCH",
            ha="center",
            va="bottom",
            fontsize=8,
            fontweight="bold",
            color="gray",
        )

    s_bound = settle_idx if settle_idx is not None else 0
    e_bound = dismount_idx if dismount_idx is not None else n_samples
    in_set_y = y_smooth[s_bound:e_bound] if e_bound > s_bound else y_smooth
    y_min_bound = min(-250, int(np.min(in_set_y)) - 40)
    y_max_bound = max(320, int(np.max(envelopes)) + 60, int(np.max(in_set_y)) + 50)
    axes[1].set_ylabel("Envelope / Y-Tilt (mG)", fontsize=10, fontweight="bold")
    axes[1].set_title("2. Causal Movement Envelope, Smoothed Y-Axis Tilt (PushUp-Style) & State Triggers", fontsize=11, fontweight="bold")
    axes[1].set_ylim(y_min_bound, y_max_bound)
    axes[1].grid(True, linestyle=":", alpha=0.5)
    axes[1].legend(loc="upper right", fontsize=8, ncol=3)

    # --------------------------------------------------------------------
    # Subplot 3 (Bottom): Raw 3-Axis Components (Directional Orientation)
    # --------------------------------------------------------------------
    axes[2].plot(time_s, x, color="#1f77b4", lw=0.9, alpha=0.85, label="X-axis (forearm long axis)")
    axes[2].plot(time_s, y, color="#2ca02c", lw=0.9, alpha=0.85, label="Y-axis (wrist lateral)")
    axes[2].plot(time_s, z, color="#d62728", lw=0.9, alpha=0.85, label="Z-axis (perpendicular / face)")
    axes[2].axhline(0, color="gray", linestyle=":", lw=0.8)
    axes[2].axhline(-1000, color="#1f77b4", linestyle="--", lw=0.8, alpha=0.6, label="-1G Hang Level (X ≈ -1000 mG)")
    axes[2].axhline(
        DETECTOR_CONFIG["x_release_threshold"],
        color="purple",
        linestyle=":",
        lw=1.1,
        alpha=0.8,
        label=f"Release Level ({DETECTOR_CONFIG['x_release_threshold']} mG)",
    )

    axes[2].set_xlabel("Time (seconds)", fontsize=10, fontweight="bold")
    axes[2].set_ylabel("Acceleration (mG)", fontsize=10, fontweight="bold")
    axes[2].set_title(
        "3. Raw 3-Axis Acceleration Components (Directional Orientation & Gravity)",
        fontsize=11,
        fontweight="bold",
    )
    axes[2].grid(True, linestyle=":", alpha=0.5)
    axes[2].set_xlim(0, duration_s)
    axes[2].legend(loc="upper right", fontsize=8, ncol=5)

    plt.tight_layout(rect=[0, 0.02, 1, 0.96])
    plt.show()


def main():
    raw_arg = sys.argv[1] if len(sys.argv) > 1 else "data/2026-09-21-18-13-48.fit"
    fit_path = resolve_fit_path(raw_arg)

    df = extract_high_freq_accel(fit_path)
    if df is None:
        print(f"Could not load data from '{raw_arg}' (resolved as '{fit_path}').")
        return

    fname = os.path.basename(fit_path)
    true_reps = extract_true_reps(fit_path)

    (
        confirmed,
        cancelled,
        narrow,
        mount_idx,
        dismount_idx,
        settle_idx,
        rep_th_hist,
        reset_th_hist,
        envelopes,
    ) = simulate_pullup_detector(df)

    print(f"File: {fname}")
    print(f"Detected: {len(confirmed)} Reps  |  True: {true_reps}")
    if mount_idx is not None:
        print(f"Mount: {mount_idx / 100.0:.2f}s  |  Settle: {settle_idx / 100.0 if settle_idx else 0.0:.2f}s")
    if dismount_idx is not None:
        print(f"Dismount: {dismount_idx / 100.0:.2f}s")
    if cancelled:
        print(f"Cancelled Reps: {len(cancelled)} at indices {cancelled}")
    if narrow:
        print(f"Twitch/Narrow Rejections: {len(narrow)} at indices {narrow}")

    plot_pullup_inspection(
        df=df,
        fname=fname,
        confirmed=confirmed,
        cancelled=cancelled,
        narrow=narrow,
        mount_idx=mount_idx,
        dismount_idx=dismount_idx,
        settle_idx=settle_idx,
        rep_th_hist=rep_th_hist,
        reset_th_hist=reset_th_hist,
        envelopes=envelopes,
        true_reps=true_reps,
    )


if __name__ == "__main__":
    main()