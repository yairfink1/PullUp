#!/usr/bin/env python3
"""
test_pull_chin_detector.py

Experiments with automatic Pull-Up vs Chin-Up classification and
directional Y-tilt peak/bottom tracking:
  - Chin-Ups: Reps peak at the TOP of Y (positive spikes).
  - Pull-Ups: Reps bottom at the TROUGH of Y (negative dips).
"""

import os
import numpy as np
from eval_pipeline import load_dataset, precompute_envelopes
from detect_pullups import simulate_with_trace
from config import DETECTOR_CONFIG


def classify_exercise(y_smooth_hang: np.ndarray) -> str:
    """
    Classifies a workout set as 'CHIN-UP' (supinated grip) or 'PULL-UP' (pronated grip)
    based on the median and upper percentile of the smoothed Y-axis tilt while hanging.
    """
    if len(y_smooth_hang) == 0:
        return "UNKNOWN"
    med_y = np.median(y_smooth_hang)
    p90_y = np.percentile(y_smooth_hang, 90)
    # Chin-ups have positive median and high positive peaks (> 200 mG)
    if (p90_y > 180 and med_y > -40) or (p90_y > 230):
        return "CHIN-UP"
    return "PULL-UP"


def evaluate_dataset_with_classification():
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(workspace_dir, "data")
    dataset, _ = load_dataset(data_dir, workspace_dir)

    # Ground truth overrides
    for d in dataset:
        if "17-33-50" in d["filename"]:
            d["true_reps"] = 13

    print("=" * 95)
    print(" AUTOMATIC PULL-UP vs CHIN-UP DETECTION & DIRECTIONAL Y-TILT AUDIT")
    print("=" * 95)

    chin_sets = []
    pull_sets = []

    for idx, item in enumerate(dataset, 1):
        fname = item["filename"]
        df = item["df"]
        x = df["x"].values.astype(np.float64)
        y = df["y"].values.astype(np.float64)
        z = df["z"].values.astype(np.float64)
        mags = item["mags"]
        diffs = item["diffs"]
        true_reps = item["true_reps"]

        # Causal smoothed Y (25 samples)
        tilt_win = 25
        y_smooth = np.zeros(len(y), dtype=np.int32)
        y_buf = [0] * tilt_win
        yz_idx = 0
        y_sum = 0
        for i in range(len(y)):
            cy = int(y[i])
            y_sum += cy - y_buf[yz_idx]
            y_buf[yz_idx] = cy
            yz_idx = (yz_idx + 1) % tilt_win
            y_smooth[i] = y_sum // tilt_win

        envs, _ = precompute_envelopes(mags, diffs)
        reps, cancelled, narrow, mount_idx, dismount_idx, settle_idx, _, _ = simulate_with_trace(
            envs, x, DETECTOR_CONFIG, y_accel=y, z_accel=z
        )

        s_idx = settle_idx if settle_idx is not None else (mount_idx if mount_idx is not None else 100)
        e_idx = dismount_idx if dismount_idx is not None else len(y) - 100
        in_hang_y = y_smooth[s_idx:e_idx] if e_idx > s_idx else y_smooth

        exercise_type = classify_exercise(in_hang_y)

        # Check Y behavior at rep confirmation moments
        y_at_reps = [y_smooth[r] for r in reps] if reps else []
        mean_y_at_reps = np.mean(y_at_reps) if y_at_reps else 0.0
        med_y = np.median(in_hang_y)
        p10_y = np.percentile(in_hang_y, 10)
        p90_y = np.percentile(in_hang_y, 90)

        record = {
            "idx": idx,
            "fname": fname,
            "true": true_reps,
            "det": len(reps),
            "med_y": med_y,
            "p10_y": p10_y,
            "p90_y": p90_y,
            "rep_y": mean_y_at_reps,
            "exercise": exercise_type,
        }

        if exercise_type == "CHIN-UP":
            chin_sets.append(record)
        else:
            pull_sets.append(record)

        print(
            f"{idx:02d} | {fname[:24]:<24} | True:{true_reps:2d} | Det:{len(reps):2d} | "
            f"Ex:{exercise_type:<7} | Med:{med_y:6.1f} | p10:{p10_y:6.1f} | p90:{p90_y:6.1f} | RepY:{mean_y_at_reps:6.1f}"
        )

    print("\n" + "=" * 95)
    print(f"Total Sets Audited: {len(dataset)}")
    print(f"  - Detected Chin-Up Sets : {len(chin_sets)}")
    print(f"  - Detected Pull-Up Sets : {len(pull_sets)}")
    print("=" * 95)

    print("\n" + "=" * 95)
    print(" DETAILED REP-BY-REP Y-AXIS PEAK / BOTTOM INSPECTION")
    print("=" * 95)

    # Inspect representative sets:
    # 55: Pull-Up 13 (Oct 19)
    # 56: Chin-Up 10 (Oct 19)
    # 54: Chin-Up 16 (Oct 19)
    # 50: Chin-Up 15 (Oct 04)
    # 49: Pull-Up 25 (Oct 04)
    # 01: Pull-Up 5 (Sep 21)
    sample_indices = [55, 56, 54, 50, 49, 1]

    for s_idx in sample_indices:
        d = dataset[s_idx - 1]
        fname = d["filename"]
        df = d["df"]
        y = df["y"].values.astype(np.float64)
        tilt_win = 25
        y_smooth = np.zeros(len(y), dtype=np.int32)
        y_buf = [0] * tilt_win
        yz_idx = 0
        y_sum = 0
        for i in range(len(y)):
            cy = int(y[i])
            y_sum += cy - y_buf[yz_idx]
            y_buf[yz_idx] = cy
            yz_idx = (yz_idx + 1) % tilt_win
            y_smooth[i] = y_sum // tilt_win

        envs, _ = precompute_envelopes(d["mags"], d["diffs"])
        reps, cancelled, narrow, mount_idx, dismount_idx, settle_idx, _, _ = simulate_with_trace(
            envs, df["x"].values, DETECTOR_CONFIG, y_accel=y, z_accel=df["z"].values
        )

        s = settle_idx or mount_idx or 100
        e = dismount_idx or (len(y) - 100)
        in_hang_y = y_smooth[s:e] if e > s else y_smooth
        ex_type = classify_exercise(in_hang_y)

    print("\n" + "=" * 95)
    print(" DIRECTIONAL TILT SIGNAL AUDIT: T_tilt = (+Y for Chin-Up, -Y for Pull-Up)")
    print("=" * 95)
    print(f" {'#':<3} | {'Type':<7} | {'True':>4} | {'Det':>4} | {'Med Hang':>9} | {'Mean Rep T':>11} | {'Min Rep T':>10} | {'Max Rep T':>10}")
    print("-" * 75)

    for idx, d in enumerate(dataset, 1):
        df = d["df"]
        y = df["y"].values.astype(np.float64)
        tilt_win = 25
        y_smooth = np.zeros(len(y), dtype=np.int32)
        y_buf = [0] * tilt_win
        yz_idx = 0
        y_sum = 0
        for i in range(len(y)):
            cy = int(y[i])
            y_sum += cy - y_buf[yz_idx]
            y_buf[yz_idx] = cy
            yz_idx = (yz_idx + 1) % tilt_win
            y_smooth[i] = y_sum // tilt_win

        envs, _ = precompute_envelopes(d["mags"], d["diffs"])
        reps, _, _, mount_idx, dismount_idx, settle_idx, _, _ = simulate_with_trace(
            envs, df["x"].values, DETECTOR_CONFIG, y_accel=y, z_accel=df["z"].values
        )

        s = settle_idx or mount_idx or 100
        e = dismount_idx or (len(y) - 100)
        in_hang = y_smooth[s:e] if e > s else y_smooth
        ex_type = classify_exercise(in_hang)
        is_chin = (ex_type == "CHIN-UP")

        t_tilt = y_smooth if is_chin else -y_smooth
        med_hang = np.median(t_tilt[s:e] if e > s else t_tilt)

        if reps:
            reps_tilt = [t_tilt[r] for r in reps]
            mean_rt = np.mean(reps_tilt)
            min_rt = int(min(reps_tilt))
            max_rt = int(max(reps_tilt))
            print(f" {idx:02d} | {ex_type:<7} | {d['true_reps']:>4} | {len(reps):>4} | {med_hang:>7.1f}mG | {mean_rt:>9.1f}mG | {min_rt:>8d}mG | {max_rt:>8d}mG")


if __name__ == "__main__":
    evaluate_dataset_with_classification()



