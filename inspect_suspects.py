#!/usr/bin/env python3
"""
inspect_suspects.py

Inspects the dataset in data/ for potential synthetic/shaking test artifacts or corrupted sets:
1. Extremely short duration (< 12 seconds).
2. Disproportionately high peak / rep frequency (> 1.2 Hz / rapid manual shaking).
3. Sets with zero sensor data or unlabeled status.
4. Large discrepancy between true reps and detected reps.
Generates PNG inspection plots in suspects_plots/ for visual review.
"""

import os
import glob
import re
from typing import List, Dict, Any
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from detect_pullups import extract_high_freq_accel, extract_true_reps
from eval_pipeline import precompute_envelopes, simulate_pullup_online, build_ground_truth_map


def inspect_dataset(data_dir: str = "data", workspace_dir: str = ".") -> List[Dict[str, Any]]:
    real_size_map = build_ground_truth_map(workspace_dir)
    fit_paths = sorted(glob.glob(os.path.join(data_dir, "*.fit")))
    results = []

    for fpath in fit_paths:
        fname = os.path.basename(fpath)
        sz = os.path.getsize(fpath)
        df = extract_high_freq_accel(fpath)

        if df is None or len(df) == 0:
            results.append({
                "path": fpath,
                "filename": fname,
                "duration_s": 0.0,
                "n_samples": 0,
                "true_reps": None,
                "det_reps": 0,
                "peak_freq": 0.0,
                "true_freq": 0.0,
                "reasons": ["No accelerometer sensor data logged"],
                "df": None
            })
            continue

        true_reps = extract_true_reps(fpath)
        source = "FIT session"
        if true_reps is None and sz in real_size_map:
            true_reps, source = real_size_map[sz]

        mags = np.sqrt(df["x"].astype(float)**2 + df["y"].astype(float)**2 + df["z"].astype(float)**2).values.astype(np.int32)
        diffs = np.abs(np.diff(mags, prepend=mags[0]))
        env, dis = precompute_envelopes(mags, diffs)

        reps_idx = simulate_pullup_online(env, dis, rep_threshold=120, reset_threshold=70, debounce_min=45, warmup_samples=100)
        det_reps = len(reps_idx)
        dur = len(df) / 25.0

        peaks_count = sum(1 for i in range(1, len(env) - 1) if env[i] > env[i - 1] and env[i] > env[i + 1] and env[i] >= 100)
        peak_freq = peaks_count / dur if dur > 0 else 0.0
        true_freq = (true_reps / dur) if (true_reps is not None and dur > 0) else 0.0

        reasons = []
        if dur < 12.0:
            reasons.append(f"Short duration ({dur:.1f}s < 12s)")
        if true_reps is None:
            reasons.append("Unlabeled / no confirmed reps")
        if peak_freq > 1.2:
            reasons.append(f"High peak freq ({peak_freq:.2f} Hz > 1.2 Hz)")
        if true_freq > 0.8:
            reasons.append(f"High rep rate ({true_freq:.2f} reps/s)")
        if true_reps is not None and abs(det_reps - true_reps) >= 3:
            reasons.append(f"Large error (|det-true| = {abs(det_reps - true_reps)})")

        results.append({
            "path": fpath,
            "filename": fname,
            "duration_s": dur,
            "n_samples": len(df),
            "true_reps": true_reps,
            "det_reps": det_reps,
            "peak_freq": peak_freq,
            "true_freq": true_freq,
            "reasons": reasons,
            "df": df,
            "env": env,
            "reps_idx": reps_idx,
            "mags": mags
        })

    return results


def plot_suspect(entry: Dict[str, Any], output_path: str):
    df = entry["df"]
    if df is None:
        return

    fs = 25.0
    time_s = np.arange(len(df)) / fs
    reps_idx = entry["reps_idx"]
    env = entry["env"]

    fig, axes = plt.subplots(2, 1, figsize=(13, 7), sharex=True)

    # Subplot 1: Raw Magnitude
    axes[0].plot(time_s, df["magnitude"], color="#1f77b4", lw=0.8, label="Accel Magnitude (mG)")
    for idx, p in enumerate(reps_idx, 1):
        axes[0].axvline(time_s[p], color="red", linestyle="--", alpha=0.8)
        axes[0].text(time_s[p], axes[0].get_ylim()[1] * 0.85, f"#{idx}", color="red", fontweight="bold", ha="center")
    axes[0].set_ylabel("Mag (mG)")
    axes[0].grid(True, linestyle=":", alpha=0.6)
    axes[0].legend(loc="upper right")
    true_str = f"True: {entry['true_reps']}" if entry['true_reps'] is not None else "True: Unknown"
    flag_str = " | ".join(entry["reasons"])
    axes[0].set_title(f"{entry['filename']} ({entry['duration_s']:.1f}s) | Det: {entry['det_reps']} | {true_str}\nFlags: {flag_str}", fontsize=11, fontweight="bold")

    # Subplot 2: Difference Envelope
    axes[1].plot(time_s, env, color="#6f42c1", lw=1.2, label="Moving Difference Envelope (mG)")
    axes[1].axhline(120, color="orange", linestyle="--", label="REP_THRESHOLD = 120 mG")
    axes[1].axhline(70, color="green", linestyle=":", label="RESET_THRESHOLD = 70 mG")
    for p in reps_idx:
        axes[1].axvline(time_s[p], color="red", linestyle="--", alpha=0.8)
    if reps_idx:
        axes[1].plot(time_s[reps_idx], env[reps_idx], "ro", label="Triggered Reps")
    axes[1].set_ylabel("Envelope (mG)")
    axes[1].set_xlabel("Time (seconds)")
    axes[1].grid(True, linestyle=":", alpha=0.6)
    axes[1].legend(loc="upper right")

    plt.tight_layout()
    plt.savefig(output_path, dpi=120)
    plt.close()


def main():
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(workspace_dir, "data")
    output_dir = os.path.join(workspace_dir, "suspects_plots")
    os.makedirs(output_dir, exist_ok=True)

    print("Analyzing dataset for synthetic / suspect workout files...")
    all_results = inspect_dataset(data_dir, workspace_dir)

    # Filter to suspect candidates
    suspects = [r for r in all_results if len(r["reasons"]) > 0]

    # Rank suspects by severity:
    # 1) files with sensor data that have multiple flags or extreme short duration / high frequency
    # 2) large discrepancy
    def severity_score(r):
        score = 0
        if r["duration_s"] == 0:
            return 100
        if r["duration_s"] < 12.0:
            score += 50
        if r["peak_freq"] > 1.2:
            score += 40
        if r["true_freq"] > 0.8:
            score += 30
        if r["true_reps"] is None:
            score += 20
        if r["true_reps"] is not None:
            score += abs(r["det_reps"] - r["true_reps"]) * 5
        return score

    suspects.sort(key=severity_score, reverse=True)

    print("\n" + "=" * 95)
    print(f" {'SUSPECT CANDIDATES SUMMARY':^93}")
    print("=" * 95)
    print(f" {'Filename':<25} | {'Duration':>8} | {'Samples':>7} | {'True':>5} | {'Det':>4} | {'Flags / Inspection Notes'}")
    print("-" * 95)

    for s in suspects:
        true_str = str(s["true_reps"]) if s["true_reps"] is not None else "N/A"
        reasons_str = "; ".join(s["reasons"])
        print(f" {s['filename']:<25} | {s['duration_s']:>7.1f}s | {s['n_samples']:>7d} | {true_str:>5} | {s['det_reps']:>4d} | {reasons_str}")
    print("=" * 95)

    # Plot top candidates with valid sensor data
    candidates_to_plot = [s for s in suspects if s["df"] is not None][:8]
    print(f"\nGenerating visual plots for top {len(candidates_to_plot)} suspects in '{output_dir}/'...")

    for rank, entry in enumerate(candidates_to_plot, 1):
        out_name = f"suspect_{rank}_{os.path.splitext(entry['filename'])[0]}.png"
        out_path = os.path.join(output_dir, out_name)
        plot_suspect(entry, out_path)
        print(f"  [{rank}] Saved plot: {out_name} (Duration: {entry['duration_s']:.1f}s, Flags: {', '.join(entry['reasons'])})")

    print("\nInspection complete.")


if __name__ == "__main__":
    main()
