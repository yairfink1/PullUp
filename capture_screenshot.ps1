# capture_screenshot.ps1
# Captures the CIQ Simulator window and saves it to simulator_view.png.
# Designed to be called by run_sim_screenshot.ps1 via Start-Process or Scheduled Task
# so that it runs in its own interactive desktop context where CopyFromScreen works.
#
# Usage: .\capture_screenshot.ps1 [-OutputPath <path>] [-StatusFile <path>] [-Down] [-SendKey <string>]

param(
    [string]$OutputPath = "$PSScriptRoot\simulator_view.png",
    [string]$StatusFile = "$PSScriptRoot\capture_status.txt",
    [switch]$Down,
    [string]$SendKey = ""
)

Set-StrictMode -Version Latest

# -------------------------------------------------------------------------
# Mark process as DPI-aware to prevent coordinate scaling / clipping
# -------------------------------------------------------------------------
if (-not ([System.Management.Automation.PSTypeName]'Win32.DpiHelper').Type) {
    Add-Type -Name 'DpiHelper' -Namespace 'Win32' -MemberDefinition '[DllImport("user32.dll")] public static extern bool SetProcessDPIAware();'
}
[Win32.DpiHelper]::SetProcessDPIAware() | Out-Null

function Write-Status([string]$msg) {
    Write-Host $msg
    [IO.File]::WriteAllText($StatusFile, $msg, [Text.Encoding]::UTF8)
}

Add-Type -AssemblyName System.Drawing -ErrorAction SilentlyContinue
Add-Type -AssemblyName System.Windows.Forms -ErrorAction SilentlyContinue

try {
    # -------------------------------------------------------------------------
    # Compile C# helper: Window management + CopyFromScreen
    # -------------------------------------------------------------------------
    if (-not ([System.Management.Automation.PSTypeName]'SimCaptureV3').Type) {
        $csharpCode = @'
using System;
using System.Drawing;
using System.Drawing.Imaging;
using System.Runtime.InteropServices;
using System.Text;

public class SimCaptureV3 {
    [DllImport("user32.dll")]
    public static extern bool GetWindowRect(IntPtr hWnd, out RECT lpRect);

    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool BringWindowToTop(IntPtr hWnd);

    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

    [DllImport("user32.dll")]
    public static extern bool SetWindowPos(IntPtr hWnd, IntPtr hWndInsertAfter, int X, int Y, int cx, int cy, uint uFlags);

    [DllImport("user32.dll")]
    public static extern int GetSystemMetrics(int nIndex);

    [DllImport("dwmapi.dll")]
    public static extern int DwmGetWindowAttribute(IntPtr hwnd, int dwAttribute, out RECT pvAttribute, int cbAttribute);

    [StructLayout(LayoutKind.Sequential)]
    public struct RECT { public int Left, Top, Right, Bottom; }

    private static readonly IntPtr HWND_TOPMOST = new IntPtr(-1);
    private static readonly IntPtr HWND_NOTOPMOST = new IntPtr(-2);
    private const uint SWP_NOSIZE = 0x0001;
    private const uint SWP_NOMOVE = 0x0002;
    private const uint SWP_NOZORDER = 0x0004;
    private const uint SWP_SHOWWINDOW = 0x0040;

    [DllImport("user32.dll", SetLastError = true)]
    public static extern IntPtr FindWindow(string lpClassName, string lpWindowName);

    [DllImport("user32.dll")]
    public static extern bool EnumWindows(EnumWindowsProc lpEnumFunc, IntPtr lParam);
    public delegate bool EnumWindowsProc(IntPtr hWnd, IntPtr lParam);

    [DllImport("user32.dll", CharSet = CharSet.Auto, SetLastError = true)]
    public static extern int GetWindowText(IntPtr hWnd, StringBuilder lpString, int nMaxCount);

    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr hWnd);

    [DllImport("user32.dll", CharSet = CharSet.Auto)]
    public static extern bool PostMessage(IntPtr hWnd, uint Msg, IntPtr wParam, IntPtr lParam);

    public static IntPtr FindSimulatorWindow() {
        IntPtr found = IntPtr.Zero;
        EnumWindows((hWnd, lParam) => {
            if (!IsWindowVisible(hWnd)) return true;
            StringBuilder sb = new StringBuilder(256);
            GetWindowText(hWnd, sb, 256);
            string title = sb.ToString();
            if (title.IndexOf("CIQ Simulator", StringComparison.OrdinalIgnoreCase) >= 0) {
                found = hWnd;
                return false;
            }
            return true;
        }, IntPtr.Zero);
        return found;
    }

    public static void CloseModalDialogs() {
        IntPtr hDialog = FindWindow(null, "Save Screenshot");
        if (hDialog != IntPtr.Zero) {
            PostMessage(hDialog, 0x0010 /*WM_CLOSE*/, IntPtr.Zero, IntPtr.Zero);
            System.Threading.Thread.Sleep(300);
        }
    }

    public static void EnsureWindowSize(IntPtr hWnd, int targetWidth, int targetHeight) {
        RECT rc;
        GetWindowRect(hWnd, out rc);
        int currentW = rc.Right - rc.Left;
        int currentH = rc.Bottom - rc.Top;
        int screenW = GetSystemMetrics(0 /*SM_CXSCREEN*/);
        int screenH = GetSystemMetrics(1 /*SM_CYSCREEN*/);
        int maxAllowedH = (screenH > 100) ? (screenH - 55) : targetHeight;
        int maxAllowedW = (screenW > 100) ? (screenW - 40) : targetWidth;
        int effTargetW = Math.Min(targetWidth, maxAllowedW);
        int effTargetH = Math.Min(targetHeight, maxAllowedH);

        int newW = Math.Max(currentW, effTargetW);
        int newH = Math.Max(currentH, effTargetH);
        newW = Math.Min(newW, maxAllowedW);
        newH = Math.Min(newH, maxAllowedH);

        int newLeft = rc.Left;
        if (newLeft + newW > screenW && screenW > 0) {
            newLeft = Math.Max(0, screenW - newW - 20);
        }
        int newTop = rc.Top;
        if (newTop + newH > screenH && screenH > 0) {
            newTop = Math.Max(0, screenH - newH - 40);
        }
        if (newW != currentW || newH != currentH || newLeft != rc.Left || newTop != rc.Top) {
            SetWindowPos(hWnd, IntPtr.Zero, newLeft, newTop, newW, newH, SWP_NOZORDER | SWP_SHOWWINDOW);
            System.Threading.Thread.Sleep(300);
        }
    }

    public static void FocusWindow(IntPtr hWnd) {
        CloseModalDialogs();
        ShowWindow(hWnd, 9);       // SW_RESTORE
        EnsureWindowSize(hWnd, 740, 800);
        SetWindowPos(hWnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
        SetWindowPos(hWnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW);
        BringWindowToTop(hWnd);
        SetForegroundWindow(hWnd);
        System.Threading.Thread.Sleep(300);
    }

    [DllImport("user32.dll")]
    public static extern bool SetCursorPos(int X, int Y);

    [DllImport("user32.dll")]
    public static extern void mouse_event(uint dwFlags, int dx, int dy, uint dwData, UIntPtr dwExtraInfo);

    private const uint MOUSEEVENTF_LEFTDOWN = 0x0002;
    private const uint MOUSEEVENTF_LEFTUP   = 0x0004;

    public static RECT GetBounds(IntPtr hWnd) {
        RECT rc;
        if (DwmGetWindowAttribute(hWnd, 9, out rc, Marshal.SizeOf(typeof(RECT))) != 0) {
            GetWindowRect(hWnd, out rc);
        }
        return rc;
    }

    public static void ClickScreen(int screenX, int screenY) {
        SetCursorPos(screenX, screenY);
        System.Threading.Thread.Sleep(80);
        mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
        System.Threading.Thread.Sleep(100);
        mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
        System.Threading.Thread.Sleep(300);
    }

    public static void SwipeUp(int cx, int cy) {
        SetCursorPos(cx, cy + 80);
        System.Threading.Thread.Sleep(50);
        mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, UIntPtr.Zero);
        System.Threading.Thread.Sleep(50);
        for (int y = cy + 80; y >= cy - 80; y -= 15) {
            SetCursorPos(cx, y);
            System.Threading.Thread.Sleep(20);
        }
        mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, UIntPtr.Zero);
        System.Threading.Thread.Sleep(300);
    }

    public static Bitmap CaptureWindow(IntPtr hWnd) {
        FocusWindow(hWnd);

        RECT rc = GetBounds(hWnd);
        int w = rc.Right  - rc.Left;
        int h = rc.Bottom - rc.Top;
        if (w <= 0 || h <= 0) { w = 760; h = 920; }

        Bitmap bmp = new Bitmap(w, h, PixelFormat.Format32bppArgb);
        using (Graphics g = Graphics.FromImage(bmp)) {
            g.CopyFromScreen(rc.Left, rc.Top, 0, 0,
                new Size(w, h), CopyPixelOperation.SourceCopy);
        }
        return bmp;
    }
}
'@

        $tempCs = [IO.Path]::ChangeExtension([IO.Path]::GetTempFileName(), '.cs')
        [IO.File]::WriteAllText($tempCs, $csharpCode, [Text.Encoding]::UTF8)
        Add-Type -Path $tempCs -ReferencedAssemblies 'System.Drawing' -ErrorAction Stop
        Remove-Item $tempCs -Force
    }

    # -------------------------------------------------------------------------
    # Find the simulator window
    # -------------------------------------------------------------------------
    $hwnd = [SimCaptureV3]::FindSimulatorWindow()
    if ($hwnd -eq [IntPtr]::Zero) {
        $simProc = Get-Process -Name "simulator" -ErrorAction SilentlyContinue |
            Where-Object { $_.MainWindowHandle -ne 0 } |
            Select-Object -First 1
        if ($simProc) {
            $hwnd = [IntPtr]$simProc.MainWindowHandle
        }
    }

    if ($hwnd -eq [IntPtr]::Zero) {
        throw "simulator.exe not found or has no window handle. Is the Connect IQ simulator open?"
    }

    Write-Host "Found simulator window: 0x$($hwnd.ToString('X8'))" -ForegroundColor Green

    # Focus simulator, ensure adequate window width/height, and dismiss modal dialogs
    [SimCaptureV3]::FocusWindow($hwnd)
    Start-Sleep -Milliseconds 400

    $rc = [SimCaptureV3]::GetBounds($hwnd)
    $w = $rc.Right - $rc.Left
    $h = $rc.Bottom - $rc.Top
    $glanceX = $rc.Left + [int]($w * 0.50)
    $glanceY = $rc.Top + [int]($h * 0.39)

    # Handle navigation
    if ($Down) {
        Write-Host "Tapping Glance at ($glanceX, $glanceY) to open app..." -ForegroundColor Cyan
        [SimCaptureV3]::FocusWindow($hwnd)
        [SimCaptureV3]::ClickScreen($glanceX, $glanceY)
        Start-Sleep -Milliseconds 1200

        Write-Host "Sending {DOWN} to switch to Page 3..." -ForegroundColor Cyan
        [SimCaptureV3]::FocusWindow($hwnd)
        [System.Windows.Forms.SendKeys]::SendWait("{DOWN}")
        Start-Sleep -Milliseconds 1000
        [System.Windows.Forms.SendKeys]::SendWait("{DOWN}")
        Start-Sleep -Milliseconds 1000
        [System.Windows.Forms.SendKeys]::SendWait("{DOWN}")
        Start-Sleep -Milliseconds 1500
    } elseif ($SendKey) {
        Write-Host "Sending key: '$SendKey'..." -ForegroundColor Cyan
        [SimCaptureV3]::FocusWindow($hwnd)
        [System.Windows.Forms.SendKeys]::SendWait($SendKey)
        Start-Sleep -Milliseconds 1200
    }

    $bmp = [SimCaptureV3]::CaptureWindow($hwnd)

    # Ensure output directory exists
    $outDir = [IO.Path]::GetDirectoryName($OutputPath)
    if ($outDir -and -not (Test-Path $outDir)) { New-Item $outDir -ItemType Directory | Out-Null }

    $bmp.Save($OutputPath, [System.Drawing.Imaging.ImageFormat]::Png)
    $bmp.Dispose()

    $img = [System.Drawing.Image]::FromFile($OutputPath)
    $msg = "OK: $($img.Width)x$($img.Height) px saved to $OutputPath"
    $img.Dispose()

    Write-Status $msg

} catch {
    Write-Status "ERROR: $_"
    exit 1
}
