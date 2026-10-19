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


# ============================================================================
# 3. Plotting & Gallery Generator
# ============================================================================
def generate_gallery(data_dir: str = "data", output_dir: str = "inspection_gallery"):
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    data_path = os.path.join(workspace_dir, data_dir)
    gallery_path = os.path.join(workspace_dir, output_dir)
    os.makedirs(gallery_path, exist_ok=True)

    print(f"Loading dataset from: {data_path}")
    dataset, skipped = load_dataset(data_path, workspace_dir)
    print(f"Loaded {len(dataset)} valid sets. Generating inspection gallery in '{output_dir}/'...\n")

    exact_matches = []
    suspect_matches = []
    mismatches = []

    # Sort dataset by True Reps (ascending), then by duration
    dataset.sort(key=lambda d: d["filename"])

    fs = 100.0  # 100 Hz hardware sensor sample rate

    for idx, item in enumerate(dataset, 1):
        fname = item["filename"]
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
        confirmed, cancelled, narrow, mount_idx, dismount_idx, settle_idx, rep_th_hist, reset_th_hist = simulate_with_trace(envelopes, x, CONFIG, y_accel=y, z_accel=z)

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
        fig.suptitle(
            f"Set #{idx:02d}: {fname}  |  True: {true_reps}  |  Detected: {det_reps} ({sign}{error})  |  Dur: {duration_s:.1f}s  [{bg_badge}]  |  {mount_str} -> {dismount_str}",
            fontsize=13, fontweight="bold", color=title_color, y=0.98
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
        axes[1].plot(time_s, rep_th_hist, color="crimson", linestyle="-", lw=1.3, label=f"Adaptive REP Threshold (start {CONFIG['rep_threshold']} mG)")
        axes[1].plot(time_s, reset_th_hist, color="forestgreen", linestyle="--", lw=1.3, label=f"Adaptive RESET Threshold (start {CONFIG['reset_threshold']} mG)")

        # Mount Settling Shading
        if settle_idx is not None:
            t_settle = settle_idx / fs
            axes[1].axvspan(0, t_settle, color="gray", alpha=0.18, label=f"Mount Settling ({t_settle:.2f}s)")
        else:
            wm_t = CONFIG["warmup_samples"] / fs
            axes[1].axvspan(0, wm_t, color="gray", alpha=0.18, label=f"Warmup ({wm_t:.1f}s)")

        # Label Confirmed Reps
        for r_i, r_samp in enumerate(confirmed, 1):
            t_rep = r_samp / fs
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
        base_name = os.path.splitext(fname)[0]
        out_fname = f"{idx:02d}_{status}_{base_name}_T{true_reps}_D{det_reps}.png"
        out_path = os.path.join(gallery_path, out_fname)
        plt.tight_layout(rect=[0, 0.02, 1, 0.96])
        for attempt in range(5):
            try:
                plt.savefig(out_path, dpi=120)
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
