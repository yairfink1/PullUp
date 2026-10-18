# sim_playback_worker.ps1
# Interactive desktop worker for Connect IQ Simulator workout playback.
# Executed in the user's interactive session via Scheduled Task.
#
# Usage:
#   .\sim_playback_worker.ps1 -FitFile "data\2026-10-04-10-12-50.fit" -DurationSeconds 34

param(
    [Parameter(Mandatory=$true)]
    [string]$FitFile,
    [int]$DurationSeconds = 34,
    [int]$ExtraWaitSeconds = 4
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes

$PROJECT = $PSScriptRoot
. "$PROJECT\capture_screenshot.ps1"

# Compile Win32 layout and input helper using a temporary .cs file to avoid escaping issues
$csharp = @'
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Drawing;

public class SimAutomationHelper {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern int GetClassName(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr hDlg, int nIDDlgItem);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, string lParam);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern void mouse_event(uint dwFlags, int dx, int dy, uint dwData, UIntPtr dwExtraInfo);
    [DllImport("user32.dll")] public static extern bool SetCursorPos(int X, int Y);

    public const uint WM_COMMAND = 0x0111;
    public const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    public const uint MOUSEEVENTF_LEFTUP   = 0x0004;

    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }

    public static void Click(int x, int y) {
        SetCursorPos(x, y);
        System.Threading.Thread.Sleep(80);
        mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
        System.Threading.Thread.Sleep(100);
        mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
        System.Threading.Thread.Sleep(200);
    }

    public static IntPtr FindActivityDialog(uint targetPid) {
        IntPtr found = IntPtr.Zero;
        EnumWindows((hWnd, lParam) => {
            if (!IsWindowVisible(hWnd)) return true;
            uint pid;
            GetWindowThreadProcessId(hWnd, out pid);
            if (pid == targetPid) {
                StringBuilder cls = new StringBuilder(256);
                GetClassName(hWnd, cls, 256);
                if (cls.ToString() == "#32770") {
                    found = hWnd;
                    return false;
                }
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    public static IntPtr FindOpenDialog(uint targetPid, IntPtr excludeHwnd) {
        IntPtr found = IntPtr.Zero;
        EnumWindows((hWnd, lParam) => {
            if (!IsWindowVisible(hWnd) || hWnd == excludeHwnd) return true;
            uint pid;
            GetWindowThreadProcessId(hWnd, out pid);
            if (pid == targetPid) {
                StringBuilder cls = new StringBuilder(256);
                GetClassName(hWnd, cls, 256);
                if (cls.ToString() == "#32770") {
                    StringBuilder text = new StringBuilder(256);
                    GetWindowText(hWnd, text, 256);
                    string t = text.ToString();
                    if (t.IndexOf("Open", StringComparison.OrdinalIgnoreCase) >= 0 ||
                        t.IndexOf("FIT", StringComparison.OrdinalIgnoreCase) >= 0) {
                        found = hWnd;
                        return false;
                    }
                }
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
'@

$tempCs = [IO.Path]::ChangeExtension([IO.Path]::GetTempFileName(), '.cs')
[IO.File]::WriteAllText($tempCs, $csharp, [Text.Encoding]::UTF8)
Add-Type -Path $tempCs -ReferencedAssemblies 'System.Drawing' -ErrorAction Stop
Remove-Item $tempCs -Force

$fullFitPath = [IO.Path]::GetFullPath($FitFile)
$fitFileName = [IO.Path]::GetFileName($fullFitPath)

# -------------------------------------------------------------------------
# Step 1: Position Simulator Window on Left (20, 10, 740, 800)
# -------------------------------------------------------------------------
$simHwnd = [SimCaptureV3]::FindSimulatorWindow()
if ($simHwnd -eq [IntPtr]::Zero) { throw "Simulator window not found" }
[SimAutomationHelper]::ShowWindow($simHwnd, 9)
[SimAutomationHelper]::SetWindowPos($simHwnd, [IntPtr]::Zero, 20, 10, 740, 800, 0x0040)
Start-Sleep -Milliseconds 600

# -------------------------------------------------------------------------
# Step 2: Open & Position Activity Data Dialog on Right (780, 10, 480, 400)
# -------------------------------------------------------------------------
$simProc = Get-Process -Name simulator
$actHwnd = [SimAutomationHelper]::FindActivityDialog($simProc.Id)
if ($actHwnd -eq [IntPtr]::Zero) {
    Write-Host "Opening Activity Data dialog via WM_COMMAND 6170..."
    [SimAutomationHelper]::PostMessage($simHwnd, 0x0111, [IntPtr]6170, [IntPtr]::Zero)
    Start-Sleep -Seconds 2
    $actHwnd = [SimAutomationHelper]::FindActivityDialog($simProc.Id)
}

if ($actHwnd -eq [IntPtr]::Zero) { throw "Failed to open Activity Data dialog" }

# Move dialog to the right so it never overlaps the watch
[SimAutomationHelper]::ShowWindow($actHwnd, 9)
[SimAutomationHelper]::SetWindowPos($actHwnd, [IntPtr]::Zero, 780, 10, 480, 400, 0x0040)
Start-Sleep -Milliseconds 600

# -------------------------------------------------------------------------
# Step 3: Select FIT/GPX Playable File & Load File
# -------------------------------------------------------------------------
$rcAct = New-Object SimAutomationHelper+RECT
[SimAutomationHelper]::GetWindowRect($actHwnd, [ref]$rcAct)

# Click ComboBox to focus it, then send 'f' and ENTER to select FIT/GPX Playable File
[SimAutomationHelper]::SetForegroundWindow($actHwnd)
Start-Sleep -Milliseconds 300
$comboX = $rcAct.Left + 350
$comboY = $rcAct.Top + 60
[SimAutomationHelper]::Click($comboX, $comboY)
Start-Sleep -Milliseconds 400
[System.Windows.Forms.SendKeys]::SendWait("f")
Start-Sleep -Milliseconds 300
[System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
Start-Sleep -Seconds 1

# Check if Open dialog appeared automatically; if not, click Load File button
$openHwnd = [SimAutomationHelper]::FindOpenDialog($simProc.Id, $actHwnd)
if ($openHwnd -eq [IntPtr]::Zero) {
    # Click Load File button via UIA or relative coordinates
    $actElem = [System.Windows.Automation.AutomationElement]::FromHandle($actHwnd)
    $condLoad = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, "Load File")
    $loadBtn = $actElem.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condLoad)
    if ($loadBtn) {
        $rc = $loadBtn.Current.BoundingRectangle
        [SimAutomationHelper]::Click([int]($rc.X + $rc.Width / 2), [int]($rc.Y + $rc.Height / 2))
    } else {
        # Fallback relative to dialog: rcAct.Left + 250, rcAct.Top + 80
        [SimAutomationHelper]::Click($rcAct.Left + 250, $rcAct.Top + 80)
    }
    Start-Sleep -Seconds 1
    $openHwnd = [SimAutomationHelper]::FindOpenDialog($simProc.Id, $actHwnd)
}

# In Open dialog: Position it on right and type file path/name
if ($openHwnd -ne [IntPtr]::Zero) {
    [SimAutomationHelper]::SetWindowPos($openHwnd, [IntPtr]::Zero, 780, 420, 580, 380, 0x0040)
    [SimAutomationHelper]::SetForegroundWindow($openHwnd)
    Start-Sleep -Milliseconds 500

    # The file name edit box is already focused on open
    # Send the full path or filename and press ENTER (NO ^a used!)
    [System.Windows.Forms.SendKeys]::SendWait($fullFitPath)
    Start-Sleep -Milliseconds 400
    [System.Windows.Forms.SendKeys]::SendWait("{ENTER}")
    Start-Sleep -Seconds 2
    Write-Host "FIT file loaded into simulator." -ForegroundColor Green
} else {
    Write-Warning "Open dialog was not found. File may already be loaded."
}

# -------------------------------------------------------------------------
# Step 4: Control Watch (Glance -> Quick Set -> Start Recording)
# -------------------------------------------------------------------------
[SimAutomationHelper]::SetForegroundWindow($simHwnd)
Start-Sleep -Milliseconds 500

$rcSim = [SimCaptureV3]::GetBounds($simHwnd)
$w = $rcSim.Right - $rcSim.Left
$h = $rcSim.Bottom - $rcSim.Top

# Glance row is at ~53% of window height; screen center is at ~67%
$glanceX = $rcSim.Left + [int]($w * 0.51)
$glanceY = $rcSim.Top + [int]($h * 0.53)
$centerX = $rcSim.Left + [int]($w * 0.51)
$centerY = $rcSim.Top + [int]($h * 0.67)

Write-Host "Glance touch point: ($glanceX, $glanceY), Center touch point: ($centerX, $centerY)" -ForegroundColor Cyan

# Tap Glance to open Quick Set
[SimAutomationHelper]::Click($glanceX, $glanceY)
Start-Sleep -Milliseconds 2200

# Tap screen center to start recording ("SETTLING...")
[SimAutomationHelper]::Click($centerX, $centerY)
Start-Sleep -Milliseconds 1500

# -------------------------------------------------------------------------
# Step 5: Click Play (▶) Button in Activity Data Dialog
# -------------------------------------------------------------------------
$actElem = [System.Windows.Automation.AutomationElement]::FromHandle($actHwnd)
$condPlay = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::AutomationIdProperty, "11")
$playBtn = $actElem.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condPlay)

if ($playBtn) {
    $rc = $playBtn.Current.BoundingRectangle
    $playX = [int]($rc.X + $rc.Width / 2)
    $playY = [int]($rc.Y + $rc.Height / 2)
    [SimAutomationHelper]::Click($playX, $playY)
} else {
    # Fallback coordinates for Play button (relative to Activity Data dialog)
    [SimAutomationHelper]::Click($rcAct.Left + 31, $rcAct.Top + 292)
}
Write-Host "Playback started! Streaming data for $DurationSeconds seconds..." -ForegroundColor Cyan

# -------------------------------------------------------------------------
# Step 6: Stream Accelerometer Data & Take Mid-Workout Screenshot
# -------------------------------------------------------------------------
$totalWait = $DurationSeconds + $ExtraWaitSeconds
$midWait = [Math]::Min(16, [int]($totalWait / 2))

if ($midWait -gt 5) {
    Start-Sleep -Seconds $midWait
    Write-Host "Capturing mid-workout live reps..."
    $bmpMid = [SimCaptureV3]::CaptureWindow($simHwnd)
    $bmpMid.Save("$PROJECT\mid_workout_reps.png", [System.Drawing.Imaging.ImageFormat]::Png)
    $bmpMid.Dispose()
    $remWait = $totalWait - $midWait
    if ($remWait -gt 0) { Start-Sleep -Seconds $remWait }
} else {
    Start-Sleep -Seconds $totalWait
}

# -------------------------------------------------------------------------
# Step 7: Tap Watch Screen to STOP Recording & Capture Final View
# -------------------------------------------------------------------------
Write-Host "Stopping recording..."
[SimAutomationHelper]::SetForegroundWindow($simHwnd)
[SimAutomationHelper]::Click($centerX, $centerY)
Start-Sleep -Milliseconds 2000

Write-Host "Capturing final set complete screenshot..."
$bmpFinal = [SimCaptureV3]::CaptureWindow($simHwnd)
$bmpFinal.Save("$PROJECT\final_set_complete.png", [System.Drawing.Imaging.ImageFormat]::Png)
$bmpFinal.Dispose()

# -------------------------------------------------------------------------
# Step 8: Tap Watch Screen to SAVE Workout Session
# -------------------------------------------------------------------------
Write-Host "Saving workout session..."
[SimAutomationHelper]::Click($centerX, $centerY)
Start-Sleep -Seconds 2

[IO.File]::WriteAllText("$PROJECT\scratch\playback_done.txt", "OK")
Write-Host "Worker completed successfully!" -ForegroundColor Green
