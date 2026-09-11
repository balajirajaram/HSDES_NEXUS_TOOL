<#
NEXUS Health Monitor Task Scheduler setup.

Register (run from the repository root):
  powershell -ExecutionPolicy Bypass -File .\tools\schedule_health_monitor.ps1
Verify:
  Get-ScheduledTask -TaskName "NEXUS-HealthMonitor"
Unregister:
  powershell -ExecutionPolicy Bypass -File .\tools\schedule_health_monitor.ps1 -Unregister
#>
[CmdletBinding()]
param([switch]$Unregister)

$ErrorActionPreference = "Stop"
$TaskName = "NEXUS-HealthMonitor"
$RepoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$Python = Join-Path $RepoRoot ".venv\Scripts\python.exe"

if ($Unregister) {
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Unregistered $TaskName"
    exit 0
}

if (-not (Test-Path $Python)) {
    throw "Repository interpreter not found: $Python"
}
$action = New-ScheduledTaskAction -Execute $Python `
    -Argument "-m tools.health_monitor" -WorkingDirectory $RepoRoot
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) `
    -RepetitionInterval (New-TimeSpan -Hours 6) `
    -RepetitionDuration (New-TimeSpan -Days 3650)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Description "Runs the NEXUS unattended health monitor every 6 hours." `
    -Force | Out-Null
Write-Host "Registered $TaskName"
Write-Host "Verify: Get-ScheduledTask -TaskName `"$TaskName`""
