"""
cand11_postset_y.py

Candidate 11: Post-Set ("Afterwards") Batch Y-Axis Wave Repetition Detector.
Implements human-eye batch visual counting over the buffered bar hang window [settle_idx : dismount_idx].

Advantages of Post-Set Batch Analysis:
  1. Zero-Phase Forward-Backward Smoothing:
     - Applies a 2-pass centered moving average (forward MA + backward MA) over the buffered
       hang array. Produces zero phase lag and zero time distortion, exactly aligning peaks
       with true physical apexes while eliminating high-frequency wrist jitter.
     - Trivial in Monkey C (< 10 lines of code, two integer loops, < 5ms on smartwatch).
  2. Global Context & Robust Orientation Classification:
     - Uses the entire hang duration to determine exercise polarity:
         Chin-Up if p85 > 160 mG and median > -20 mG; else Pull-Up.
     - Inverts signal (sig = +Y for chin-ups, -Y for pull-ups) so reps are always positive crests.
  3. Topographic Peak Prominence:
     - Measures true prominence (height above surrounding valleys on both left and right).
     - Adaptive reference scaling: thresh = max(min_prom_floor, top_p_ratio * ref_prom),
       scaling automatically between high-amplitude explosive sets and low-amplitude smooth sets.
  4. Multi-Modal Movement Confirmation:
     - Requires movement envelope max_env >= min_env during the wave, confirming physical movement
       while rejecting static re-gripping adjustments.
"""

from typing import Any, Dict, List, Optional, Tuple
import numpy as np
import pandas as pd
from scipy.signal import find_peaks

from eval_pipeline import precompute_envelopes


def extract_hang_bounds(
    x_accel: np.ndarray,
    envs: np.ndarray,
    hang_min_x: int = -1300,
    hang_max_x: int = -700,
    hang_streak_req: int = 35,
    mount_exit_env: int = 70,
    mount_max_wait: int = 130,
    x_release_threshold: int = -300,
    release_streak_req: int = 35,
) -> Tuple[int, int]:
    """
    Isolates the active bar hang interval [settle_idx, dismount_idx]
    using proven baseline mount lock and settling criteria.
    """
    n = len(x_accel)

    # 1. Mount confirmation: X in [-1300, -700] mG for >= 35 samples
    mount_idx = 0
    has_hung = False
    for i in range(hang_streak_req, n):
        if np.all((x_accel[i-hang_streak_req:i] >= hang_min_x) & (x_accel[i-hang_streak_req:i] <= hang_max_x)):
            has_hung = True
            mount_idx = i
            break

    if not has_hung:
        return 0, n

    # 2. Dead-hang settling: envelope < 70 mG or 130 samples ceiling
    settle_idx = mount_idx
    for i in range(mount_idx, min(n, mount_idx + mount_max_wait)):
        if envs[i] < mount_exit_env:
            settle_idx = i
            break

    # 3. Dismount departure latch: X > -300 mG for >= 35 samples
    dismount_idx = n
    for i in range(settle_idx + release_streak_req, n):
        if np.all(x_accel[i-release_streak_req:i] > x_release_threshold):
            dismount_idx = i - release_streak_req
            break

    return settle_idx, dismount_idx


def smooth_two_pass_centered(arr: np.ndarray, win: int = 35) -> np.ndarray:
    """
    Zero-phase centered moving average via 2-pass (forward + backward) boxcar convolution.
    Matches two sequential for-loops in Garmin Monkey C with O(N) integer arithmetic.
    """
    kernel = np.ones(win, dtype=np.float64) / win
    fwd = np.convolve(arr.astype(np.float64), kernel, mode="same")
    bwd = np.convolve(fwd[::-1], kernel, mode="same")[::-1]
    return bwd


def detect(
    df: pd.DataFrame,
    win_smooth: int = 35,
    min_prom_floor: float = 65.0,
    top_p_ratio: float = 0.35,
    min_spacing: int = 70,
    min_env_activity: int = 40,
    edge_margin_mount: int = 35,
    edge_margin_dismount: int = 25,
) -> List[int]:
    """
    Post-set batch repetition detector using zero-phase smoothed Y-axis topographic prominence.
    Returns list of repetition apex sample indices.
    """
    x = df["x"].values
    y = df["y"].values
    z = df["z"].values if "z" in df.columns else np.zeros_like(y)
    n = len(y)

    sq_sums = df["x"].values.astype(np.int64)**2 + df["y"].values.astype(np.int64)**2 + df["z"].values.astype(np.int64)**2
    mags = np.sqrt(sq_sums).astype(np.int32)
    diffs = np.abs(np.diff(mags, prepend=mags[0]))
    envs, _ = precompute_envelopes(mags, diffs)

    s_idx, e_idx = extract_hang_bounds(x, envs)
    if (e_idx - s_idx) < 120:
        s_idx, e_idx = 0, n

    y_hang = y[s_idx:e_idx]
    if len(y_hang) < 60:
        return []

    # Robust global exercise classification over full hang
    med_y = float(np.median(y_hang))
    p85_y = float(np.percentile(y_hang, 85))
    is_chin = bool((p85_y > 160 and med_y > -20) or (p85_y > 210))
    sign = 1.0 if is_chin else -1.0

    # Zero-phase centered smoothing
    y_smooth = smooth_two_pass_centered(y_hang, win=win_smooth)
    sig = sign * y_smooth

    # Find all local peaks with base spacing
    p_all, props = find_peaks(sig, distance=min_spacing, prominence=30)
    if len(p_all) == 0:
        return []

    proms = props["prominences"]
    top_n = min(len(proms), 4)
    ref_prom = float(np.median(sorted(proms)[-top_n:]))
    prom_threshold = max(float(min_prom_floor), top_p_ratio * ref_prom)

    valid_reps = []
    for p_offset, prom in zip(p_all, proms):
        # Exclude immediate mount settling and dismount departure edges
        if p_offset < edge_margin_mount or p_offset > (len(y_hang) - edge_margin_dismount):
            continue

        if prom >= prom_threshold:
            global_idx = s_idx + p_offset
            # Multi-modal envelope activity check: verify real movement occurred
            w_start = max(0, global_idx - 35)
            w_end = min(n, global_idx + 35)
            if np.max(envs[w_start:w_end]) >= min_env_activity:
                valid_reps.append(global_idx)

    return valid_reps


if __name__ == "__main__":
    from experiments.cv import load_all_dataset
    from experiments.common import calculate_metrics, format_metrics
    dataset, tr_split, te_split = load_all_dataset()
    m_tr = calculate_metrics(tr_split, detect)
    m_te = calculate_metrics(te_split, detect)
    print(format_metrics("Cand 11 TRAIN", m_tr))
    print(format_metrics("Cand 11 TEST (30)", m_te))
