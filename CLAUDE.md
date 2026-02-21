# CLAUDE.md — Project Instructions

This repo is `cowork-session-sync`: an automated backup and distillation pipeline for Claude Cowork sessions.

## What This Repo Does

It watches the local Cowork session storage directory, copies raw `audit.jsonl` files to an output directory (local or SMB/NAS), and distills each into a clean Markdown transcript. It also tags sessions with project keywords and maintains a session index.

## Platform Support

| | Windows | macOS |
|---|---------|-------|
| Session path | `%APPDATA%\Claude\local-agent-mode-sessions\` | `~/Library/Application Support/Claude/local-agent-mode-sessions/` |
| Scheduling | Windows Scheduled Task (`Register-CoworkSync.ps1`) | launchd (`com.cowork-sync.agent.plist`) |
| SMB output | UNC paths: `\\server\share\path` | Mount paths: `/Volumes/sharename/path` |
| Runtime | PowerShell 7+ (`pwsh`) | PowerShell 7+ (`brew install powershell`) |

## Repo Structure

```
├── CLAUDE.md                       ← You are here (project instructions for Claude)
├── README.md                       ← User-facing documentation
├── Sync-CoworkSessions.ps1         ← Main sync + distillation script (cross-platform)
├── Register-CoworkSync.ps1         ← Windows Scheduled Task registration
├── com.cowork-sync.agent.plist     ← macOS launchd agent (scheduling)
├── config.example.json             ← Template config (user copies to config.json)
├── .gitignore                      ← Excludes config.json, raw/, distilled/, SESSION-INDEX.md
└── LICENSE                         ← MIT
```

## Key Design Decisions (do not re-litigate)

1. **Config-driven**: all paths and format assumptions live in `config.json`, never hardcoded.
2. **Format-aware**: the script validates Cowork's undocumented storage format on every run and surfaces structural changes via diagnostics rather than silently producing garbage.
3. **Config knobs over code edits**: the `format` section in config.json exposes every assumption about the storage layout. Users adjust config, not code.
4. **Project tagging is keyword-based**: no NLP, no external deps. Dictionary in config.json, case-insensitive substring match. Sessions can match multiple projects.
5. **Raw archive is always kept**: distillation is lossy by design (strips thinking blocks, tool_use JSON, signatures). The raw copy is the safety net.
6. **State tracking via SHA256**: only changed files are reprocessed. State file is local to the machine.
7. **Cross-platform via PowerShell 7**: one script, two scheduling mechanisms. No bash port needed — pwsh runs natively on macOS.

## When Helping Users

If a user opens this repo in Cowork and asks for help:

### macOS Setup
1. Install PowerShell 7: `brew install powershell`
2. Copy `config.example.json` to `config.json`
3. Set `sessions_dir` to `~/Library/Application Support/Claude/local-agent-mode-sessions`
   - Tilde (`~`) is expanded to the home directory at runtime.
   - `%APPDATA%` style variables do NOT work on macOS.
4. Set `output_dir` to local path or SMB mount point (e.g., `/Volumes/nas-share/cowork-sessions`)
5. Set `state_file` to `~/.local/share/cowork-sync-state.json` or any writable path
6. Test: `pwsh -File Sync-CoworkSessions.ps1 -Check`
7. Run: `pwsh -File Sync-CoworkSessions.ps1 -DryRun`
8. Schedule: edit `com.cowork-sync.agent.plist` (update paths), then:
   ```bash
   cp com.cowork-sync.agent.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.cowork-sync.agent.plist
   ```

### Windows Setup
1. Install PowerShell 7: https://aka.ms/powershell
2. Copy `config.example.json` to `config.json`
3. Set `sessions_dir` to `%APPDATA%\Claude\local-agent-mode-sessions` (default, usually works)
4. Set `output_dir` to local path or UNC: `\\server\share\path\cowork-sessions`
5. Test: `pwsh -ExecutionPolicy Bypass -File Sync-CoworkSessions.ps1 -Check`
6. Run: `pwsh -ExecutionPolicy Bypass -File Sync-CoworkSessions.ps1 -DryRun`
7. Schedule (elevated prompt): `pwsh -ExecutionPolicy Bypass -File Register-CoworkSync.ps1`

### Troubleshooting Format Changes
If Anthropic changes the Cowork session format, the script's `--Check` flag will print specific diagnostics. Guide the user to adjust the `format` section in `config.json`:
- `session_dir_prefix`: folder name prefix (currently `local_`)
- `transcript_filename`: transcript file name (currently `audit.jsonl`)
- `expected_entry_types`: JSONL entry type values
- `expected_init_fields`: fields expected in the init block

Do NOT guess at format changes. Run `-Check`, read the output, and adjust based on what the script actually found.

### SMB on macOS
macOS mounts SMB shares under `/Volumes/`. To mount:
```bash
# GUI: Finder → Go → Connect to Server → smb://10.0.0.5/sharename
# CLI: mount_smbfs //user@10.0.0.5/sharename /Volumes/sharename
```
The `output_dir` in config.json should be the mount point path: `/Volumes/sharename/cowork-sessions`

Auto-mount on login: System Settings → General → Login Items → add the share. Or use `/etc/auto_master` for automount.

## Code Style

- PowerShell 7+ only (no Windows PowerShell 5.1 compatibility needed)
- Functions use PascalCase with `-` verb prefix (PowerShell convention)
- Error handling via `$ErrorActionPreference = "Stop"` + targeted try/catch
- All user-facing output goes through `Write-Host` with color coding:
  - Green: success
  - Yellow: dry run / warning
  - Red: error
  - DarkCyan: informational metrics
  - White: processing status
