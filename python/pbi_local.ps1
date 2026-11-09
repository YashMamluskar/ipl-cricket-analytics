<#
  Helpers to talk to the Analysis Services engine that Power BI Desktop runs locally
  (used only for validation and refresh; no credentials involved - Desktop's local
  engine accepts the signed-in Windows user).

  Usage:
    . python/pbi_local.ps1
    $port = Get-PbiPort
    Invoke-PbiDax -Port $port -Query "EVALUATE ROW(""x"", 1)"
    Invoke-PbiTmsl -Port $port -Command '{"refresh":{"type":"full","objects":[{"database":"..."}]}}'
#>
$script:AdomdDll = 'C:\Program Files\Microsoft Power BI Desktop\bin\Microsoft.PowerBI.AdomdClient.dll'
[void][Reflection.Assembly]::LoadFrom($script:AdomdDll)

function Get-PbiPort {
    $roots = @("$env:USERPROFILE\Microsoft\Power BI Desktop Store App\AnalysisServicesWorkspaces",
               "$env:LOCALAPPDATA\Microsoft\Power BI Desktop\AnalysisServicesWorkspaces")
    $files = foreach ($r in $roots) { if (Test-Path $r) { Get-ChildItem $r -Recurse -Filter msmdsrv.port.txt -ErrorAction SilentlyContinue } }
    $f = $files | Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if (-not $f) { throw "No running Power BI Desktop model found" }
    [int]([IO.File]::ReadAllText($f.FullName, [Text.Encoding]::Unicode).Trim())
}

function Open-Pbi([int]$Port) {
    $c = New-Object Microsoft.AnalysisServices.AdomdClient.AdomdConnection("Data Source=localhost:$Port")
    $c.Open(); return $c
}

function Get-PbiDatabase([int]$Port) {
    $c = Open-Pbi $Port
    $cmd = $c.CreateCommand(); $cmd.CommandText = "SELECT [CATALOG_NAME] FROM `$SYSTEM.DBSCHEMA_CATALOGS"
    $r = $cmd.ExecuteReader(); $null = $r.Read(); $db = $r.GetString(0); $r.Close(); $c.Close(); return $db
}

function Invoke-PbiDax([int]$Port, [string]$Query) {
    $c = Open-Pbi $Port
    $cmd = $c.CreateCommand(); $cmd.CommandText = $Query; $cmd.CommandTimeout = 600
    $r = $cmd.ExecuteReader()
    $rows = New-Object System.Collections.Generic.List[object]
    while ($r.Read()) {
        $o = [ordered]@{}
        for ($i = 0; $i -lt $r.FieldCount; $i++) { $o[$r.GetName($i)] = $(if ($r.IsDBNull($i)) { $null } else { $r.GetValue($i) }) }
        $rows.Add([pscustomobject]$o)
    }
    $r.Close(); $c.Close(); return $rows
}

function Invoke-PbiTmsl([int]$Port, [string]$Command) {
    $c = Open-Pbi $Port
    $cmd = $c.CreateCommand(); $cmd.CommandText = $Command; $cmd.CommandTimeout = 1800
    $null = $cmd.ExecuteNonQuery(); $c.Close()
}

