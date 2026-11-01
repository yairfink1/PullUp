# sim_playback_worker.ps1
# Discreet background worker for Connect IQ Simulator workout playback.
# Uses background Win32 messages (PostMessage / SendMessage / SWP_NOACTIVATE / HWND_BOTTOM)
# so it never steals window focus, pops over your screen, or moves your mouse cursor,
# even when you switch to another Windows Virtual Desktop.
#
# Usage:
#   .\sim_playback_worker.ps1 -FitFile "data\2026-10-31-21-42-15_chinup_4reps_24921944389.fit" -DurationSeconds 14

param(
    [Parameter(Mandatory=$true)]
    [string]$FitFile,
    [int]$DurationSeconds = 34,
    [int]$ExtraWaitSeconds = 4,
    [switch]$CaptureScreenshots = $true
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing
if (-not ([System.Management.Automation.PSTypeName]'Win32.DpiHelper').Type) {
    Add-Type -Name 'DpiHelper' -Namespace 'Win32' -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
}
[Win32.DpiHelper]::SetProcessDPIAware() | Out-Null

$PROJECT = $PSScriptRoot

$csharp = @'
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Text;

public class SimAutomationHelper {
    [DllImport("user32.dll")] public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr hWndParent, EnumWindowsProc lpEnumFunc, IntPtr lParam);
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hWnd, out uint lpdwProcessId);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern int GetClassName(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool IsIconic(IntPtr hWnd);
    [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);
    [DllImport("user32.dll")] public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);
    [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);
    [DllImport("user32.dll")] public static extern bool PrintWindow(IntPtr hWnd, IntPtr hdcBlt, uint nFlags);
    [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr hWnd, ref POINT lpPoint);
    [DllImport("user32.dll")] public static extern IntPtr GetDlgItem(IntPtr hDlg, int nIDDlgItem);
    [DllImport("user32.dll")] public static extern int GetDlgCtrlID(IntPtr hWnd);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, string lParam);
    [DllImport("user32.dll", CharSet = CharSet.Auto)] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, StringBuilder lParam);
    [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")] public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);

    public const uint WM_COMMAND        = 0x0111;
    public const uint WM_CLOSE          = 0x0010;
    public const uint WM_SETTEXT        = 0x000C;
    public const uint WM_GETTEXT        = 0x000D;
    public const uint WM_KEYDOWN        = 0x0100;
    public const uint WM_KEYUP          = 0x0101;
    public const uint WM_MOUSEMOVE      = 0x0200;
    public const uint WM_LBUTTONDOWN    = 0x0201;
    public const uint WM_LBUTTONUP      = 0x0202;
    public const uint BM_CLICK          = 0x00F5;
    public const uint CB_GETCURSEL      = 0x0147;
    public const uint CB_SETCURSEL      = 0x014E;
    public const int  VK_HOME           = 0x24;
    public const int  SW_SHOWNOACTIVATE = 4;
    public const uint SWP_NOSIZE        = 0x0001;
    public const uint SWP_NOMOVE        = 0x0002;
    public const uint SWP_NOACTIVATE    = 0x0010;
    public static readonly IntPtr HWND_BOTTOM = new IntPtr(1);

    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int Left, Top, Right, Bottom; }
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }

    public static RECT GetBounds(IntPtr hWnd) {
        RECT rc;
        GetWindowRect(hWnd, out rc);
        return rc;
    }

    public static Bitmap CaptureBackground(IntPtr hWnd) {
        RECT rc;
        GetWindowRect(hWnd, out rc);
        int w = rc.Right - rc.Left;
        int h = rc.Bottom - rc.Top;
        if (w <= 0 || h <= 0) { w = 740; h = 1020; }
        Bitmap bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb);
        using (Graphics g = Graphics.FromImage(bmp)) {
            IntPtr hdc = g.GetHdc();
            try {
                // PW_RENDERFULLCONTENT = 0x00000002 renders the window's DWM surface in background
                bool ok = PrintWindow(hWnd, hdc, 2);
                if (!ok) {
                    PrintWindow(hWnd, hdc, 0);
                }
            } finally {
                g.ReleaseHdc(hdc);
            }
        }
        return bmp;
    }

    public static IntPtr MakeLParam(int x, int y) {
        return (IntPtr)((y << 16) | (x & 0xFFFF));
    }

    public static void BackgroundClickScreenOnChild(IntPtr childHwnd, int screenX, int screenY) {
        POINT pt = new POINT { X = screenX, Y = screenY };
        ScreenToClient(childHwnd, ref pt);
        IntPtr lParam = MakeLParam(pt.X, pt.Y);
        PostMessage(childHwnd, WM_MOUSEMOVE, IntPtr.Zero, lParam);
        System.Threading.Thread.Sleep(30);
        PostMessage(childHwnd, WM_LBUTTONDOWN, (IntPtr)1, lParam);
        System.Threading.Thread.Sleep(80);
        PostMessage(childHwnd, WM_LBUTTONUP, IntPtr.Zero, lParam);
        System.Threading.Thread.Sleep(150);
    }

    public static string GetControlText(IntPtr hWnd) {
        if (hWnd == IntPtr.Zero) return "";
        StringBuilder sb = new StringBuilder(512);
        SendMessage(hWnd, WM_GETTEXT, (IntPtr)512, sb);
        return sb.ToString();
    }

    public const int  VK_RETURN         = 0x0D;

    public static bool SetOpenDialogPathAndAccept(IntPtr openHwnd, string fitPath) {
        IntPtr targetEdit = IntPtr.Zero;

        // 1. First look for ComboBoxEx32 or ComboBox with ID 1148 (standard file name box)
        EnumChildWindows(openHwnd, (hChild, lp) => {
            int id = GetDlgCtrlID(hChild);
            if (id == 1148) {
                StringBuilder ccls = new StringBuilder(256);
                GetClassName(hChild, ccls, 256);
                string cls = ccls.ToString();
                if (cls.Equals("Edit", StringComparison.OrdinalIgnoreCase)) {
                    targetEdit = hChild;
                    return false;
                }
                // Check if it has a child Edit control
                EnumChildWindows(hChild, (hInner, lp2) => {
                    StringBuilder icls = new StringBuilder(256);
                    GetClassName(hInner, icls, 256);
                    if (icls.ToString().Equals("Edit", StringComparison.OrdinalIgnoreCase)) {
                        targetEdit = hInner;
                        return false;
                    }
                    return true;
                }, IntPtr.Zero);
                if (targetEdit != IntPtr.Zero) return false;
            }
            return true;
        }, IntPtr.Zero);

        // 2. Fallback: find any Edit control that is not search box
        if (targetEdit == IntPtr.Zero) {
            EnumChildWindows(openHwnd, (hChild, lp) => {
                StringBuilder ccls = new StringBuilder(256);
                GetClassName(hChild, ccls, 256);
                if (ccls.ToString().Equals("Edit", StringComparison.OrdinalIgnoreCase)) {
                    targetEdit = hChild;
                    return false;
                }
                return true;
            }, IntPtr.Zero);
        }

        if (targetEdit != IntPtr.Zero) {
            SendMessage(targetEdit, WM_SETTEXT, IntPtr.Zero, fitPath);
            System.Threading.Thread.Sleep(100);

            // Send Enter key to Edit control
            PostMessage(targetEdit, WM_KEYDOWN, (IntPtr)VK_RETURN, IntPtr.Zero);
            PostMessage(targetEdit, WM_KEYUP,   (IntPtr)VK_RETURN, IntPtr.Zero);
            System.Threading.Thread.Sleep(150);
        }

        // Also click Open button (ID 1)
        IntPtr hOpenBtn = GetDlgItem(openHwnd, 1);
        if (hOpenBtn != IntPtr.Zero) {
            PostMessage(hOpenBtn, BM_CLICK, IntPtr.Zero, IntPtr.Zero);
        }
        PostMessage(openHwnd, WM_COMMAND, (IntPtr)1, hOpenBtn);

        return targetEdit != IntPtr.Zero;
    }

    public static IntPtr FindSimulatorWindow(uint targetPid) {
        IntPtr found = IntPtr.Zero;
        EnumWindows((hWnd, lParam) => {
            if (!IsWindowVisible(hWnd)) return true;
            uint pid;
            GetWindowThreadProcessId(hWnd, out pid);
            if (pid == targetPid) {
                StringBuilder cls = new StringBuilder(256);
                GetClassName(hWnd, cls, 256);
                if (cls.ToString() == "wxWindowNR") {
                    StringBuilder sb = new StringBuilder(256);
                    GetWindowText(hWnd, sb, 256);
                    if (sb.ToString().IndexOf("CIQ Simulator", StringComparison.OrdinalIgnoreCase) >= 0) {
                        found = hWnd;
                        return false;
                    }
                }
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    public static IntPtr FindChildPanel(IntPtr simHwnd) {
        IntPtr found = IntPtr.Zero;
        EnumChildWindows(simHwnd, (hWnd, lParam) => {
            StringBuilder sb = new StringBuilder(256);
            GetWindowText(hWnd, sb, 256);
            if (sb.ToString() == "panel") {
                found = hWnd;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return found;
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
                    StringBuilder txt = new StringBuilder(256);
                    GetWindowText(hWnd, txt, 256);
                    if (txt.ToString().Length == 0 || txt.ToString().IndexOf("Activity", StringComparison.OrdinalIgnoreCase) >= 0) {
                        found = hWnd;
                        return false;
                    }
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

    public static void CloseExtraDialogs(uint targetPid, IntPtr keepHwnd) {
        EnumWindows((hWnd, lParam) => {
            if (!IsWindowVisible(hWnd) || hWnd == keepHwnd) return true;
            uint pid;
            GetWindowThreadProcessId(hWnd, out pid);
            if (pid == targetPid) {
                StringBuilder cls = new StringBuilder(256);
                GetClassName(hWnd, cls, 256);
                if (cls.ToString() == "#32770") {
                    PostMessage(hWnd, WM_CLOSE, IntPtr.Zero, IntPtr.Zero);
                }
            }
            return true;
        }, IntPtr.Zero);
    }

    public static IntPtr FindChildByClassAndText(IntPtr parent, string className, string textContains) {
        IntPtr found = IntPtr.Zero;
        EnumChildWindows(parent, (hWnd, lParam) => {
            StringBuilder cls = new StringBuilder(256);
            GetClassName(hWnd, cls, 256);
            if (className == null || cls.ToString().Equals(className, StringComparison.OrdinalIgnoreCase)) {
                if (textContains == null) {
                    found = hWnd;
                    return false;
                }
                StringBuilder txt = new StringBuilder(256);
                GetWindowText(hWnd, txt, 256);
                if (txt.ToString().IndexOf(textContains, StringComparison.OrdinalIgnoreCase) >= 0) {
                    found = hWnd;
                    return false;
                }
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }
}
'@

if (-not ([System.Management.Automation.PSTypeName]'SimAutomationHelper').Type) {
    Add-Type -TypeDefinition $csharp -ReferencedAssemblies 'System.Drawing' -ErrorAction Stop
}

$fullFitPath = [IO.Path]::GetFullPath($FitFile)
if (-not (Test-Path $fullFitPath)) {
    throw "Target FIT file not found: $fullFitPath"
}

# -------------------------------------------------------------------------
# Step 1: Ensure Simulator Window is Sized in Background (HWND_BOTTOM, No Activate)
# -------------------------------------------------------------------------
$simProc = Get-Process -Name simulator -ErrorAction Stop | Select-Object -First 1
$simHwnd = [SimAutomationHelper]::FindSimulatorWindow($simProc.Id)
if ($simHwnd -eq [IntPtr]::Zero) { throw "Simulator window not found" }

if ([SimAutomationHelper]::IsIconic($simHwnd)) {
    [SimAutomationHelper]::ShowWindow($simHwnd, [SimAutomationHelper]::SW_SHOWNOACTIVATE) | Out-Null
    Start-Sleep -Milliseconds 300
}
[SimAutomationHelper]::SetWindowPos($simHwnd, [SimAutomationHelper]::HWND_BOTTOM, 20, 10, 740, 1020, [SimAutomationHelper]::SWP_NOACTIVATE) | Out-Null
Start-Sleep -Milliseconds 300

$panelHwnd = [SimAutomationHelper]::FindChildPanel($simHwnd)
if ($panelHwnd -eq [IntPtr]::Zero) { throw "Watch canvas panel not found" }

# -------------------------------------------------------------------------
# Step 2: Open Activity Data Dialog in Background (HWND_BOTTOM, No Activate)
# -------------------------------------------------------------------------
$actHwnd = [SimAutomationHelper]::FindActivityDialog($simProc.Id)
if ($actHwnd -eq [IntPtr]::Zero) {
    Write-Host "Opening Activity Data dialog via WM_COMMAND 6170..."
    [SimAutomationHelper]::PostMessage($simHwnd, [SimAutomationHelper]::WM_COMMAND, [IntPtr]6170, [IntPtr]::Zero) | Out-Null
    Start-Sleep -Milliseconds 1200
    $actHwnd = [SimAutomationHelper]::FindActivityDialog($simProc.Id)
}
if ($actHwnd -eq [IntPtr]::Zero) { throw "Failed to open Activity Data dialog" }

[SimAutomationHelper]::SetWindowPos($actHwnd, [SimAutomationHelper]::HWND_BOTTOM, 780, 10, 480, 400, [SimAutomationHelper]::SWP_NOACTIVATE) | Out-Null
[SimAutomationHelper]::CloseExtraDialogs($simProc.Id, $actHwnd)
Start-Sleep -Milliseconds 250

# -------------------------------------------------------------------------
# Step 3: Select Option 0 ('FIT/GPX Playable File') via WM_KEYDOWN VK_HOME
#         so wxWidgets genuinely enables the 'Load File' button in background!
# -------------------------------------------------------------------------
$hCombo = [SimAutomationHelper]::GetDlgItem($actHwnd, 0)
$hLoadBtn = [SimAutomationHelper]::GetDlgItem($actHwnd, 1)

if ($hCombo -ne [IntPtr]::Zero) {
    # Send WM_KEYDOWN / WM_KEYUP VK_HOME directly to ComboBox in background
    [SimAutomationHelper]::SendMessage($hCombo, [SimAutomationHelper]::WM_KEYDOWN, [IntPtr][SimAutomationHelper]::VK_HOME, [IntPtr]::Zero) | Out-Null
    [SimAutomationHelper]::SendMessage($hCombo, [SimAutomationHelper]::WM_KEYUP,   [IntPtr][SimAutomationHelper]::VK_HOME, [IntPtr]::Zero) | Out-Null
    Start-Sleep -Milliseconds 400
}

# Click 'Load File' button in background once enabled
if ($hLoadBtn -eq [IntPtr]::Zero) { throw "Load File button not found" }
[SimAutomationHelper]::PostMessage($hLoadBtn, [SimAutomationHelper]::BM_CLICK, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null

$openHwnd = [IntPtr]::Zero
for ($i = 0; $i -lt 20; $i++) {
    Start-Sleep -Milliseconds 150
    $openHwnd = [SimAutomationHelper]::FindOpenDialog($simProc.Id, $actHwnd)
    if ($openHwnd -ne [IntPtr]::Zero) { break }
}

if ($openHwnd -ne [IntPtr]::Zero) {
    # Keep Open dialog behind all windows without activating
    [SimAutomationHelper]::SetWindowPos($openHwnd, [SimAutomationHelper]::HWND_BOTTOM, 780, 420, 580, 380, [SimAutomationHelper]::SWP_NOACTIVATE) | Out-Null
    Start-Sleep -Milliseconds 250

    $accepted = $false
    for ($attempt = 1; $attempt -le 5; $attempt++) {
        [SimAutomationHelper]::SetOpenDialogPathAndAccept($openHwnd, $fullFitPath) | Out-Null
        Start-Sleep -Milliseconds 350
        if (-not [SimAutomationHelper]::IsWindowVisible($openHwnd)) {
            $accepted = $true
            break
        }
    }

    if (-not $accepted) {
        Write-Warning "Open dialog did not close automatically; closing dialog."
        [SimAutomationHelper]::PostMessage($openHwnd, [SimAutomationHelper]::WM_CLOSE, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
    }

    Start-Sleep -Milliseconds 400
    $hFileEdit = [SimAutomationHelper]::FindChildByClassAndText($actHwnd, "Edit", $null)
    Write-Host "FIT file loaded in background: '$([SimAutomationHelper]::GetControlText($hFileEdit))'" -ForegroundColor Green
} else {
    Write-Warning "Open dialog was not found."
}

# -------------------------------------------------------------------------
# Step 4: Control Watch in Background via panelHwnd (Glance -> Quick Set -> Start)
# -------------------------------------------------------------------------
$rcSim = [SimAutomationHelper]::GetBounds($simHwnd)
$w = $rcSim.Right - $rcSim.Left
$h = $rcSim.Bottom - $rcSim.Top

$glanceX = $rcSim.Left + [int]($w * 0.51)
$glanceY = $rcSim.Top + [int]($h * 0.41)
$centerX = $rcSim.Left + [int]($w * 0.51)
$centerYRatio = if ($h -gt 900) { 0.575 } else { 0.67 }
$centerY = $rcSim.Top + [int]($h * $centerYRatio)

Write-Host "Background touch points -> Glance: ($glanceX, $glanceY), Center: ($centerX, $centerY)" -ForegroundColor Cyan

# Tap Glance in background
[SimAutomationHelper]::BackgroundClickScreenOnChild($panelHwnd, $glanceX, $glanceY)
Start-Sleep -Milliseconds 2200

# Tap screen center in background to start recording
[SimAutomationHelper]::BackgroundClickScreenOnChild($panelHwnd, $centerX, $centerY)
Start-Sleep -Milliseconds 1500

# -------------------------------------------------------------------------
# Step 5: Click Play (▶) Button (ID=11) in Background via BM_CLICK
# -------------------------------------------------------------------------
$hPlayBtn = [SimAutomationHelper]::GetDlgItem($actHwnd, 11)
[SimAutomationHelper]::PostMessage($hPlayBtn, [SimAutomationHelper]::BM_CLICK, [IntPtr]::Zero, [IntPtr]::Zero) | Out-Null
Write-Host "Playback started in background! Streaming data for $DurationSeconds seconds..." -ForegroundColor Cyan

# -------------------------------------------------------------------------
# Step 6: Stream Accelerometer Data
# -------------------------------------------------------------------------
$totalWait = $DurationSeconds + $ExtraWaitSeconds
$midWait = [Math]::Min(16, [int]($totalWait / 2))

if ($CaptureScreenshots -and $midWait -gt 5) {
    Start-Sleep -Seconds $midWait
    $bmpMid = [SimAutomationHelper]::CaptureBackground($simHwnd)
    $bmpMid.Save("$PROJECT\mid_workout_reps.png", [System.Drawing.Imaging.ImageFormat]::Png)
    $bmpMid.Dispose()
    $remWait = $totalWait - $midWait
    if ($remWait -gt 0) { Start-Sleep -Seconds $remWait }
} else {
    Start-Sleep -Seconds $totalWait
}

# -------------------------------------------------------------------------
# Step 7: Tap Watch Screen in Background to STOP Recording
# -------------------------------------------------------------------------
Write-Host "Stopping recording in background..."
[SimAutomationHelper]::BackgroundClickScreenOnChild($panelHwnd, $centerX, $centerY)
Start-Sleep -Milliseconds 2000

if ($CaptureScreenshots) {
    $bmpFinal = [SimAutomationHelper]::CaptureBackground($simHwnd)
    $bmpFinal.Save("$PROJECT\final_set_complete.png", [System.Drawing.Imaging.ImageFormat]::Png)
    $bmpFinal.Dispose()
}

# -------------------------------------------------------------------------
# Step 8: Tap Watch Screen in Background to SAVE Workout Session
# -------------------------------------------------------------------------
Write-Host "Saving workout session in background..."
[SimAutomationHelper]::BackgroundClickScreenOnChild($panelHwnd, $centerX, $centerY)
Start-Sleep -Seconds 2

[IO.File]::WriteAllText("$PROJECT\scratch\playback_done.txt", "OK")
Write-Host "Worker completed discreetly in background!" -ForegroundColor Green
