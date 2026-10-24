"""
cand12_postset_multimodal.py

Candidate 12: Post-Set Unified Multi-Modal Consensus Detector.
Primary production-grade architecture combining the high false-positive suppression
of the canonical baseline with the zero-phase visual clarity of post-set batch Y-wave analysis.

Key Architectural Elements:
  1. Exact Hang Window [s_idx : e_idx]:
     - Uses verified mount stabilization lock (X in [-1300, -700] mG) and dead-hang settling.
     - Anchors dismount latch at the exact departure sample where X rises above -300 mG.
  2. Multi-Modal Dual-Pass Signal Analysis:
     - Primary Channel: Canonical baseline state machine with all physical guards.
     - Secondary Channel: Zero-phase centered 2-pass (forward + backward) smoothed Y-axis
       repetition wave with adaptive topographic prominence.
  3. Post-Set Bidirectional Consensus Arbiter:
     - High-Confidence Agreement: When baseline and Y-wave apexes align within match_window (85 samples),
       the repetition is confirmed unconditionally.
     - Post-Set Dismount Rollback: If the final baseline trigger occurred near departure (< 45 samples)
       without corresponding Y-wave apex, it is pruned as a dismount arm-drop artifact.
     - Fatigue Dropout Recovery: In wide silence gaps (>= 1.6x cadence, >= 210 samples), missing
       fatigue repetitions with verified Y-wave prominence and envelope movement (>= 55 mG) are admitted.
     - Tail Burnout Recovery: Late-set fading repetitions occurring after baseline lockout in high-volume sets
       (>= 6 reps) are recovered from the post-set waveform while user remains hanging.
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd

from eval_pipeline import simulate_pullup_online, precompute_envelopes
import experiments.cand11_postset_y as cand11


def detect(
    df: pd.DataFrame,
    match_window: int = 90,
    min_gap_to_insert: int = 220,
    tail_min_gap: int = 140,
    gap_min_env: int = 55,
    tail_min_reps: int = 6,
) -> List[int]:
    """
    Post-set multimodal consensus repetition detector.
    Returns list of confirmed repetition sample indices.
    """
    x = df["x"].values
    y = df["y"].values
    z = df["z"].values if "z" in df.columns else np.zeros_like(y)
    n = len(df)

    sq_sums = df["x"].values.astype(np.int64)**2 + df["y"].values.astype(np.int64)**2 + df["z"].values.astype(np.int64)**2
    mags = np.sqrt(sq_sums).astype(np.int32)
    diffs = np.abs(np.diff(mags, prepend=mags[0]))
    envs, _ = precompute_envelopes(mags, diffs)

    # 1. Primary Channel: Canonical baseline detector
    base_reps = simulate_pullup_online(envs, None, x, y, z)

    # 2. Secondary Channel: Post-set zero-phase Y-wave detector
    post_reps = cand11.detect(df)

    # 3. Consensus arbitration
    final_reps = list(base_reps)

    # Find active hang window
    hang = np.where(x <= -300)[0]
    if len(hang) > 0 and len(final_reps) > 0:
        dismount_sample = hang[-1]
        last_b = final_reps[-1]
        # Dismount rollback: prune trailing trigger if user was departing and Y-wave did not confirm
        if (dismount_sample - last_b) < 45:
            has_match = any(abs(p - last_b) <= match_window for p in post_reps)
            if not has_match:
                final_reps.pop()

    # Calculate median cadence
    if len(final_reps) >= 2:
        intervals = [final_reps[k] - final_reps[k-1] for k in range(1, len(final_reps))]
        med_cadence = float(np.median(intervals))
    else:
        med_cadence = 140.0

    gap_threshold = max(min_gap_to_insert, 1.8 * med_cadence)

    for p_r in post_reps:
        dt_nearest = min(abs(r - p_r) for r in final_reps) if final_reps else 999
        if dt_nearest < match_window:
            continue  # Already matched with baseline

        w_start = max(0, p_r - 35)
        w_end = min(n, p_r + 35)
        env_peak_near = float(np.max(envs[w_start:w_end]))

        # Case A: Fading repetitions in the tail of the set (after last baseline trigger)
        if final_reps and p_r > final_reps[-1]:
            if len(final_reps) >= tail_min_reps:
                if (p_r - final_reps[-1]) >= max(tail_min_gap, 0.80 * med_cadence):
                    if len(hang) > 0 and p_r < (hang[-1] - 30) and env_peak_near >= 40:
                        final_reps.append(p_r)

        # Case B: Internal fatigue dropout in wide gap between baseline reps
        elif final_reps and p_r < final_reps[-1] and p_r > final_reps[0]:
            for k in range(len(final_reps) - 1):
                r_left = final_reps[k]
                r_right = final_reps[k+1]
                if r_left < p_r < r_right:
                    if (r_right - r_left) >= gap_threshold:
                        if (p_r - r_left) >= 0.70 * med_cadence and (r_right - p_r) >= 0.70 * med_cadence:
                            if env_peak_near >= gap_min_env:
                                final_reps.append(p_r)
                    break
        elif not final_reps:
            final_reps.append(p_r)

    final_reps.sort()
    return final_reps


if __name__ == "__main__":
    from experiments.cv import load_all_dataset
    from experiments.common import calculate_metrics, format_metrics
    dataset, tr_split, te_split = load_all_dataset()
    m_tr = calculate_metrics(tr_split, detect)
    m_te = calculate_metrics(te_split, detect)
    print(format_metrics("Cand 12 TRAIN", m_tr))
    print(format_metrics("Cand 12 TEST (30)", m_te))
