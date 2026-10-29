# launch_simulator_beta.ps1
# Helper to launch the Garmin Connect IQ Simulator and load PullUp Beta
#
# Usage:
#   .\launch_simulator_beta.ps1
#   .\launch_simulator_beta.ps1 -Device fr265

param(
    [string]$Device = "fr165m"
)

$PROJECT = $PSScriptRoot
& "$PROJECT\launch_simulator.ps1" -Device $Device -Beta
