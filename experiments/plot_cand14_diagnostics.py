"""
plot_cand14_diagnostics.py

Generates high-resolution diagnostic visualizer cards for Candidate 14 (Strict 1-to-1 Bipartite Consensus):
  - 2026-10-17-09-44-55.fit (Test: Canonical 20-rep set recovered from 11 in baseline to 19 reps)
  - 2026-10-10-07-24-16.fit (Test: 20-rep burnout set - 20/20 Exact Match)
  - 2026-10-24-15-15-53.fit (Train: New 6-rep set - 6/6 Exact Match)
  - 2026-10-13-14-37-37.fit (Test: 5-rep set - 5/5 Exact Match)
  - 2026-10-21-05-57-53.fit (Test: 10-rep set - 10/10 Exact Match)
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
from eval_pipeline import simulate_pullup_online, precompute_envelopes
import experiments.cand14_postset_consensus as cand14
import experiments.cand11_postset_y as cand11


def generate_plot(item: dict, output_path: str):
    df = item["df"]
    fname = item["filename"]
    true_reps = item["true_reps"]

    x = df["x"].values.astype(np.float64)
    y = df["y"].values.astype(np.float64)
    z = df["z"].values.astype(np.float64)
    n = len(df)
    time_s = np.arange(n) / 100.0

    sq_sums = df["x"].values.astype(np.int64)**2 + df["y"].values.astype(np.int64)**2 + df["z"].values.astype(np.int64)**2
    mags = np.sqrt(sq_sums).astype(np.int32)
    diffs = np.abs(np.diff(mags, prepend=mags[0]))
    envs, _ = precompute_envelopes(mags, diffs)

    s_idx, e_idx = cand11.extract_hang_bounds(x, envs)
    if (e_idx - s_idx) < 120:
        s_idx, e_idx = 0, n

    y_hang = y[s_idx:e_idx]
    med_y = float(np.median(y_hang)) if len(y_hang) > 0 else 0
    p85_y = float(np.percentile(y_hang, 85)) if len(y_hang) > 0 else 0
    is_chin = bool((p85_y > 160 and med_y > -20) or (p85_y > 210))
    sign = 1.0 if is_chin else -1.0

    y_smooth = cand11.smooth_two_pass_centered(y_hang, win=35)
    sig = sign * y_smooth

    # Run Candidate 14
    final_reps, base_reps, post_reps, matched_pairs, added_reps, pruned_reps = cand14.detect_with_channels(df)

    err = len(final_reps) - true_reps
    err_str = f"{err:+d}" if err != 0 else "EXACT MATCH"
    status_color = "#155724" if err == 0 else ("#004085" if err > 0 else "#721c24")

    fig, axes = plt.subplots(3, 1, figsize=(15, 11), sharex=True, dpi=130)

    # Title
    ex_name = "CHIN-UP" if is_chin else "PULL-UP"
    fig.suptitle(
        f"Candidate 14 Bipartite Consensus: {fname}  |  [{ex_name}]  |  True: {true_reps}  |  Base: {len(base_reps)}  |  Cand 14: {len(final_reps)} ({err_str})",
        fontsize=13,
        fontweight="bold",
        color=status_color,
        y=0.98,
    )

    # Row 1: 3-Axis Accel & Active Hang Region
    axes[0].plot(time_s, x, label="X-axis (forearm vertical)", color="#1f77b4", lw=1.2, alpha=0.9)
    axes[0].plot(time_s, y, label="Y-axis (lateral tilt)", color="#2ca02c", lw=1.0, alpha=0.8)
    axes[0].plot(time_s, z, label="Z-axis (depth)", color="#7f7f7f", lw=0.8, alpha=0.5)
    axes[0].axvspan(s_idx / 100.0, e_idx / 100.0, color="green", alpha=0.08, label=f"Active Hang [{s_idx/100:.1f}s - {e_idx/100:.1f}s]")
    axes[0].axhline(-300, color="red", linestyle="--", lw=1.2, label="Release Gate (-300 mG)")
    axes[0].axhspan(-1300, -700, color="blue", alpha=0.08, label="Mount Lock [-1300, -700] mG")
    axes[0].set_ylabel("Accel (mG)", fontsize=10, fontweight="bold")
    axes[0].set_title("1. 3-Axis Wrist Accelerometer & Active Hang Window", fontsize=11, fontweight="bold")
    axes[0].legend(loc="upper right", fontsize=8, ncol=3)
    axes[0].grid(True, linestyle=":", alpha=0.5)

    # Row 2: Zero-Phase Y-Waveform (Single-Cycle Verification)
    t_hang = np.arange(s_idx, e_idx) / 100.0
    axes[1].plot(t_hang, sig, label="Zero-Phase Centered Y-Wave (2-Pass Triangular MA, win=35)", color="#2ca02c", lw=1.6)
    axes[1].axhline(0, color="black", linestyle=":", lw=0.8, alpha=0.6)

    for r_idx in final_reps:
        r_offset = r_idx - s_idx
        if 0 <= r_offset < len(sig):
            axes[1].scatter(r_idx / 100.0, sig[r_offset], color="crimson", marker="o", s=65, zorder=5)

    axes[1].set_ylabel("Tilt Wave (mG)", fontsize=10, fontweight="bold")
    axes[1].set_title("2. Zero-Phase Y-Axis Waveform (1-to-1 Stroke Cycle Verification)", fontsize=11, fontweight="bold")
    axes[1].legend(loc="upper right", fontsize=8)
    axes[1].grid(True, linestyle=":", alpha=0.5)

    # Row 3: Movement Envelope & Multi-Modal Consensus Triggers
    axes[2].plot(time_s, envs, label="Movement Envelope (37-sample MA |diff|)", color="#ff7f0e", lw=1.2, alpha=0.75)
    axes[2].axhline(40, color="orange", linestyle=":", lw=1.0, label="Movement Activity Floor (40 mG)")

    # Baseline triggers in Blue
    for r_idx in base_reps:
        axes[2].axvline(r_idx / 100.0, color="#1f77b4", linestyle=":", lw=1.1, alpha=0.5)
    axes[2].scatter([r / 100.0 for r in base_reps], [envs[r] for r in base_reps], color="#1f77b4", s=35, zorder=4, label=f"Baseline Primary ({len(base_reps)} reps)")

    # Final Cand 14 verified reps in Crimson
    for r_i, r_idx in enumerate(final_reps, 1):
        t_r = r_idx / 100.0
        env_val = envs[r_idx]
        axes[2].axvline(t_r, color="crimson", linestyle="--", lw=1.3, alpha=0.85)
        axes[2].scatter(t_r, env_val, color="crimson", s=50, zorder=5)
        axes[2].text(t_r, env_val + 14, f"#{r_i}", ha="center", va="bottom", fontsize=8, fontweight="bold", color="crimson")

    axes[2].scatter([], [], color="crimson", s=50, label=f"Cand 14 Consensus ({len(final_reps)} reps)")
    axes[2].set_xlabel("Time (seconds)", fontsize=10, fontweight="bold")
    axes[2].set_ylabel("Envelope (mG)", fontsize=10, fontweight="bold")
    axes[2].set_title(f"3. 1-to-1 Bipartite Consensus Repetitions (Detected = {len(final_reps)} vs True = {true_reps})", fontsize=11, fontweight="bold")
    axes[2].legend(loc="upper right", fontsize=8, ncol=3)
    axes[2].grid(True, linestyle=":", alpha=0.5)

    plt.tight_layout()
    plt.savefig(output_path, dpi=130)
    plt.close()
    print(f"Saved diagnostic plot: {output_path}")


def main():
    dataset, tr_split, te_split = load_all_dataset()
    targets = [
        "2026-10-17-09-44-55.fit",
        "2026-10-10-07-24-16.fit",
        "2026-10-24-15-15-53.fit",
        "2026-10-13-14-37-37.fit",
        "2026-10-21-05-57-53.fit",
    ]

    for fname in targets:
        item = next((d for d in dataset if d["filename"] == fname), None)
        if item is not None:
            out_name = f"cand14_{fname.replace('.fit', '.png')}"
            out_path = os.path.join(EXPERIMENTS_DIR, out_name)
            generate_plot(item, out_path)


if __name__ == "__main__":
    main()
