"""
plot_cand8_diagnostic.py

Generates a diagnostic visualizer for Candidate 8 (Baseline + Y-Rescue Channel)
on the key fatigue test file 2026-10-17-09-44-55.fit.
Marks Baseline-confirmed repetitions in BLUE and Rescued repetitions in CRIMSON/GOLD.
"""

import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

EXPERIMENTS_DIR = os.path.dirname(os.path.abspath(__file__))
PULLUP_DIR = os.path.dirname(EXPERIMENTS_DIR)
if PULLUP_DIR not in sys.path:
    sys.path.insert(0, PULLUP_DIR)

from experiments.cv import load_all_dataset
from experiments.common import compute_smoothed_axis, compute_envelope
import experiments.cand8_baseline_y_rescue as cand8


def generate_cand8_diagnostic():
    dataset, tr_split, te_split = load_all_dataset()
    target_fname = "2026-10-17-09-44-55.fit"
    item = next((d for d in te_split if d["filename"] == target_fname), None)
    if item is None:
        print(f"Error: could not find {target_fname}")
        return

    df = item["df"]
    true_reps = item["true_reps"]

    params = {
        "rescue_window": 105,
        "min_gap_samples": 100,
        "min_thresh_for_rescue": 125.0,
        "min_reps_for_rescue": 3,
        "gate_elevated_only": True,
        "gate_rhythm": False,
    }

    all_reps, base_reps, resc_reps = cand8.detect_with_channels(df, **params)

    x = df["x"].values.astype(np.float64)
    y = df["y"].values.astype(np.float64)
    z = df["z"].values.astype(np.float64)
    mags = item["mags"]
    diffs = item["diffs"]
    envs = compute_envelope(diffs, window_size=37)
    yf = compute_smoothed_axis(y, window_size=25)
    ys = compute_smoothed_axis(y, window_size=250)

    # Chin-up positive tilt wave
    y_wave = (yf.astype(np.float64) - ys.astype(np.float64))

    n_samples = len(df)
    time_s = np.arange(n_samples) / 100.0

    fig, axes = plt.subplots(3, 1, figsize=(15, 11), sharex=True, dpi=140)

    # Title
    fig.suptitle(
        f"Candidate 8 Multi-Channel Diagnostic: {target_fname}  |  True Reps: {true_reps}  |  Detected: {len(all_reps)} (Base: {len(base_reps)}, Rescued: {len(resc_reps)})",
        fontsize=13,
        fontweight="bold",
        color="#004085",
        y=0.98,
    )

    # Row 1: Raw Accelerometer Signals
    axes[0].plot(time_s, x, label="X-axis (forearm vertical)", color="#1f77b4", lw=1.2, alpha=0.9)
    axes[0].plot(time_s, y, label="Y-axis (lateral tilt)", color="#2ca02c", lw=1.0, alpha=0.8)
    axes[0].plot(time_s, z, label="Z-axis (depth)", color="#7f7f7f", lw=0.8, alpha=0.5)
    axes[0].axhline(-300, color="red", linestyle="--", lw=1.2, label="Release Gate (-300 mG)")
    axes[0].axhspan(-1300, -700, color="blue", alpha=0.08, label="Mount Lock [-1300, -700] mG")
    axes[0].set_ylabel("Accel (mG)", fontsize=10, fontweight="bold")
    axes[0].set_title("1. 3-Axis Wrist Accelerometer & Orientation Hang Gate", fontsize=11, fontweight="bold")
    axes[0].legend(loc="upper right", fontsize=8, ncol=3)
    axes[0].grid(True, linestyle=":", alpha=0.5)

    # Row 2: Adaptive Y-Wave Excursion Channel
    axes[1].plot(time_s, y_wave, label="Y-Axis Detrended Repetition Wave (Y_fast - Y_slow)", color="#9467bd", lw=1.5)
    axes[1].axhline(0, color="black", linestyle=":", lw=0.8, alpha=0.6)
    # Mark rescued apex points on Y-wave
    for r_idx in resc_reps:
        axes[1].scatter(r_idx / 100.0, y_wave[r_idx], color="crimson", marker="*", s=140, zorder=5, label="Rescued Apex" if r_idx == resc_reps[0] else "")
    axes[1].set_ylabel("Tilt Deviation (mG)", fontsize=10, fontweight="bold")
    axes[1].set_title("2. Candidate 7 Secondary Rescue Channel (Y-Axis Periodic Excursion)", fontsize=11, fontweight="bold")
    axes[1].legend(loc="upper right", fontsize=8)
    axes[1].grid(True, linestyle=":", alpha=0.5)

    # Row 3: Movement Envelope with Two-Color Channel Markers
    axes[2].plot(time_s, envs, label="Movement Envelope (37-sample MA |diff|)", color="#ff7f0e", lw=1.2, alpha=0.8)
    axes[2].axhline(105, color="gray", linestyle=":", lw=0.9, label="Baseline Start Threshold (105 mG)")
    axes[2].axhline(params["min_thresh_for_rescue"], color="purple", linestyle="--", lw=1.0, label=f"Rescue Threshold Gate ({params['min_thresh_for_rescue']:.0f} mG)")

    # Baseline confirmed reps (Blue circles)
    for b_i, b_idx in enumerate(base_reps, 1):
        t_b = b_idx / 100.0
        env_val = envs[b_idx]
        axes[2].axvline(t_b, color="#0056b3", linestyle="--", lw=1.3, alpha=0.85)
        axes[2].scatter(t_b, env_val, color="#0056b3", s=50, zorder=5, label="Baseline Channel Rep" if b_i == 1 else "")
        axes[2].text(t_b, env_val + 14, f"B{b_i}", ha="center", va="bottom", fontsize=8, fontweight="bold", color="#0056b3")

    # Rescued reps (Crimson stars)
    for r_i, r_idx in enumerate(resc_reps, 1):
        t_r = r_idx / 100.0
        env_val = envs[r_idx]
        axes[2].axvline(t_r, color="crimson", linestyle="-", lw=1.6, alpha=0.9)
        axes[2].scatter(t_r, env_val, color="crimson", marker="*", s=160, zorder=6, label="Rescued Rep (Y-Wave)" if r_i == 1 else "")
        axes[2].text(t_r, env_val + 24, f"R{r_i}", ha="center", va="bottom", fontsize=8, fontweight="bold", color="crimson")

    axes[2].set_xlabel("Time (seconds)", fontsize=10, fontweight="bold")
    axes[2].set_ylabel("Envelope (mG)", fontsize=10, fontweight="bold")
    axes[2].set_title(f"3. Dual-Channel Repetition Triggers (Total = {len(all_reps)} vs True = {true_reps})", fontsize=11, fontweight="bold")
    axes[2].legend(loc="upper right", fontsize=8)
    axes[2].grid(True, linestyle=":", alpha=0.5)

    output_path = os.path.join(EXPERIMENTS_DIR, "cand8_diagnostic_2026-10-17-09-44-55.png")
    plt.tight_layout()
    plt.savefig(output_path, dpi=140)
    plt.close()
    print(f"[Done] Saved Cand8 diagnostic plot to: {output_path}")


if __name__ == "__main__":
    generate_cand8_diagnostic()
