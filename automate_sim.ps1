# automate_sim.ps1
# Full automation pipeline: ensure simulator → build → push → capture screenshot.
#
# IMPORTANT: This script must be run from an interactive PowerShell terminal,
# NOT from a background agent process. The screenshot capture uses a Scheduled Task
# that requires interactive desktop access (Windows Session Isolation).
#
# Usage (from terminal):
#   .\automate_sim.ps1              # Build, push, capture glance view
#   .\automate_sim.ps1 -Down        # Build, push, navigate to main view, capture
#   .\automate_sim.ps1 -SkipBuild   # Skip build, re-push existing binary, capture

param(
    [switch]$Down = $true,
    [string]$SendKey = "",
    [switch]$SkipBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
$PROJECT  = $PSScriptRoot
$SDK_BIN  = "$env:APPDATA\Garmin\ConnectIQ\Sdks\connectiq-sdk-win-9.2.0-2026-06-09-92a1605b2\bin"
$TARGET   = "fr165m"
$OUT_PRG  = "bin\PullUp.prg"
$DEV_KEY  = "developer_key"
$JUNGLE   = "monkey.jungle"
$OUTPUT_PNG = "$PROJECT\simulator_view.png"

# ---------------------------------------------------------------------------
# Step 1 - Ensure Connect IQ Simulator is running
# ---------------------------------------------------------------------------
$simProc = Get-Process -Name "simulator" -ErrorAction SilentlyContinue
if (-not $simProc) {
    Write-Host "[1/4] Launching Connect IQ Simulator..." -ForegroundColor Cyan
    Start-Process "$SDK_BIN\connectiq.bat" -WindowStyle Hidden
    $timeout = 30
    $found = $false
    for ($i = 0; $i -lt $timeout; $i++) {
        Start-Sleep -Seconds 1
        $simProc = Get-Process -Name "simulator" -ErrorAction SilentlyContinue
        if ($simProc) {
            $found = $true
            break
        }
    }
    if (-not $found) {
        Write-Error "Simulator did not start within ${timeout}s. Aborting."
        exit 1
    }
    Write-Host "Simulator launched (PID $($simProc.Id))." -ForegroundColor Green
    Start-Sleep -Seconds 3
} else {
    Write-Host "[1/4] Simulator already running (PID $($simProc.Id))." -ForegroundColor Green
}

# ---------------------------------------------------------------------------
# Step 2 - Build the project
# ---------------------------------------------------------------------------
if (-not $SkipBuild) {
    Write-Host "`n[2/4] Building $TARGET ..." -ForegroundColor Cyan
    & "$SDK_BIN\monkeyc.bat" -d $TARGET -f $JUNGLE -o $OUT_PRG -y $DEV_KEY
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Build FAILED (exit $LASTEXITCODE)."
        exit 1
    }
    Write-Host "Build successful." -ForegroundColor Green
} else {
    Write-Host "`n[2/4] Skipping build (using existing $OUT_PRG)." -ForegroundColor Yellow
}

# ---------------------------------------------------------------------------
# Step 3 - Push binary to simulator via monkeydo
# ---------------------------------------------------------------------------
Write-Host "`n[3/4] Pushing to simulator..." -ForegroundColor Cyan
Start-Process "$SDK_BIN\monkeydo.bat" -ArgumentList "bin/PullUp.prg", $TARGET -WindowStyle Hidden
Start-Sleep -Seconds 3
Write-Host "App pushed to simulator." -ForegroundColor Green

# ---------------------------------------------------------------------------
# Step 4 - Capture screenshot via interactive Scheduled Task
# ---------------------------------------------------------------------------
Write-Host "`n[4/4] Capturing screenshot via Scheduled Task..." -ForegroundColor Cyan
Remove-Item "$PROJECT\capture_status.txt" -ErrorAction SilentlyContinue

try {
    $taskScript = "$PROJECT\run_capture_task.ps1"
    $navArgs = ""
    if ($Down) {
        $navArgs = " -Down"
    } elseif ($SendKey) {
        $navArgs = " -SendKey `"$SendKey`""
    }
    $runnerCode = "& `"$PROJECT\capture_screenshot.ps1`"$navArgs -OutputPath `"$OUTPUT_PNG`" -StatusFile `"$PROJECT\capture_status.txt`" *>&1 | Out-File `"$PROJECT\capture_debug.log`" -Encoding utf8"
    [IO.File]::WriteAllText($taskScript, $runnerCode, [Text.Encoding]::UTF8)

    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$taskScript`""
    $principal = New-ScheduledTaskPrincipal -UserId $env:USERNAME -LogonType Interactive
    Register-ScheduledTask -TaskName "CIQ_ScreenCapture" -Action $action -Principal $principal -Force | Out-Null
    Start-ScheduledTask -TaskName "CIQ_ScreenCapture"

    # Wait for capture to complete (signalled by capture_status.txt)
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Path "$PROJECT\capture_status.txt") { break }
    }

    Unregister-ScheduledTask -TaskName "CIQ_ScreenCapture" -Confirm:$false -ErrorAction SilentlyContinue
} catch {
    Write-Warning "Scheduled task capture failed: $_"
}

# ---------------------------------------------------------------------------
# Report result
# ---------------------------------------------------------------------------
if (Test-Path "$PROJECT\capture_status.txt") {
    $status = (Get-Content "$PROJECT\capture_status.txt" -Raw).Trim()
    if ($status -like "OK*") {
        Write-Host "`n$status" -ForegroundColor Green
    } else {
        Write-Host "`nCapture issue: $status" -ForegroundColor Yellow
    }
} else {
    Write-Warning "Capture timed out or status file not produced."
    Write-Warning "Make sure this script is run from an interactive terminal (not a background agent)."
    exit 1
}

if (Test-Path $OUTPUT_PNG) {
    Write-Host "`nScreenshot saved to: $OUTPUT_PNG" -ForegroundColor Green
} else {
    Write-Warning "Screenshot file not found at $OUTPUT_PNG."
    exit 1
}
