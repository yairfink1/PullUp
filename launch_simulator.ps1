# launch_simulator.ps1
# Simple helper to launch the Garmin Connect IQ Simulator and load PullUp

param(
    [string]$Device = "fr165m",
    [switch]$Beta
)

$SDK_BIN = "$env:APPDATA\Garmin\ConnectIQ\Sdks\connectiq-sdk-win-9.2.0-2026-06-09-92a1605b2\bin"
$simExe  = Join-Path $SDK_BIN "simulator.exe"
$monkeydo = Join-Path $SDK_BIN "monkeydo.bat"
$PROJECT = $PSScriptRoot

# 1. Start simulator using interactive task launcher if not running
$simProc = Get-Process -Name simulator -ErrorAction SilentlyContinue
if (-not $simProc) {
    Write-Host "Launching Connect IQ Simulator via interactive task..." -ForegroundColor Cyan
    & "$PROJECT\scratch\launch_sim.ps1"
    Start-Sleep -Seconds 3
    $simProc = Get-Process -Name simulator -ErrorAction SilentlyContinue
}

if ($simProc) {
    Write-Host "Simulator is running (PID: $($simProc.Id))." -ForegroundColor Green
} else {
    Write-Warning "Could not confirm simulator process."
}

# 2. Build target binary if needed
$prgName = if ($Beta) { "PullUp-Beta.prg" } else { "PullUp.prg" }
$buildScript = if ($Beta) { "build_beta.ps1" } else { "build_prod.ps1" }
$prgPath = Join-Path $PROJECT "bin\$prgName"

if (-not (Test-Path $prgPath)) {
    Write-Host "Building $prgName..." -ForegroundColor Yellow
    & "$PROJECT\$buildScript" -Target prg -Device $Device
}

# 3. Push PRG to simulator using monkeydo
Write-Host "Loading $prgName onto $Device simulator..." -ForegroundColor Green
Start-Process $monkeydo -ArgumentList "bin/$prgName", $Device -WorkingDirectory $PROJECT

Write-Host "[OK] PullUp loaded in simulator!" -ForegroundColor Cyan
