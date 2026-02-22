# CLAUDE.md — Project Instructions

This repo is `cowork-session-sync`: an automated backup and distillation pipeline for Claude Cowork sessions.

## What This Repo Does

It watches the local Cowork session storage directory, copies raw `audit.jsonl` files to an output directory (local or SMB/NAS), and distills each into a clean Markdown transcript. It also tags sessions with project keywords and maintains a session index.

## Development Infrastructure — NAS Access

The canonical repo clone lives on the NAS, accessible from multiple paths depending on context:

| Context | Path |
|---------|------|
| Proxmox hosts (node00–node06) | `/mnt/pve/gs-nas/yjjoe-workspace/Anthropic/root/unified-cowork-repo` |
| Windows (SMB mapped drive) | `Z:\yjjoe-workspace\Anthropic\root\unified-cowork-repo` |
| Cowork sessions (ssh-relay) | Use any `node0X` host alias via ssh-relay MCP tool |

**NAS details:**
- NFS server: `10.255.10.193`, export: `/mnt/home-storage/gitsilence-nas`, NFSv4.2
- Mounted on all 7 Proxmox hosts at `/mnt/pve/gs-nas` (defined in `/etc/pve/storage.cfg`)
- Git is installed on all Proxmox hosts (git 2.47.3)
- Git remote: `https://github.com/yjjoeathome-byte/unified-cowork.git` (HTTPS, push requires GitHub auth)

**For Cowork/Claude sessions:** Use ssh-relay to any Proxmox host (node00–node06) for git operations. All hosts have equivalent access. No PAT required for read operations or local branch work — only `git push` needs GitHub credentials (configured on the Windows side).

**Git push host:** node03 is the canonical push host. It has an ed25519 deploy key (`/root/.ssh/github_deploy_unified_cowork`) registered as a repo-scoped deploy key on GitHub with write access. The remote URL is SSH: `git@github.com-unified-cowork:yjjoeathome-byte/unified-cowork.git` (routed via `/root/.ssh/config` Host alias). If node03 is down, any other Proxmox host can push — but a new deploy key must be generated on that host and added to the repo on GitHub first.

**NFS ownership note:** First git operation on a new host requires `git config --global --add safe.directory /mnt/pve/gs-nas/yjjoe-workspace/Anthropic/root/unified-cowork-repo` due to NFS UID mapping.

**Windows access is read-only.** The SMB-mapped `Z:\` view of the repo shows the SSH remote URL but cannot push (no deploy key, NFS permission denied on `.git/config`). This is by design — node03 pushes, Windows reads.

**Working directory hygiene:** Windows Explorer creates `Thumbs.db`, `Zone.Identifier`, and CRLF artifacts on the NFS share. These are not tracked — ignore them in `git status`. If CRLF diffs appear on all files, run `git checkout -- .` to reset.

## Platform Support

| | Windows | macOS | Linux |
|---|---------|-------|-------|
| Session path | `%APPDATA%\Claude\local-agent-mode-sessions\` | `~/Library/Application Support/Claude/local-agent-mode-sessions/` | `~/.config/Claude/local-agent-mode-sessions/` |
| Scheduling | Windows Scheduled Task (`Register-CoworkSync.ps1`) | launchd (`com.cowork-sync.python.plist`) | cron |
| SMB output | UNC paths: `\\server\share\path` | Mount paths: `/Volumes/sharename/path` | Mount paths (e.g., `/mnt/nas/path`) |
| Runtime (primary) | Python 3.8+ | Python 3 (bundled with macOS 12.3+) | Python 3 |
| Runtime (alt) | PowerShell 7+ (`pwsh`) | PowerShell 7+ (`brew install powershell`) | PowerShell 7+ |

## Repo Structure

```
├── CLAUDE.md                       ← You are here (project instructions for Claude)
├── README.md                       ← User-facing documentation
├── SECURITY.md                     ← Security considerations and vulnerability reporting
├── cowork_sync.py                  ← Main sync + distillation script (Python 3, primary)
├── Sync-CoworkSessions.ps1         ← Alternative sync script (PowerShell 7)
├── Register-CoworkSync.ps1         ← Windows Scheduled Task registration (PowerShell)
├── com.cowork-sync.python.plist    ← macOS launchd agent (Python)
├── com.cowork-sync.agent.plist     ← macOS launchd agent (PowerShell, alternative)
├── config.example.json             ← Template config — Windows
├── config.example.macos.json       ← Template config — macOS
├── config.example.linux.json       ← Template config — Linux
├── examples/
│   └── catch-up-protocol.md        ← CLAUDE.md template for session catch-up on new chats
├── .gitignore                      ← Excludes config.json, raw/, distilled/, SESSION-INDEX.md
└── LICENSE                         ← GPL-3.0
```

## Output Files

The pipeline generates the following in the output directory:

| File | Purpose |
|------|---------|
| `SESSION-INDEX.md` | Full session index table (date, name, project, model, turns, cost, links) |
| `CATCH-UP.md` | Lightweight catch-up index grouped by project with topic lines. Designed for consumption by CLAUDE.md catch-up protocol — cheap to load, gives a new session enough context to offer restoration. |
| `raw/*.jsonl` | Verbatim copies of `audit.jsonl` files |
| `distilled/*.md` | Clean Markdown transcripts (text only, no tool_use JSON or thinking blocks) |

## Key Design Decisions (do not re-litigate)

1. **Config-driven**: all paths and format assumptions live in `config.json`, never hardcoded.
2. **Format-aware**: the script validates Cowork's undocumented storage format on every run and surfaces structural changes via diagnostics rather than silently producing garbage.
3. **Config knobs over code edits**: the `format` section in config.json exposes every assumption about the storage layout. Users adjust config, not code.
4. **Project tagging is keyword-based**: no NLP, no external deps. Dictionary in config.json, case-insensitive substring match. Sessions can match multiple projects.
5. **Raw archive is always kept**: distillation is lossy by design (strips thinking blocks, tool_use JSON, signatures). The raw copy is the safety net.
6. **State tracking via SHA256**: only changed files are reprocessed. State file is local to the machine.
7. **Cross-platform via Python 3 stdlib**: one script, three scheduling mechanisms. Python 3.8+ with no pip dependencies. PowerShell 7 version kept as an alternative.
8. **Catch-up index is heuristic, not LLM-generated**: topic extraction uses the first user message (truncated to 120 chars). No API calls, no inference cost. Good enough for a menu; the distilled file provides full context when selected.
9. **CATCH-UP.md is a separate file from SESSION-INDEX.md**: the index is a flat table for reference; the catch-up file is grouped by project for consumption by the CLAUDE.md protocol. Different audiences, different formats.

## When Helping Users

If a user opens this repo in Cowork and asks for help:

### macOS Setup (Python — recommended)
1. Python 3 is bundled with macOS 12.3+ — no install needed.
2. Copy `config.example.macos.json` to `config.json`
3. Set `sessions_dir` to `~/Library/Application Support/Claude/local-agent-mode-sessions`
   - Tilde (`~`) is expanded to the home directory at runtime.
   - `%APPDATA%` style variables do NOT work on macOS.
4. Set `output_dir` to local path or SMB mount point (e.g., `/Volumes/nas-share/cowork-sessions`)
5. Set `state_file` to `~/.local/share/cowork-sync-state.json` or any writable path
6. Test: `python3 cowork_sync.py --check`
7. Run: `python3 cowork_sync.py --dry-run`
8. Schedule: edit `com.cowork-sync.python.plist` (update paths), then:
   ```bash
   cp com.cowork-sync.python.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.cowork-sync.python.plist
   ```

### macOS Setup (PowerShell — alternative)
1. Install PowerShell 7: `brew install powershell`
2. Copy `config.example.macos.json` to `config.json`
3. Same config as above.
4. Test: `pwsh -File Sync-CoworkSessions.ps1 -Check`
5. Run: `pwsh -File Sync-CoworkSessions.ps1 -DryRun`
6. Schedule: use `com.cowork-sync.agent.plist` instead.

### Windows Setup
1. Python 3.8+: https://www.python.org/downloads/ (or use the Microsoft Store)
2. Copy `config.example.json` to `config.json`
3. Set `sessions_dir` to `%APPDATA%\Claude\local-agent-mode-sessions` (default, usually works)
4. Set `output_dir` to local path or UNC: `\\server\share\path\cowork-sessions`
5. Test: `python cowork_sync.py --check`
6. Run: `python cowork_sync.py --dry-run`
7. Schedule: use Windows Task Scheduler to run `python cowork_sync.py` on an interval.
   - PowerShell alternative: `pwsh -ExecutionPolicy Bypass -File Register-CoworkSync.ps1`

### Linux Setup
1. Python 3 is pre-installed on most distributions.
2. Copy `config.example.linux.json` to `config.json`
3. Set `sessions_dir` to `~/.config/Claude/local-agent-mode-sessions`
4. Set `output_dir` to local path or mount point (e.g., `/mnt/nas/cowork-sessions`)
5. Test: `python3 cowork_sync.py --check`
6. Run: `python3 cowork_sync.py --dry-run`
7. Schedule via cron:
   ```bash
   crontab -e
   # Add: run every 5 minutes
   */5 * * * * cd /path/to/cowork-session-sync && python3 cowork_sync.py >> /tmp/cowork-sync.log 2>&1
   ```

### Troubleshooting Format Changes
If Anthropic changes the Cowork session format, the script's `--check` flag (Python) or `-Check` flag (PowerShell) will print specific diagnostics. Guide the user to adjust the `format` section in `config.json`:
- `session_dir_prefix`: folder name prefix (currently `local_`)
- `transcript_filename`: transcript file name (currently `audit.jsonl`)
- `expected_entry_types`: JSONL entry type values
- `expected_init_fields`: fields expected in the init block

Do NOT guess at format changes. Run `--check` (or `-Check` for PowerShell), read the output, and adjust based on what the script actually found.

### SMB on macOS
macOS mounts SMB shares under `/Volumes/`. To mount:
```bash
# GUI: Finder → Go → Connect to Server → smb://10.0.0.5/sharename
# CLI: mount_smbfs //user@10.0.0.5/sharename /Volumes/sharename
```
The `output_dir` in config.json should be the mount point path: `/Volumes/sharename/cowork-sessions`

Auto-mount on login: System Settings → General → Login Items → add the share. Or use `/etc/auto_master` for automount.

## Code Style

### Python (`cowork_sync.py`)
- Python 3.8+ stdlib only — no pip dependencies
- Functions use `snake_case` (PEP 8)
- Colored output via `TermColor` class — auto-detects TTY, VT100 on Windows
- Error handling via early `sys.exit(1)` with diagnostic messages

### PowerShell (`Sync-CoworkSessions.ps1`)
- PowerShell 7+ only (no Windows PowerShell 5.1 compatibility needed)
- Functions use PascalCase with `-` verb prefix (PowerShell convention)
- Error handling via `$ErrorActionPreference = "Stop"` + targeted try/catch

### Both
- All user-facing output uses color coding:
  - Green: success
  - Yellow: dry run / warning
  - Red: error
  - Cyan: informational metrics
  - White: processing status
