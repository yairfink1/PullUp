#!/usr/bin/env python3
"""
eval_pipeline.py

Offline evaluation and parameter tuning pipeline for Garmin CIQ Pull-Up Repetition Detection.
- Discovers all .fit workout sets in data/
- Extracts True Reps from FIT session/lap messages or reference files
- Simulates the causal running envelope detection algorithm (matching Monkey C)
- Computes comprehensive evaluation metrics (MAE, Exact Match, Total Reps, Error Distribution)
- Supports fast parameter grid search to optimize detection accuracy on fatigue sets
"""

import sys
import os
import glob
import re
import time
import argparse
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import pandas as pd

try:
    import fitdecode
except ImportError:
    sys.exit("Error: 'fitdecode' is required. Install with: pip install fitdecode")

from config import (
    WINDOW_SIZE,
    REP_THRESHOLD,
    RESET_THRESHOLD,
    ADAPTIVE_REP_FLOOR,
    ADAPTIVE_RESET_FLOOR,
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


# ============================================================================
# 1. FIT Data Extraction & Ground Truth Labeling
# ============================================================================

def extract_high_freq_accel(fit_path: str) -> Optional[pd.DataFrame]:
    """
    Extracts raw 100 Hz accelerometer data (calibrated_accel_x/y/z) from a FIT file.
    Returns a DataFrame with ['x', 'y', 'z', 'magnitude'] or None if no sensor data.
    """
    x_vals, y_vals, z_vals = [], [], []

    try:
        with fitdecode.FitReader(fit_path) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                if frame.name in ("accelerometer_data", "sensor_data"):
                    x = frame.get_value("calibrated_accel_x") if frame.has_field("calibrated_accel_x") else (
                        frame.get_value("accel_x") if frame.has_field("accel_x") else (
                            frame.get_value("x") if frame.has_field("x") else None
                        )
                    )
                    y = frame.get_value("calibrated_accel_y") if frame.has_field("calibrated_accel_y") else (
                        frame.get_value("accel_y") if frame.has_field("accel_y") else (
                            frame.get_value("y") if frame.has_field("y") else None
                        )
                    )
                    z = frame.get_value("calibrated_accel_z") if frame.has_field("calibrated_accel_z") else (
                        frame.get_value("accel_z") if frame.has_field("accel_z") else (
                            frame.get_value("z") if frame.has_field("z") else None
                        )
                    )

                    if x is not None and y is not None and z is not None:
                        if isinstance(x, (list, tuple, np.ndarray)):
                            x_vals.extend(x)
                            y_vals.extend(y)
                            z_vals.extend(z)
                        else:
                            x_vals.append(x)
                            y_vals.append(y)
                            z_vals.append(z)
    except Exception as e:
        print(f"Warning: error reading {fit_path}: {e}")
        return None

    if not x_vals:
        return None

    df = pd.DataFrame({"x": x_vals, "y": y_vals, "z": z_vals})
    sq_sum = df["x"].astype(float)**2 + df["y"].astype(float)**2 + df["z"].astype(float)**2
    df["magnitude"] = np.sqrt(sq_sum)
    return df


def extract_fit_session_reps(fit_path: str) -> Optional[int]:
    """
    Extracts repetition count recorded in the FIT session or lap summary messages.
    """
    try:
        with fitdecode.FitReader(fit_path) as fit:
            for frame in fit:
                if not isinstance(frame, fitdecode.FitDataMessage):
                    continue
                if frame.name in ("session", "lap"):
                    for field in frame.fields:
                        if field.name and "rep" in field.name.lower() and "unconfirmed" not in field.name.lower():
                            if field.value is not None and isinstance(field.value, (int, float)):
                                return int(field.value)
    except Exception:
        pass
    return None


def build_ground_truth_map(workspace_dir: str) -> Dict[int, Tuple[int, str]]:
    """
    Scans the real/ directory to map file sizes to ground truth rep counts
    for older benchmark sets that did not write FitContributor fields.
    """
    size_map = {}
    real_dir = os.path.join(workspace_dir, "real")
    if not os.path.isdir(real_dir):
        return size_map

    for rf in glob.glob(os.path.join(real_dir, "*.fit")):
        fname = os.path.basename(rf)
        sz = os.path.getsize(rf)
        # Parse rep count from name (e.g. pull5.fit -> 5, chin8.fit -> 8, real_pullups_2.fit -> 2)
        m = re.search(r"(\d+)", fname)
        if m:
            size_map[sz] = (int(m.group(1)), f"real/{fname}")
        elif "real_pullups_x" in fname:
            size_map[sz] = (5, f"real/{fname}")
    return size_map


def load_dataset(data_dir: str, workspace_dir: str) -> Tuple[List[Dict[str, Any]], List[Tuple[str, str]]]:
    """
    Loads all .fit workout sets, extracts raw accelerometer signals,
    and associates each file with its ground truth rep count.
    """
    real_size_map = build_ground_truth_map(workspace_dir)
    fit_paths = sorted(glob.glob(os.path.join(data_dir, "*.fit")))

    valid_sets = []
    skipped_files = []

    # Explicit ground truth overrides for visually confirmed sets
    MANUAL_LABELS = {
        "2026-09-21-21-15-13.fit": (4, "Manual inspection (suspect 2)"),
        "2026-09-21-21-15-39.fit": (5, "Manual inspection (suspect 3)"),
        "2026-10-19-17-33-50.fit": (13, "User confirmation (13 reps)"),
    }

    for path in fit_paths:
        fname = os.path.basename(path)
        sz = os.path.getsize(path)

        df = extract_high_freq_accel(path)
        if df is None or len(df) == 0:
            skipped_files.append((fname, "No high-freq accelerometer data"))
            continue

        true_reps = None
        source = None

        if fname in MANUAL_LABELS:
            true_reps, source = MANUAL_LABELS[fname]
        else:
            true_reps = extract_fit_session_reps(path)
            source = "FIT session field"

            if true_reps is None and sz in real_size_map:
                true_reps, source = real_size_map[sz]

        if true_reps is None:
            skipped_files.append((fname, f"Has {len(df)} samples, but no ground truth rep count found"))
            continue

        # Precompute signal arrays for fast simulation and grid search
        sq_sums = df["x"].values.astype(np.int64)**2 + df["y"].values.astype(np.int64)**2 + df["z"].values.astype(np.int64)**2
        mags = np.sqrt(sq_sums).astype(np.int32)
        diffs = np.abs(np.diff(mags, prepend=mags[0]))

        valid_sets.append({
            "path": path,
            "filename": fname,
            "true_reps": true_reps,
            "source": source,
            "df": df,
            "mags": mags,
            "diffs": diffs,
            "n_samples": len(df),
            "duration_s": len(df) / 100.0
        })

    return valid_sets, skipped_files


# ============================================================================
# 2. Causal Online Repetition Detector (Exact Monkey C Logic)
# ============================================================================

def precompute_envelopes(mags: np.ndarray, diffs: np.ndarray,
                         window_size: int = WINDOW_SIZE,
                         high_mag_level: int = 1900,
                         sustained_threshold: int = 6) -> Tuple[np.ndarray, np.ndarray]:
    """
    Computes the running integer difference envelope and dismount surge trigger moments.
    Matches the O(1) circular buffer integer arithmetic in PullUpDetector.mc.
    """
    n = len(mags)
    diff_buf = [0] * window_size
    buf_idx = 0
    buf_sum = 0
    envelopes = np.zeros(n, dtype=np.int32)
    dismount_events = np.zeros(n, dtype=bool)
    high_mag_streak = 0

    for i in range(n):
        mag = mags[i]
        diff = diffs[i]

        if mag >= high_mag_level:
            high_mag_streak += 1
        else:
            high_mag_streak = 0
        if high_mag_streak >= sustained_threshold:
            dismount_events[i] = True

        buf_sum -= diff_buf[buf_idx]
        diff_buf[buf_idx] = diff
        buf_sum += diff
        buf_idx = (buf_idx + 1) % window_size

        envelopes[i] = buf_sum // window_size

    return envelopes, dismount_events


def simulate_pullup_online(envelopes: np.ndarray,
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
                           mount_exit_env: int = MOUNT_EXIT_ENV) -> List[int]:
    """
    Simulates the Hybrid v2 Combined online repetition detection state machine:
      STATE_MOUNT_SETTLING (-1) -> STATE_READY_TO_ARM (0) -> STATE_ARMED (1) -> STATE_COOLDOWN (2)
    Combines:
      1. Mount Settling & Pre-First-Rep Mount Shockwave Re-entry Guard (>= 355 mG before Rep #1).
      2. O(1) 25-sample Transverse (Y, Z) Tilt Fusion (within-wave peak-to-trough range gating & smooth-rep rescue).
      3. Wave Impulse Gating (>= 550 mG-samples), Post-Explosive Bounce Suppression, and Cooldown Exit Hysteresis.
      4. Valley-to-Peak Prominence Rescues & Deep-Fatigue Cooldown Calibration (84 samples after valley <= 54 mG).
    """
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


# ============================================================================
# 3. Evaluation Metrics & Reporting
# ============================================================================

def evaluate_dataset(dataset: List[Dict[str, Any]],
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
                           mount_exit_env: int = MOUNT_EXIT_ENV) -> Dict[str, Any]:
    """
    Runs the online detector with given parameters across all dataset files
    and aggregates accuracy metrics.
    """
    results = []
    total_true = 0
    total_detected = 0
    overcount_sets = 0
    undercount_sets = 0
    exact_matches = 0
    abs_errors = []

    for item in dataset:
        env = item.get("envelope")
        dis = item.get("dismount_events")
        if env is None or dis is None:
            env, dis = precompute_envelopes(item["mags"], item["diffs"])
            item["envelope"] = env
            item["dismount_events"] = dis

        x_accel = item["df"]["x"].values if "df" in item and "x" in item["df"].columns else None
        y_accel = item["df"]["y"].values if "df" in item and "y" in item["df"].columns else None
        z_accel = item["df"]["z"].values if "df" in item and "z" in item["df"].columns else None

        rep_indices = simulate_pullup_online(
            env,
            dismount_events=None,
            x_accel=x_accel,
            y_accel=y_accel,
            z_accel=z_accel,
            rep_threshold=rep_threshold,
            reset_threshold=reset_threshold,
            debounce_min=debounce_min,
            debounce_max=debounce_max,
            warmup_samples=warmup_samples,
            dismount_lockout_dur=dismount_lockout_dur,
            cancel_window=cancel_window,
            cooldown_timeout_samples=cooldown_timeout_samples,
            min_wave_duration=min_wave_duration,
            x_release_threshold=x_release_threshold,
            x_latch_streak_len=x_latch_streak_len,
            cancel_prior_window=cancel_prior_window,
            hang_streak_req=hang_streak_req,
            mount_exit_env=mount_exit_env
        )
        detected_count = len(rep_indices)
        true_count = item["true_reps"]
        err = detected_count - true_count

        total_true += true_count
        total_detected += detected_count
        abs_errors.append(abs(err))

        if err == 0:
            exact_matches += 1
        elif err > 0:
            overcount_sets += 1
        else:
            undercount_sets += 1

        results.append({
            "filename": item["filename"],
            "true_reps": true_count,
            "detected_reps": detected_count,
            "error": err,
            "abs_error": abs(err),
            "duration_s": item["duration_s"],
            "source": item["source"],
            "rep_indices": rep_indices
        })

    n = len(dataset)
    signed_errors = [r["error"] for r in results]
    within_1_matches = sum(1 for r in results if r["abs_error"] <= 1)

    mae = float(np.mean(abs_errors)) if n > 0 else 0.0
    bias = float(np.mean(signed_errors)) if n > 0 else 0.0
    exact_pct = (exact_matches / n * 100.0) if n > 0 else 0.0
    within_1_pct = (within_1_matches / n * 100.0) if n > 0 else 0.0

    return {
        "mae": mae,
        "bias": bias,
        "exact_matches": exact_matches,
        "exact_pct": exact_pct,
        "within_1_matches": within_1_matches,
        "within_1_pct": within_1_pct,
        "total_true": total_true,
        "total_detected": total_detected,
        "net_diff": total_detected - total_true,
        "overcount_sets": overcount_sets,
        "undercount_sets": undercount_sets,
        "n_sets": n,
        "file_results": results,
        "params": {
            "rep_threshold": rep_threshold,
            "reset_threshold": reset_threshold,
            "debounce_min": debounce_min,
            "warmup_samples": warmup_samples,
            "dismount_lockout_dur": dismount_lockout_dur,
            "cancel_window": cancel_window,
            "cooldown_timeout_samples": cooldown_timeout_samples,
            "min_wave_duration": min_wave_duration
        }
    }


def print_evaluation_report(metrics: Dict[str, Any], title: str = "Evaluation Report"):
    """Prints a formatted evaluation summary to the console."""
    p = metrics["params"]
    print("\n" + "=" * 70)
    print(f" {title.upper()}")
    print("=" * 70)
    timeout_s = f"{p['cooldown_timeout_samples']/100.0:.2f}s" if p.get('cooldown_timeout_samples') else "None"
    min_wave_s = f"{p['min_wave_duration']/100.0:.2f}s" if p.get('min_wave_duration') else "None"
    print(f" Parameters: REP_THRESHOLD={p['rep_threshold']} mG, RESET_THRESHOLD={p['reset_threshold']} mG")
    print(f"             DEBOUNCE={p['debounce_min']} ({p['debounce_min']/100.0:.2f}s), WARMUP={p['warmup_samples']} ({p['warmup_samples']/100.0:.2f}s), TIMEOUT={timeout_s}, MIN_WAVE={min_wave_s}")
    print("-" * 70)
    print(f" Total Evaluated Sets        : {metrics['n_sets']}")
    print(f" Exact Match Accuracy        : {metrics['exact_matches']}/{metrics['n_sets']} ({metrics['exact_pct']:.1f}%)")
    print(f" Within-1 (±1 Rep) Accuracy  : {metrics['within_1_matches']}/{metrics['n_sets']} ({metrics['within_1_pct']:.1f}%)")
    print(f" Mean Absolute Error (MAE)   : {metrics['mae']:.3f} reps/set")
    print(f" Mean Signed Error (Bias)    : {metrics['bias']:+.3f} reps/set")
    print(f" Total Reps (True vs Det)    : {metrics['total_true']} vs {metrics['total_detected']} (Net: {metrics['net_diff']:+d})")
    print(f" Error Distribution          : Exact={metrics['exact_matches']}, Undercount={metrics['undercount_sets']}, Overcount={metrics['overcount_sets']}")
    print("=" * 70)

    # Print files with non-zero error
    discrepancies = [r for r in metrics["file_results"] if r["error"] != 0]
    if discrepancies:
        print(f"\n Discrepancies ({len(discrepancies)} files):")
        print(f" {'Filename':<26} | {'True':>5} | {'Det':>5} | {'Error':>6} | {'Duration':>8}")
        print(" " + "-" * 60)
        for r in discrepancies:
            print(f" {r['filename']:<26} | {r['true_reps']:>5} | {r['detected_reps']:>5} | {r['error']:>+6d} | {r['duration_s']:>7.1f}s")
    else:
        print("\n Perfect 100% exact match across all sets!")
    print()


# ============================================================================
# 4. Parameter Grid Search
# ============================================================================

def run_grid_search(dataset: List[Dict[str, Any]], top_k: int = 10) -> List[Dict[str, Any]]:
    """
    Executes a grid search across key detector parameters to find configurations
    that minimize Mean Absolute Error (MAE) while balancing over/undercounting.
    """
    print("\n" + "=" * 70)
    print(" STARTING PARAMETER GRID SEARCH ACROSS ALL WORKOUT SETS")
    print("=" * 70)

    # Pre-generate envelope and dismount arrays once
    for item in dataset:
        if "envelope" not in item:
            env, dis = precompute_envelopes(item["mags"], item["diffs"])
            item["envelope"] = env
            item["dismount_events"] = dis

    # Search space definition
    rep_thresholds = list(range(80, 155, 5))      # 80 to 150 mG
    debounces = [30, 35, 40, 45]                 # 1.2s to 1.8s
    warmups = [50, 75, 100, 150, 200]            # 2.0s to 8.0s
    cancel_windows = [30, 35, 40]

    # Pre-extract numpy data for pure fast inner loop
    env_list = [d["envelope"] for d in dataset]
    dis_list = [d["dismount_events"] for d in dataset]
    x_list = [d["df"]["x"].values if "df" in d and "x" in d["df"].columns else None for d in dataset]
    true_list = np.array([d["true_reps"] for d in dataset], dtype=np.int32)
    n_sets = len(dataset)

    total_configs = sum(
        len(list(range(50, r_th - 5, 5))) * len(debounces) * len(warmups)
        for r_th in rep_thresholds
    )
    print(f"Total parameter combinations to evaluate: {total_configs}")
    t0 = time.time()

    scored_configs = []

    for r_th in rep_thresholds:
        for reset_th in range(50, r_th - 5, 5):
            for deb in debounces:
                for wm in warmups:
                    abs_err_sum = 0
                    exact_count = 0
                    net_diff = 0

                    for i in range(n_sets):
                        rep_idx = simulate_pullup_online(
                            env_list[i],
                            dismount_events=dis_list[i],
                            x_accel=x_list[i],
                            rep_threshold=r_th,
                            reset_threshold=reset_th,
                            debounce_min=deb,
                            warmup_samples=wm,
                            dismount_lockout_dur=50,
                            cancel_window=35
                        )
                        det = len(rep_idx)
                        diff = det - true_list[i]
                        abs_err_sum += abs(diff)
                        net_diff += diff
                        if diff == 0:
                            exact_count += 1

                    mae = abs_err_sum / n_sets
                    scored_configs.append({
                        "mae": mae,
                        "exact_matches": exact_count,
                        "exact_pct": exact_count / n_sets * 100.0,
                        "net_diff": net_diff,
                        "rep_th": r_th,
                        "reset_th": reset_th,
                        "deb": deb,
                        "wm": wm
                    })

    dt = time.time() - t0
    print(f"Grid search completed in {dt:.2f} seconds ({len(scored_configs)/dt:.0f} configs/sec).\n")

    # Sort primarily by MAE (ascending), then by exact match (descending), then by net_diff absolute
    scored_configs.sort(key=lambda c: (c["mae"], -c["exact_matches"], abs(c["net_diff"])))

    print(f"TOP {top_k} PARAMETER CONFIGURATIONS (Sorted by MAE):")
    print(f" {'Rank':<4} | {'REP':>5} | {'RESET':>5} | {'DEB':>5} | {'WM':>5} | {'MAE':>6} | {'Exact':>11} | {'Net Diff':>8}")
    print("-" * 65)

    for rank, c in enumerate(scored_configs[:top_k], 1):
        deb_s = f"{c['deb']/100.0:.2f}s"
        wm_s = f"{c['wm']/100.0:.2f}s"
        exact_str = f"{c['exact_matches']}/{n_sets} ({c['exact_pct']:.1f}%)"
        print(f" #{rank:<3} | {c['rep_th']:>5} | {c['reset_th']:>5} | {c['deb']:>5} ({deb_s}) | {c['wm']:>5} ({wm_s}) | {c['mae']:>6.3f} | {exact_str:>11} | {c['net_diff']:>+8d}")
    print("-" * 65)

    return scored_configs


# ============================================================================
# 5. Main CLI Entry Point
# ============================================================================

def main():
    parser = argparse.ArgumentParser(description="Garmin CIQ Pull-Up Repetition Evaluation & Tuning Pipeline")
    parser.add_argument("file", nargs="?", help="Specific .fit file to evaluate (optional)")
    parser.add_argument("--data-dir", default="data", help="Directory containing .fit workout files (default: data)")
    parser.add_argument("--tune", "--grid-search", action="store_true", help="Run parameter grid search across dataset")
    parser.add_argument("--rep-thresh", type=int, default=REP_THRESHOLD, help=f"Primary rep envelope threshold (mG, default: {REP_THRESHOLD})")
    parser.add_argument("--reset-thresh", type=int, default=RESET_THRESHOLD, help=f"Reset threshold (mG, default: {RESET_THRESHOLD})")
    parser.add_argument("--debounce", type=int, default=DEBOUNCE_MIN, help=f"Refractory debounce samples (default: {DEBOUNCE_MIN} = {DEBOUNCE_MIN/100:.2f}s)")
    parser.add_argument("--warmup", type=int, default=WARMUP_SAMPLES, help=f"Warmup suppression samples (default: {WARMUP_SAMPLES} = {WARMUP_SAMPLES/100:.2f}s)")
    args = parser.parse_args()

    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(workspace_dir, args.data_dir) if not os.path.isabs(args.data_dir) else args.data_dir

    if args.file:
        # Single-file evaluation
        file_path = args.file if os.path.isabs(args.file) else os.path.join(workspace_dir, args.file)
        if not os.path.exists(file_path):
            sys.exit(f"Error: file not found: {file_path}")

        df = extract_high_freq_accel(file_path)
        if df is None:
            sys.exit("Error: no accelerometer data in file.")

        true_reps = extract_fit_session_reps(file_path)
        sq_sums = df["x"].values.astype(np.int64)**2 + df["y"].values.astype(np.int64)**2 + df["z"].values.astype(np.int64)**2
        mags = np.sqrt(sq_sums).astype(np.int32)
        diffs = np.abs(np.diff(mags, prepend=mags[0]))
        envelopes, dismount_events = precompute_envelopes(mags, diffs)

        reps_idx = simulate_pullup_online(
            envelopes,
            dismount_events=None,
            x_accel=df["x"].values,
            rep_threshold=args.rep_thresh,
            reset_threshold=args.reset_thresh,
            debounce_min=args.debounce,
            warmup_samples=args.warmup
        )

        print("=" * 60)
        print(f"File: {os.path.basename(file_path)}")
        print(f"Duration: {len(df)/100.0:.1f}s ({len(df)} samples)")
        print(f"True Reps: {true_reps if true_reps is not None else 'Not recorded'}")
        print(f"Detected Reps: {len(reps_idx)}")
        for idx, p in enumerate(reps_idx, 1):
            print(f"  Rep #{idx}: t={p/100.0:.2f}s (sample {p}, env={envelopes[p]} mG)")
        print("=" * 60)
        return

    # Dataset loading
    print(f"Discovering and loading .fit workout sets from: {data_dir}")
    dataset, skipped = load_dataset(data_dir, workspace_dir)

    print(f"Found {len(dataset) + len(skipped)} total .fit files in {args.data_dir}/:")
    print(f"  - Successfully loaded with Ground Truth: {len(dataset)} sets")
    print(f"  - Skipped (unlabeled or no sensor data): {len(skipped)} files")

    # Baseline evaluation
    baseline_metrics = evaluate_dataset(
        dataset,
        rep_threshold=args.rep_thresh,
        reset_threshold=args.reset_thresh,
        debounce_min=args.debounce,
        warmup_samples=args.warmup
    )
    print_evaluation_report(baseline_metrics, title="Baseline Performance (Current Detection Parameters)")

    if args.tune:
        top_configs = run_grid_search(dataset, top_k=5)
        best = top_configs[0]

        tuned_metrics = evaluate_dataset(
            dataset,
            rep_threshold=best["rep_th"],
            reset_threshold=best["reset_th"],
            debounce_min=best["deb"],
            warmup_samples=best["wm"]
        )
        print_evaluation_report(tuned_metrics, title="Optimized Performance (Best Grid Search Configuration)")

        # Print comparison
        print("\n" + "=" * 70)
        print(" PERFORMANCE COMPARISON: BASELINE vs OPTIMIZED")
        print("=" * 70)
        print(f" Metric                     | Baseline (140/110)  | Optimized ({best['rep_th']}/{best['reset_th']}) | Delta")
        print("-" * 70)
        print(f" Mean Absolute Error (MAE)  | {baseline_metrics['mae']:>8.3f} reps    | {tuned_metrics['mae']:>8.3f} reps   | {tuned_metrics['mae'] - baseline_metrics['mae']:>+7.3f}")
        print(f" Exact Match Accuracy       | {baseline_metrics['exact_pct']:>8.1f}%        | {tuned_metrics['exact_pct']:>8.1f}%       | {tuned_metrics['exact_pct'] - baseline_metrics['exact_pct']:>+7.1f}%")
        print(f" Exact Matches Count        | {baseline_metrics['exact_matches']:>8d} sets    | {tuned_metrics['exact_matches']:>8d} sets   | {tuned_metrics['exact_matches'] - baseline_metrics['exact_matches']:>+7d}")
        print(f" Total Detected Reps        | {baseline_metrics['total_detected']:>8d} reps    | {tuned_metrics['total_detected']:>8d} reps   | {tuned_metrics['total_detected'] - baseline_metrics['total_detected']:>+7d}")
        print(f" Total True Reps            | {baseline_metrics['total_true']:>8d} reps    | {tuned_metrics['total_true']:>8d} reps   |       0")
        print("=" * 70)


if __name__ == "__main__":
    main()
