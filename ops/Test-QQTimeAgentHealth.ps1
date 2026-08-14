param(
    [ValidateRange(1, 65535)][int]$Port = 8000,
    [ValidateRange(1, 600)][int]$TimeoutSeconds = 120
)

$ErrorActionPreference = "Stop"
$BaseUrl = "http://127.0.0.1:$Port"
$deadline = (Get-Date).AddSeconds($TimeoutSeconds)
$ready = $null
do {
    try {
        $ready = Invoke-RestMethod -Uri "$BaseUrl/health/ready" -TimeoutSec 10
    } catch {
        $ready = $null
    }
    if ($null -ne $ready -and $ready.status -eq "ready") { break }
    if ((Get-Date) -ge $deadline) { throw "QQ Time Agent did not become ready within $TimeoutSeconds seconds" }
    Start-Sleep -Seconds 2
} while ($true)
$metrics = Invoke-WebRequest -Uri "$BaseUrl/metrics" -TimeoutSec 10
if ($metrics.StatusCode -ne 200) { throw "Metrics endpoint is unavailable" }
Write-Output "QQ Time Agent health and metrics are available on loopback port $Port."
