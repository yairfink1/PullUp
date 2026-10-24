"""
Train/test evaluation harness.

Splits data/ according to split.json and reports metrics separately for the
train and test sets, so that detector changes can be judged on held-out data
instead of only on the sets they were tuned against.

Usage:
    python train_test_eval.py            # evaluate current detector on both splits
    python train_test_eval.py --verbose  # also list per-file discrepancies
"""
import argparse
import json
import os
from typing import Any, Dict, List, Tuple

from eval_pipeline import evaluate_dataset, load_dataset

WORKSPACE_DIR = os.path.dirname(os.path.abspath(__file__))
SPLIT_PATH = os.path.join(WORKSPACE_DIR, "split.json")


def load_split(dataset: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Partitions the loaded dataset into (train, test) using split.json."""
    with open(SPLIT_PATH, "r", encoding="utf-8") as f:
        test_names = set(json.load(f)["test"])

    train = [item for item in dataset if item["filename"] not in test_names]
    test = [item for item in dataset if item["filename"] in test_names]

    # Fail loudly if split.json references files that no longer exist,
    # otherwise test metrics would silently shrink.
    missing = test_names - {item["filename"] for item in test}
    if missing:
        raise FileNotFoundError(f"split.json test files missing from data/: {sorted(missing)}")
    return train, test


def format_metrics(name: str, metrics: Dict[str, Any]) -> str:
    """One-line summary used for side-by-side train/test comparison."""
    return (f"{name:<6} n={metrics['n_sets']:>3} | "
            f"exact {metrics['exact_matches']:>2}/{metrics['n_sets']} ({metrics['exact_pct']:5.1f}%) | "
            f"within1 {metrics['within_1_matches']:>2}/{metrics['n_sets']} ({metrics['within_1_pct']:5.1f}%) | "
            f"MAE {metrics['mae']:.3f} | bias {metrics['bias']:+.3f} | "
            f"reps {metrics['total_true']} vs {metrics['total_detected']}")


def print_discrepancies(metrics: Dict[str, Any]):
    for r in metrics["file_results"]:
        if r["error"] != 0:
            print(f"    {r['filename']:<26} true={r['true_reps']:>3} det={r['detected_reps']:>3} err={r['error']:+d}")


def main():
    parser = argparse.ArgumentParser(description="Train/test evaluation of the pull-up detector")
    parser.add_argument("--verbose", action="store_true", help="List per-file discrepancies")
    args = parser.parse_args()

    dataset, _skipped = load_dataset(os.path.join(WORKSPACE_DIR, "data"), WORKSPACE_DIR)
    train, test = load_split(dataset)

    for name, subset in (("TRAIN", train), ("TEST", test)):
        metrics = evaluate_dataset(subset)
        print(format_metrics(name, metrics))
        if args.verbose:
            print_discrepancies(metrics)


if __name__ == "__main__":
    main()
