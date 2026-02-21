<#
.SYNOPSIS
    Register-CoworkSync — Sets up a Windows Scheduled Task for Sync-CoworkSessions.ps1.

.DESCRIPTION
    Run once from an elevated PowerShell 7 prompt.
    Reads config.json to resolve the script path (same directory as this file).
#>

param(
    [int]$IntervalMinutes = 5
)

$ScriptPath = Join-Path $PSScriptRoot "Sync-CoworkSessions.ps1"
if (-not (Test-Path $ScriptPath)) {
    Write-Error "Sync-CoworkSessions.ps1 not found at: $ScriptPath"
    exit 1
}

$TaskName = "CoworkSessionSync"
$PwshPath = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $PwshPath) {
    Write-Error "pwsh (PowerShell 7) not found in PATH. Install it first: https://aka.ms/powershell"
    exit 1
}

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action   = New-ScheduledTaskAction -Execute $PwshPath -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$ScriptPath`""
$Trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 2)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Auto-sync Cowork sessions with distillation (every $IntervalMinutes min)" -RunLevel Limited

Write-Host "[+] Scheduled task '$TaskName' registered — runs every $IntervalMinutes minutes." -ForegroundColor Green
Write-Host "    Test now:    Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "    Check:       Get-ScheduledTaskInfo -TaskName '$TaskName'"
Write-Host "    Remove:      Unregister-ScheduledTask -TaskName '$TaskName'"
