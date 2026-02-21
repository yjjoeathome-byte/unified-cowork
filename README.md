# cowork-session-sync

Automated backup and distillation pipeline for [Claude Cowork](https://www.anthropic.com) sessions.

Cowork sessions accumulate valuable context — reasoning chains, corrections, dead-end analysis, decisions — that exists only on your local machine with no built-in sync or export. This tool watches for new sessions, archives the raw transcripts, and distills each into a clean Markdown file that humans and LLMs can read efficiently.

## ⚠️ Format Stability Warning

**This tool parses an undocumented, internal data format.** Anthropic has not published a specification for Cowork's session storage. Everything here was reverse-engineered from observed behavior as of February 2026.

Things that **will** change without notice:
- The storage directory path (`local-agent-mode-sessions` today)
- The folder naming convention (`local_{uuid}` today)
- The transcript filename (`audit.jsonl` today)
- The JSONL entry schema (field names, entry types, nesting)

**The script is designed to detect and surface these changes rather than silently break.** On every run, it validates the session directory structure and JSONL format against expected patterns. When something doesn't match, it prints specific diagnostics and points you to the config knobs that need adjustment.

If the format changes, here's what to expect:

| Change | Symptom | Fix |
|--------|---------|-----|
| Storage path moved | `Sessions directory not found` + alternative paths listed | Update `sessions_dir` in config.json |
| Transcript file renamed | `No audit.jsonl files found` + alternative filenames listed | Update `format.transcript_filename` |
| Folder prefix changed | `Session directory does not start with expected prefix` | Update `format.session_dir_prefix` |
| New entry types added | `Unknown entry types: newtype(×N)` — non-fatal, entries skipped | No action needed (or update script to handle them) |
| JSONL replaced with JSON | `Failed to parse JSONL line` + hint about single-object JSON | Script needs structural update — check repo issues |
| Init block fields renamed | `Init block missing expected fields` — metadata may be incomplete | Update `format.expected_init_fields` |

The `format` section in `config.json` exposes every assumption the script makes about the storage layout. When Anthropic changes something, you adjust the config rather than editing the script.

## What It Does

```
C:\Users\you\AppData\Roaming\Claude\          Your output directory
  local-agent-mode-sessions\                    (local or SMB/NAS)
    {account-uuid}\                           ┌──────────────────────────┐
      {project-uuid}\                         │  raw/                    │
        local_{session-uuid}\    ──────►      │    2026-02-14_session.jsonl
          audit.jsonl                         │  distilled/              │
                                              │    2026-02-14_session.md │
                                              │  SESSION-INDEX.md        │
                                              └──────────────────────────┘
```

For each session:
1. **Archives** the raw `audit.jsonl` (lossless copy — your safety net)
2. **Distills** into a Markdown transcript: user messages, Claude's text responses, tool summaries, metadata header
3. **Tags** with project keywords (configurable dictionary)
4. **Indexes** all sessions in a single `SESSION-INDEX.md` with date, name, project, model, turns, cost

What gets stripped during distillation: thinking blocks, tool_use JSON payloads, permission request/response pairs, cryptographic signatures, init blocks, raw tool results. Typical compression: **80–90% reduction** in file size while preserving all conversational content.

## Requirements

- **Windows 10/11** or **macOS** (Apple Silicon or Intel)
- **PowerShell 7+** (`pwsh`)
  - Windows: [install here](https://aka.ms/powershell)
  - macOS: `brew install powershell`
- **Claude Desktop** with Cowork sessions

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/YOUR-USERNAME/cowork-session-sync.git
cd cowork-session-sync

# 2. Create your config from the appropriate template
```

### Windows

```powershell
cp config.example.json config.json
# Edit config.json — set output_dir (local path or UNC for NAS)
# Default sessions_dir uses %APPDATA% and works out of the box
```

### macOS

```bash
cp config.example.macos.json config.json
# Edit config.json — replace USERNAME with your macOS username
# Set output_dir to local path or SMB mount point
```

Session storage paths by platform:

| Platform | Path |
|----------|------|
| Windows | `%APPDATA%\Claude\local-agent-mode-sessions\` |
| macOS | `~/Library/Application Support/Claude/local-agent-mode-sessions/` |

> **macOS note**: `%APPDATA%` does not expand on macOS. Use absolute paths or `~` (e.g., `~/Library/Application Support/Claude/local-agent-mode-sessions`).

### Config Reference

```jsonc
{
    // Where Cowork stores sessions (default works for Windows as of Feb 2026)
    "sessions_dir": "%APPDATA%\\Claude\\local-agent-mode-sessions",

    // Where to write archives and distilled transcripts
    // Local path:  "C:\\Users\\you\\Documents\\cowork-sessions"
    // SMB/NAS:     "\\\\10.0.0.5\\share\\cowork-sessions"
    "output_dir": "\\\\YOUR-NAS-IP\\share\\path\\to\\cowork-sessions",

    // State file for tracking processed sessions (default is fine)
    "state_file": "%LOCALAPPDATA%\\cowork-sync-state.json",

    // Tag sessions by keyword (optional, can be empty {})
    "project_tags": {
        "my-project": ["keyword1", "keyword2"],
        "other-project": ["other-keyword"]
    },

    // Format assumptions — adjust if Anthropic changes the storage layout
    "format": {
        "session_dir_prefix": "local_",
        "transcript_filename": "audit.jsonl",
        "min_file_size_bytes": 1024,
        "expected_entry_types": ["system", "user", "assistant", "result", "tool_use_summary"],
        "expected_init_fields": ["session_id", "model", "cwd", "mcp_servers"]
    }
}
```

Environment variables (`%APPDATA%`, `%LOCALAPPDATA%`) are expanded at runtime.

### SMB / NAS Output

**Windows**: use UNC paths (`\\server\share\...`). The script validates network connectivity before writing. Mapped drive letters (Z:, etc.) may not be available in scheduled task contexts — always use UNC paths.

**macOS**: mount the share first, then use the mount point path.
```bash
# GUI: Finder → Go → Connect to Server → smb://10.0.0.5/sharename
# CLI:
mkdir -p /Volumes/sharename
mount_smbfs //user@10.0.0.5/sharename /Volumes/sharename
```
Set `output_dir` in config.json to `/Volumes/sharename/cowork-sessions`.

For auto-mount on login: System Settings → General → Login Items → add the share. For headless/server use, add an entry to `/etc/auto_master`.

## Usage

### Windows

```powershell
# Validate config and session format
pwsh -ExecutionPolicy Bypass -File Sync-CoworkSessions.ps1 -Check

# Preview (no files written)
pwsh -ExecutionPolicy Bypass -File Sync-CoworkSessions.ps1 -DryRun

# Run
pwsh -ExecutionPolicy Bypass -File Sync-CoworkSessions.ps1

# Force re-process all sessions
pwsh -ExecutionPolicy Bypass -File Sync-CoworkSessions.ps1 -Force
```

### macOS

```bash
# Validate config and session format
pwsh -File Sync-CoworkSessions.ps1 -Check

# Preview (no files written)
pwsh -File Sync-CoworkSessions.ps1 -DryRun

# Run
pwsh -File Sync-CoworkSessions.ps1

# Force re-process all sessions
pwsh -File Sync-CoworkSessions.ps1 -Force
```

> macOS does not enforce execution policies — `-ExecutionPolicy Bypass` is not needed.

### Automated Scheduling

#### Windows (Scheduled Task)

From an **elevated** PowerShell 7 prompt:

```powershell
pwsh -ExecutionPolicy Bypass -File Register-CoworkSync.ps1

# Custom interval (default: 5 minutes)
pwsh -ExecutionPolicy Bypass -File Register-CoworkSync.ps1 -IntervalMinutes 10
```

The script will prompt for your Windows password. The task runs as "Run whether user is logged on or not" — completely invisible, no console flash, no window.

> **Windows Hello users**: if you don't know your password (biometric/PIN only), set one first from an elevated prompt: `net user YourUsername *` — this won't affect Windows Hello.

Manage the task:
```powershell
Get-ScheduledTaskInfo -TaskName 'CoworkSessionSync'
Start-ScheduledTask -TaskName 'CoworkSessionSync'          # run now
Unregister-ScheduledTask -TaskName 'CoworkSessionSync'     # remove
```

#### macOS (launchd)

1. Edit `com.cowork-sync.agent.plist`:
   - Update the path to `pwsh` (Apple Silicon: `/opt/homebrew/bin/pwsh`, Intel: `/usr/local/bin/pwsh`)
   - Update the path to `Sync-CoworkSessions.ps1`
   - Update `WorkingDirectory` to the repo directory

2. Install and load:
```bash
cp com.cowork-sync.agent.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.cowork-sync.agent.plist
```

Manage the agent:
```bash
launchctl list | grep cowork-sync                          # verify loaded
launchctl start com.cowork-sync.agent                      # run now
cat /tmp/cowork-sync.log                                   # check output
launchctl unload ~/Library/LaunchAgents/com.cowork-sync.agent.plist  # stop
```

## Output Structure

```
output_dir/
├── SESSION-INDEX.md          ← Catalog of all sessions (auto-generated)
├── raw/                      ← Lossless audit.jsonl copies
│   ├── 2026-02-14_sleepy-charming-ramanujan.jsonl
│   └── ...
└── distilled/                ← Clean Markdown transcripts
    ├── 2026-02-14_sleepy-charming-ramanujan.md
    └── ...
```

### Distilled Transcript Format

Each `.md` file contains:

```markdown
# Session: sleepy-charming-ramanujan

| Field | Value |
|-------|-------|
| Model | `claude-sonnet-4-20250514` |
| Session ID | `34c47d46...` |
| Started | 2026-02-14T09:15:00Z |
| Ended | 2026-02-14T18:42:00Z |
| User turns | 225 |
| Cost (USD) | $107.74 |
| MCP servers | ssh-relay, kubernetes |
| Projects | my-project |
| Format version | 2026-02 |

---
### User

(user message text)

### Claude

(assistant response text)

> **Tool**: (one-line tool summary)

---
### User

(next message)
...
```

### Session Index

`SESSION-INDEX.md` is a Markdown table rebuilt on every run:

```
| Date | Session | Project(s) | Model | Turns | Cost | Files |
|------|---------|------------|-------|-------|------|-------|
| 2026-02-14 | sleepy-charming-ramanujan | my-project | claude-sonnet-4-5 | 225 | $107.74 | distilled / raw |
```

## Project Tagging

Sessions are auto-tagged by scanning the distilled transcript for keywords. A session can match multiple projects or none (`untagged`).

```json
"project_tags": {
    "infra-project": ["proxmox", "kubernetes", "terraform"],
    "ml-research": ["vllm", "LoRA", "fine-tuning"]
}
```

Keywords are matched case-insensitively. Use specific terms to avoid false positives — `"vllm"` is better than `"model"`.

## Use With LLMs

The distilled transcripts are designed to be fed to Claude (or any LLM) for cross-session continuity. Typical workflow:

1. Start a new Cowork session
2. Point Claude at `SESSION-INDEX.md` to find relevant past sessions
3. Have Claude read the specific `distilled/*.md` file for context
4. Resume work with full history

The distilled format is optimized for LLM consumption: minimal noise, structured headers, inline tool summaries. Raw JSONL should only be consulted when distilled content is missing detail (rare).

## Troubleshooting

### "No new or modified sessions"
The script tracks files by SHA256 hash. If nothing changed since the last run, there's nothing to do. Use `-Force` to re-process everything.

### "Sessions directory not found"
Anthropic moved the storage path. The script will list alternative paths it found under `%APPDATA%\Claude\`. Update `sessions_dir` in your config.

### "Cannot reach server" (SMB output)
The NAS/server at the UNC path is unreachable. Check network connectivity and share permissions.

### Scheduled task runs but nothing happens
Check `LastTaskResult`: `0` = success, non-zero = error.
```powershell
Get-ScheduledTaskInfo -TaskName 'CoworkSessionSync' | Select LastRunTime, LastTaskResult
```
Common issue: the task can't resolve the script path. Use UNC paths, not mapped drive letters.

### Unknown entry types warning
Non-fatal. Cowork added new entry types the script doesn't handle yet. The entries are skipped but everything else works. Check the repo for script updates.

## How It Works (Technical)

The script recurses `sessions_dir` looking for files matching `format.transcript_filename` inside directories prefixed with `format.session_dir_prefix`. Each match is an `audit.jsonl` file — one JSON object per line.

Entry types handled:
- `system` (subtype `init`): session metadata extraction (model, session name, MCP servers, timestamps)
- `system` (subtype `permission_request`/`permission_response`): dropped (noise)
- `user`: user messages — text content extracted, tool results dropped (except errors)
- `assistant`: Claude responses — only `type: "text"` blocks kept; thinking, tool_use, and signatures dropped
- `tool_use_summary`: one-line tool descriptions — kept as blockquotes
- `result`: cost and end timestamp extraction

State tracking uses SHA256 hashes stored in a local JSON file. Only changed files are re-processed on each run.

## License

MIT

## Disclaimer

This tool parses an undocumented format. It is not affiliated with, endorsed by, or supported by Anthropic. Use at your own risk. Anthropic may change the session storage format at any time without notice.
