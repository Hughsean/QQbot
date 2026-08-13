$ErrorActionPreference = "Stop"
$ready = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health/ready" -TimeoutSec 120
$metrics = Invoke-WebRequest -Uri "http://127.0.0.1:8000/metrics" -TimeoutSec 10
if ($ready.status -ne "ready") { throw "QQ Time Agent is not ready" }
if ($metrics.StatusCode -ne 200) { throw "Metrics endpoint is unavailable" }
Write-Output "QQ Time Agent health and metrics are available."
