# Pull-Up Counter - Garmin Connect IQ Project Context

## 1. Project Overview & Objective
A real-time pull-up repetition tracking application designed for the **Garmin Forerunner 165 Music (`fr165m`)** and 55+ round Garmin smartwatches using Connect IQ SDK 9.x+ (Monkey C).
The app automatically counts pull-up and chin-up repetitions live during a set at 100 Hz (everything runs, records, and saves at 100 Hz, explicitly NOT 25 Hz), provides audio/haptic feedback, persists metrics locally across app launches, and records structured strength activities (including user-confirmed Pull-Up vs. Chin-Up labels) to Garmin Connect.

---

## 2. Architecture & UI State

### Views & Navigation
1. **Glance View (`PullUpGlanceView`):**
   - Shows app icon (`glance_icon` 30x30 / `launcher_icon` 54x54).
   - Title: "Pull Ups".
   - Subtitles: "X reps today" (Green) and "Y reps this week" (Light Gray).
   - Storage managed in `PullUpStorage.mc` with automatic rollover (Sunday = start of week).
2. **Main / Quick Set View (`PullUpView` or Page 0 of `PullUpContainerView`):**
   - Page 1 of 2 in two-page mode / Page 0 of 3 in container mode. Designed for quick standalone sets.
   - Smooth Drag Scrolling & Snapping: 3-page continuous vertical carousel with zero-allocation rendering, local stats caching (`refreshCachedStats`), lightweight drag interaction updates (`markInteraction`), and snappy spring physics (`12ms` tick, `55%` ease-out, `12px` velocity floor).
   - `START`: Starts live sensor recording session.
   - Live exercise feedback: Displays `"PULL UP"` or `"CHIN UP"` dynamically based on real-time wrist tilt and rep-wave classification.
   - `STOP`: Opens edit/confirm screen (`PullUpEditView`).
   - Page Indicator: Native-style dot indicator on the **LEFT edge (9 o'clock)** with 3-second auto-hide.
3. **Multi-Set Workout View (`PullUpMultiSetView` or Page 1 of `PullUpContainerView`):**
   - Page 2 of 2 / Page 1 of 3 (accessible via `DOWN` / scroll).
   - Maintains a single continuous session with multiple sets (laps) and rest timers (`PullUpRestView` / `PullUpFinishView`).
4. **Edit / Confirm Dialog (`PullUpEditView` / `PullUpEditDelegate`):**
   - Bezel-safe circular layout: All titles and stacked action hints (`FONT_XTINY`, capped at $\le 0.85 \cdot h$) are sized to never clip on round displays.
   - Dynamic exercise title: `"PULL UP DONE"` or `"CHIN UP DONE"` in Quick Set, and `"SET X: PULL UP"` / `"SET X: CHIN UP"` in Multi-Set.
   - `UP` / `DOWN`: Adjust rep count (`"UP / DOWN: Adjust Reps"`).
   - **Hold `UP` (`onMenu` / `KEY_MENU`)**: Toggles the set exercise type between `"PULL UP"` and `"CHIN UP"` (`"Hold UP: Pull / Chin"`) so the user can confirm or correct the classification before saving.
   - `START`: Confirm reps + exercise type and save workout session (`"START: Save"` or `"START: Save & Rest"`).
   - `BACK`: Discard set/session (`"BACK: Discard"`).
5. **Finish Workout Dialog (`PullUpFinishView` / `PullUpFinishDelegate`):**
   - Bezel-safe header `"WORKOUT DONE?"` (`FONT_TINY` at `0.14 * h`), total reps display, and stacked action rows (`"START: Save Workout"`, `"DOWN: Resume Rest"`, `"BACK: Discard"`).

---

## 3. Repetition Detection Engine & Physical Orientation Guards
- **Sampling Rate Architecture**:
  - **Everything is strictly 100 Hz**: Live sensor polling on-device, FIT file recording/saving, closed-loop simulator playback, and offline analysis pipelines all execute at 100 Hz (explicitly **not** 25 Hz).
- **Signal Processing**:
  - Raw magnitude: `mag = sqrt(x^2 + y^2 + z^2) [mG]`
  - First difference: `diff = |mag - prev_mag|`
  - Running movement envelope: `envelope = moving_average(diff, WINDOW_SIZE=37)` via O(1) circular buffer.
  - Causal Transverse Tilt Fusion: 25-sample O(1) circular buffers (`_yBuf`, `_zBuf`) compute `y_smooth` and `z_smooth`, tracking within-wave transverse peak-to-trough range `wave_tilt_ptp = (wave_y_max - wave_y_min) + (wave_z_max - wave_z_min)`.
- **Automatic Exercise Classification (Pull-Up vs. Chin-Up)**:
  - Forearm rotation between pronated (Pull-Up) and supinated (Chin-Up) flips the lateral $Y$-axis.
  - **Strict Vertical-Hang Baseline Accumulation**: Only accumulates `_hangYSum`, `_hangYSamples`, and high-tilt samples (`ySmooth >= 140 mG` in `_hangYHighSamples`) when the user is strictly in vertical bar hang ($X \le -650\text{ mG}$, `_xStreak == 0`, and `_state != STATE_MOUNT_SETTLING`), preventing arm-raise and dismount transition bias.
  - **Per-Rep $Y$-Wave Excursion Voting**: Chin-Ups exhibit strong positive $Y$ peaks ($+200\text{ to }+400\text{ mG}$), whereas Pull-Ups exhibit negative $Y$ dips ($-110\text{ to }-280\text{ mG}$). On each confirmed rep, `_recordConfirmedRep` casts a vote (`_chinRepVotes` if `_waveYMax >= 180` and `_waveYMax + _waveYMin > 40`; `_pullRepVotes` if `_waveYMin <= -110` or `_waveYMax + _waveYMin < -20`).
  - **Combined Decision (`_updateExerciseClassification`)**: Combines per-rep wave polarity votes with the vertical-hang baseline (`meanHangY > 95 mG` or `meanHangY > 55 mG` with $\ge 25\%$ high-tilt samples), achieving **20 / 20 (100%)** classification accuracy on the labeled `real/` reference sets.
- **Physical Bar Hang & Mount Architecture**:
  - Forearm vertical lock: When gripping bar overhead, X-axis aligns anti-parallel to gravity ($X \approx -1000\text{ mG}$).
  - Sustained Mount (`has_hung`): Requires $X \in [-1300, -700]\text{ mG}$ continuously for $\ge 35$ samples ($0.35\text{s}$ at 100 Hz) to prevent premature set arming during arm raise/setup.
  - Mount Settling (`STATE_MOUNT_SETTLING = -1`): Detector holds in settling state until envelope drops below `MOUNT_EXIT_ENV` ($< 92\text{ mG}$) or hits hard ceiling ($130$ samples / $1.30\text{s}$) while actively hanging ($X \le -300\text{ mG}$).
  - Pre-First-Rep Mount Shockwave Re-entry Guard: If `repCount == 0` and `curEnvelope >= 355 mG` while in hang, re-enters `STATE_MOUNT_SETTLING` to absorb secondary jump/mount impacts before Rep #1.
- **Hybrid v2 Combined State Machine**:
  - `STATE_MOUNT_SETTLING (-1)`: Wait for dead-hang envelope $< 92\text{ mG}$ (or $1.3\text{s}$ ceiling) $\to$ transitions to `STATE_READY_TO_ARM (0)`.
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
- **Post-Set Consensus & Watchdog Protection (`PullUpDetector.mc` & `cand14_postset_consensus.py`)**:
  - **2-Stage Post-Set Consensus**: Reconciles the online trajectory (`_baseReps`) against a global offline-equivalent peak detector (`_findPeaksExtrema`) using dynamic cadence estimation (`_calcSortedCadence`), boundary artifact pruning, double-counted wobble merging, and missed-rep gap rescue (`_runStep7GapRescue`).
  - **Deferred Execution Outside Sensor Interrupts**: Connect IQ `onQuickSensorData` callbacks execute in a tight interrupt batch with a strict watchdog instruction limit. `_runPostSetConsensus()` is therefore never called inside `processSample()`; it runs exclusively inside `finalizeSet()` after `Sensor.unregisterSensorDataListener()` when the set stops, granting it a full UI execution budget and preventing `Watchdog Tripped Error - Code Executed Too Long` crashes.
  - **Bounded Prominence Window**: `_findPeaksExtrema` bounds left/right valley scans to `k ± 35` extrema ($\sim 3.5\text{s}$), reducing peak extraction from $O(M^2)$ to $O(M)$ ($\sim 3.4\times$ faster) with zero accuracy loss.
  - **Pre-Filtered Bipartite Matching & Fast Gap-Rescue Bypass**: Step 2 pre-collects only candidate pairs with $|b - p| \le 100$ before greedy matching ($\sim 200\times$ fewer loop iterations on high-rep sets), and `_runStep7GapRescue` pre-checks `need7a`, `need7b`, and `need7c` before calling `_findPeaksExtrema` a second time—allowing full post-set consensus to run on sets of any length without tripping the watchdog.
  - **Round 10 Consensus Refinements (136/136 Exact Parity)**:
    * **Short-Set Double-Trigger Cadence Protection**: In Step 4, when `base_reps == post_reps + 1` and `len(confirmed_reps) >= 3` with `med_conf <= 280`, derives minimum spacing from the uncorrupted bipartite `confirmed_reps` cadence instead of the double-trigger-deflated baseline cadence, eliminating intra-rep false triggers without requiring all post reps to be matched.
    * **Pre-First-Rep Rhythmic Dropout Recovery**: In Step 5, relaxes the $\ge 90\text{ mG}$ pre-first-rep mount oscillation rejection gate when severe baseline dropout is present (`post_reps - base_reps >= 2`) and peaks precede `min(confirmed_reps)` by $\ge 180$ samples, rescuing smooth initial repetitions missed by online envelope thresholds while preserving mount-settling rejection.
    * **Universal 75-Sample Gap-Rescue Floor**: Aligns the Step 5 internal 2-rep gap-rescue distance guard with the detector's global minimum spacing floor ($75$ samples), allowing internal Y peaks within $1.75\times$ cadence gaps to be recovered when baseline triggers latched with a phase delay.
    * **Volume Burnout Rep Recovery**: In Step 7b, extends late slow-burnout rep recovery before dismount to sets of $\ge 8$ confirmed reps with raw prominence $\ge 170\text{ mG}$, capturing fatigued final repetitions across all set volumes.

---

## 4. Garmin FIT Recording Architecture (CRITICAL)

### Sport Configuration:
- Create session via:
  ```monkeyc
  ActivityRecording.createSession({
      :name         => "PullUp Quick Set",
      :sport        => Activity.SPORT_TRAINING,
      :subSport     => Activity.SUB_SPORT_STRENGTH_TRAINING,
      :sensorLogger => _quickSensorLogger
  });
  ```
- **Developer Field Contributions** (configured in `resources/strings/fit_contributions.xml` & `strings.xml`):
  - Field `0` (`Total Reps`): `FitContributor.MESG_TYPE_SESSION`, `DATA_TYPE_UINT16`, units `"reps"`.
  - Field `1` (`Set Reps`): `FitContributor.MESG_TYPE_LAP`, `DATA_TYPE_UINT16`, units `"reps"`.
  - Field `2` (`Pull-Up Reps`): `FitContributor.MESG_TYPE_SESSION`, `DATA_TYPE_UINT16`, units `"reps"`.
  - Field `3` (`Chin-Up Reps`): `FitContributor.MESG_TYPE_SESSION`, `DATA_TYPE_UINT16`, units `"reps"`.
  - Field `4` (`Exercise Type`): `FitContributor.MESG_TYPE_LAP`, `DATA_TYPE_UINT8`, units `"0=Pull 1=Chin"` (`0` = Pull-Up, `1` = Chin-Up).

### Critical FIT Lifecycle Rules:
1. In Quick Set Mode, there is strictly **ONE LAP**. Do **NOT** call `session.addLap()`. Calling `addLap()` immediately before `stop()` creates an empty trailing lap that corrupts rep stats.
2. Always call `setData(...)` on `_totalRepsField`, `_lapRepsField`, `_pullRepsField`, `_chinRepsField`, and `_lapExField` with the final user-confirmed rep count and exercise type **BEFORE** calling `session.stop()` and `session.save()`.
3. Ensure fields are instantiated immediately upon `createSession()` and never nulled out before data is committed.
4. **Empty Session Discard (0 Reps Guard)**: Any standalone quick set confirmed with 0 reps, or multi-set workout finished with 0 total reps, must call `session.discard()` instead of `session.save()` to prevent blank activities polluting Garmin Connect.

---

## 5. Dataset & Benchmark Performance
- **Active Dataset**: 136 verified `.fit` workout sets in `data/` (all in `TRAIN`; `TEST2` is empty and awaiting the next gathering round; train result 136/136 exact (100.0%) after the Round 10 consensus refinements: short-set double-trigger cadence protection from confirmed reps, pre-first-rep rhythmic dropout recovery, universal 75-sample gap-rescue distance floor, and late slow-burnout rep recovery for volume sets >= 8 reps, ported 100% symmetrically to `cand14_postset_consensus.py` and `PullUpDetector.mc`) (partitioned via `split.json` into `TRAIN` and `TEST2`).
- **Ground-Truth Exercise Type Collection**:
  - Every set saved on the watch records the user-confirmed `Pull-Up Reps`, `Chin-Up Reps`, and lap `Exercise Type` (`0=Pull, 1=Chin`) directly inside the `.fit` file.
  - When syncing downloaded activities via [`Calisthenics/sync_fit_files.py`](file:///c:/Users/TLP-001/Documents/Garmin/Calisthenics/sync_fit_files.py) or inspecting via [`read_fit_reps.py`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/read_fit_reps.py), the pipeline extracts these FIT developer fields first so every newly synced set carries a 100% user-verified `pullup` vs. `chinup` ground-truth label for model training and evaluation.

---

## 6. Development & Testing Workflow
- **Offline Pipeline Tools**:
  - `eval_pipeline.py`: Comprehensive test harness, canonical FSM, grid search tuning, and metrics reporting across all `.fit` sets.
  - `train_test_eval.py`: Evaluates detector accuracy separately across `TRAIN` and `TEST2` splits defined in `split.json`.
  - `detect_pullups.py`: Trace-enhanced detector (`simulate_with_trace`) and 3-row diagnostic visualizer including smoothed $Y$-axis tilt trace.
  - `generate_inspection_gallery.py`: Batch audit card generator into `inspection_gallery/` featuring automated `[CHIN-UP]` vs `[PULL-UP]` badges.
  - `plot_dataset_errors.py`: Generates dataset diagnostic dashboard.
  - `read_fit_reps.py`: Extracts `Total Reps`, `Pull-Up Reps`, `Chin-Up Reps`, and per-lap `Exercise Type` (`PULL UP` / `CHIN UP`) from `.fit` files.
- **Interactive Simulator Launchers**:
  - **Beta Launcher**: [`launch_simulator_beta.ps1`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/launch_simulator_beta.ps1) builds `bin/PullUp-Beta.prg` and launches the Connect IQ Simulator in the interactive desktop session via `scratch/launch_sim.ps1`.
  - **Production Launcher**: [`launch_simulator.ps1`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/launch_simulator.ps1) builds `bin/PullUp.prg` and loads it into the simulator.
- **Closed-Loop Simulator Automation Pipeline**:
  - Comprehensive guide documented in [`SIMULATION.md`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/SIMULATION.md).
  - **Discreet Background Worker (`sim_playback_worker.ps1`)**:
    * Automates the Connect IQ Simulator using background Win32 messages (`PostMessage`, `SendMessage`, `BM_CLICK`, `WM_KEYDOWN`, `SWP_NOACTIVATE`, `HWND_BOTTOM`, and `PrintWindow` with `PW_RENDERFULLCONTENT = 2`).
    * Never steals window focus, never moves the user's mouse cursor, and continues operating cleanly even when the user switches to another Windows Virtual Desktop.
    * Selects option `0` (`FIT/GPX Playable File`) in the Activity Data dialog via `WM_KEYDOWN` (`VK_HOME`) so wxWidgets enables the `Load File` button (`ID=1`) in the background.
    * Traverses the Open File dialog's `ComboBoxEx32` (`ID=1148`) hierarchy to locate the inner `Edit` control (`ID=1001`), sets the `.fit` path via `WM_SETTEXT`, sends `VK_RETURN` (`Enter`), and clicks `Open` (`ID=1`) with a 5-attempt visibility verification loop.
    * Automatically captures background screenshots [`mid_workout_reps.png`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/mid_workout_reps.png) (mid-set) and [`final_set_complete.png`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/final_set_complete.png) (on the Set Complete confirmation screen).
  - **Single-Set Playback Runners (`run_sim_playback_beta.ps1` & `run_sim_playback.ps1`)**:
    * Builds and pushes `bin/PullUp-Beta.prg` (or `bin/PullUp.prg`), runs the background playback worker, extracts the simulator's saved `.fit` activity reps via `read_fit_reps.py`, runs `eval_pipeline.py`, and verifies 100% parity.
    * Supports positive 1-based indexing from the start of `data/` (`1` = first file, `2` = second file, etc.), negative indexing from the end of `data/` (`-1` = latest file, `-2` = second-to-last, etc.), or an explicit file path:
      ```powershell
      # Run on the latest .fit file in data/ (default):
      .\run_sim_playback_beta.ps1 -FitFile -1

      # Run on the 2nd .fit file from the start of data/:
      .\run_sim_playback_beta.ps1 -FitFile 2

      # Run on the 53rd .fit file from the start:
      .\run_sim_playback_beta.ps1 -FitFile 53

      # Run on a specific .fit file path:
      .\run_sim_playback_beta.ps1 -FitFile "data\2026-10-19-20-44-19_chinup_10reps.fit"
      ```
  - **Full Train-Set Batch Parity Suite (`test_all_beta.ps1`)**:
    * Iterates across all training `.fit` files in `data/` (automatically excluding any `test2` holdout files defined in `split.json`).
    * Runs [`run_sim_playback_beta.ps1`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/run_sim_playback_beta.ps1) on each file, verifies `Simulator Detected Reps == Offline Python Reps`, saves each set's final completion screenshot to `sim_images\final_set_completer_<x>.png`, and writes a CSV report to `sim_images\test_all_beta_summary.csv`.
    * Supports full or partial range execution via `-StartIndex` and `-EndIndex`:
      ```powershell
      # Run across the entire training set (1..N):
      .\test_all_beta.ps1

      # Resume or run from a specific index to the end:
      .\test_all_beta.ps1 -StartIndex 53

      # Run a specific sub-range of training sets:
      .\test_all_beta.ps1 -StartIndex 20 -EndIndex 35
      ```
- **Quick Screen Capture Tool**:
  - [`capture_screenshot.ps1`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/capture_screenshot.ps1) / `run_sim_screenshot.ps1`: DPI-aware desktop capture helper for UI audit.
- **App IDs & Dual-Release Architecture**:
  - **Production App ID (`93ef5a4f-b4fb-4e3b-bc44-88b2c8af9403`)**: Used for the public store release on `main`.
  - **Beta App ID (`a3d8b1c2-e4f5-6789-abcd-ef0123456789`)**: Used for live device testing on `beta`. Displays a distinct "BETA" badge on launcher icon and titles the app `"Pull Ups (Beta)"`.
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

## 7. Git Repository Integration & Dual-Branch Workflow

- **Isolated Repository**: `PullUp` is configured as an independent Git repository located at `c:\Users\TLP-001\Documents\Garmin\PullUp`.
- **Branch Hierarchy**:
  - `feat/*`: Topic / feature branches for new development or tuning.
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
