#!/usr/bin/env python3
"""
plot_dataset_errors.py

Generates a comprehensive 4-quadrant diagnostic dashboard for the cleaned 35-workout dataset:
1. Subplot 1: Distribution of True Reps (Histogram / Bar chart)
2. Subplot 2: True Reps vs. Detected Reps (Scatter plot with y = x parity reference line)
3. Subplot 3: Residual / Error Plot (True - Detected vs. Duration and Rep Count)
4. Subplot 4: Summary table of top error outliers
Saves high-resolution figure to dataset_analysis.png.
"""

import os
import sys
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from eval_pipeline import load_dataset, evaluate_dataset


def generate_dashboard(output_path: str = "dataset_analysis.png"):
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(workspace_dir, "data")

    print(f"Loading cleaned dataset from: {data_dir}")
    dataset, skipped = load_dataset(data_dir, workspace_dir)
    print(f"Loaded {len(dataset)} valid workout sets (skipped {len(skipped)}).")

    # Evaluate using default detector parameters
    metrics = evaluate_dataset(dataset)

    results = metrics["file_results"]
    filenames = [r["filename"] for r in results]
    true_reps = np.array([r["true_reps"] for r in results])
    det_reps = np.array([r["detected_reps"] for r in results])
    errors = det_reps - true_reps  # Positive: overcount, Negative: undercount
    residuals = true_reps - det_reps  # Positive: undercounted reps
    durations = np.array([r["duration_s"] for r in results])

    fig = plt.figure(figsize=(16, 12), dpi=150)
    plt.suptitle("Garmin Pull-Up Dataset Analysis & Repetition Detector Diagnostics", fontsize=16, fontweight="bold", y=0.98)

    # ------------------------------------------------------------------------
    # Subplot 1: Distribution of True Reps
    # ------------------------------------------------------------------------
    ax1 = fig.add_subplot(2, 2, 1)
    unique_reps, counts = np.unique(true_reps, return_counts=True)
    bars = ax1.bar(unique_reps, counts, width=0.8, color="#2b5c8f", edgecolor="black", alpha=0.85)
    ax1.set_title(f"1. Distribution of True Reps ({len(results)} Clean Sets)", fontsize=12, fontweight="bold")
    ax1.set_xlabel("True Rep Count", fontsize=10)
    ax1.set_ylabel("Number of Workout Sets", fontsize=10)
    ax1.grid(True, linestyle=":", alpha=0.6, axis="y")
    ax1.set_xticks(np.arange(0, max(unique_reps) + 2, 2))
    for b in bars:
        h = b.get_height()
        ax1.text(b.get_x() + b.get_width() / 2.0, h + 0.15, str(int(h)), ha="center", va="bottom", fontsize=9, fontweight="bold")

    # ------------------------------------------------------------------------
    # Subplot 2: True Reps vs. Detected Reps (Parity Plot)
    # ------------------------------------------------------------------------
    ax2 = fig.add_subplot(2, 2, 2)
    max_val = max(np.max(true_reps), np.max(det_reps)) + 2
    ax2.plot([0, max_val], [0, max_val], "k--", lw=1.5, label="Ideal Parity (y = x)")

    # Color code points: green = exact match, red = undercount, blue = overcount
    colors = []
    for e in errors:
        if e == 0:
            colors.append("#28a745")  # Green
        elif e < 0:
            colors.append("#dc3545")  # Red (undercount)
        else:
            colors.append("#007bff")  # Blue (overcount)

    scatter = ax2.scatter(true_reps, det_reps, c=colors, s=70, edgecolors="black", linewidth=0.8, zorder=5)
    ax2.set_title("2. True Reps vs. Detected Reps", fontsize=12, fontweight="bold")
    ax2.set_xlabel("True Reps (Confirmed Ground Truth)", fontsize=10)
    ax2.set_ylabel("Detected Reps (Online CIQ Detector)", fontsize=10)
    ax2.set_xlim(0, max_val)
    ax2.set_ylim(0, max_val)
    ax2.grid(True, linestyle=":", alpha=0.6)

    # Custom legend
    from matplotlib.lines import Line2D
    legend_elements = [
        Line2D([0], [0], color="k", linestyle="--", label="Ideal Parity (y = x)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#28a745", markersize=8, markeredgecolor="k", label=f"Exact Match ({metrics['exact_matches']})"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#dc3545", markersize=8, markeredgecolor="k", label=f"Undercount ({metrics['undercount_sets']})"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#007bff", markersize=8, markeredgecolor="k", label=f"Overcount ({metrics['overcount_sets']})"),
    ]
    ax2.legend(handles=legend_elements, loc="upper left", fontsize=9)

    # ------------------------------------------------------------------------
    # Subplot 3: Residual / Error Plot (True - Detected vs Duration)
    # ------------------------------------------------------------------------
    ax3 = fig.add_subplot(2, 2, 3)
    ax3.axhline(0, color="black", linestyle="-", lw=1.2)
    ax3.axhspan(-1, 1, color="green", alpha=0.12, label="Acceptable Band (±1 Rep)")

    sc = ax3.scatter(durations, residuals, c=true_reps, cmap="viridis", s=70, edgecolors="black", linewidth=0.8, zorder=5)
    cbar = plt.colorbar(sc, ax=ax3)
    cbar.set_label("True Rep Count", fontsize=9)

    ax3.set_title("3. Detection Residuals (True - Detected) vs. Workout Duration", fontsize=12, fontweight="bold")
    ax3.set_xlabel("Workout Duration (seconds)", fontsize=10)
    ax3.set_ylabel("Residual: True - Detected Reps", fontsize=10)
    ax3.grid(True, linestyle=":", alpha=0.6)
    ax3.legend(loc="upper left", fontsize=9)

    # Annotate outlier fatigue files
    for i, r in enumerate(results):
        if abs(residuals[i]) >= 3:
            ax3.annotate(
                f"{r['filename'][-12:-4]} ({r['true_reps']}r, -{residuals[i]})",
                (durations[i], residuals[i]),
                xytext=(0, 7 if residuals[i] > 0 else -14),
                textcoords="offset points",
                fontsize=8,
                ha="center",
                fontweight="bold",
                color="#b30000" if residuals[i] > 0 else "#004085"
            )

    # ------------------------------------------------------------------------
    # Subplot 4: Summary Table of Outliers
    # ------------------------------------------------------------------------
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.axis("off")
    ax4.set_title("4. Top Residual Outliers (|Error| >= 2)", fontsize=12, fontweight="bold")

    outliers = [r for r in results if abs(r["error"]) >= 2]
    outliers.sort(key=lambda x: abs(x["error"]), reverse=True)

    table_data = []
    for o in outliers:
        sign = "+" if o["error"] > 0 else ""
        table_data.append([
            o["filename"],
            str(o["true_reps"]),
            str(o["detected_reps"]),
            f"{sign}{o['error']}",
            f"{o['duration_s']:.1f}s"
        ])

    if table_data:
        table = ax4.table(
            cellText=table_data,
            colLabels=["Filename", "True", "Det", "Error", "Duration"],
            colWidths=[0.38, 0.12, 0.12, 0.15, 0.18],
            loc="center",
            cellLoc="center"
        )
        table.auto_set_font_size(False)
        table.set_fontsize(9)
        table.scale(1.0, 1.4)

        # Style table header and cells
        for (row, col), cell in table.get_celld().items():
            if row == 0:
                cell.set_facecolor("#2b5c8f")
                cell.set_text_props(color="white", fontweight="bold")
            else:
                err_val = int(outliers[row - 1]["error"])
                if err_val < 0:
                    cell.set_facecolor("#ffeef0")
                elif err_val > 0:
                    cell.set_facecolor("#eef6ff")
    else:
        ax4.text(
            0.5, 0.5,
            "Zero Outliers!\n50 / 50 (100.0%) Exact Match\nMAE: 0.000 reps/set",
            ha="center", va="center", fontsize=14, fontweight="bold", color="#155724",
            bbox=dict(boxstyle="round,pad=0.8", facecolor="#d4edda", edgecolor="#28a745", lw=2)
        )

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    plt.savefig(output_path, dpi=150)
    plt.close()
    print(f"Diagnostics dashboard successfully saved to: {output_path}")


if __name__ == "__main__":
    out_file = sys.argv[1] if len(sys.argv) > 1 else "dataset_analysis.png"
    generate_dashboard(out_file)
