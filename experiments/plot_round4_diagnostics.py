"""
plot_round4_diagnostics.py

Generates high-resolution diagnostic visualizer plots for Round 4 on:
  1. The new 20-rep test sets:
     - 2026-10-10-07-24-16.fit (True: 20)
     - 2026-10-10-16-50-29.fit (True: 20)
     - 2026-10-13-06-57-18.fit (True: 20)
  2. The three new October 24 sets:
     - 2026-10-24-14-17-16.fit (True: 12)
     - 2026-10-24-14-17-51.fit (True: 8)
     - 2026-10-24-14-19-34.fit (True: 5)
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
from eval_pipeline import simulate_pullup_online
import experiments.cand9_latched_y_rescue as cand9
import experiments.cand10_y_refined as cand10


def generate_plot(item: dict, output_path: str):
    df = item["df"]
    fname = item["filename"]
    true_reps = item["true_reps"]

    x = df["x"].values.astype(np.float64)
    y = df["y"].values.astype(np.float64)
    z = df["z"].values.astype(np.float64)
    mags = item["mags"]
    diffs = item["diffs"]
    envs = compute_envelope(diffs, window_size=37)
    yf = compute_smoothed_axis(y, window_size=25)
    ys = compute_smoothed_axis(y, window_size=250)

    # Classify exercise
    hang_mask = x <= -300
    first_y = y[hang_mask][:50].mean() if hang_mask.sum() >= 50 else y[:50].mean()
    is_chin = first_y > 20
    sign = 1.0 if is_chin else -1.0
    y_wave = sign * (yf.astype(np.float64) - ys.astype(np.float64))

    # Detectors
    base_reps = simulate_pullup_online(envs, None, x, y, z)
    c9_all, c9_base, c9_resc = cand9.detect_with_channels(df)
    c10_reps = cand10.detect(df)

    n_samples = len(df)
    time_s = np.arange(n_samples) / 100.0

    fig, axes = plt.subplots(3, 1, figsize=(15, 11), sharex=True, dpi=130)

    # Title
    ex_name = "CHIN-UP" if is_chin else "PULL-UP"
    fig.suptitle(
        f"Round 4 Diagnostic: {fname}  |  [{ex_name}]  |  True: {true_reps}  |  Base: {len(base_reps)}  |  Cand 9: {len(c9_all)}  |  Cand 10: {len(c10_reps)}",
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

    # Row 2: Y-Wave Periodic Excursions
    axes[1].plot(time_s, yf, label="Y Fast (25-sample MA)", color="#2ca02c", lw=1.1, alpha=0.7)
    axes[1].plot(time_s, ys, label="Y Slow (250-sample MA)", color="#8c564b", linestyle="--", lw=1.1, alpha=0.7)
    axes[1].plot(time_s, y_wave, label="Repetition Wave = sign*(Y_fast - Y_slow)", color="#9467bd", lw=1.5)
    axes[1].axhline(0, color="black", linestyle=":", lw=0.8, alpha=0.6)
    axes[1].set_ylabel("Tilt Deviation (mG)", fontsize=10, fontweight="bold")
    axes[1].set_title("2. Forearm Detrended Y-Axis Excursion Waveform", fontsize=11, fontweight="bold")
    axes[1].legend(loc="upper right", fontsize=8)
    axes[1].grid(True, linestyle=":", alpha=0.5)

    # Row 3: Movement Envelope with Comparison of All Detectors
    axes[2].plot(time_s, envs, label="Movement Envelope (37-sample MA |diff|)", color="#ff7f0e", lw=1.2, alpha=0.75)

    # Mark Baseline reps in Blue
    for r_idx in base_reps:
        axes[2].axvline(r_idx / 100.0, color="#1f77b4", linestyle=":", lw=1.1, alpha=0.7)
    axes[2].scatter([r / 100.0 for r in base_reps], [envs[r] for r in base_reps], color="#1f77b4", s=35, zorder=4, label=f"Baseline ({len(base_reps)} reps)")

    # Mark Cand 9 Rescued reps in Crimson
    for r_idx in c9_resc:
        axes[2].axvline(r_idx / 100.0, color="crimson", linestyle="-", lw=1.5, alpha=0.9)
    if c9_resc:
        axes[2].scatter([r / 100.0 for r in c9_resc], [envs[r] for r in c9_resc], color="crimson", marker="*", s=140, zorder=6, label=f"Cand 9 Rescued ({len(c9_resc)} reps)")

    # Mark Cand 10 (Standalone Y) in Green diamonds
    axes[2].scatter([r / 100.0 for r in c10_reps], [envs[r] for r in c10_reps], color="#2ca02c", marker="D", s=40, zorder=5, label=f"Cand 10 Y-Refined ({len(c10_reps)} reps)")

    axes[2].set_xlabel("Time (seconds)", fontsize=10, fontweight="bold")
    axes[2].set_ylabel("Envelope (mG)", fontsize=10, fontweight="bold")
    axes[2].set_title(f"3. Detection Timings across Channels (Ground Truth = {true_reps} reps)", fontsize=11, fontweight="bold")
    axes[2].legend(loc="upper right", fontsize=8, ncol=2)
    axes[2].grid(True, linestyle=":", alpha=0.5)

    plt.tight_layout()
    plt.savefig(output_path, dpi=130)
    plt.close()
    print(f"Saved diagnostic plot: {output_path}")


def main():
    dataset, tr_split, te_split = load_all_dataset()
    targets = [
        "2026-10-10-07-24-16.fit",
        "2026-10-10-16-50-29.fit",
        "2026-10-13-06-57-18.fit",
        "2026-10-24-14-17-16.fit",
        "2026-10-24-14-17-51.fit",
        "2026-10-24-14-19-34.fit",
    ]

    for fname in targets:
        item = next((d for d in dataset if d["filename"] == fname), None)
        if item is not None:
            out_name = f"round4_{fname.replace('.fit', '.png')}"
            out_path = os.path.join(EXPERIMENTS_DIR, out_name)
            generate_plot(item, out_path)


if __name__ == "__main__":
    main()
