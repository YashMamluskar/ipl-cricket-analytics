<#
  Select a report page tab in the running Power BI Desktop window via Windows UI Automation
  (used only to capture page screenshots). Usage: powershell -File python/pbi_select_page.ps1 -Page "Player performance"
#>
param([Parameter(Mandatory = $true)][string]$Page)
Add-Type -AssemblyName UIAutomationClient, UIAutomationTypes
$p = Get-Process PBIDesktop -ErrorAction SilentlyContinue | Where-Object { $_.MainWindowHandle -ne 0 } | Select-Object -First 1
if (-not $p) { throw "Power BI Desktop is not running" }
$root = [System.Windows.Automation.AutomationElement]::FromHandle($p.MainWindowHandle)
$cond = New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty, $Page)
$els = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $cond)
foreach ($e in $els) {
    foreach ($pat in @([System.Windows.Automation.SelectionItemPattern]::Pattern, [System.Windows.Automation.InvokePattern]::Pattern)) {
        $obj = $null
        if ($e.TryGetCurrentPattern($pat, [ref]$obj)) {
            if ($pat -eq [System.Windows.Automation.SelectionItemPattern]::Pattern) { $obj.Select() } else { $obj.Invoke() }
            "selected '$Page' via $($pat.ProgrammaticName)"; exit 0
        }
    }
}
"no selectable element named '$Page' (found $($els.Count))"; exit 1
