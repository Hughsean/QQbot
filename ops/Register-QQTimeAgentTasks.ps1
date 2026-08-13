param([switch]$Apply)

$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Launcher = Join-Path $PSScriptRoot "Start-QQTimeAgentRole.ps1"
$roles = @("web", "worker", "qq", "tunnel")

foreach ($role in $roles) {
    $taskName = "QQ Time Agent - $role"
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument (
        "-NoProfile -ExecutionPolicy Bypass -File `"$Launcher`" -Role $role"
    ) -WorkingDirectory $ProjectRoot
    $trigger = New-ScheduledTaskTrigger -AtLogOn
    $settings = New-ScheduledTaskSettingsSet -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) `
        -ExecutionTimeLimit (New-TimeSpan -Days 3650) -StartWhenAvailable
    if ($Apply) {
        Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger `
            -Settings $settings -Description "QQ Time Agent $role role" -Force | Out-Null
        Write-Output "Registered: $taskName"
    } else {
        Write-Output "Would register: $taskName"
    }
}

if (-not $Apply) {
    Write-Output "Dry run only. Re-run with -Apply after production deployment approval."
}
