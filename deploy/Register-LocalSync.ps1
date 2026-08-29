#Requires -Version 7.0
<#
.SYNOPSIS
    Register-LocalSync — Sets up a Windows Scheduled Task for the local deployment.

.DESCRIPTION
    Registers a Scheduled Task that runs Run-SyncAndMirror.ps1 from a local path
    (not a network drive). This ensures the task runs even when VPN blocks NAS access.

    Run once from an elevated PowerShell 7 prompt AFTER deploying files to the local path.

.EXAMPLE
    # Deploy first:
    #   robocopy Z:\...\unified-cowork-repo\deploy D:\anthropic\nas-replication /E
    #   copy Z:\...\unified-cowork-repo\cowork_sync.py D:\anthropic\nas-replication\
    #   copy Z:\...\unified-cowork-repo\Sync-CoworkSessions.ps1 D:\anthropic\nas-replication\
    #   rename D:\anthropic\nas-replication\config.local.json config.json
    # Then register:
    #   pwsh -ExecutionPolicy Bypass -File D:\anthropic\nas-replication\Register-LocalSync.ps1
#>

param(
    [int]$IntervalMinutes = 5,
    [string]$DeployDir = "D:\anthropic\nas-replication"
)

$ScriptPath = Join-Path $DeployDir "Run-SyncAndMirror.ps1"
if (-not (Test-Path $ScriptPath)) {
    Write-Error "Run-SyncAndMirror.ps1 not found at: $ScriptPath"
    Write-Host "Deploy the files first. See comments in this script for instructions." -ForegroundColor Yellow
    exit 1
}

$TaskName = "CoworkSessionSync"
$PwshPath = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $PwshPath) {
    Write-Error "pwsh (PowerShell 7) not found in PATH."
    exit 1
}

# Remove existing task if present
$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[~] Removing existing task '$TaskName'..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

$Action   = New-ScheduledTaskAction -Execute $PwshPath -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$ScriptPath`"" -WorkingDirectory $DeployDir
$Trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 2)

Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "Cowork session sync (local + NAS mirror, every $IntervalMinutes min)" -RunLevel Limited

Write-Host ""
Write-Host "[+] Scheduled task '$TaskName' registered." -ForegroundColor Green
Write-Host "    Script:     $ScriptPath" -ForegroundColor Cyan
Write-Host "    Interval:   every $IntervalMinutes minutes" -ForegroundColor Cyan
Write-Host "    Working dir: $DeployDir" -ForegroundColor Cyan
Write-Host ""
Write-Host "    Test now:    Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "    Check:       Get-ScheduledTaskInfo -TaskName '$TaskName'"
Write-Host "    Remove:      Unregister-ScheduledTask -TaskName '$TaskName'"
