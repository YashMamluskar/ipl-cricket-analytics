<#
  Phase 6d - Open the generated PBIP in Power BI Desktop, refresh the model through the local
  engine, and capture a screenshot of every report page.

  powershell -File python/06d_open_refresh_capture.ps1 [-OutDir dashboard/screenshots] [-NoCapture]

  Closes any running Power BI Desktop first (save your work in other reports before running).
#>
param([string]$OutDir = "dashboard\screenshots", [switch]$NoCapture,
      [string[]]$Pages = @("IPL overview", "Player performance", "Match and team insights"))
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pbip = (Resolve-Path (Join-Path $here "..\dashboard\IPL_Cricket_Analytics\IPL_Cricket_Analytics.pbip")).Path
. (Join-Path $here "pbi_local.ps1")

Get-Process PBIDesktop -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 3
$exe = "$env:LOCALAPPDATA\Microsoft\WindowsApps\PBIDesktopStore.exe"
if (-not (Test-Path $exe)) { $exe = "C:\Program Files\Microsoft Power BI Desktop\bin\PBIDesktop.exe" }
$t0 = Get-Date
Start-Process -FilePath $exe -ArgumentList "`"$pbip`""
$deadline = (Get-Date).AddSeconds(240)
do { Start-Sleep -Seconds 5; $p = Get-Process PBIDesktop -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowTitle -like "IPL_Cricket_Analytics*" } }
until ($p -or (Get-Date) -gt $deadline)
if (-not $p) { throw "Power BI Desktop did not open the project within 4 minutes" }
Start-Sleep -Seconds 15
$port = $null
for ($i = 0; $i -lt 24 -and -not $port; $i++) {
    try { $cand = Get-PbiPort; $f = Get-ChildItem "$env:USERPROFILE\Microsoft\Power BI Desktop Store App\AnalysisServicesWorkspaces", "$env:LOCALAPPDATA\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces" -Recurse -Filter msmdsrv.port.txt -ErrorAction SilentlyContinue | Sort-Object LastWriteTime -Descending | Select-Object -First 1; if ($f.LastWriteTime -gt $t0) { $port = $cand } } catch {}
    if (-not $port) { Start-Sleep -Seconds 5 }
}
if (-not $port) { throw "Local engine for this session not found" }
$db = Get-PbiDatabase $port
$r0 = Get-Date
Invoke-PbiTmsl -Port $port -Command ('{"refresh":{"type":"full","objects":[{"database":"' + $db + '"}]}}')
"refreshed in $([int]((Get-Date) - $r0).TotalSeconds)s (engine port $port)"
if ($NoCapture) { return }
$out = Join-Path $here "..\$OutDir"; New-Item -ItemType Directory -Force $out | Out-Null
Start-Sleep -Seconds 10
$i = 1
foreach ($pg in $Pages) {
    & powershell -NoProfile -File (Join-Path $here "pbi_select_page.ps1") -Page $pg | Out-Null
    Start-Sleep -Seconds 12
    $file = Join-Path (Resolve-Path $out) ("{0:D2}_{1}.png" -f $i, ($pg -replace '[^A-Za-z0-9]+', '_'))
    & powershell -NoProfile -File (Join-Path $here "pbi_screenshot.ps1") -Out $file
    $i++
}

