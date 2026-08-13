param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("web", "worker", "qq", "tunnel")]
    [string]$Role
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$LogDirectory = Join-Path $ProjectRoot "logs"
New-Item -ItemType Directory -Force -Path $LogDirectory | Out-Null

$commands = @{
    web = Join-Path $ProjectRoot ".venv\Scripts\qq-time-agent-web.exe"
    worker = Join-Path $ProjectRoot ".venv\Scripts\qq-time-agent-worker.exe"
    qq = Join-Path $ProjectRoot ".venv\Scripts\qq-time-agent-qq.exe"
    tunnel = "ssh"
}
$arguments = @{
    web = @()
    worker = @()
    qq = @()
    tunnel = @(
        "-NT", "-R", "127.0.0.1:8000:127.0.0.1:8000",
        "-o", "ExitOnForwardFailure=yes",
        "-o", "ServerAliveInterval=30",
        "-o", "ServerAliveCountMax=3",
        "-o", "StrictHostKeyChecking=yes",
        "Tencent"
    )
}

while ($true) {
    $timestamp = Get-Date -Format "yyyyMMdd"
    $stdout = Join-Path $LogDirectory "$Role-$timestamp.out.log"
    $stderr = Join-Path $LogDirectory "$Role-$timestamp.err.log"
    $process = Start-Process -FilePath $commands[$Role] -ArgumentList $arguments[$Role] `
        -WorkingDirectory $ProjectRoot -NoNewWindow -Wait -PassThru `
        -RedirectStandardOutput $stdout -RedirectStandardError $stderr
    if ($process.ExitCode -eq 0) { break }
    Start-Sleep -Seconds 5
}
