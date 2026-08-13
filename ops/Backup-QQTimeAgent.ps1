param(
    [Parameter(Mandatory = $true)][string]$Destination,
    [string]$DatabaseName = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $DatabaseName) {
    $DatabaseName = (docker compose --project-directory $ProjectRoot exec -T postgres sh -c `
        'printf %s "$POSTGRES_DB"').Trim()
    if ($LASTEXITCODE -ne 0) { throw "Reading PostgreSQL database name failed" }
}
if ($DatabaseName -notmatch '^[a-z][a-z0-9_]{0,62}$') {
    throw "DatabaseName must be a safe PostgreSQL identifier"
}
$resolved = [System.IO.Path]::GetFullPath($Destination)
New-Item -ItemType Directory -Force -Path $resolved | Out-Null
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backup = Join-Path $resolved "qq-time-agent-$timestamp.dump"
docker compose --project-directory $ProjectRoot exec -T postgres sh -c `
    'pg_dump -U "$POSTGRES_USER" -d "$1" -Fc -f /tmp/qq-time-agent.dump' sh $DatabaseName
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL backup failed" }
docker compose --project-directory $ProjectRoot cp postgres:/tmp/qq-time-agent.dump $backup
if ($LASTEXITCODE -ne 0) { throw "Copying PostgreSQL backup failed" }
Get-FileHash -Algorithm SHA256 -LiteralPath $backup | Format-List | Out-File "$backup.sha256"
Write-Output $backup
