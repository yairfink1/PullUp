#!/usr/bin/env python3
"""
plot_dataset_errors.py

Generates a comprehensive 4-quadrant diagnostic dashboard for the dataset,
fully synchronized with generate_inspection_gallery.py and cand14 post-set consensus:
1. Subplot 1: Distribution of True Reps (Histogram / Bar chart) split by TRAIN vs TEST2
2. Subplot 2: True Reps vs. Detected Reps (Parity Plot with split markers)
3. Subplot 3: Detection Residuals (True - Detected) vs. Duration and Rep Count
4. Subplot 4: Summary Table of Outliers / Evaluation Scorecard
Saves high-resolution figure to dataset_analysis.png.
"""

import os
import sys
import json
from typing import List, Dict, Any, Set
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.lines import Line2D

from eval_pipeline import load_dataset, precompute_envelopes
from config import DETECTOR_CONFIG
import experiments.cand14_postset_consensus as cand14


def load_test_set_names(workspace_dir: str) -> Set[str]:
    """Loads held-out test set filenames from split.json if available."""
    split_path = os.path.join(workspace_dir, "split.json")
    if os.path.isfile(split_path):
        with open(split_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return set(data.get("test2", data.get("test", [])))
    return set()


def evaluate_dataset_with_cand14(dataset: List[Dict[str, Any]], test_names: Set[str]) -> Dict[str, Any]:
    """
    Evaluates dataset using cand14 consensus matching (matching generate_inspection_gallery.py).
    """
    results = []
    total_true = 0
    total_detected = 0
    exact_matches = 0
    overcount_sets = 0
    undercount_sets = 0
    within_1_count = 0
    abs_errors = []

    train_exact = 0
    train_within_1 = 0
    train_total = 0
    train_abs_errors = []
    test_exact = 0
    test_within_1 = 0
    test_total = 0
    test_abs_errors = []

    fs = 100.0

    for item in dataset:
        fname = item["filename"]
        is_test = fname in test_names
        df = item["df"]
        true_reps = item["true_reps"]
        n_samples = len(df)
        duration_s = n_samples / fs

        confirmed, _, _, _, _, _ = cand14.detect_with_channels(df)
        det_reps = len(confirmed)
        error = det_reps - true_reps
        abs_err = abs(error)

        total_true += true_reps
        total_detected += det_reps
        abs_errors.append(abs_err)

        if abs_err <= 1:
            within_1_count += 1
            if is_test:
                test_within_1 += 1
            else:
                train_within_1 += 1

        if error == 0:
            exact_matches += 1
            if is_test:
                test_exact += 1
            else:
                train_exact += 1
        elif error > 0:
            overcount_sets += 1
        else:
            undercount_sets += 1

        if is_test:
            test_total += 1
            test_abs_errors.append(abs_err)
        else:
            train_total += 1
            train_abs_errors.append(abs_err)

        results.append({
            "filename": fname,
            "is_test": is_test,
            "true_reps": true_reps,
            "detected_reps": det_reps,
            "error": error,
            "abs_error": abs_err,
            "duration_s": duration_s
        })

    n_total = len(dataset)
    mae = float(np.mean(abs_errors)) if abs_errors else 0.0

    return {
        "file_results": results,
        "n_total": n_total,
        "total_true": total_true,
        "total_detected": total_detected,
        "exact_matches": exact_matches,
        "overcount_sets": overcount_sets,
        "undercount_sets": undercount_sets,
        "within_1_count": within_1_count,
        "mae": mae,
        "train_total": train_total,
        "train_exact": train_exact,
        "train_within_1": train_within_1,
        "train_mae": float(np.mean(train_abs_errors)) if train_abs_errors else 0.0,
        "test_total": test_total,
        "test_exact": test_exact,
        "test_within_1": test_within_1,
        "test_mae": float(np.mean(test_abs_errors)) if test_abs_errors else 0.0,
    }


def generate_dashboard(output_path: str = "dataset_analysis.png"):
    workspace_dir = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(workspace_dir, "data")

    print(f"Loading cleaned dataset from: {data_dir}")
    dataset, skipped = load_dataset(data_dir, workspace_dir)
    test_names = load_test_set_names(workspace_dir)
    print(f"Loaded {len(dataset)} valid workout sets ({len(dataset) - len(test_names)} TRAIN, {len(test_names)} TEST2; skipped {len(skipped)}).")

    # Evaluate using cand14 consensus detector (identical to generate_inspection_gallery.py)
    print("Evaluating with Candidate 14 post-set consensus detector...")
    metrics = evaluate_dataset_with_cand14(dataset, test_names)

    results = metrics["file_results"]
    true_reps = np.array([r["true_reps"] for r in results])
    det_reps = np.array([r["detected_reps"] for r in results])
    errors = np.array([r["error"] for r in results])
    residuals = true_reps - det_reps  # Positive: undercounted reps
    durations = np.array([r["duration_s"] for r in results])
    is_test_mask = np.array([r["is_test"] for r in results])

    fig = plt.figure(figsize=(16, 12), dpi=150)
    plt.suptitle(
        f"Garmin Pull-Up Dataset Analysis & Detector Diagnostics (Cand 14 Consensus)\n"
        f"Total: {metrics['n_total']} Sets | Exact: {metrics['exact_matches']}/{metrics['n_total']} ({metrics['exact_matches']/metrics['n_total']*100:.1f}%) | "
        f"±1 Rep: {metrics['within_1_count']}/{metrics['n_total']} ({metrics['within_1_count']/metrics['n_total']*100:.1f}%) | MAE: {metrics['mae']:.3f} reps/set",
        fontsize=14, fontweight="bold", y=0.98
    )

    # ------------------------------------------------------------------------
    # Subplot 1: Distribution of True Reps (Stacked TRAIN vs TEST2)
    # ------------------------------------------------------------------------
    ax1 = fig.add_subplot(2, 2, 1)
    max_rep = int(np.max(true_reps)) if len(true_reps) > 0 else 20
    all_reps = np.arange(1, max_rep + 2)
    train_counts = [np.sum((true_reps == r) & (~is_test_mask)) for r in all_reps]
    test_counts = [np.sum((true_reps == r) & is_test_mask) for r in all_reps]

    p1 = ax1.bar(all_reps, train_counts, width=0.75, color="#2b5c8f", edgecolor="black", alpha=0.85, label=f"TRAIN ({metrics['train_total']})")
    p2 = ax1.bar(all_reps, test_counts, bottom=train_counts, width=0.75, color="#e67e22", edgecolor="black", alpha=0.85, label=f"TEST2 ({metrics['test_total']})")

    ax1.set_title(f"1. Distribution of True Reps ({len(results)} Total Sets)", fontsize=11, fontweight="bold")
    ax1.set_xlabel("True Rep Count", fontsize=10)
    ax1.set_ylabel("Number of Workout Sets", fontsize=10)
    ax1.grid(True, linestyle=":", alpha=0.6, axis="y")
    ax1.set_xticks(np.arange(0, max_rep + 2, 2))
    ax1.legend(loc="upper right", fontsize=9)

    for i, r in enumerate(all_reps):
        tot = train_counts[i] + test_counts[i]
        if tot > 0:
            ax1.text(r, tot + 0.15, str(tot), ha="center", va="bottom", fontsize=8.5, fontweight="bold")

    # ------------------------------------------------------------------------
    # Subplot 2: True Reps vs. Detected Reps (Parity Plot)
    # ------------------------------------------------------------------------
    ax2 = fig.add_subplot(2, 2, 2)
    max_val = max(np.max(true_reps), np.max(det_reps)) + 2 if len(true_reps) > 0 else 25
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

    # TRAIN as circles, TEST2 as stars
    train_idx = np.where(~is_test_mask)[0]
    test_idx = np.where(is_test_mask)[0]

    if len(train_idx) > 0:
        ax2.scatter(
            true_reps[train_idx], det_reps[train_idx],
            c=[colors[i] for i in train_idx],
            s=65, marker="o", edgecolors="black", linewidth=0.8, zorder=5, label="TRAIN Set"
        )
    if len(test_idx) > 0:
        ax2.scatter(
            true_reps[test_idx], det_reps[test_idx],
            c=[colors[i] for i in test_idx],
            s=120, marker="*", edgecolors="black", linewidth=0.9, zorder=6, label="TEST2 Set"
        )

    ax2.set_title("2. True Reps vs. Detected Reps (Parity)", fontsize=11, fontweight="bold")
    ax2.set_xlabel("True Reps (Confirmed Ground Truth)", fontsize=10)
    ax2.set_ylabel("Detected Reps (Cand 14 Consensus)", fontsize=10)
    ax2.set_xlim(0, max_val)
    ax2.set_ylim(0, max_val)
    ax2.grid(True, linestyle=":", alpha=0.6)

    # Custom legend
    legend_elements = [
        Line2D([0], [0], color="k", linestyle="--", label="Ideal Parity (y = x)"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#28a745", markersize=8, markeredgecolor="k", label=f"Exact Match ({metrics['exact_matches']})"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#dc3545", markersize=8, markeredgecolor="k", label=f"Undercount ({metrics['undercount_sets']})"),
        Line2D([0], [0], marker="o", color="w", markerfacecolor="#007bff", markersize=8, markeredgecolor="k", label=f"Overcount ({metrics['overcount_sets']})"),
        Line2D([0], [0], marker="*", color="w", markerfacecolor="#e67e22", markersize=10, markeredgecolor="k", label=f"TEST2 Set ({metrics['test_total']})"),
    ]
    ax2.legend(handles=legend_elements, loc="upper left", fontsize=8.5)

    # ------------------------------------------------------------------------
    # Subplot 3: Residual / Error Plot (True - Detected vs Duration)
    # ------------------------------------------------------------------------
    ax3 = fig.add_subplot(2, 2, 3)
    ax3.axhline(0, color="black", linestyle="-", lw=1.2)
    ax3.axhspan(-1, 1, color="green", alpha=0.12, label="Acceptable Band (±1 Rep)")

    sc = ax3.scatter(durations, residuals, c=true_reps, cmap="viridis", s=70, edgecolors="black", linewidth=0.8, zorder=5)
    cbar = plt.colorbar(sc, ax=ax3)
    cbar.set_label("True Rep Count", fontsize=9)

    ax3.set_title("3. Detection Residuals (True - Detected) vs. Workout Duration", fontsize=11, fontweight="bold")
    ax3.set_xlabel("Workout Duration (seconds)", fontsize=10)
    ax3.set_ylabel("Residual: True - Detected Reps", fontsize=10)
    ax3.grid(True, linestyle=":", alpha=0.6)
    ax3.legend(loc="upper left", fontsize=8.5)

    # Annotate outlier files (|residual| >= 2)
    for i, r in enumerate(results):
        if abs(residuals[i]) >= 2:
            tag = " [TEST2]" if r["is_test"] else ""
            ax3.annotate(
                f"{r['filename'][-12:-4]}{tag} ({r['true_reps']}r, {residuals[i]:+d})",
                (durations[i], residuals[i]),
                xytext=(0, 7 if residuals[i] > 0 else -14),
                textcoords="offset points",
                fontsize=8,
                ha="center",
                fontweight="bold",
                color="#b30000" if residuals[i] > 0 else "#004085"
            )

    # ------------------------------------------------------------------------
    # Subplot 4: Summary Table of Outliers (|Error| >= 1)
    # ------------------------------------------------------------------------
    ax4 = fig.add_subplot(2, 2, 4)
    ax4.axis("off")
    ax4.set_title("4. Error Outliers & Set Breakdown", fontsize=11, fontweight="bold")

    outliers = [r for r in results if r["abs_error"] > 0]
    outliers.sort(key=lambda x: (x["abs_error"], x["is_test"]), reverse=True)

    table_data = []
    # Cap displayed rows to top 14 so it renders legibly
    for o in outliers[:14]:
        sign = "+" if o["error"] > 0 else ""
        split_lbl = "TEST2" if o["is_test"] else "TRAIN"
        table_data.append([
            split_lbl,
            o["filename"],
            str(o["true_reps"]),
            str(o["detected_reps"]),
            f"{sign}{o['error']}",
            f"{o['duration_s']:.1f}s"
        ])

    if table_data:
        table = ax4.table(
            cellText=table_data,
            colLabels=["Split", "Filename", "True", "Det", "Error", "Duration"],
            colWidths=[0.14, 0.40, 0.11, 0.11, 0.12, 0.12],
            loc="center",
            cellLoc="center"
        )
        table.auto_set_font_size(False)
        table.set_fontsize(8.5)
        table.scale(1.0, 1.35)

        # Style table header and cells
        for (row, col), cell in table.get_celld().items():
            if row == 0:
                cell.set_facecolor("#2b5c8f")
                cell.set_text_props(color="white", fontweight="bold")
            else:
                err_val = int(outliers[row - 1]["error"])
                is_t = outliers[row - 1]["is_test"]
                if is_t:
                    cell.set_facecolor("#fff3cd")  # Light amber for test set
                elif err_val < 0:
                    cell.set_facecolor("#ffeef0")
                elif err_val > 0:
                    cell.set_facecolor("#eef6ff")
    else:
        ax4.text(
            0.5, 0.5,
            f"Zero Outliers!\n{metrics['exact_matches']} / {metrics['n_total']} (100.0%) Exact Match\nMAE: 0.000 reps/set",
            ha="center", va="center", fontsize=14, fontweight="bold", color="#155724",
            bbox=dict(boxstyle="round,pad=0.8", facecolor="#d4edda", edgecolor="#28a745", lw=2)
        )

    plt.tight_layout(rect=[0, 0.03, 1, 0.95])
    fig_path = output_path if os.path.isabs(output_path) else os.path.join(workspace_dir, output_path)
    plt.savefig(fig_path, dpi=150)
    plt.close()
    print(f"Diagnostics dashboard successfully saved to: {fig_path}\n")

    print("=" * 72)
    print(" PULLUP DATASET EVALUATION SUMMARY (TRAIN vs TEST2)")
    print("=" * 72)
    print(f" Total Workout Sets   : {metrics['n_total']} ({metrics['train_total']} TRAIN, {metrics['test_total']} TEST2)")
    if metrics["train_total"] > 0:
        print(f" TRAIN Exact Matches  : {metrics['train_exact']}/{metrics['train_total']} ({metrics['train_exact']/metrics['train_total']*100:.1f}%) | +/-1 Rep: {metrics['train_within_1']}/{metrics['train_total']} ({metrics['train_within_1']/metrics['train_total']*100:.1f}%) | MAE: {metrics['train_mae']:.3f}")
    if metrics["test_total"] > 0:
        print(f" TEST2 Exact Matches  : {metrics['test_exact']}/{metrics['test_total']} ({metrics['test_exact']/metrics['test_total']*100:.1f}%) | +/-1 Rep: {metrics['test_within_1']}/{metrics['test_total']} ({metrics['test_within_1']/metrics['test_total']*100:.1f}%) | MAE: {metrics['test_mae']:.3f}")
    print(f" Overall Exact Match  : {metrics['exact_matches']}/{metrics['n_total']} ({metrics['exact_matches']/metrics['n_total']*100:.1f}%) | MAE: {metrics['mae']:.3f} reps")
    print("=" * 72)


if __name__ == "__main__":
    out_file = sys.argv[1] if len(sys.argv) > 1 else "dataset_analysis.png"
    generate_dashboard(out_file)
