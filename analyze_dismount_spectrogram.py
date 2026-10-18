#!/usr/bin/env python3
"""
analyze_dismount_spectrogram.py

Computes STFT Spectrograms and raw acceleration time-series across representative
sets (e.g. 2026-09-24-10-55-16.fit, 2026-09-24-11-10-58.fit, test.fit) to visualize:
- Low-frequency pull-up repetitions (0.3 - 1.0 Hz)
- Broadband shock impulse at the landing/dismount drop (> 10 - 35 Hz)

Saves diagnostic figure to spectrogram_analysis.png.
"""

import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from scipy.signal import spectrogram

from eval_pipeline import extract_high_freq_accel


def analyze_spectrograms(output_path: str = "spectrogram_analysis.png"):
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    target_files = [
        os.path.join(workspace_dir, "data", "2026-09-24-10-55-16.fit"),
        os.path.join(workspace_dir, "data", "2026-09-24-11-10-58.fit"),
        os.path.join(workspace_dir, "test.fit")
    ]

    fs = 100.0  # 100 Hz sample rate
    fig, axes = plt.subplots(len(target_files), 2, figsize=(16, 12), dpi=150)
    plt.suptitle("Garmin Pull-Up Acceleration & STFT Spectrogram Analysis: Reps vs. Dismount Impact",
                 fontsize=14, fontweight="bold", y=0.98)

    for row_idx, file_path in enumerate(target_files):
        fname = os.path.basename(file_path)
        if not os.path.exists(file_path):
            print(f"File not found: {file_path}")
            continue

        df = extract_high_freq_accel(file_path)
        if df is None:
            continue

        sq = df["x"].values.astype(np.int64)**2 + df["y"].values.astype(np.int64)**2 + df["z"].values.astype(np.int64)**2
        mags = np.sqrt(sq).astype(np.float64)
        n_samples = len(mags)
        time_s = np.arange(n_samples) / fs

        # --------------------------------------------------------------------
        # Left: Raw Acceleration Magnitude with 1G & 1900 mG thresholds
        # --------------------------------------------------------------------
        ax_time = axes[row_idx, 0]
        ax_time.plot(time_s, mags, color="#2c3e50", lw=0.9, alpha=0.9, label="Magnitude (mG)")
        ax_time.axhline(1000, color="gray", linestyle=":", lw=1.0, alpha=0.8, label="1G Static Level")
        ax_time.axhline(1900, color="purple", linestyle="--", lw=1.0, alpha=0.8, label="High-G Impact (1900 mG)")
        ax_time.set_title(f"Time Series: {fname} (Duration: {n_samples/fs:.1f}s)", fontsize=11, fontweight="bold")
        ax_time.set_ylabel("Magnitude (mG)", fontsize=10)
        ax_time.set_xlabel("Time (s)", fontsize=9)
        ax_time.grid(True, linestyle=":", alpha=0.5)
        ax_time.set_ylim(0, max(3500, np.max(mags) + 200))
        ax_time.legend(loc="upper right", fontsize=8)

        # --------------------------------------------------------------------
        # Right: STFT Spectrogram (Broadband shock vs rep cadence)
        # --------------------------------------------------------------------
        ax_spec = axes[row_idx, 1]
        
        # Detrend for spectral analysis (subtract mean 1000 mG)
        sig = mags - np.mean(mags)
        nperseg = 128  # 1.28s window
        noverlap = 112  # ~87% overlap for high time resolution
        
        f, t_spec, Sxx = spectrogram(sig, fs=fs, nperseg=nperseg, noverlap=noverlap, window="hann")

        # Log power
        Sxx_log = 10 * np.log10(Sxx + 1e-6)
        
        im = ax_spec.pcolormesh(t_spec, f, Sxx_log, shading="gouraud", cmap="inferno", vmin=-10, vmax=35)
        ax_spec.set_title(f"Spectrogram (STFT): {fname}", fontsize=11, fontweight="bold")
        ax_spec.set_ylabel("Frequency (Hz)", fontsize=10)
        ax_spec.set_xlabel("Time (s)", fontsize=9)
        ax_spec.set_ylim(0, 35)  # Focus up to 35 Hz
        ax_spec.axhspan(0.3, 1.2, color="cyan", alpha=0.18, label="Pull-Up Rep Band (0.3 - 1.2 Hz)")
        ax_spec.axhline(10.0, color="white", linestyle="--", lw=0.9, alpha=0.7, label="Shock Impulse Band (> 10 Hz)")
        ax_spec.legend(loc="upper right", fontsize=8)

        cbar = fig.colorbar(im, ax=ax_spec, fraction=0.046, pad=0.04)
        cbar.set_label("Power (dB)", fontsize=8)

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"Spectrogram analysis saved successfully to: {output_path}")


if __name__ == "__main__":
    out_file = sys.argv[1] if len(sys.argv) > 1 else "spectrogram_analysis.png"
    analyze_spectrograms(out_file)
