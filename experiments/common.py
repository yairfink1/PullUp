"""
common.py

Shared utilities and evaluation metrics for Pull-Up detector experiments.
Provides:
  - Data loading and split partitioning (reusing eval_pipeline and train_test_eval)
  - Metrics calculation strictly matching eval_pipeline.evaluate_dataset:
      exact matches, within-1 matches, MAE, bias, total reps
  - O(1) causal circular buffer helpers portable to Monkey C
  - Causal bar hang / mount / dismount state tracking
"""

import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

# Add PullUp directory to sys.path so we can import eval_pipeline and train_test_eval
EXPERIMENTS_DIR = os.path.dirname(os.path.abspath(__file__))
PULLUP_DIR = os.path.dirname(EXPERIMENTS_DIR)
if PULLUP_DIR not in sys.path:
    sys.path.insert(0, PULLUP_DIR)

from eval_pipeline import load_dataset, evaluate_dataset
from train_test_eval import load_split


def load_train_test() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Loads all FIT workout sets from data/ and splits them into (train, test)
    based on split.json. Train has 56 sets; Test has 20 sets.
    """
    data_dir = os.path.join(PULLUP_DIR, "data")
    dataset, skipped = load_dataset(data_dir, PULLUP_DIR)
    if skipped:
        print(f"Notice: skipped {len(skipped)} files during load_dataset")
    train, test = load_split(dataset)
    return train, test


class HangTracker:
    """
    Causal, online O(1) bar hang & orientation gate.
    Portable to Garmin Monkey C:
      - Mount confirmation: Sustained forearm vertical hang (X in [-1300, -700] mG)
        for >= 35 consecutive samples (0.35s at 100 Hz).
      - Active hang: X <= -300 mG.
      - Dismount latch: Sustained departure (X > -300 mG) for >= 35 consecutive
        samples permanently latches set termination.
    """
    def __init__(
        self,
        hang_min_x: int = -1300,
        hang_max_x: int = -700,
        hang_streak_req: int = 35,
        x_release_threshold: int = -300,
        x_latch_streak_len: int = 35,
    ):
        self.hang_min_x = hang_min_x
        self.hang_max_x = hang_max_x
        self.hang_streak_req = hang_streak_req
        self.x_release_threshold = x_release_threshold
        self.x_latch_streak_len = x_latch_streak_len

        self.has_hung = False
        self.mount_streak = 0
        self.dismount_streak = 0
        self.set_locked = False
        self.hang_start_idx = -1

    def update(self, i: int, cur_x: float) -> Tuple[bool, bool, bool]:
        """
        Processes one sample at index i with raw X acceleration.
        Returns (has_hung, in_hang, set_locked).
        """
        if self.set_locked:
            return self.has_hung, False, True

        # 1. Mount detection: require sustained vertical lock
        if not self.has_hung:
            if self.hang_min_x <= cur_x <= self.hang_max_x:
                self.mount_streak += 1
                if self.mount_streak >= self.hang_streak_req:
                    self.has_hung = True
                    self.hang_start_idx = i
            else:
                self.mount_streak = 0
        else:
            # 2. Dismount latch: count continuous samples above release threshold
            if cur_x > self.x_release_threshold:
                self.dismount_streak += 1
                if self.dismount_streak >= self.x_latch_streak_len:
                    self.set_locked = True
                    return self.has_hung, False, True
            else:
                self.dismount_streak = 0

        in_hang = self.has_hung and (cur_x <= self.x_release_threshold) and not self.set_locked
        return self.has_hung, in_hang, self.set_locked


def compute_envelope(diffs: np.ndarray, window_size: int = 37) -> np.ndarray:
    """
    Computes causal moving average of absolute magnitude differences
    using O(1) circular buffer integer arithmetic, matching Monkey C.
    """
    n = len(diffs)
    diff_buf = [0] * window_size
    buf_idx = 0
    buf_sum = 0
    envelopes = np.zeros(n, dtype=np.int32)

    for i in range(n):
        d = int(diffs[i])
        buf_sum += d - diff_buf[buf_idx]
        diff_buf[buf_idx] = d
        buf_idx = (buf_idx + 1) % window_size
        envelopes[i] = buf_sum // window_size

    return envelopes


def compute_smoothed_axis(values: np.ndarray, window_size: int = 25) -> np.ndarray:
    """
    Computes causal moving average of an axis using O(1) circular buffer arithmetic.
    """
    n = len(values)
    buf = [0] * window_size
    buf_idx = 0
    buf_sum = 0
    smoothed = np.zeros(n, dtype=np.int32)

    for i in range(n):
        v = int(values[i])
        buf_sum += v - buf[buf_idx]
        buf[buf_idx] = v
        buf_idx = (buf_idx + 1) % window_size
        count = min(i + 1, window_size)
        smoothed[i] = buf_sum // count

    return smoothed


def calculate_metrics(
    dataset: List[Dict[str, Any]],
    detect_fn: Callable[..., List[int]],
    **params: Any,
) -> Dict[str, Any]:
    """
    Evaluates a candidate detection function on the provided dataset.
    Computes metrics identical to eval_pipeline.evaluate_dataset:
      exact_matches, exact_pct, within_1_matches, within_1_pct,
      mae, bias, total_true, total_detected, file_results.
    """
    results = []
    total_true = 0
    total_detected = 0
    overcount_sets = 0
    undercount_sets = 0
    exact_matches = 0
    abs_errors = []

    for item in dataset:
        df = item["df"]
        true_count = item["true_reps"]

        rep_indices = detect_fn(df, **params)
        detected_count = len(rep_indices)
        err = detected_count - true_count

        total_true += true_count
        total_detected += detected_count
        abs_errors.append(abs(err))

        if err == 0:
            exact_matches += 1
        elif err > 0:
            overcount_sets += 1
        else:
            undercount_sets += 1

        results.append({
            "filename": item["filename"],
            "true_reps": true_count,
            "detected_reps": detected_count,
            "error": err,
            "abs_error": abs(err),
            "rep_indices": rep_indices,
            "duration_s": item.get("duration_s", len(df) / 100.0),
        })

    n = len(dataset)
    signed_errors = [r["error"] for r in results]
    within_1_matches = sum(1 for r in results if r["abs_error"] <= 1)

    mae = float(np.mean(abs_errors)) if n > 0 else 0.0
    bias = float(np.mean(signed_errors)) if n > 0 else 0.0
    exact_pct = (exact_matches / n * 100.0) if n > 0 else 0.0
    within_1_pct = (within_1_matches / n * 100.0) if n > 0 else 0.0

    return {
        "mae": mae,
        "bias": bias,
        "exact_matches": exact_matches,
        "exact_pct": exact_pct,
        "within_1_matches": within_1_matches,
        "within_1_pct": within_1_pct,
        "total_true": total_true,
        "total_detected": total_detected,
        "net_diff": total_detected - total_true,
        "overcount_sets": overcount_sets,
        "undercount_sets": undercount_sets,
        "n_sets": n,
        "file_results": results,
        "params": params,
    }


def evaluate_baseline(dataset: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Evaluates the existing baseline detector (simulate_pullup_online) via evaluate_dataset.
    """
    return evaluate_dataset(dataset)


def format_metrics(name: str, metrics: Dict[str, Any]) -> str:
    """
    One-line summary for displaying evaluation metrics.
    """
    return (
        f"{name:<6} n={metrics['n_sets']:>3} | "
        f"exact {metrics['exact_matches']:>2}/{metrics['n_sets']} ({metrics['exact_pct']:5.1f}%) | "
        f"within1 {metrics['within_1_matches']:>2}/{metrics['n_sets']} ({metrics['within_1_pct']:5.1f}%) | "
        f"MAE {metrics['mae']:.3f} | bias {metrics['bias']:+.3f} | "
        f"reps {metrics['total_true']} vs {metrics['total_detected']}"
    )
