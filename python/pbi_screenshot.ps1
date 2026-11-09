<#
  Capture the Power BI Desktop main window (or the whole primary screen) to a PNG.
  Read-only screen capture; no clicks or keystrokes are sent.
  Usage: powershell -File python/pbi_screenshot.ps1 -Out <png> [-FullScreen]
#>
param([Parameter(Mandatory = $true)][string]$Out, [switch]$FullScreen)
Add-Type -AssemblyName System.Drawing, System.Windows.Forms
Add-Type @"
using System; using System.Runtime.InteropServices;
public class W32 {
  [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
  [DllImport("user32.dll")] public static extern bool GetWindowRect(IntPtr h, out RECT r);
  [DllImport("user32.dll")] public static extern bool SetProcessDPIAware();
}
"@
[W32]::SetProcessDPIAware() | Out-Null
$bounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
if (-not $FullScreen) {
    $p = Get-Process PBIDesktop -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
    if ($p) {
        $r = New-Object W32+RECT
        [W32]::GetWindowRect($p.MainWindowHandle, [ref]$r) | Out-Null
        if (($r.R - $r.L) -gt 200) { $bounds = New-Object System.Drawing.Rectangle($r.L, $r.T, ($r.R - $r.L), ($r.B - $r.T)) }
    }
}
$bmp = New-Object System.Drawing.Bitmap($bounds.Width, $bounds.Height)
$g = [System.Drawing.Graphics]::FromImage($bmp)
$g.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $bounds.Size)
$bmp.Save($Out, [System.Drawing.Imaging.ImageFormat]::Png)
$g.Dispose(); $bmp.Dispose()
"saved $Out ($($bounds.Width)x$($bounds.Height))"
