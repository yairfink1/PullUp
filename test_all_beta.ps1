# test_all_beta.ps1
# Runs automated closed-loop Connect IQ Simulator playback & parity verification
# across all training .fit files (per split.json) using run_sim_playback_beta.ps1,
# saving each run's final screenshot to sim_images\final_set_completer_<x>.png.
#
# Usage:
#   .\test_all_beta.ps1
#   .\test_all_beta.ps1 -StartIndex 10 -EndIndex 20

param(
    [int]$StartIndex = 1,
    [int]$EndIndex = -1,
    [int]$ExtraWaitSeconds = 4
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$PROJECT = $PSScriptRoot
$simImagesDir = Join-Path $PROJECT "sim_images"
if (-not (Test-Path $simImagesDir)) {
    New-Item -ItemType Directory -Path $simImagesDir -Force | Out-Null
}

# Load split.json to filter out any test2 sets (keeping only train sets)
$splitPath = Join-Path $PROJECT "split.json"
$testSet = @()
if (Test-Path $splitPath) {
    $splitJson = Get-Content $splitPath -Raw | ConvertFrom-Json
    if ($splitJson.PSObject.Properties.Name -contains "test2") {
        $testSet = @($splitJson.test2)
    } elseif ($splitJson.PSObject.Properties.Name -contains "test") {
        $testSet = @($splitJson.test)
    }
}

$allFitFiles = @(Get-ChildItem -Path (Join-Path $PROJECT "data\*.fit") | Sort-Object Name)
$trainFiles = @($allFitFiles | Where-Object { $testSet -notcontains $_.Name })

if ($trainFiles.Count -eq 0) {
    throw "No training FIT files found in data/ directory."
}

$totalTrain = $trainFiles.Count
if ($EndIndex -lt 0 -or $EndIndex -gt $totalTrain) {
    $EndIndex = $totalTrain
}
if ($StartIndex -lt 1 -or $StartIndex -gt $EndIndex) {
    throw "Invalid range: StartIndex=$StartIndex, EndIndex=$EndIndex (total train files: $totalTrain)."
}

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "  GARMIN SIMULATOR - FULL TRAIN SET PARITY SUITE (PullUp-Beta)" -ForegroundColor Cyan
Write-Host "  Total Train Files : $totalTrain (Running #$StartIndex to #$EndIndex)" -ForegroundColor Cyan
Write-Host "  Screenshots Dir   : $simImagesDir" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

$results = [System.Collections.Generic.List[PSCustomObject]]::new()
$passCount = 0
$failCount = 0

for ($x = $StartIndex; $x -le $EndIndex; $x++) {
    $fileInfo = $trainFiles[$x - 1]
    $relPath = "data\$($fileInfo.Name)"

    Write-Host "`n------------------------------------------------------------------" -ForegroundColor Yellow
    Write-Host "  [$x / $EndIndex] Testing: $($fileInfo.Name)" -ForegroundColor Yellow
    Write-Host "------------------------------------------------------------------" -ForegroundColor Yellow

    $simReps = $null
    $offlineReps = $null
    $passed = $false

    try {
        $outputLines = & (Join-Path $PROJECT "run_sim_playback_beta.ps1") -FitFile $relPath -ExtraWaitSeconds $ExtraWaitSeconds *>&1
        foreach ($line in $outputLines) {
            $text = $line.ToString()
            Write-Host "  $text"
            if ($text -match "^Simulator Detected Reps\s*:\s*(\d+)") {
                $simReps = [int]$Matches[1]
            }
            if ($text -match "^Offline Python Reps\s*:\s*(\d+)") {
                $offlineReps = [int]$Matches[1]
            }
        }

        if ($null -ne $simReps -and $null -ne $offlineReps -and $simReps -eq $offlineReps) {
            $passed = $true
            $passCount++
        } else {
            $failCount++
        }
    } catch {
        Write-Warning "Error during run #$x ($($fileInfo.Name)): $_"
        $failCount++
    }

    # Copy final_set_complete.png -> sim_images\final_set_completer_<x>.png
    $srcImg = Join-Path $PROJECT "final_set_complete.png"
    $dstImg = Join-Path $simImagesDir "final_set_completer_$x.png"
    if (Test-Path $srcImg) {
        Copy-Item -Path $srcImg -Destination $dstImg -Force
        Write-Host "  Saved screenshot: $dstImg" -ForegroundColor Green
    } else {
        Write-Warning "  final_set_complete.png was not found after run #$x"
    }

    $results.Add([PSCustomObject]@{
        Index       = $x
        File        = $fileInfo.Name
        SimReps     = $simReps
        OfflineReps = $offlineReps
        Status      = if ($passed) { "PASS" } else { "FAIL" }
        Screenshot  = "sim_images\final_set_completer_$x.png"
    })
}

# Save summary report to CSV as well for easy inspection
$csvPath = Join-Path $simImagesDir "test_all_beta_summary.csv"
$results | Export-Csv -Path $csvPath -NoTypeInformation -Encoding UTF8

Write-Host "`n==================================================================" -ForegroundColor Cyan
Write-Host "  FINAL SUMMARY: $passCount PASSED / $($passCount + $failCount) TOTAL" -ForegroundColor $(if ($failCount -eq 0) { "Green" } else { "Yellow" })
Write-Host "  Screenshots : $simImagesDir\final_set_completer_<x>.png" -ForegroundColor Cyan
Write-Host "  CSV Report  : $csvPath" -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

if ($failCount -gt 0) {
    Write-Host "`nDiscrepancies / Failures:" -ForegroundColor Red
    $results | Where-Object { $_.Status -ne "PASS" } | Format-Table -AutoSize
}
