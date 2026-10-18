#!/usr/bin/env python3
"""
plot_spectral_diagnostics.py

Generates synchronized 3-row diagnostic figures sharing the exact X-axis:
- Row 1: Raw 3-axis acceleration (X, Y, Z separately) showing orientation & gravitational shifts.
- Row 2: Acceleration Magnitude (mG) with current candidate detection events & thresholds.
- Row 3: High-resolution STFT Spectrogram covering the full 0 to 50 Hz Nyquist range.

Saves high-res cards into spectral_inspection/.
"""

import os
import sys
import glob
from typing import List, Dict, Any
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import spectrogram

from eval_pipeline import extract_high_freq_accel, precompute_envelopes, simulate_pullup_online


def generate_spectral_plots(target_files: List[str] = None, output_dir: str = "spectral_inspection"):
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    out_path = os.path.join(workspace_dir, output_dir)
    os.makedirs(out_path, exist_ok=True)

    if target_files is None:
        target_files = [
            "data/2026-09-24-10-55-16.fit",
            "data/2026-09-24-11-10-58.fit",
            "data/2026-09-24-11-15-50.fit",
            "test.fit",
            "data/2026-09-22-18-38-40.fit",
            "data/2026-09-21-20-04-12.fit",
            "data/2026-09-24-13-09-25.fit"
        ]

    fs = 100.0  # 100 Hz hardware sampling rate

    for rel_path in target_files:
        full_path = os.path.join(workspace_dir, rel_path) if not os.path.isabs(rel_path) else rel_path
        if not os.path.exists(full_path):
            print(f"Skipping (not found): {full_path}")
            continue

        fname = os.path.basename(full_path)
        print(f"Generating spectral diagnostics for: {fname}...")

        df = extract_high_freq_accel(full_path)
        if df is None:
            continue

        n_samples = len(df)
        time_s = np.arange(n_samples) / fs

        x = df["x"].values.astype(np.float64)
        y = df["y"].values.astype(np.float64)
        z = df["z"].values.astype(np.float64)
        sq = x**2 + y**2 + z**2
        mags = np.sqrt(sq).astype(np.int32)
        diffs = np.abs(np.diff(mags, prepend=mags[0]))

        # Run candidate detector
        envelopes, dismount_events = precompute_envelopes(mags, diffs)
        rep_indices = simulate_pullup_online(
            envelopes, dismount_events,
            rep_threshold=120,
            reset_threshold=70,
            debounce_min=45,
            warmup_samples=100,
            cooldown_timeout_samples=100,
            min_wave_duration=45
        )

        fig, axes = plt.subplots(3, 1, figsize=(16, 11), sharex=True, dpi=130)
        plt.suptitle(f"Synchronized 3-Axis & Full-Nyquist Spectral Diagnostics: {fname} (Duration: {n_samples/fs:.1f}s | Det Reps: {len(rep_indices)})",
                     fontsize=14, fontweight="bold", y=0.98)

        # --------------------------------------------------------------------
        # Row 1: Raw 3-Axis Acceleration (X, Y, Z)
        # --------------------------------------------------------------------
        ax1 = axes[0]
        ax1.plot(time_s, x, color="#1f77b4", lw=0.9, alpha=0.85, label="X-axis (forearm long axis)")
        ax1.plot(time_s, y, color="#2ca02c", lw=0.9, alpha=0.85, label="Y-axis (wrist lateral)")
        ax1.plot(time_s, z, color="#d62728", lw=0.9, alpha=0.85, label="Z-axis (perpendicular / face)")
        ax1.axhline(0, color="gray", linestyle=":", lw=0.8)
        ax1.axhline(-1000, color="#1f77b4", linestyle="--", lw=0.8, alpha=0.6, label="-1G Static Hang Level (X ≈ -1000 mG)")
        ax1.set_ylabel("Acceleration (mG)", fontsize=10, fontweight="bold")
        ax1.set_title("1. Individual 3-Axis Components (Directional Gravity & Impact Shock)", fontsize=11, fontweight="bold")
        ax1.grid(True, linestyle=":", alpha=0.5)
        ax1.legend(loc="upper right", fontsize=8, ncol=4)

        # --------------------------------------------------------------------
        # Row 2: Magnitude & Candidate Detections
        # --------------------------------------------------------------------
        ax2 = axes[1]
        ax2.plot(time_s, mags, color="#2c3e50", lw=0.8, alpha=0.8, label="Raw Magnitude (mG)")
        ax2.plot(time_s, envelopes, color="#ff7f0e", lw=1.3, label="Causal Movement Envelope")
        ax2.axhline(1000, color="gray", linestyle=":", lw=0.9, alpha=0.7)
        ax2.axhline(1900, color="purple", linestyle="--", lw=1.0, alpha=0.7, label="1900 mG Impact Line")

        # Mark confirmed reps
        for idx, r in enumerate(rep_indices, 1):
            t_r = r / fs
            ax2.axvline(t_r, color="crimson", linestyle="--", lw=1.2, alpha=0.85)
            ax2.plot(t_r, envelopes[r], marker="o", markersize=6, color="crimson")
            ax2.text(t_r, envelopes[r] + 25, f"#{idx}", ha="center", va="bottom", fontsize=8, fontweight="bold", color="crimson")

        ax2.set_ylabel("Magnitude (mG)", fontsize=10, fontweight="bold")
        ax2.set_title("2. Accelerometer Magnitude & Online Repetition Triggers", fontsize=11, fontweight="bold")
        ax2.grid(True, linestyle=":", alpha=0.5)
        ax2.set_ylim(0, max(2600, np.max(mags) + 200))
        ax2.legend(loc="upper right", fontsize=8, ncol=3)

        # --------------------------------------------------------------------
        # --------------------------------------------------------------------
        # Row 3: Full 0 Hz to 50 Hz Nyquist Spectrogram (STFT)
        # --------------------------------------------------------------------
        ax3 = axes[2]
        # Detrend signal
        sig = mags - np.mean(mags)
        nperseg = 64   # 0.64s window for high temporal localization
        noverlap = 58  # ~90% overlap for crisp shock line resolution
        
        f, t_spec, Sxx = spectrogram(sig, fs=fs, nperseg=nperseg, noverlap=noverlap, window="hann")
        Sxx_log = 10 * np.log10(Sxx + 1e-6)

        im = ax3.pcolormesh(t_spec, f, Sxx_log, shading="gouraud", cmap="inferno", vmin=-10, vmax=35)
        ax3.set_ylabel("Frequency (Hz)", fontsize=10, fontweight="bold")
        ax3.set_xlabel("Time (seconds)", fontsize=10, fontweight="bold")
        ax3.set_title("3. Full-Nyquist Spectrogram (0 to 50 Hz) - Rep Cadence vs Broadband Landing Shock", fontsize=11, fontweight="bold")
        ax3.set_ylim(0, 50)
        ax3.set_xlim(time_s[0], time_s[-1])
        ax3.axhspan(0.3, 1.2, color="cyan", alpha=0.18, label="Pull-Up Rep Cadence (0.3 - 1.2 Hz)")
        ax3.axhspan(35, 50, color="magenta", alpha=0.12, label="High-Frequency Shock Band (35 - 50 Hz)")
        ax3.legend(loc="upper right", fontsize=8)

        # Ensure all 3 subplots have identical horizontal bounding boxes by attaching
        # an identical right divider to each axis (only displaying colorbar on row 3).
        from mpl_toolkits.axes_grid1 import make_axes_locatable
        divider1 = make_axes_locatable(ax1)
        cax1 = divider1.append_axes("right", size="2.5%", pad=0.12)
        cax1.axis("off")

        divider2 = make_axes_locatable(ax2)
        cax2 = divider2.append_axes("right", size="2.5%", pad=0.12)
        cax2.axis("off")

        divider3 = make_axes_locatable(ax3)
        cax3 = divider3.append_axes("right", size="2.5%", pad=0.12)
        cbar = fig.colorbar(im, cax=cax3)
        cbar.set_label("Spectral Power (dB)", fontsize=8)

        plt.tight_layout(rect=[0, 0.02, 1, 0.96])
        base_name = os.path.splitext(fname)[0]
        out_file = os.path.join(out_path, f"spectral_{base_name}.png")
        plt.savefig(out_file, dpi=130)
        plt.close()

    print(f"\nAll spectral diagnostic plots saved to: {out_path}\n")


if __name__ == "__main__":
    generate_spectral_plots()
