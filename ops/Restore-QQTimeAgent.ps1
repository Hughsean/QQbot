param(
    [Parameter(Mandatory = $true)][string]$BackupFile,
    [Parameter(Mandatory = $true)][string]$Confirmation,
    [string]$DatabaseName = ""
)

$ErrorActionPreference = "Stop"
if ($Confirmation -ne "RESTORE-QQ-TIME-AGENT") {
    throw "Restore requires the exact confirmation RESTORE-QQ-TIME-AGENT"
}
$ProjectRoot = Split-Path -Parent $PSScriptRoot
if (-not $DatabaseName) {
    $DatabaseName = (docker compose --project-directory $ProjectRoot exec -T postgres sh -c `
        'printf %s "$POSTGRES_DB"').Trim()
    if ($LASTEXITCODE -ne 0) { throw "Reading PostgreSQL database name failed" }
}
if ($DatabaseName -notmatch '^[a-z][a-z0-9_]{0,62}$') {
    throw "DatabaseName must be a safe PostgreSQL identifier"
}
$resolved = (Resolve-Path -LiteralPath $BackupFile).Path
docker compose --project-directory $ProjectRoot exec -T postgres sh -c `
    'rm -f /tmp/qq-time-agent-current-tombstones.csv && psql -U "$POSTGRES_USER" -d "$1" -v ON_ERROR_STOP=1 -c "COPY (SELECT tombstone_id, subject_ref, requested_at, purge_by, status, completed_at FROM data_lifecycle_tombstones) TO ''/tmp/qq-time-agent-current-tombstones.csv'' WITH (FORMAT csv)"' sh $DatabaseName
if ($LASTEXITCODE -ne 0) { throw "Exporting current deletion ledger failed" }
docker compose --project-directory $ProjectRoot cp $resolved postgres:/tmp/qq-time-agent-restore.dump
if ($LASTEXITCODE -ne 0) { throw "Copying restore backup failed" }
docker compose --project-directory $ProjectRoot exec -T postgres sh -c `
    'dropdb --force -U "$POSTGRES_USER" "$1" && createdb -U "$POSTGRES_USER" "$1" && pg_restore --no-owner -U "$POSTGRES_USER" -d "$1" /tmp/qq-time-agent-restore.dump' sh $DatabaseName
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL database replacement failed" }
$previousDatabaseName = [Environment]::GetEnvironmentVariable("DATABASE_NAME", "Process")
$env:DATABASE_NAME = $DatabaseName
try {
    & (Join-Path $ProjectRoot ".venv\Scripts\alembic.exe") upgrade head
    if ($LASTEXITCODE -ne 0) { throw "Database migration after restore failed" }
    docker compose --project-directory $ProjectRoot exec -T postgres sh -c `
        'psql -U "$POSTGRES_USER" -d "$1" -v ON_ERROR_STOP=1 -c "CREATE TEMP TABLE restored_tombstones (LIKE data_lifecycle_tombstones INCLUDING DEFAULTS); COPY restored_tombstones (tombstone_id, subject_ref, requested_at, purge_by, status, completed_at) FROM ''/tmp/qq-time-agent-current-tombstones.csv'' WITH (FORMAT csv); INSERT INTO data_lifecycle_tombstones SELECT * FROM restored_tombstones ON CONFLICT (subject_ref) DO NOTHING;"' sh $DatabaseName
    if ($LASTEXITCODE -ne 0) { throw "Merging current deletion ledger failed" }
    & (Join-Path $ProjectRoot ".venv\Scripts\qq-time-agent-replay-tombstones.exe")
    if ($LASTEXITCODE -ne 0) { throw "Tombstone replay after restore failed" }
} finally {
    if ($null -eq $previousDatabaseName) {
        Remove-Item Env:DATABASE_NAME -ErrorAction SilentlyContinue
    } else {
        $env:DATABASE_NAME = $previousDatabaseName
    }
}
Write-Output "Restore, tombstone replay, and migration completed. Start services only after readiness passes."
