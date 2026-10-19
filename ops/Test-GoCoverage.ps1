param([Parameter(Mandatory = $true)][string]$CoveragePath)

$ErrorActionPreference = 'Stop'
$coverageLines = Get-Content -LiteralPath $CoveragePath
if ($coverageLines.Count -lt 2 -or $coverageLines[0] -notmatch '^mode: (set|count|atomic)$') {
    throw 'Go coverage profile is empty or invalid'
}
$blocks = @{}
foreach ($coverageLine in $coverageLines | Select-Object -Skip 1) {
    if ($coverageLine -notmatch '^(qqtimeagent/\S+)\s+(\d+)\s+(\d+)$') {
        throw 'Coverage must contain only this project; use -coverpkg=qqtimeagent/...'
    }
    $location = $Matches[1]
    $statements = [int]$Matches[2]
    $covered = [long]$Matches[3] -gt 0
    if ($blocks.ContainsKey($location)) {
        if ($blocks[$location].Statements -ne $statements) { throw 'Inconsistent coverage blocks' }
        $blocks[$location].Covered = $blocks[$location].Covered -or $covered
    } else {
        $blocks[$location] = @{ Statements = $statements; Covered = $covered }
    }
}
$groups = @{ total = @{ Statements = 0; Covered = 0 } }
foreach ($location in $blocks.Keys) {
    $block = $blocks[$location]
    $package = ($location -split ':')[0] -replace '/[^/]+$', ''
    $keys = @('total')
    if ($package -match '/internal/modules/[^/]+/(domain|application)$') {
        $keys += $package
        if (-not $groups.ContainsKey($package)) { $groups[$package] = @{ Statements = 0; Covered = 0 } }
    }
    foreach ($key in $keys) {
        $groups[$key].Statements += $block.Statements
        if ($block.Covered) { $groups[$key].Covered += $block.Statements }
    }
}
foreach ($key in $groups.Keys | Sort-Object) {
    $group = $groups[$key]
    if ($group.Statements -le 0) { throw "No measured statements: $key" }
    $percent = 100.0 * $group.Covered / $group.Statements
    $minimum = if ($key -eq 'total') { 80 } else { 90 }
    Write-Host ('{0}: {1:N1}% (required {2}%)' -f $key, $percent, $minimum)
    if ($percent -lt $minimum) { throw "Coverage gate failed: $key" }
}
