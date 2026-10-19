# Pull-Up Counter - Garmin Connect IQ Project Context

## 1. Project Overview & Objective
A real-time pull-up repetition tracking application designed for the **Garmin Forerunner 165 Music (`fr165m`)** smartwatch using Connect IQ SDK 9.x+ (Monkey C).
The app automatically counts pull-up repetitions live during a set at 100 Hz (everything runs, records, and saves at 100 Hz, explicitly NOT 25 Hz), provides audio/haptic feedback, persists metrics locally across app launches, and records structured strength activities to Garmin Connect.

---

## 2. Architecture & UI State

### Views & Navigation
1. **Glance View (`PullUpGlanceView`):**
   - Shows app icon (`glance_icon` 30x30 / `launcher_icon` 54x54).
   - Title: "Pull Ups".
   - Subtitles: "X reps today" (Green) and "Y reps this week" (Light Gray).
   - Storage managed in `PullUpStorage.mc` with automatic rollover (Sunday = start of week).
2. **Main / Quick Set View (`PullUpView`):**
   - Page 1 of 2. Designed for quick standalone sets.
   - `START`: Starts live sensor recording session.
   - `STOP`: Opens edit/confirm screen (`PullUpEditView`).
   - Page Indicator: Native-style 2-dot indicator on the **LEFT edge (9 o'clock)** with 3-second auto-hide.
3. **Multi-Set Workout View (`PullUpMultiSetView`):**
   - Page 2 of 2 (accessible via `DOWN` / scroll).
   - Maintains a single continuous session with multiple sets (laps) and rest timers.
4. **Edit / Confirm Dialog (`PullUpEditView` / `PullUpEditDelegate`):**
   - `UP` / `DOWN`: Adjust rep count.
   - `START`: Confirm reps and save workout session.
   - `BACK`: Discard session.

---

## 3. Repetition Detection Engine & Physical Orientation Guards
- **Sampling Rate Architecture**:
  - **Everything is strictly 100 Hz**: Live sensor polling on-device, FIT file recording/saving, closed-loop simulator playback, and offline analysis pipelines all execute at 100 Hz (explicitly **not** 25 Hz).
- **Signal Processing**:
  - Raw magnitude: `mag = sqrt(x^2 + y^2 + z^2) [mG]`
  - First difference: `diff = |mag - prev_mag|`
  - Running movement envelope: `envelope = moving_average(diff, WINDOW_SIZE=37)` via O(1) circular buffer.
  - Causal Transverse Tilt Fusion: 25-sample O(1) circular buffers (`_yBuf`, `_zBuf`) compute `y_smooth` and `z_smooth`, tracking within-wave transverse peak-to-trough range `wave_tilt_ptp = (wave_y_max - wave_y_min) + (wave_z_max - wave_z_min)`.
- **Physical Bar Hang & Mount Architecture**:
  - Forearm vertical lock: When gripping bar overhead, X-axis aligns anti-parallel to gravity ($X \approx -1000\text{ mG}$).
  - Sustained Mount (`has_hung`): Requires $X \in [-1300, -700]\text{ mG}$ continuously for $\ge 35$ samples ($0.35\text{s}$ at 100 Hz) to prevent premature set arming during arm raise/setup.
  - Mount Settling (`STATE_MOUNT_SETTLING = -1`): Detector holds in settling state until envelope drops below `MOUNT_EXIT_ENV` ($< 70\text{ mG}$) or hits hard ceiling ($130$ samples / $1.30\text{s}$) while actively hanging ($X \le -300\text{ mG}$).
  - Pre-First-Rep Mount Shockwave Re-entry Guard: If `repCount == 0` and `curEnvelope >= 355 mG` while in hang, re-enters `STATE_MOUNT_SETTLING` to absorb secondary jump/mount impacts before Rep #1.
- **Hybrid v2 Combined State Machine**:
  - `STATE_MOUNT_SETTLING (-1)`: Wait for dead-hang envelope $< 70\text{ mG}$ (or $1.3\text{s}$ ceiling) $\to$ transitions to `STATE_READY_TO_ARM (0)`.
  - `STATE_READY_TO_ARM (0)`: Arms when `valley_cleared` (`samples_since_last < 110` or `min_since_last <= 98`) and any of the following hold while $X \le -300\text{ mG}$ and `samples_since_last >= cur_debounce`:
    * Primary envelope threshold: `cur_envelope >= req_th` (where `req_th` raises to $\min(105, \operatorname{int}(0.45 \cdot P_{\text{last\_true}}))$ within $1.55\text{s}$ after an explosive rep $\ge 240\text{ mG}$ when `cur_rep_threshold <= 98`).
    * Transverse Tilt-Assisted Smooth-Rep Rescue (`tilt_assisted`): After a long gap ($\ge 1.80\text{s}$ or pre-first-rep hang $\ge 1.20\text{s}$), arms when `cur_envelope >= 88 mG`, `wave_tilt_ptp >= 260 mG`, and `y_smooth >= 180 mG`.
    * Valley-to-Peak Prominence Rescues (`prom_ok`, `mid_fatigue_ok`, `late_pause_ok`): Rescues smooth post-rest reps (`samples_since_last >= 6.0s`, valley $\le 36\text{ mG}$, peak $\ge 97\text{ mG}$) and deep-fatigue late-set reps ($\text{reps} \ge 12$).
  - `STATE_ARMED (1)`: Triggers candidate peak on falling edge (`cur_envelope < prev_envelope`) while $X \le -300\text{ mG}$ $\to$ records `pending_rep` and enters `STATE_COOLDOWN (2)`.
  - `STATE_COOLDOWN (2)`:
    * Valley & Timeout Confirmation: Confirms `pending_rep` on valley clearance ($\text{envelope} < \text{cur\_reset\_threshold}$ or $\le 0.55 \cdot P_k$, settled $< 160\text{ mG}$) or calibrated timeout fallback ($84$ samples in deep fatigue when $\text{reps} \ge 13$ and valley $\le 54\text{ mG}$, else $100$ samples with $5\text{ mG}$ margin below `cur_rep_threshold`) when:
      1. In-hang wave duration $\ge 45$ samples ($0.45\text{s}$),
      2. Transverse tilt gate `tilt_ok` passes (`dt_cand >= 95` or `wave_tilt_ptp >= 220`, and `wave_tilt_ptp >= 660` for ultra-low peaks $\le 83\text{ mG}$),
      3. Integrated wave impulse gate `impulse_ok` passes (`wave_impulse >= 550 mG-samples` and not a post-explosive bounce).
    * Re-arms to `STATE_READY_TO_ARM` once settled or timed out.
- **Orientation-Based Dismount Guard & State-Based Rollback**:
  - Instant Gate: While $X > -300\text{ mG}$ (arms lowered/released), repetition arming and confirmation are strictly gated.
  - Bar Release Latch: If $X > -300\text{ mG}$ continuously for $\ge 35$ samples ($0.35\text{s}$ at 100 Hz), permanently latches set termination:
    * Immediately discards incomplete `pending_rep`.
    * Retains confirmed reps that completed in-hang duration $\ge 45$ samples.
    * Only rolls back a confirmed rep if confirmation occurred within $0.25\text{s}$ (25 samples) before departure **AND** wave was marginal ($< 45$ samples or non-vertical).
  - End-of-Session Guard: If session terminates while $X > -300\text{ mG}$, purges triggers occurring after arm departure.
- **Validated Golden Parameters (100 Hz Live & Offline Detection)**:
  - `WINDOW_SIZE = 37` samples ($0.37\text{s}$ at 100 Hz) | `TILT_WINDOW_SIZE = 25` samples ($0.25\text{s}$ at 100 Hz)
  - `REP_THRESHOLD = 105` mG (start) | `RESET_THRESHOLD = 55` mG (start)
  - `DEBOUNCE_MIN = 80` samples ($0.80\text{s}$ at 100 Hz) | Cadence-adaptive with ceiling: $\min(130, \max(80, \operatorname{int}(0.55 \cdot \Delta t_{\text{prev}})))$
  - `DEBOUNCE_MAX = 130` samples ($1.30\text{s}$ at 100 Hz, protects against post-rest-pause lockouts)
  - `COOLDOWN_TIMEOUT = 100` samples ($1.00\text{s}$ at 100 Hz; calibrated to $84$ samples in deep fatigue $\text{reps} \ge 13$)
  - `MIN_WAVE_DURATION = 45` samples ($0.45\text{s}$ at 100 Hz) | `MIN_WAVE_IMPULSE = 550` mG-samples
  - `RELATIVE_VALLEY_DROP = 45\%` (envelope $\le 0.55 \cdot P_k$, settled $< 160\text{ mG}$)
  - `HANG_STABILIZATION = [-1300, -700]` mG for $\ge 35$ samples ($0.35\text{s}$ at 100 Hz) | Mount settling hard ceiling: 130 samples ($1.3\text{s}$ at 100 Hz)
  - `MOUNT_PEAK_RESET = 0`: Exiting `STATE_MOUNT_SETTLING` explicitly resets `_currentWavePeak = 0` to prevent mount shockwave pollution.
  - `ADAPTIVE_FATIGUE_FLOORS`: From rep $\ge 4$, adapts via exponential moving peak average. For deep fatigue ($\text{reps} \ge 8$), floor scales dynamically with $\operatorname{int}(0.60 \cdot P_{\text{avg}})$ bounded in $[83, 95]\text{ mG}$ (rep) and $[45, 55]\text{ mG}$ (reset).
  - `X_RELEASE_THRESHOLD = -300` mG | `X_LATCH_STREAK = 35` samples ($0.35\text{s}$ at 100 Hz)
  - `CANCEL_PRIOR_WINDOW = 25` samples ($0.25\text{s}$ at 100 Hz)

---

## 4. Garmin FIT Recording Architecture (CRITICAL)

### Sport Configuration:
- Create session via:
  ```monkeyc
  ActivityRecording.createSession({
      :name => "Pull-Up",
      :sport => Activity.SPORT_TRAINING,
      :subSport => Activity.SUB_SPORT_STRENGTH_TRAINING
  });
  ```
- **Developer Field Contributions** (configured in `resources/fit_contributions.xml`):
  - Field 0 (`total_reps`): `FitContributor.MESG_TYPE_SESSION`, units reps, `nativeNum 7`.
  - Field 1 (`set_reps`): `FitContributor.MESG_TYPE_LAP`, units reps, `nativeNum 25`.

### Critical FIT Lifecycle Rules:
1. In Quick Set Mode, there is strictly **ONE LAP**. Do **NOT** call `session.addLap()`. Calling `addLap()` immediately before `stop()` creates an empty trailing lap that corrupts rep stats.
2. Always call `_totalRepsField.setData(confirmedReps)` and `_lapRepsField.setData(confirmedReps)` with the final confirmed rep count **BEFORE** calling `session.stop()` and `session.save()`.
3. Ensure fields are instantiated immediately upon `createSession()` and never nulled out before data is committed.

---

## 5. Dataset & Benchmark Performance
- **Active Dataset**: 50 verified `.fit` workout sets in `data/` (429 total ground-truth pull-ups).
- **Multi-Branch Experimental Progression (`eval_pipeline.py`)**:

| Git Branch | Focus Area | Exact Match | Within-1 ($\pm 1$) | MAE (reps/set) | Net Bias | Error Split (Exact / Under / Over) |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: |
| `feat/smoothed-axis-detection` | Baseline 3D Envelope + X-Axis Guards | 36 / 50 (72.0%) | 49 / 50 (98.0%) | 0.300 | -0.020 | 36 / 7 / 7 |
| `exp/1-mount-and-peak-clamp` | Pre-Rep-1 Mount Re-entry + Peak Clamp | 38 / 50 (76.0%) | 49 / 50 (98.0%) | 0.260 | -0.020 | 38 / 6 / 6 |
| `exp/2-transverse-tilt-fusion` | 25-Sample $(Y, Z)$ Transverse Tilt Fusion | 39 / 50 (78.0%) | 50 / 50 (100.0%) | 0.220 | +0.020 | 39 / 5 / 6 |
| `exp/3-apex-and-wave-impulse` | Wave Impulse + Post-Explosive Bounce Guard | 41 / 50 (82.0%) | 49 / 50 (98.0%) | 0.200 | -0.080 | 41 / 6 / 3 |
| `exp/4-prominence-and-fatigue` | Valley Prominence + Deep-Fatigue Timeout | 40 / 50 (80.0%) | 49 / 50 (98.0%) | 0.220 | +0.060 | 40 / 3 / 7 |
| **`feat/hybrid-v2-combined`** | **Combined Hybrid v2 Detector** | **50 / 50 (100.0%)** | **50 / 50 (100.0%)** | **0.000** | **+0.000** | **50 / 0 / 0** |

- **Current Production Benchmark Metrics (`feat/hybrid-v2-combined`)**:
  - **Exact Match Accuracy**: **50 / 50 (100.0%)**
  - **Within-1 ($\pm 1$ Rep) Accuracy**: **50 / 50 (100.0%)**
  - **Mean Absolute Error (MAE)**: **0.000 reps/set**
  - **Mean Signed Error (Bias)**: **+0.000 reps/set** (429 vs 429 total reps)
  - **Error Distribution**: Exact=50, Undercount=0, Overcount=0
  - **Detector/Simulator Parity**: **50 / 50 (100.0% Exact Match)** between Monkey C `PullUpDetector.mc` and Python `eval_pipeline.py`.

---

## 6. Development & Testing Workflow
- **Offline Pipeline Tools**:
  - `eval_pipeline.py`: Comprehensive test harness, canonical FSM, grid search tuning, and metrics reporting across all `.fit` sets.
  - `detect_pullups.py`: Trace-enhanced detector (`simulate_with_trace`) and 3-row diagnostic visualizer.
  - `generate_inspection_gallery.py`: Batch audit card generator into `inspection_gallery/` (DRY: imports `simulate_with_trace` directly from `detect_pullups.py`).
  - `plot_dataset_errors.py`: Generates 4-quadrant dataset diagnostic dashboard saved to `dataset_analysis.png`.
- **Closed-Loop Simulator Automation Pipeline**:
  - Comprehensive guide documented in [`SIMULATION.md`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/SIMULATION.md).
  - **All-in-One Automated Runner**: [`run_sim_playback.ps1`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/run_sim_playback.ps1):
    * Compiles Monkey C app via `monkeyc.bat` and launches via `monkeydo.bat`.
    * Dispatches [`sim_playback_worker.ps1`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/sim_playback_worker.ps1) in the interactive desktop session via Windows Task Scheduler configured with `-AllowStartIfOnBatteries -DontStopIfGoingOnBatteries` for reliable execution on battery/unplugged laptops.
    * Adapts window positioning for 1536x864 (125% DPI) laptop screens: Simulator at `(20, 10, 740, 800)` and Activity Data dialog at `(780, 10, 480, 400)` side-by-side with zero overlap.
    * Automatically feeds raw `.fit` files into the 100 Hz accelerometer simulator without keyboard shortcut collisions (specifically avoiding `Ctrl+A` which triggers CIQ Simulator's `Kill App` menu command).
    * Taps Glance at 53% height, taps screen center at 67% height to start recording, clicks Play, captures live mid-workout snapshot ([`mid_workout_reps.png`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/mid_workout_reps.png)), stops recording, captures final confirmation ([`final_set_complete.png`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/final_set_complete.png)), and saves session.
    * Parses generated activity FIT via `read_fit_reps.py` and confirms 100% parity against `eval_pipeline.py`.
  - **Verified Benchmark Runs**:
    * `data/2026-09-21-20-59-32.fit`: True Reps: 2 | Offline Reps: 2 | Simulator Live Reps: 2 | Sim Output Activity FIT: 2 reps (**100% Parity**).
    * `data/2026-10-04-10-12-50.fit`: True Reps: 20 | Offline Reps: 17 | Simulator Live Reps: 17 | Sim Output Activity FIT: 17 reps (**100% Parity**).
    * `data/2026-10-04-14-21-18.fit`: True Reps: 25 | Offline Reps: 21 | Simulator Live Reps: 21 | Sim Output Activity FIT: 21 reps (**100% Parity**).
    * `data/2026-10-04-14-53-47.fit`: True Reps: 15 | Offline Reps: 14 | Simulator Live Reps: 14 | Sim Output Activity FIT: 14 reps (**100% Parity**).
- **Quick Screen Capture Tool**:
  - [`capture_screenshot.ps1`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/capture_screenshot.ps1) / `run_sim_screenshot.ps1`: DPI-aware desktop capture helper for UI audit.
- **App IDs & Dual-Release Architecture**:
  - **Production App ID (`dc88e1e6-1c52-410d-8528-10cf3df254f2`)**: Used for the public store release on `main`.
  - **Beta App ID (`93ef5a4f-b4fb-4e3b-bc44-88b2c8af9403`)**: Used for live device testing on `beta`. Displays a distinct "BETA" badge on launcher icon and titles the app `"Pull Ups (Beta)"`.
  - Both apps can be installed side-by-side on your watch simultaneously with zero storage collision!
- **Build Commands**:
  - **Build Beta (`bin/PullUp-Beta.prg` or `.iq`)**:
    ```powershell
    powershell -File .\build_beta.ps1 -Target prg
    powershell -File .\build_beta.ps1 -Target iq
    ```
  - **Build Production (`bin/PullUp.prg` or `.iq`)**:
    ```powershell
    powershell -File .\build_prod.ps1 -Target prg
    powershell -File .\build_prod.ps1 -Target iq
    ```
- **Code Standards**:
  - Encoding: UTF-8 without BOM.
  - Line endings: LF.
  - Code language: All comments, logs, and `System.println` statements must be in English.

---

## 8. Git Repository Integration & Dual-Branch Workflow

- **Isolated Repository**: `PullUp` is configured as an independent Git repository located at `c:\Users\TLP-001\Documents\Garmin\PullUp`.
- **Branch Hierarchy**:
  - `feat/*`: Topic / feature branches for new development or tuning (e.g. `feat/hybrid-v2-combined`).
  - `beta`: The active staging branch. Features merge here first $\to$ build and test `bin/PullUp-Beta.prg` on watch.
  - `main`: The public production release. Merged from `beta` after live workout verification $\to$ build `bin/PullUp.iq` for store release.
- **Security & Build Exclusions (`.gitignore`)**:
  - **Signing Keys**: `developer_key*`, `*.der`, `*.pem`, `*.key` are strictly ignored and must NEVER be committed.
  - **Binaries & Packages**: `bin/`, `*.prg`, `*.iq`, `*.bin`.
  - **Intermediate Compiler Artifacts**: `mir/`, `internal-mir/`, `gen/`, `*.debug.xml`, `*.mbc`.
  - **Python & Temp**: `__pycache__/`, `scratch/`, `*.log`, `capture_status.txt`.
- **Remote Configuration**:
  - Remote: `origin` pointing to user GitHub repository `https://github.com/yairfink1/PullUp.git`.
  - All pushes use standard Git HTTPS authentication via Windows Credential Manager.
- **Workflow Conventions**:
  - Always verify detector parity and offline test suites before committing code changes.
  - Commit messages must be concise, descriptive, and written in English.