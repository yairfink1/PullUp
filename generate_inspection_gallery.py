#!/usr/bin/env python3
"""
generate_inspection_gallery.py

Generates high-resolution diagnostic plots for every .fit file in the dataset,
showing raw acceleration magnitude, causal running envelope, threshold lines,
warmup periods, dismount events, confirmed rep triggers, and cancelled reps.

Saves sorted visual cards into inspection_gallery/ for easy visual auditing.
"""

import os
import sys
import glob
import json
from typing import List, Dict, Any, Tuple, Optional
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from eval_pipeline import load_dataset, precompute_envelopes
from config import DETECTOR_CONFIG, ADAPTIVE_REP_FLOOR, ADAPTIVE_RESET_FLOOR


# Use the centralized config from config.py as the single source of truth.
# To experiment with different parameters, edit config.py directly.
CONFIG = DETECTOR_CONFIG


# ============================================================================
# 2. Detailed Simulator Tracking Confirmed, Rejected Triggers & Set Bounds
# ============================================================================
# Import canonical simulate_with_trace from detect_pullups to avoid code duplication
# and guarantee 100% synchronization across offline analysis tools.
from detect_pullups import simulate_with_trace
import experiments.cand11_postset_y as cand11
import experiments.cand14_postset_consensus as cand14


def load_test_set_names(workspace_dir: str) -> set:
    """Loads held-out test set filenames from split.json if available."""
    split_path = os.path.join(workspace_dir, "split.json")
    if os.path.isfile(split_path):
        with open(split_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("test2", data.get("test", [])))
    return set()


# ============================================================================
# 3. Plotting & Gallery Generator
# ============================================================================
def generate_gallery(data_dir: str = "data", output_dir: str = "inspection_gallery"):
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(workspace_dir, data_dir)
    gallery_path = os.path.join(workspace_dir, output_dir)
    os.makedirs(gallery_path, exist_ok=True)

    # Remove stale PNG cards before regenerating so indices and split tags stay clean
    for old_png in glob.glob(os.path.join(gallery_path, "*.png")):
        try:
            os.remove(old_png)
        except OSError:
            pass

    test_names = load_test_set_names(workspace_dir)

    print(f"Loading dataset from: {data_path}")
    dataset, skipped = load_dataset(data_path, workspace_dir)
    print(f"Loaded {len(dataset)} valid sets ({len(dataset) - len(test_names)} TRAIN, {len(test_names)} TEST2). Generating inspection gallery in '{output_dir}/'...\n")

    exact_matches = []
    suspect_matches = []
    mismatches = []

    # Sort dataset so TRAIN sets come first (chronological), followed by TEST sets (chronological),
    # making it effortless to browse TRAIN vs TEST in file explorer while keeping chronological order within each split.
    dataset.sort(key=lambda d: (1 if d["filename"] in test_names else 0, d["filename"]))

    fs = 100.0  # 100 Hz hardware sensor sample rate
    train_idx = 0
    test_idx = 0

    for idx, item in enumerate(dataset, 1):
        fname = item["filename"]
        is_test = fname in test_names
        if is_test:
            test_idx += 1
            split_tag = "TEST2"
            split_idx = test_idx
        else:
            train_idx += 1
            split_tag = "TRAIN"
            split_idx = train_idx
        df = item["df"]
        x = df["x"].values.astype(np.float64)
        y = df["y"].values.astype(np.float64)
        z = df["z"].values.astype(np.float64)
        mags = item["mags"]
        diffs = item["diffs"]
        true_reps = item["true_reps"]
        n_samples = len(mags)
        duration_s = n_samples / fs
        time_s = np.arange(n_samples) / fs

        envelopes, _ = precompute_envelopes(mags, diffs)
        base_confirmed, cancelled, narrow, mount_idx, dismount_idx, settle_idx, rep_th_hist, reset_th_hist = simulate_with_trace(envelopes, x, CONFIG, y_accel=y, z_accel=z)
        confirmed, _, post_reps, _, added_reps, pruned_reps = cand14.detect_with_channels(df)
        cancelled = sorted(set(list(cancelled) + [int(p) for p in pruned_reps]))

        det_reps = len(confirmed)
        error = det_reps - true_reps

        # Categorize
        if error == 0:
            status = "MATCH"
            near_end = any((n_samples - r) < 150 for r in confirmed)
            if cancelled or near_end:
                suspect_matches.append((fname, true_reps, det_reps, error, duration_s, len(cancelled)))
            else:
                exact_matches.append((fname, true_reps, det_reps, error, duration_s))
        elif error > 0:
            status = "OVER"
            mismatches.append((fname, true_reps, det_reps, error, duration_s))
        else:
            status = "UNDER"
            mismatches.append((fname, true_reps, det_reps, error, duration_s))

        # Generate 3-Row Stacked Figure
        fig, axes = plt.subplots(3, 1, figsize=(16, 11), sharex=True, dpi=120)

        # Precompute 2-pass zero-phase smoothed Y-axis wrist tilt (35-sample centered MA)
        y_smooth = cand11.smooth_two_pass_centered(y, win=35).astype(np.int32)

        # Automatic exercise classification from hang posture & rep excursion
        s_hang = settle_idx if settle_idx is not None else (mount_idx if mount_idx is not None else 100)
        e_hang = dismount_idx if dismount_idx is not None else (n_samples - 100)
        in_hang_y = y_smooth[s_hang:e_hang] if e_hang > s_hang else y_smooth
        med_hang_y = np.median(in_hang_y) if len(in_hang_y) > 0 else 0
        p90_hang_y = np.percentile(in_hang_y, 90) if len(in_hang_y) > 0 else 0
        is_chin = bool((p90_hang_y > 180 and med_hang_y > -40) or (p90_hang_y > 230))
        exercise_name = "CHIN-UP" if is_chin else "PULL-UP"

        # Color title based on status
        if status == "MATCH":
            title_color = "#155724"  # Green
            bg_badge = "EXACT MATCH"
        elif status == "OVER":
            title_color = "#004085"  # Blue
            bg_badge = f"OVERCOUNT (+{error})"
        else:
            title_color = "#721c24"  # Red
            bg_badge = f"UNDERCOUNT ({error})"

        sign = "+" if error > 0 else ""
        mount_str = f"Mount: {mount_idx/fs:.2f}s (Settle: {settle_idx/fs:.2f}s)" if (mount_idx is not None and settle_idx is not None) else (f"Mount: {mount_idx/fs:.2f}s" if mount_idx is not None else "Mount: N/A")
        dismount_str = f"Dismount: {dismount_idx/fs:.2f}s" if dismount_idx is not None else "Dismount: End"

        # Subtle background tint for TEST sets so they are visually distinct at a glance
        if is_test:
            fig.patch.set_facecolor("#fffcf2")

        fig.suptitle(
            f"[{split_tag} #{split_idx:02d}]  {fname}  |  [{exercise_name}]  |  True: {true_reps}  |  Detected: {det_reps} ({sign}{error})  |  Dur: {duration_s:.1f}s  [{bg_badge}]  |  {mount_str} -> {dismount_str}",
            fontsize=12.5, fontweight="bold", color=title_color, y=0.98
        )


        # --------------------------------------------------------------------
        # Helper: Draw Purple Bar Mount & Dismount Boundary Lines Across Subplots
        # --------------------------------------------------------------------
        for ax in axes:
            if mount_idx is not None:
                t_m = mount_idx / fs
                ax.axvline(t_m, color="purple", linestyle="--", lw=1.5, alpha=0.9,
                           label="Bar Mount (X <= -600 mG)" if ax == axes[0] else "")
            if dismount_idx is not None:
                t_d = dismount_idx / fs
                ax.axvline(t_d, color="purple", linestyle="--", lw=1.5, alpha=0.9,
                           label="Bar Dismount (X > -300 mG)" if ax == axes[0] else "")
                # Dim out post-dismount region
                ax.axvspan(t_d, duration_s, color="purple", alpha=0.08,
                           label="Post-Workout Latch Lockout" if ax == axes[1] else "")

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
        axes[1].axhline(0, color="gray", linestyle=":", lw=0.8, alpha=0.6)
        axes[1].plot(

            time_s,
            y_smooth,
            color="#2ca02c",
            lw=1.6,
            alpha=0.95,
            label="Zero-Phase Smoothed Y-Axis Tilt (2-Pass 35-Sample MA)",
        )
        axes[1].plot(time_s, envelopes, color="#0056b3", lw=1.5, label="Movement Envelope (37-sample MA)")
        axes[1].plot(time_s, rep_th_hist, color="crimson", linestyle="-", lw=1.3, label=f"Adaptive REP Threshold (start {CONFIG['rep_threshold']} mG)")
        axes[1].plot(time_s, reset_th_hist, color="forestgreen", linestyle="--", lw=1.3, label=f"Adaptive RESET Threshold (start {CONFIG['reset_threshold']} mG)")

        # Mount Settling Shading
        if settle_idx is not None:
            t_settle = settle_idx / fs
            axes[1].axvspan(0, t_settle, color="gray", alpha=0.18, label=f"Mount Settling ({t_settle:.2f}s)")
        else:
            wm_t = CONFIG["warmup_samples"] / fs
            axes[1].axvspan(0, wm_t, color="gray", alpha=0.18, label=f"Warmup ({wm_t:.1f}s)")

        # Label Confirmed Reps (distinguishing Y-Wave Rescued Reps with green stars)
        added_set = set(int(a) for a in added_reps)
        for r_i, r_samp in enumerate(confirmed, 1):
            t_rep = r_samp / fs
            is_added = int(r_samp) in added_set
            if is_added:
                y_val = int(y_smooth[r_samp])
                axes[1].axvline(t_rep, color="#1b7837", linestyle="--", lw=1.2, alpha=0.9)
                axes[1].plot(t_rep, y_val, marker="*", markersize=9, color="#1b7837", zorder=6)
                axes[1].text(t_rep, y_val + 16, f"#{r_i} (Y)", ha="center", va="bottom", fontsize=8, fontweight="bold", color="#1b7837")
            else:
                env_val = envelopes[r_samp]
                axes[1].axvline(t_rep, color="crimson", linestyle="--", lw=1.1, alpha=0.85)
                axes[1].plot(t_rep, env_val, marker="o", markersize=6, color="crimson", zorder=5)
                axes[1].text(t_rep, env_val + 14, f"#{r_i}", ha="center", va="bottom", fontsize=8, fontweight="bold", color="crimson")

        # Label Cancelled Reps
        for c_samp in cancelled:
            t_c = c_samp / fs
            env_val = envelopes[c_samp]
            axes[1].axvline(t_c, color="darkorange", linestyle="-.", lw=1.4, alpha=0.9)
            axes[1].plot(t_c, env_val, marker="x", markersize=8, color="darkorange", markeredgewidth=2, zorder=5)
            axes[1].text(t_c, env_val + 14, "CANC", ha="center", va="bottom", fontsize=8, fontweight="bold", color="darkorange")

        # Label Narrow Twitch Rejected Reps
        for n_samp in narrow:
            t_n = n_samp / fs
            env_val = envelopes[n_samp]
            axes[1].axvline(t_n, color="gray", linestyle=":", lw=1.4, alpha=0.9)
            axes[1].plot(t_n, env_val, marker="v", markersize=7, color="gray", zorder=5)
            axes[1].text(t_n, env_val + 14, "TWITCH", ha="center", va="bottom", fontsize=8, fontweight="bold", color="gray")

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
        axes[2].axhline(CONFIG["x_release_threshold"], color="purple", linestyle=":", lw=1.1, alpha=0.8,
                        label=f"Release Level ({CONFIG['x_release_threshold']} mG)")

        axes[2].set_xlabel("Time (seconds)", fontsize=10, fontweight="bold")
        axes[2].set_ylabel("Acceleration (mG)", fontsize=10, fontweight="bold")
        axes[2].set_title("3. Raw 3-Axis Acceleration Components (Directional Orientation & Gravity)", fontsize=11, fontweight="bold")
        axes[2].grid(True, linestyle=":", alpha=0.5)
        axes[2].set_xlim(0, duration_s)
        axes[2].legend(loc="upper right", fontsize=8, ncol=5)

        # Save plot (with brief retry for transient Windows file-sync locks)
        # Prefix with TRAIN_XX or TEST_XX so file explorer naturally groups and sorts them
        base_name = os.path.splitext(fname)[0]
        out_fname = f"{split_tag}_{split_idx:02d}_{status}_{base_name}_T{true_reps}_D{det_reps}.png"
        out_path = os.path.join(gallery_path, out_fname)
        plt.tight_layout(rect=[0, 0.02, 1, 0.96])
        for attempt in range(5):
            try:
                plt.savefig(out_path, dpi=120, facecolor=fig.get_facecolor())
                break
            except OSError:
                if attempt == 4:
                    raise
                import time
                time.sleep(0.3)
        plt.close()

    print(f"Successfully generated all {len(dataset)} diagnostic cards in: {gallery_path}\n")

    # ========================================================================
    # 4. Summary Classification Report
    # ========================================================================
    print("=" * 80)
    print(" INSPECTION GALLERY AUDIT SUMMARY")
    print("=" * 80)
    print(f" Total Workout Sets Audited : {len(dataset)}")
    print(f" - Definite Exact Matches   : {len(exact_matches)}")
    print(f" - Suspect Matches          : {len(suspect_matches)} (count matches, but dismount/borderline trigger)")
    print(f" - Clear Mismatches         : {len(mismatches)} (undercounts / overcounts)")
    print("-" * 80)

    print("\n[1] DEFINITE EXACT MATCHES (Clean Rep Transitions):")
    print(f" {'Filename':<28} | {'True':>4} | {'Det':>4} | {'Dur':>6}")
    print("-" * 50)
    for m in exact_matches:
        print(f" {m[0]:<28} | {m[1]:>4} | {m[2]:>4} | {m[4]:>5.1f}s")

    if suspect_matches:
        print("\n[2] SUSPECT MATCHES (Verify trigger location / dismount proximity):")
        print(f" {'Filename':<28} | {'True':>4} | {'Det':>4} | {'Dur':>6} | Notes")
        print("-" * 70)
        for m in suspect_matches:
            notes = []
            if m[5] > 0:
                notes.append(f"{m[5]} rep(s) cancelled by dismount")
            notes.append("Rep trigger near end of set")
            print(f" {m[0]:<28} | {m[1]:>4} | {m[2]:>4} | {m[4]:>5.1f}s | {', '.join(notes)}")

    if mismatches:
        print("\n[3] CLEAR MISMATCHES (Requires algorithm adjustment):")
        print(f" {'Filename':<28} | {'True':>4} | {'Det':>4} | {'Error':>6} | {'Dur':>6} | Type")
        print("-" * 65)
        for m in mismatches:
            t = "Overcount" if m[3] > 0 else "Undercount"
            sign = "+" if m[3] > 0 else ""
            print(f" {m[0]:<28} | {m[1]:>4} | {m[2]:>4} | {sign}{m[3]:>5d} | {m[4]:>5.1f}s | {t}")
    print("=" * 80)


if __name__ == "__main__":
    generate_gallery()
