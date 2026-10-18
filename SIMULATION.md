# Connect IQ Simulator & Offline Parity Verification Guide

This document provides instructions for compiling the Garmin Pull-Up application, running it inside the Garmin Connect IQ Simulator, feeding raw `.fit` workout recordings into the simulation, extracting the resulting repetition count, and verifying parity against the offline Python analysis suite.

---

## 1. Architecture Overview & Parity Objective

The Pull-Up Counter project maintains two parallel implementations of the repetition detection engine:

```
                          ┌───────────────────────────────────────────────┐
                          │             Raw Accelerometer Data            │
                          │             (Recorded .FIT File)              │
                          └──────────────────────┬────────────────────────┘
                                                 │
                        ┌────────────────────────┴────────────────────────┐
                        ▼                                                 ▼
        ┌───────────────────────────────┐                 ┌───────────────────────────────┐
        │       GARMIN SIMULATOR        │                 │    PYTHON OFFLINE PIPELINE    │
        │   (Monkey C Implementation)   │                 │     (NumPy Implementation)    │
        ├───────────────────────────────┤                 ├───────────────────────────────┤
        │ - source/PullUpDetector.mc    │                 │ - eval_pipeline.py            │
        │ - Executed inside simulator   │                 │ - detect_pullups.py           │
        │ - Writes .FIT to Temp/        │                 │ - generate_inspection_gallery │
        └───────────────┬───────────────┘                 └───────────────┬───────────────┘
                        │                                                 │
                        ▼                                                 ▼
             [Simulated Rep Count]                             [Offline Rep Count]
                        │                                                 │
                        └────────────────────────┬────────────────────────┘
                                                 │
                                                 ▼
                                     ┌───────────────────────┐
                                     │  Parity Verification  │
                                     │   (Sim == Offline)    │
                                     └───────────────────────┘
```

- **Online Engine (Monkey C)**: Located in [`source/PullUpDetector.mc`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/source/PullUpDetector.mc). Runs on the physical watch at 25 Hz or in the simulator at the recording's native rate (100 Hz).
- **Offline Suite (Python)**:
  - [`config.py`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/config.py): Single source of truth for all detector parameters.
  - [`eval_pipeline.py`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/eval_pipeline.py): Canonical offline FSM implementation (`simulate_pullup_online`), dataset benchmarking, and parameter grid search.
  - [`detect_pullups.py`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/detect_pullups.py): Trace-enhanced detector (`simulate_with_trace`) and 3-row diagnostic visualizer.
  - [`generate_inspection_gallery.py`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/generate_inspection_gallery.py): Batch audit card generator (imports `simulate_with_trace` from `detect_pullups.py`).
  - [`plot_dataset_errors.py`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/plot_dataset_errors.py): 4-quadrant dataset diagnostic dashboard.

---

## 2. Environment & Tooling Paths

All paths in PowerShell commands use standard environment variables:

| Tool | Path / Command |
|---|---|
| **Connect IQ SDK Bin** | `$env:APPDATA\Garmin\ConnectIQ\Sdks\connectiq-sdk-win-9.2.0-2026-06-09-92a1605b2\bin` |
| **Monkey C Compiler** | `& "$SDK_BIN\monkeyc.bat"` |
| **Simulator Launcher** | `& "$SDK_BIN\connectiq.bat"` (starts `simulator.exe`) |
| **App Loader** | `& "$SDK_BIN\monkeydo.bat"` |
| **CIQ Shell CLI** | `& "$SDK_BIN\shell.exe"` |
| **Target Device ID** | `fr165m` (Garmin Forerunner 165 Music) |
| **Developer Key** | `developer_key` (in project root) |
| **Build Jungle** | `monkey.jungle` (in project root) |
| **Compiled App** | `bin/PullUp.prg` |
| **Sim Activities Dir** | `$env:LOCALAPPDATA\Temp\com.garmin.connectiq\GARMIN\Activities\` |

---

## 3. Step-by-Step Simulation & Parity Workflow

### Step 1: Compile the Monkey C Application

Build `bin/PullUp.prg` targeting the `fr165m` device:

```powershell
$SDK_BIN = "$env:APPDATA\Garmin\ConnectIQ\Sdks\connectiq-sdk-win-9.2.0-2026-06-09-92a1605b2\bin"
& "$SDK_BIN\monkeyc.bat" -d fr165m -f monkey.jungle -o bin/PullUp.prg -y developer_key
```

Verify that compilation exits with code `0`.

---

### Step 2: Ensure Simulator is Running

Check if `simulator.exe` is already running; if not, launch it:

```powershell
$sim = Get-Process -Name simulator -ErrorAction SilentlyContinue
if (-not $sim) {
    Start-Process "$SDK_BIN\connectiq.bat" -WindowStyle Normal
    Start-Sleep -Seconds 4
}
```

---

### Step 3: Push Application to Simulator

Load the freshly compiled binary into the active simulator:

```powershell
Start-Process "$SDK_BIN\monkeydo.bat" -ArgumentList "bin/PullUp.prg", "fr165m" -WindowStyle Hidden
Start-Sleep -Seconds 3
```

---

### Step 4: Feed the .FIT Accelerometer Data to the Simulator

You can feed the `.fit` file using either the **Automated CLI** or the **Interactive GUI**:

#### Option A: Programmatic CLI (Automated via `shell.exe`)

The Connect IQ SDK includes `shell.exe`, which communicates directly with the simulator over TCP:

```powershell
$FIT_FILE = "C:\Users\TLP-001\Documents\Garmin\PullUp\data\2026-09-21-18-13-48.fit"

# Start parsing / streaming FIT file for simulation playback:
& "$SDK_BIN\shell.exe" fit_parse "$FIT_FILE"
```

To stop playback at any time:
```powershell
& "$SDK_BIN\shell.exe" fit_parse --stop
```

#### Feeding Data & Controlling the Workout on the Watch

The watch application advances through four distinct screens via screen taps (or the physical `ENTER` / `START` key):

```
┌────────────────────────┐      Tap Screen      ┌────────────────────────┐
│      GLANCE VIEW       │ ───────────────────> │  QUICK SET (Page 0)    │
│  "X reps today"        │                      │  "Press START to record"│
└────────────────────────┘                      └───────────┬────────────┘
                                                            │ Tap Screen
                                                            ▼
┌────────────────────────┐      Tap Screen      ┌────────────────────────┐
│      SET COMPLETE      │ <─────────────────── │   ACTIVE RECORDING     │
│  "X reps" (START=Save) │                      │   "SETTLING... / REPS" │
└───────────┬────────────┘                      └────────────────────────┘
            │ Tap Screen
            ▼
┌────────────────────────┐
│      SAVED TO FIT      │
│  Written to Temp/      │
└────────────────────────┘
```

#### Step-by-Step Execution:

1. **Open the Activity Data window**:
   - In the CIQ Simulator menu: **Simulation** -> **Activity Data** (or press menu shortcut).
   - In the playback dialog, select **FIT/GPX Playable File** -> click **Load File**.
   - Browse to your target file (e.g. `c:\Users\TLP-001\Documents\Garmin\PullUp\data\2026-09-21-18-13-48.fit`).
2. **Open the App from Glance**:
   - Tap the watch face on the Glance view (or send `{ENTER}`). The app opens into **Quick Set** ("Press START to record").
3. **Start the Recording Session**:
   - Tap the watch face again. The display changes to **"SETTLING..."** and the elapsed timer begins running.
4. **Start Accelerometer Playback**:
   - In the simulator's **Activity Data** window, click the black **Play (▶)** triangle.
   - The simulator streams high-frequency accelerometer samples into the watch engine.
   - You will see the Rep counter increase live on screen as repetitions are confirmed.
5. **Stop and Save the Set**:
   - Once playback finishes, tap the watch face to stop recording. The screen displays **"SET COMPLETE: X"**.

#### Automated Runner: `run_sim_playback.ps1`

An all-in-one PowerShell script [`run_sim_playback.ps1`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/run_sim_playback.ps1) automates the entire sequence above:
```powershell
.\run_sim_playback.ps1 -FitFile "data\2026-10-04-10-12-50.fit"
```
This script automatically:
1. Builds the Monkey C app (`monkeyc.bat`) and launches the simulator (`monkeydo.bat`).
2. Dispatches [`sim_playback_worker.ps1`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/sim_playback_worker.ps1) via Windows Task Scheduler into the user's interactive desktop session.
3. Positions the simulator at `(50, 50, 760, 920)` and the Activity Data dialog at `(830, 50, 480, 420)` side-by-side to guarantee **zero window overlap**.
4. Selects **FIT/GPX Playable File** and safely loads the target `.fit` file into the Activity Data dialog without shortcut collisions.
5. Taps Glance and starts recording on the watch.
6. Clicks the Play button to stream the 100 Hz accelerometer data.
7. Captures a mid-workout snapshot ([`mid_workout_reps.png`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/mid_workout_reps.png)) showing live incrementing reps.
8. Stops recording, captures the final confirmation view ([`final_set_complete.png`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/final_set_complete.png)), and saves the session.
9. Parses the resulting activity FIT file via [`read_fit_reps.py`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/read_fit_reps.py).
10. Runs offline [`eval_pipeline.py`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/eval_pipeline.py) on the input file and verifies 100% closed-loop parity.

> [!IMPORTANT]
> **Simulator GUI Automation Safety Rules**:
> - **Zero Overlap Layout**: The Activity Data dialog defaults to centering itself over its parent (the simulator window), which blocks watch touch targets. Moving it to `(830, 50)` keeps both windows fully accessible simultaneously.
> - **Never Send `Ctrl+A`**: In Connect IQ Simulator, `Ctrl+A` is the menu shortcut for **`Simulation -> Kill App`**. Sending `^a` to focus or select text in file dialogs causes an audible Windows beep and crashes the watch app to the Garmin blue triangle logo. Always enter file paths directly without `Ctrl+A`.

#### Verified Closed-Loop Benchmark Run:
```text
============================================================
Input FIT File           : data\2026-10-04-10-12-50.fit
Simulator Detected Reps  : 17
Offline Python Reps      : 17
Mid-Workout Screenshot   : mid_workout_reps.png (11 reps at t=16s)
Final Screenshot         : final_set_complete.png (SET COMPLETE: 17)
Output Activity FIT      : 2026-10-04-13-20-24.fit (Total Reps: 17)

>>> RESULT: 100% PARITY CONFIRMED! (Simulator == Offline == 17 reps) <<<
============================================================
```

---

### Step 5: Stop the Workout and Save the Session

1. When playback finishes (or after the final rep), press **STOP** on the watch.
2. Confirm reps on the confirmation/edit view and save the session.
3. The simulator writes the activity summary and developer fields to:
   `$env:LOCALAPPDATA\Temp\com.garmin.connectiq\GARMIN\Activities\YYYY-MM-DD-HH-MM-SS.fit`

---

### Step 6: Extract Rep Count from the Simulator's Output .FIT

Use the project's [`read_fit_reps.py`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/read_fit_reps.py) script to parse the latest simulated activity:

```powershell
# Get the most recently modified FIT file from the simulator's activity directory:
$latestFit = Get-ChildItem -Path "$env:LOCALAPPDATA\Temp\com.garmin.connectiq\GARMIN\Activities\*.fit" |
    Sort-Object LastWriteTime -Descending |
    Select-Object -First 1

python read_fit_reps.py $latestFit.FullName
```

Example output:
```text
========================================
FIT File: ...\2026-10-04-11-43-08.fit
========================================
Total Reps: 5

Lap / Set Breakdown:
  Lap 1: 5 reps
========================================
```

---

### Step 7: Run Offline Python Analysis on the SAME Input File

Run the offline detector on the exact same `.fit` input file that was fed into the simulation:

```powershell
# 1. Single-file detailed trace and rep count:
python detect_pullups.py data/2026-09-21-18-13-48.fit

# 2. Canonical evaluation pipeline:
python eval_pipeline.py data/2026-09-21-18-13-48.fit
```

---

### Step 8: Verify Parity

Compare the three numbers:

| Metric | Source |
|---|---|
| **Simulator Count** | Output of `read_fit_reps.py <sim_output.fit>` |
| **Offline Count** | Output of `detect_pullups.py <input.fit>` or `eval_pipeline.py <input.fit>` |
| **Ground Truth (True Reps)** | Documented in `CONTEXT.md` / `read_fit_reps.py <input.fit>` |

- **Exact Parity Confirmed**: `Simulator Count == Offline Count`.
- **Discrepancy Detected**: If `Simulator Count != Offline Count`, see Section 5 below.

---

## 4. Parameter Synchronization Reference

To maintain parity, any tuning change made in Python must be mirrored in Monkey C:

| Concept | `config.py` (Python) | `PullUpDetector.mc` (Monkey C) | Baseline (100 Hz) |
|---|---|---|---|
| **Running Window** | `WINDOW_SIZE` | `WINDOW_SIZE` | `37` samples |
| **Rep Threshold** | `REP_THRESHOLD` | `BASE_REP_THRESHOLD` | `105` mG |
| **Reset Threshold** | `RESET_THRESHOLD` | `BASE_RESET_THRESHOLD` | `60` mG |
| **Mount Exit Env** | `70` (in state -1) | `MOUNT_EXIT_ENV` | `70` mG |
| **Dismount Surge G** | `1900` | `HIGH_MAG_LEVEL` | `1900` mG (Gated by $X > -300$ mG) |
| **Hang X Release** | `X_RELEASE_THRESHOLD` | `X_RELEASE_THRESHOLD` | `-300` mG |
| **Hang Zone X** | `[-1300, -700]` mG | `[-1300, -700]` mG | `[-1300, -700]` mG |
| **Hang Streak Req** | `HANG_STREAK_REQ` | `_hangStreakReq` | `35` samples (0.35s) |
| **Mount Ceiling** | `130` samples (1.30s) | `_mountCeilingSamples` | `130` samples (1.30s) |
| **Min Wave Dur** | `MIN_WAVE_DURATION` | `_minWaveDuration` | `45` samples (0.45s) |
| **Debounce Floor** | `DEBOUNCE_MIN` | `_debounceMin` | `85` samples (0.85s) |
| **Debounce Base**  | `DEBOUNCE_MIN = 95`       | `_debounceMin = 95`         | `95` samples (0.95s) |
| **Debounce Ceiling**| `DEBOUNCE_MAX = 130`      | `_debounceMax = 130`        | `130` samples (1.30s) |
| **Debounce Adapt** | `min(130, max(95, 0.55*dt))` | `min(130, max(95, 55*dt/100))` | `55%` of interval |
| **Mount Peak Reset**| `current_wave_peak = 0`   | `_currentWavePeak = 0`      | On mount settling exit |
| **Cooldown Timeout**| `COOLDOWN_TIMEOUT_SAMPLES` | `_cooldownTimeoutSamples`   | `100` samples (1.00s) |
| **Latch Streak**   | `X_LATCH_STREAK_LEN`      | `_xLatchStreakLen`          | `35` samples (0.35s) |
| **Prior Cancel Win**| `CANCEL_PRIOR_WINDOW`     | `_cancelPriorWindow`        | `25` samples (0.25s) |
| **Adaptive Rep Floor**| `dyn_rep_floor [82, 95]` | `dynRepFloor [82, 95]`      | Deep fatigue scaling (100% synced) |
| **Adaptive Reset Floor**| `dyn_reset_floor [45, 55]`| `dynResetFloor [45, 55]`    | Deep fatigue scaling (100% synced) |

> [!NOTE]
> **Parameter Synchronization & Fatigue Adaptation**:
> 1. `DEBOUNCE_MIN` is synchronized at `95` samples ($0.95\text{s}$) to reflect human physical minimum cadence and suppress $0.88\text{s} - 0.90\text{s}$ drop rebound oscillations.
> 2. `DEBOUNCE_MAX` is capped at `130` samples ($1.30\text{s}$) to ensure that long rest pauses on the bar ($> 2.5\text{s}$) never lock out subsequent reps.
> 3. Exiting `STATE_MOUNT_SETTLING` explicitly resets `_currentWavePeak = 0` to prevent mount shockwave peaks from contaminating subsequent relative valley checks.
> 4. Dynamic fatigue floors scale with `0.60 * peak_avg` bounded in $[82, 95]\text{ mG}$ for reps $\ge 8$, allowing deep fatigue reps down to $82\text{ mG}$ to confirm.

---

## 5. Troubleshooting Parity Discrepancies

If the simulator and offline Python produce different counts on the same `.fit` file:

1. **High-G Explosive Rep Rejection vs Bar Release**:
   - Check if explosive reps exceeded `1900 mG` during concentric movement.
   - If user is still hanging on the bar ($X \le -300\text{ mG}$), High-G surges must not trigger dismount lockout.
2. **Sample Rate Scaling**:
   - `PullUpDetector.mc` scales sample thresholds in `start(sampleRate)`.
   - Native `.fit` playback from `data/` runs at 100 Hz (`rateScale = 1.0`).
   - If the watch sensor runs at 25 Hz live, `rateScale = 0.25`. Verify which rate the simulation was fed.
3. **Mount Settling Gate**:
   - Check if initial arm-raising shockwave triggered rep `#1` prematurely before user settled in hang.
   - Run `python detect_pullups.py <file>` and verify `Mount:` and `Settle:` timestamps in the title bar.
4. **Bar Release Rollback**:
   - Check if the dismount motion occurred within 0.25s of the final rep confirmation.
   - In `PullUpDetector.mc`, `System.println` outputs `Bar release rollback - retracted rep` if rollback fired. Check the simulator console output.
5. **Interactive GUI vs Headless Agent**:
   - The Connect IQ simulator requires a desktop GUI session to render windows. Background agents cannot directly send keystrokes without using the Scheduled Task bridge ([`capture_screenshot.ps1`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/capture_screenshot.ps1) / [`run_sim_screenshot.ps1`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/run_sim_screenshot.ps1)).
   - For automated closed-loop runs, execute [`run_sim_playback.ps1`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/run_sim_playback.ps1).
6. **App Crash to Blue Triangle Screen (Windows Beep)**:
   - In Connect IQ Simulator, `Ctrl+A` (`^a`) is the menu shortcut for `Simulation -> Kill App`.
   - If an automation script sends `^a` while the main simulator window is focused, the app is killed immediately and the watch resets to the Garmin blue triangle logo.
   - Fix: Always enter file paths directly without sending `Ctrl+A`, or set text via Win32 `WM_SETTEXT` (as implemented in [`sim_playback_worker.ps1`](file:///c:/Users/TLP-001/Documents/Garmin/PullUp/sim_playback_worker.ps1)).
7. **Watch Not Responding to Screen Clicks**:
   - Windows `#32770` dialogs (such as Activity Data) default to opening centered over their parent window. If the dialog covers the watch, clicks intended for Glance or Quick Set hit the dialog instead.
   - Fix: Ensure the side-by-side positioning routine runs before sending clicks to the watch.
8. **Task Scheduler Fails When Laptop is on Battery (Unplugged from AC / HDMI)**:
   - Windows Task Scheduler tasks default to `DisallowStartIfOnBatteries = True`. If the laptop is unplugged, tasks remain in `Queued` state and never execute, leading to null process reference errors.
   - Fix: Always pass `-Settings (New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries)` when creating tasks (`CIQ_LaunchSimulator` and `CIQ_RunPlayback`).
9. **Screen Resolution & Touch Coordinate Scaling (1536x864 / 125% DPI)**:
   - When running on a standalone laptop screen (1536x864 working area), 920px tall windows exceed the display boundary, and hardcoded relative coordinates hit the bezel rim.
   - Fix: Size the simulator to `(20, 10, 740, 800)` and Activity Data to `(780, 10, 480, 400)`. Use relative vertical ratios: Glance tap at ~53% (`$rcSim.Top + int($h * 0.53)`) and screen center at ~67% (`$rcSim.Top + int($h * 0.67)`). Ensure `SetForegroundWindow` is called before watch taps.
