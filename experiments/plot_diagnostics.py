"""
plot_diagnostics.py

Generates high-resolution diagnostic visualizer plots for Candidate 7 (Adaptive Y-Axis Wave Detector)
on the key failure case (2026-10-17-09-44-55.fit) and its two worst test discrepancy files:
  - 2026-10-17-09-44-55.fit (True: 20, Detected: 20 - Exact Match)
  - 2026-10-17-10-47-21.fit (True: 5, Detected: 7 - Overcount +2)
  - 2026-10-17-10-31-12.fit (True: 7, Detected: 6 - Undercount -1)
"""

import os
import sys
from typing import List
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
import experiments.cand7_y_adaptive as cand7


def generate_single_diagnostic(
    target_fname: str,
    output_png: str,
    dataset: List[dict],
    params: dict,
):
    item = next((d for d in dataset if d["filename"] == target_fname), None)
    if item is None:
        print(f"Warning: could not find {target_fname}")
        return

    df = item["df"]
    true_reps = item["true_reps"]
    detected_reps = cand7.detect(df, **params)

    x = df["x"].values.astype(np.float64)
    y = df["y"].values.astype(np.float64)
    z = df["z"].values.astype(np.float64)
    mags = item["mags"]
    diffs = item["diffs"]
    envs = compute_envelope(diffs, window_size=37)
    yf = compute_smoothed_axis(y, window_size=params.get("win_fast", 25))
    ys = compute_smoothed_axis(y, window_size=params.get("win_slow", 250))

    # Exercise classification
    hang_mask = x <= -300
    if hang_mask.sum() > 50:
        first_y = y[hang_mask][:50].mean()
        is_chin = first_y > 20
    else:
        is_chin = False
    sign = 1.0 if is_chin else -1.0
    y_wave = sign * (yf.astype(np.float64) - ys.astype(np.float64))

    n_samples = len(df)
    time_s = np.arange(n_samples) / 100.0

    err = len(detected_reps) - true_reps
    err_str = f"{err:+d}" if err != 0 else "EXACT MATCH"
    status_color = "#155724" if err == 0 else ("#004085" if err > 0 else "#721c24")

    fig, axes = plt.subplots(3, 1, figsize=(15, 10.5), sharex=True, dpi=130)

    # Title
    exercise_str = "CHIN-UP" if is_chin else "PULL-UP"
    fig.suptitle(
        f"Candidate 7 (Adaptive Y) Diagnostic: {target_fname} | [{exercise_str}] | True: {true_reps} | Detected: {len(detected_reps)} ({err_str})",
        fontsize=13,
        fontweight="bold",
        color=status_color,
        y=0.98,
    )

    # Row 1: Raw Accelerometer Signals & Hang Gates
    axes[0].plot(time_s, x, label="X-axis (forearm vertical)", color="#1f77b4", lw=1.2, alpha=0.9)
    axes[0].plot(time_s, y, label="Y-axis (lateral tilt)", color="#2ca02c", lw=1.0, alpha=0.8)
    axes[0].plot(time_s, z, label="Z-axis (depth)", color="#7f7f7f", lw=0.8, alpha=0.5)
    axes[0].axhline(-300, color="red", linestyle="--", lw=1.2, label="Release Gate (-300 mG)")
    axes[0].axhspan(-1300, -700, color="blue", alpha=0.08, label="Mount Lock [-1300, -700] mG")
    axes[0].set_ylabel("Accel (mG)", fontsize=10, fontweight="bold")
    axes[0].set_title("1. 3-Axis Accelerometer & Bar Hang Lock", fontsize=11, fontweight="bold")
    axes[0].legend(loc="upper right", fontsize=8, ncol=3)
    axes[0].grid(True, linestyle=":", alpha=0.5)

    # Row 2: Instantaneous Y_fast vs Slow Baseline Y_slow and Normalized Y_wave
    axes[1].plot(time_s, yf, label="Y Fast (25-sample MA)", color="#2ca02c", lw=1.2, alpha=0.85)
    axes[1].plot(time_s, ys, label="Y Baseline (250-sample MA)", color="#8c564b", linestyle="--", lw=1.2, alpha=0.75)
    axes[1].plot(time_s, y_wave, label="Repetition Wave = sign*(Y_fast - Y_slow)", color="#9467bd", lw=1.5)
    axes[1].axhline(0, color="black", linestyle=":", lw=0.8, alpha=0.6)
    axes[1].set_ylabel("Tilt Deviation (mG)", fontsize=10, fontweight="bold")
    axes[1].set_title("2. Causal Forearm Detrending & Directional Wave", fontsize=11, fontweight="bold")
    axes[1].legend(loc="upper right", fontsize=8, ncol=3)
    axes[1].grid(True, linestyle=":", alpha=0.5)

    # Row 3: Movement Envelope & Confirmed Rep Trigger Markers
    axes[2].plot(time_s, envs, label="Movement Envelope (37-sample MA |diff|)", color="#ff7f0e", lw=1.2, alpha=0.75)
    axes[2].axhline(params.get("min_env", 50), color="orange", linestyle=":", lw=1.0, label=f"Envelope Bump Floor ({params.get('min_env', 50)} mG)")

    for r_i, r_samp in enumerate(detected_reps, 1):
        t_rep = r_samp / 100.0
        env_val = envs[r_samp]
        axes[2].axvline(t_rep, color="crimson", linestyle="--", lw=1.2, alpha=0.85)
        axes[2].scatter(t_rep, env_val, color="crimson", s=45, zorder=5)
        axes[2].text(t_rep, env_val + 15, f"#{r_i}", ha="center", va="bottom", fontsize=8, fontweight="bold", color="crimson")

    axes[2].set_xlabel("Time (seconds)", fontsize=10, fontweight="bold")
    axes[2].set_ylabel("Envelope (mG)", fontsize=10, fontweight="bold")
    axes[2].set_title(f"3. Rep Triggers (Total Detected = {len(detected_reps)} vs True = {true_reps})", fontsize=11, fontweight="bold")
    axes[2].legend(loc="upper right", fontsize=8)
    axes[2].grid(True, linestyle=":", alpha=0.5)

    plt.tight_layout()
    plt.savefig(output_png, dpi=140)
    plt.close()
    print(f"Generated diagnostic plot: {output_png}")


def main():
    dataset, _, _ = load_all_dataset()
    best_params = {"a_arm": 0.60, "b_reset": 0.50, "debounce": 75, "min_env": 50}

    targets = [
        ("2026-10-17-09-44-55.fit", "cand7_diagnostic_2026-10-17-09-44-55.png"),
        ("2026-10-17-10-47-21.fit", "cand7_diagnostic_2026-10-17-10-47-21.png"),
        ("2026-10-17-10-31-12.fit", "cand7_diagnostic_2026-10-17-10-31-12.png"),
    ]

    for fname, out_name in targets:
        out_path = os.path.join(EXPERIMENTS_DIR, out_name)
        generate_single_diagnostic(fname, out_path, dataset, best_params)


if __name__ == "__main__":
    main()
