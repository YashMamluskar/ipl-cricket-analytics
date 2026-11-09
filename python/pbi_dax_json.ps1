<#
  Run one DAX query (read from a file) against the open Power BI Desktop model; print JSON rows.
  Used by python/06e_validate_dashboard.py. Errors are printed as {"__error__": "..."}.
#>
param([Parameter(Mandatory = $true)][string]$QueryFile, [int]$Port = 0)
$ErrorActionPreference = "Stop"
. (Join-Path (Split-Path -Parent $MyInvocation.MyCommand.Path) "pbi_local.ps1")
if ($Port -eq 0) { $Port = Get-PbiPort }
$q = [IO.File]::ReadAllText($QueryFile, [Text.Encoding]::UTF8)
try {
    $rows = Invoke-PbiDax -Port $Port -Query $q
    if ($rows.Count -eq 0) { "[]" } else { ConvertTo-Json -InputObject @($rows) -Depth 3 -Compress }
} catch {
    ConvertTo-Json -InputObject @(@{ "__error__" = $_.Exception.Message }) -Compress
}
