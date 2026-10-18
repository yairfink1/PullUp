# run_sim_screenshot.ps1
# Agent workflow: compile the binary, push to simulator, navigate to screen, and capture screenshot.
#
# Usage: .\run_sim_screenshot.ps1 [-Down] [-SendKey <string>]

param(
    [switch]$Down = $true,
    [string]$SendKey = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
$PROJECT = $PSScriptRoot
$SDK_BIN = "$env:APPDATA\Garmin\ConnectIQ\Sdks\connectiq-sdk-win-9.2.0-2026-06-09-92a1605b2\bin"
$TARGET  = "fr165m"
$OUT_PRG = "bin\PullUp.prg"
$DEV_KEY = "developer_key"
$JUNGLE  = "monkey.jungle"

# ---------------------------------------------------------------------------
# Step 1 - Compile the binary
# ---------------------------------------------------------------------------
Write-Host "Building $TARGET ..." -ForegroundColor Cyan
& "$SDK_BIN\monkeyc.bat" -d $TARGET -f $JUNGLE -o $OUT_PRG -y $DEV_KEY

if ($LASTEXITCODE -ne 0) {
    Write-Error "Build FAILED (exit $LASTEXITCODE)."
    exit 1
}
Write-Host "BUILD SUCCESSFUL." -ForegroundColor Green

# ---------------------------------------------------------------------------
# Step 2 - Push the compiled binary to the running simulator
# ---------------------------------------------------------------------------
# monkeydo.bat is a persistent host process that stays alive for the entire
# simulator session. Start-Process launches it detached with -WindowStyle Hidden.
# ---------------------------------------------------------------------------
Write-Host "`nPushing to simulator..." -ForegroundColor Cyan
Start-Process "$SDK_BIN\monkeydo.bat" -ArgumentList "bin/PullUp.prg", "fr165m" -WindowStyle Hidden
Start-Sleep -Seconds 3
Write-Host "App pushed to simulator." -ForegroundColor Green

# ---------------------------------------------------------------------------
# Step 3 - Bring simulator to foreground, send keys, and capture screenshot
# ---------------------------------------------------------------------------
# Bypasses Windows background session isolation by executing capture_screenshot.ps1
# as the active logged-in user in their interactive desktop session.
# ---------------------------------------------------------------------------
Write-Host "`nCapturing screenshot via interactive Scheduled Task..." -ForegroundColor Cyan
Remove-Item "$PROJECT\capture_status.txt" -ErrorAction SilentlyContinue

try {
    $taskScript = "$PROJECT\run_capture_task.ps1"
    $navArgs = ""
    if ($SendKey) {
        $navArgs = " -SendKey `"$SendKey`""
    } elseif ($Down) {
        $navArgs = " -Down"
    }
    $runnerCode = "& `"$PROJECT\capture_screenshot.ps1`"$navArgs -OutputPath `"$PROJECT\simulator_view.png`" -StatusFile `"$PROJECT\capture_status.txt`" *>&1 | Out-File `"$PROJECT\capture_debug.log`" -Encoding utf8"
    [IO.File]::WriteAllText($taskScript, $runnerCode, [Text.Encoding]::UTF8)

    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-ExecutionPolicy Bypass -WindowStyle Hidden -File `"$taskScript`""
    Register-ScheduledTask -TaskName "CIQ_ScreenCapture" -Action $action -User $env:USERNAME -Force | Out-Null
    Start-ScheduledTask -TaskName "CIQ_ScreenCapture"

    # Wait for capture script to complete
    $captured = $false
    for ($i = 0; $i -lt 60; $i++) {
        Start-Sleep -Milliseconds 500
        if (Test-Path "$PROJECT\capture_status.txt") {
            $captured = $true
            break
        }
    }

    Unregister-ScheduledTask -TaskName "CIQ_ScreenCapture" -Confirm:$false
} catch {
    Write-Warning "Scheduled task capture failed: $_"
}

if (Test-Path "$PROJECT\capture_status.txt") {
    $status = (Get-Content "$PROJECT\capture_status.txt" -Raw).Trim()
    Write-Host "Capture Status: $status" -ForegroundColor $(if ($status -like "OK*") { "Green" } else { "Yellow" })
} else {
    Write-Warning "Capture timed out or status file not produced."
}
