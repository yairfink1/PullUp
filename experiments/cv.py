"""
cv.py

Stratified K-Fold Cross-Validation Framework for Pull-Up Repetition Detection.
Evaluates detectors across all 76 workout sets in data/, partitioned into 5 folds
stratified by ground-truth rep count (seed = 42).

Primary evaluation metric for candidate selection:
  - Held-out 5-fold CV Exact %, Within-1 %, MAE, and Bias.
  - Also computes performance on original split.json (56 train / 20 test).
"""

import os
import sys
from typing import Any, Callable, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from sklearn.model_selection import StratifiedKFold

# Add PullUp directory to sys.path
EXPERIMENTS_DIR = os.path.dirname(os.path.abspath(__file__))
PULLUP_DIR = os.path.dirname(EXPERIMENTS_DIR)
if PULLUP_DIR not in sys.path:
    sys.path.insert(0, PULLUP_DIR)

from eval_pipeline import load_dataset, evaluate_dataset
from train_test_eval import load_split
from experiments.common import calculate_metrics, format_metrics


def load_all_dataset() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Loads all 76 sets from data/ and returns (all_sets, train_split, test_split).
    """
    data_dir = os.path.join(PULLUP_DIR, "data")
    dataset, skipped = load_dataset(data_dir, PULLUP_DIR)
    train_split, test_split = load_split(dataset)
    return dataset, train_split, test_split


def get_stratified_folds(
    dataset: List[Dict[str, Any]],
    n_splits: int = 5,
    seed: int = 42,
) -> List[Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]]:
    """
    Creates 5 stratified folds based on rep count bins:
      [0, 3], (3, 6], (6, 10], (10, 15], (15, 100]
    Returns list of (train_fold, test_fold) pairs.
    """
    reps = np.array([d["true_reps"] for d in dataset])
    bins = [0, 3, 6, 10, 15, 100]
    strata = np.digitize(reps, bins)

    skf = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    folds = []
    dataset_arr = np.array(dataset, dtype=object)

    for train_idx, test_idx in skf.split(dataset_arr, strata):
        train_fold = list(dataset_arr[train_idx])
        test_fold = list(dataset_arr[test_idx])
        folds.append((train_fold, test_fold))

    return folds


def evaluate_baseline_cv(
    dataset: List[Dict[str, Any]],
    n_splits: int = 5,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Evaluates existing simulate_pullup_online across the 5 stratified folds.
    """
    folds = get_stratified_folds(dataset, n_splits=n_splits, seed=seed)
    fold_metrics = []
    all_test_results = []

    for fold_i, (train_fold, test_fold) in enumerate(folds):
        m = evaluate_dataset(test_fold)
        fold_metrics.append(m)
        all_test_results.extend(m["file_results"])

    # Aggregate cross-fold metrics
    total_sets = len(dataset)
    total_exact = sum(r["error"] == 0 for r in all_test_results)
    total_within1 = sum(abs(r["error"]) <= 1 for r in all_test_results)
    mean_mae = float(np.mean([m["mae"] for m in fold_metrics]))
    mean_bias = float(np.mean([m["bias"] for m in fold_metrics]))
    mean_exact_pct = float(np.mean([m["exact_pct"] for m in fold_metrics]))
    mean_within1_pct = float(np.mean([m["within_1_pct"] for m in fold_metrics]))

    return {
        "n_folds": n_splits,
        "total_sets": total_sets,
        "mean_exact_pct": mean_exact_pct,
        "mean_within1_pct": mean_within1_pct,
        "mean_mae": mean_mae,
        "mean_bias": mean_bias,
        "total_exact": total_exact,
        "total_within1": total_within1,
        "fold_metrics": fold_metrics,
        "all_results": all_test_results,
    }


def evaluate_detector_cv(
    dataset: List[Dict[str, Any]],
    detect_fn: Callable[..., List[int]],
    param_grid: Optional[List[Dict[str, Any]]] = None,
    fixed_params: Optional[Dict[str, Any]] = None,
    n_splits: int = 5,
    seed: int = 42,
) -> Dict[str, Any]:
    """
    Evaluates a candidate detection function using 5-fold cross-validation.
    If param_grid is given: nested tuning inside each fold's train portion.
    If fixed_params is given: evaluates those parameters across each fold.
    """
    folds = get_stratified_folds(dataset, n_splits=n_splits, seed=seed)
    fold_metrics = []
    all_test_results = []
    best_params_per_fold = []

    for fold_i, (train_fold, test_fold) in enumerate(folds, 1):
        if param_grid is not None:
            # Tune strictly inside this fold's train part
            best_exact = -1
            best_mae = float("inf")
            best_p = param_grid[0]
            for p in param_grid:
                m_tr = calculate_metrics(train_fold, detect_fn, **p)
                if (m_tr["exact_matches"] > best_exact) or (
                    m_tr["exact_matches"] == best_exact and m_tr["mae"] < best_mae
                ):
                    best_exact = m_tr["exact_matches"]
                    best_mae = m_tr["mae"]
                    best_p = p
            params_to_eval = best_p
            best_params_per_fold.append(best_p)
        else:
            params_to_eval = fixed_params or {}
            best_params_per_fold.append(params_to_eval)

        # Evaluate selected parameters on held-out test fold
        m_te = calculate_metrics(test_fold, detect_fn, **params_to_eval)
        fold_metrics.append(m_te)
        all_test_results.extend(m_te["file_results"])

    total_sets = len(dataset)
    total_exact = sum(r["error"] == 0 for r in all_test_results)
    total_within1 = sum(abs(r["error"]) <= 1 for r in all_test_results)
    mean_mae = float(np.mean([m["mae"] for m in fold_metrics]))
    mean_bias = float(np.mean([m["bias"] for m in fold_metrics]))
    mean_exact_pct = float(np.mean([m["exact_pct"] for m in fold_metrics]))
    mean_within1_pct = float(np.mean([m["within_1_pct"] for m in fold_metrics]))

    return {
        "n_folds": n_splits,
        "total_sets": total_sets,
        "mean_exact_pct": mean_exact_pct,
        "mean_within1_pct": mean_within1_pct,
        "mean_mae": mean_mae,
        "mean_bias": mean_bias,
        "total_exact": total_exact,
        "total_within1": total_within1,
        "best_params_per_fold": best_params_per_fold,
        "fold_metrics": fold_metrics,
        "all_results": all_test_results,
    }


def format_cv_summary(name: str, cv_res: Dict[str, Any]) -> str:
    """
    Formats a one-line summary string for CV evaluation results.
    """
    return (
        f"{name:<24} | "
        f"CV Exact: {cv_res['total_exact']:>2}/{cv_res['total_sets']} ({cv_res['mean_exact_pct']:5.1f}%) | "
        f"CV $\\pm 1$: {cv_res['total_within1']:>2}/{cv_res['total_sets']} ({cv_res['mean_within1_pct']:5.1f}%) | "
        f"CV MAE: {cv_res['mean_mae']:.3f} | "
        f"CV Bias: {cv_res['mean_bias']:+.3f}"
    )


if __name__ == "__main__":
    dataset, tr_split, te_split = load_all_dataset()
    print(f"Loaded {len(dataset)} total sets ({len(tr_split)} train, {len(te_split)} test).")
    print("Evaluating baseline on 5-fold CV...")
    base_cv = evaluate_baseline_cv(dataset)
    print(format_cv_summary("Baseline (Current FSM)", base_cv))
