#Requires -Version 7.0
<#
.SYNOPSIS
    Run-SyncAndMirror — Wrapper that runs Sync-CoworkSessions.ps1 then mirrors to NAS.

.DESCRIPTION
    Phase 1: Run the sync script against local staging (D:\anthropic\cowork-sessions).
             This always succeeds regardless of NAS availability.
    Phase 2: If the NAS is reachable, robocopy local staging → NAS mirror.
             If the NAS is unreachable (e.g., Cisco Secure Client active), skip silently.
             Next run will catch up.

    Designed for Windows Scheduled Task execution.
    All paths are resolved from config.json co-located with this script.

.NOTES
    Deploy to: D:\anthropic\nas-replication\
    Requires:  Sync-CoworkSessions.ps1 (or cowork_sync.py) in same directory
#>

[CmdletBinding()]
param(
    [string]$ConfigFile = (Join-Path $PSScriptRoot "config.json"),
    [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# ============================================================================
# Configuration
# ============================================================================
$NasServer     = "10.255.10.193"
$NasMirrorPath = "\\$NasServer\mnt\home-storage\gitsilence-nas\yjjoe-workspace\Anthropic\root\cowork-sessions"
$PingTimeout   = 2  # seconds

# Read output_dir from config to know what to mirror
if (-not (Test-Path $ConfigFile)) {
    Write-Host "[!] Config file not found: $ConfigFile" -ForegroundColor Red
    exit 1
}
$cfg = Get-Content $ConfigFile -Raw | ConvertFrom-Json
$localOutputDir = [Environment]::ExpandEnvironmentVariables($cfg.output_dir)

# ============================================================================
# Phase 1: Local sync (always runs)
# ============================================================================
Write-Host "=== Phase 1: Local sync ===" -ForegroundColor Cyan

# Prefer Python (no pwsh dependency on the script itself)
$pythonScript = Join-Path $PSScriptRoot "cowork_sync.py"
$pwshScript   = Join-Path $PSScriptRoot "Sync-CoworkSessions.ps1"

$syncArgs = @("-c", $ConfigFile)
if ($DryRun) { $syncArgs += "--dry-run" }

if (Test-Path $pythonScript) {
    $pythonExe = (Get-Command python -ErrorAction SilentlyContinue).Source
    if (-not $pythonExe) { $pythonExe = (Get-Command python3 -ErrorAction SilentlyContinue).Source }
    if ($pythonExe) {
        & $pythonExe $pythonScript @syncArgs
        $syncExit = $LASTEXITCODE
    } else {
        Write-Host "[!] Python not found, falling back to PowerShell" -ForegroundColor Yellow
        & pwsh -NoProfile -File $pwshScript -ConfigFile $ConfigFile $(if ($DryRun) { "-DryRun" })
        $syncExit = $LASTEXITCODE
    }
} elseif (Test-Path $pwshScript) {
    & pwsh -NoProfile -File $pwshScript -ConfigFile $ConfigFile $(if ($DryRun) { "-DryRun" })
    $syncExit = $LASTEXITCODE
} else {
    Write-Host "[!] No sync script found in $PSScriptRoot" -ForegroundColor Red
    exit 1
}

if ($syncExit -ne 0) {
    Write-Host "[!] Sync exited with code $syncExit" -ForegroundColor Red
    # Don't exit — still attempt mirror if local output exists
}

# ============================================================================
# Phase 2: Mirror to NAS (best-effort)
# ============================================================================
Write-Host ""
Write-Host "=== Phase 2: NAS mirror ===" -ForegroundColor Cyan

if (-not (Test-Path $localOutputDir)) {
    Write-Host "[=] No local output to mirror ($localOutputDir)" -ForegroundColor DarkGray
    exit $syncExit
}

# Check NAS reachability
$reachable = Test-Connection -TargetName $NasServer -Count 1 -TimeoutSeconds $PingTimeout -Quiet -ErrorAction SilentlyContinue
if (-not $reachable) {
    Write-Host "[~] NAS ($NasServer) unreachable — VPN active? Mirror skipped." -ForegroundColor Yellow
    Write-Host "    Local output at: $localOutputDir" -ForegroundColor Yellow
    Write-Host "    Will mirror on next run when NAS is reachable." -ForegroundColor Yellow
    exit 0
}

# Mirror with robocopy
# /MIR = mirror (delete files at destination that don't exist at source)
# /R:1 /W:2 = 1 retry, 2 second wait (fast fail)
# /NP = no progress percentage (cleaner log)
# /NDL = don't log directory names
# /NFL = don't log file names (use /V to see them)
$robocopyArgs = @(
    $localOutputDir,
    $NasMirrorPath,
    "/MIR",
    "/R:1",
    "/W:2",
    "/NP",
    "/NDL",
    "/XF", "config.json"  # Don't mirror local config to NAS
)

if ($DryRun) {
    Write-Host "[DRY] Would robocopy:" -ForegroundColor Yellow
    Write-Host "    Source:      $localOutputDir" -ForegroundColor Yellow
    Write-Host "    Destination: $NasMirrorPath" -ForegroundColor Yellow
} else {
    Write-Host "[*] Mirroring: $localOutputDir -> $NasMirrorPath"
    & robocopy @robocopyArgs

    # Robocopy exit codes: 0-7 are success/info, 8+ are errors
    if ($LASTEXITCODE -lt 8) {
        Write-Host "[+] NAS mirror complete." -ForegroundColor Green
    } else {
        Write-Host "[!] Robocopy error (exit code $LASTEXITCODE)" -ForegroundColor Red
        Write-Host "    Local output is safe at: $localOutputDir" -ForegroundColor Yellow
    }
}

Write-Host ""
Write-Host "=== Done ===" -ForegroundColor Cyan
