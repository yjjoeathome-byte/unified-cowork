<#
.SYNOPSIS
    Register-CoworkSync — Sets up a Windows Scheduled Task for Sync-CoworkSessions.ps1.

.DESCRIPTION
    Run once from an elevated PowerShell 7 prompt.
    Registers the task as "Run whether user is logged on or not" — runs in a
    background session with zero desktop interaction, no console flash ever.
    Will prompt for your Windows password once during registration.
#>

param(
    [int]$IntervalMinutes = 5
)

$ScriptPath = Join-Path $PSScriptRoot "Sync-CoworkSessions.ps1"
$TaskName = "CoworkSessionSync"

$PwshPath = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
if (-not $PwshPath) {
    Write-Error "pwsh (PowerShell 7) not found in PATH. Install it first: https://aka.ms/powershell"
    exit 1
}

if (-not (Test-Path $ScriptPath)) {
    Write-Error "Sync-CoworkSessions.ps1 not found at: $ScriptPath"
    exit 1
}

# Get current user and prompt for password
$Username = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
Write-Host "Registering task as: $Username" -ForegroundColor Cyan
Write-Host "The task will run in the background — no window, no flash." -ForegroundColor Cyan
Write-Host ""
Write-Host "NOTE: If you use Windows Hello (biometric/PIN) and don't know your" -ForegroundColor Yellow
Write-Host "      password, set one first:  net user $($Username.Split('\')[1]) *" -ForegroundColor Yellow
Write-Host ""
$Password = Read-Host -Prompt "Enter your Windows password" -AsSecureString
$BSTR = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($Password)
$PlainPassword = [System.Runtime.InteropServices.Marshal]::PtrToStringAuto($BSTR)
[System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($BSTR)

# Remove existing task if present
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action   = New-ScheduledTaskAction -Execute $PwshPath -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$ScriptPath`""
$Trigger  = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes $IntervalMinutes)
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 2)

# "Run whether user is logged on or not" — fully non-interactive, no desktop session
Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings `
    -Description "Auto-sync Cowork sessions with distillation (every $IntervalMinutes min)" `
    -RunLevel Limited -User $Username -Password $PlainPassword

# Clear password from memory
$PlainPassword = $null

Write-Host ""
Write-Host "[+] Scheduled task '$TaskName' registered — runs every $IntervalMinutes minutes, fully hidden." -ForegroundColor Green
Write-Host "    Test now:    Start-ScheduledTask -TaskName '$TaskName'"
Write-Host "    Check:       Get-ScheduledTaskInfo -TaskName '$TaskName'"
Write-Host "    Remove:      Unregister-ScheduledTask -TaskName '$TaskName'"
