# Local Deployment — VPN-Resilient Cowork Sync

## Problem

The sync scripts and config previously lived on the NAS (`Z:\`). When Cisco Secure Client (VPN) is active, the NAS is unreachable, so the Scheduled Task fails to even launch the script.

## Solution

Two-phase architecture:
1. **Local sync** — scripts + config live on `D:\anthropic\nas-replication\`, output goes to `D:\anthropic\cowork-sessions\`. Always runs.
2. **NAS mirror** — after local sync, robocopy to NAS if reachable. Skipped silently when VPN blocks the NAS. Next run catches up.

## Deployment Steps

From an elevated PowerShell 7 prompt:

```powershell
# 1. Create the local directories
mkdir D:\anthropic\nas-replication -Force
mkdir D:\anthropic\cowork-sessions -Force

# 2. Copy files from repo to local deployment
$repo = "Z:\yjjoe-workspace\Anthropic\root\unified-cowork-repo"
Copy-Item "$repo\cowork_sync.py" "D:\anthropic\nas-replication\"
Copy-Item "$repo\Sync-CoworkSessions.ps1" "D:\anthropic\nas-replication\"
Copy-Item "$repo\deploy\Run-SyncAndMirror.ps1" "D:\anthropic\nas-replication\"
Copy-Item "$repo\deploy\Register-LocalSync.ps1" "D:\anthropic\nas-replication\"
Copy-Item "$repo\deploy\config.local.json" "D:\anthropic\nas-replication\config.json"

# 3. Validate
python D:\anthropic\nas-replication\cowork_sync.py -c D:\anthropic\nas-replication\config.json --check

# 4. Dry run
pwsh -File D:\anthropic\nas-replication\Run-SyncAndMirror.ps1 -DryRun

# 5. Register the Scheduled Task (replaces the old NAS-based task)
pwsh -ExecutionPolicy Bypass -File D:\anthropic\nas-replication\Register-LocalSync.ps1

# 6. Test it
Start-ScheduledTask -TaskName 'CoworkSessionSync'
Get-ScheduledTaskInfo -TaskName 'CoworkSessionSync'
```

## What's in each directory

```
D:\anthropic\nas-replication\       ← Scripts + config (always accessible)
    config.json                     ← Points sessions_dir at MSIX path, output_dir at local staging
    cowork_sync.py                  ← Main sync script
    Sync-CoworkSessions.ps1         ← PowerShell alternative
    Run-SyncAndMirror.ps1           ← Wrapper: runs sync then mirrors to NAS
    Register-LocalSync.ps1          ← Scheduled Task registration

D:\anthropic\cowork-sessions\       ← Local staging (always writable)
    SESSION-INDEX.md
    CATCH-UP.md
    raw/
    distilled/
```

## Updating scripts

When you update the repo, re-copy the changed files:
```powershell
Copy-Item "$repo\cowork_sync.py" "D:\anthropic\nas-replication\" -Force
# etc.
```

The Scheduled Task does not need re-registration unless `Run-SyncAndMirror.ps1` moves.
