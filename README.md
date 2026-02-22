# cowork-session-sync

Automated backup, distillation, and **cross-session context restoration** for [Claude Cowork](https://www.anthropic.com) sessions.

Every Cowork session starts from scratch. This tool fixes that. It watches your local sessions, archives the raw transcripts, distills each into clean Markdown, and generates a **catch-up index** that lets new Cowork chats pick up exactly where you left off — automatically, at near-zero token cost.

## Try it in 10 seconds

Once the pipeline is running, open a **brand-new** Cowork chat and type:

```
catchup-bunny
```

That's it. Claude reads your session index, shows a numbered menu of your past work grouped by project, and asks which one to resume. Pick a number and you're back in context — no copy-paste, no file hunting, no re-explaining.

> **One phrase. Full session continuity across chats.**

See [Session Catch-Up](#session-catch-up-new-chat-bootstrap) for how it works under the hood, or keep reading for setup.

---

## Quick Start: New Chat Catch-Up

**The problem:** you open a new Cowork session and have to manually explain what you were working on yesterday.

**The fix:** the pipeline generates `CATCH-UP.md` — a lightweight index of all your sessions grouped by project, each with a topic line:

```markdown
## my-infra-project

- **2026-02-20** friendly-wizardly-lamport (171 turns, $31.39): "upgrade the storage nodes to NVMe"
- **2026-02-19** festive-quirky-gauss (131 turns, $35.74): "debug the ceph rebalance stall"

## untagged

- **2026-02-16** clever-sweet-noether (1 turns, $0.09): "test session"
```

Add a catch-up protocol to your global `CLAUDE.md` (template in `examples/catch-up-protocol.md`) and every new chat will:

1. Read `CATCH-UP.md` (~few KB, a few hundred tokens)
2. Present your projects and recent sessions as a numbered list
3. Wait for you to pick one or say "fresh topic"
4. Load the first ~50 lines of the selected distilled transcript
5. Resume work with context — no manual re-explaining

**Total bootstrap cost: under 1K tokens.**

See [Session Catch-Up](#session-catch-up-new-chat-bootstrap) below for full setup instructions.

---

## What It Does

```
Session storage directory                 Your output directory
  {account-uuid}/                         (local or SMB/NAS)
    {project-uuid}/                     ┌──────────────────────────┐
      local_{session-uuid}/    ──────►  │  raw/                    │
        audit.jsonl                     │    2026-02-14_session.jsonl
                                        │  distilled/              │
                                        │    2026-02-14_session.md │
                                        │  SESSION-INDEX.md        │
                                        │  CATCH-UP.md             │
                                        └──────────────────────────┘
```

For each session:
1. **Archives** the raw `audit.jsonl` (lossless copy — your safety net)
2. **Distills** into a Markdown transcript: user messages, Claude's text responses, tool summaries, metadata header
3. **Tags** with project keywords (configurable dictionary)
4. **Indexes** all sessions in a single `SESSION-INDEX.md` with date, name, project, model, turns, cost
5. **Generates `CATCH-UP.md`** — a project-grouped topic index for new-chat context restoration

What gets stripped during distillation: thinking blocks, tool_use JSON payloads, permission request/response pairs, cryptographic signatures, init blocks, raw tool results. Typical compression: **~95% reduction** in file size while preserving all conversational content.

## ⚠️ Format Stability Warning

**This tool parses an undocumented, internal data format.** Anthropic has not published a specification for Cowork's session storage. Everything here was reverse-engineered from observed behavior as of February 2026.

Things that **will** change without notice: the storage directory path, the folder naming convention, the transcript filename, the JSONL entry schema.

**The script is designed to detect and surface these changes rather than silently break.** On every run, it validates the session directory structure and JSONL format against expected patterns. When something doesn't match, it prints specific diagnostics and points you to the config knobs that need adjustment.

| Change | Symptom | Fix |
|--------|---------|-----|
| Storage path moved | `Sessions directory not found` + alternative paths listed | Update `sessions_dir` in config.json |
| Transcript file renamed | `No audit.jsonl files found` + alternative filenames listed | Update `format.transcript_filename` |
| Folder prefix changed | `Session directory does not start with expected prefix` | Update `format.session_dir_prefix` |
| New entry types added | `Unknown entry types: newtype(×N)` — non-fatal, entries skipped | No action needed (or update script to handle them) |
| JSONL replaced with JSON | `Failed to parse JSONL line` + hint about single-object JSON | Script needs structural update — check repo issues |
| Init block fields renamed | `Init block missing expected fields` — metadata may be incomplete | Update `format.expected_init_fields` |

The `format` section in `config.json` exposes every assumption the script makes about the storage layout. When Anthropic changes something, you adjust the config rather than editing the script.

### Format Reference

For a complete reverse-engineered specification of the `audit.jsonl` format — all entry types, field inventories, annotated examples from real sessions, compression rationale, and common pitfalls — see:

**[Cowork `audit.jsonl` — Reverse-Engineered Session Format Reference](cowork-audit-jsonl-format-reference.md)**

## Format Documentation Gap

Anthropic ships Cowork with no public documentation of the `audit.jsonl` session format written to `local-agent-mode-sessions/`. This format reference was reverse-engineered from analysis of 744 sessions across 10 days of Opus 4.6 usage.

If official documentation exists, please [open an issue](https://github.com/yjjoeathome-byte/unified-cowork/issues) — otherwise, [`cowork-audit-jsonl-format-reference.md`](./cowork-audit-jsonl-format-reference.md) is the most complete public specification available.

See also: [anthropics/claude-code#27724](https://github.com/anthropics/claude-code/issues/27724) — documentation request filed upstream.

## Requirements

- **Python 3.8+** (primary — stdlib only, no pip dependencies)
  - macOS 12.3+: bundled as `/usr/bin/python3`
  - Linux: pre-installed on most distributions
  - Windows: [python.org](https://www.python.org/downloads/) or Microsoft Store
- **Claude Desktop** with Cowork sessions

**Alternative runtime**: PowerShell 7+ (`pwsh`) — the original `Sync-CoworkSessions.ps1` is still included for users who prefer it.

## Setup

```bash
# 1. Clone the repo
git clone https://github.com/yjjoeathome-byte/unified-cowork.git
cd unified-cowork

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
# Edit config.json — set output_dir to local path or SMB mount point
```

### Linux

```bash
cp config.example.linux.json config.json
# Edit config.json — set output_dir to local path or mount point
```

Session storage paths by platform:

| Platform | Path |
|----------|------|
| Windows | `%APPDATA%\Claude\local-agent-mode-sessions\` |
| macOS | `~/Library/Application Support/Claude/local-agent-mode-sessions/` |
| Linux | `~/.config/Claude/local-agent-mode-sessions/` |

> **macOS note**: `%APPDATA%` does not expand on macOS. Use absolute paths or `~` (e.g., `~/Library/Application Support/Claude/local-agent-mode-sessions`).

### Config Reference

```jsonc
{
    // Where Cowork stores sessions
    "sessions_dir": "~/Library/Application Support/Claude/local-agent-mode-sessions",

    // Where to write archives and distilled transcripts
    // Local path:  "~/Documents/cowork-sessions"
    // SMB/NAS:     "/Volumes/sharename/cowork-sessions" (macOS)
    //              "\\\\10.0.0.5\\share\\cowork-sessions" (Windows UNC)
    "output_dir": "~/Documents/cowork-sessions",

    // State file for tracking processed sessions (default is fine)
    "state_file": "~/.local/share/cowork-sync-state.json",

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
        "expected_entry_types": ["system", "user", "assistant", "result", "tool_use_summary", "rate_limit_event"],
        "expected_init_fields": ["session_id", "model", "cwd", "mcp_servers"]
    }
}
```

Environment variables (`%APPDATA%`, `%LOCALAPPDATA%`) are expanded at runtime on Windows. Tilde (`~`) is expanded on all platforms.

### SMB / NAS Output

**Windows**: use UNC paths (`\\server\share\...`). The script validates network connectivity before writing. Mapped drive letters (Z:, etc.) may not be available in scheduled task contexts — always use UNC paths.

**macOS**: mount the share first, then use the mount point path.
```bash
# GUI: Finder -> Go -> Connect to Server -> smb://10.0.0.5/sharename
# CLI:
mkdir -p /Volumes/sharename
mount_smbfs //user@10.0.0.5/sharename /Volumes/sharename
```
Set `output_dir` in config.json to `/Volumes/sharename/cowork-sessions`.

For auto-mount on login: System Settings -> General -> Login Items -> add the share. For headless/server use, add an entry to `/etc/auto_master`.

**Linux**: mount the share, then use the mount point path.
```bash
sudo mount -t cifs //10.0.0.5/sharename /mnt/nas -o username=user,uid=$(id -u)
```
Set `output_dir` to `/mnt/nas/cowork-sessions`. For persistent mounts, add to `/etc/fstab`.

## Usage

```bash
# Validate config and session format
python3 cowork_sync.py --check

# Preview (no files written)
python3 cowork_sync.py --dry-run

# Run
python3 cowork_sync.py

# Force re-process all sessions
python3 cowork_sync.py --force

# Use a custom config file
python3 cowork_sync.py -c /path/to/config.json
```

> **Windows**: use `python` instead of `python3` if that's how Python is installed.

<details>
<summary>PowerShell alternative</summary>

```powershell
# Windows
pwsh -ExecutionPolicy Bypass -File Sync-CoworkSessions.ps1 -Check
pwsh -ExecutionPolicy Bypass -File Sync-CoworkSessions.ps1 -DryRun
pwsh -ExecutionPolicy Bypass -File Sync-CoworkSessions.ps1
pwsh -ExecutionPolicy Bypass -File Sync-CoworkSessions.ps1 -Force

# macOS (requires: brew install powershell)
pwsh -File Sync-CoworkSessions.ps1 -Check
pwsh -File Sync-CoworkSessions.ps1 -DryRun
pwsh -File Sync-CoworkSessions.ps1
```
</details>

### Automated Scheduling

#### macOS (launchd)

macOS uses **launchd** agents for scheduled tasks (the equivalent of Windows Scheduled Tasks or Linux cron). The plist file tells launchd what to run, how often, and where to log output.

**Prerequisites**: Run the script manually first to verify it works:
```bash
python3 cowork_sync.py --check
python3 cowork_sync.py --dry-run
python3 cowork_sync.py
```

**Setup**:

1. Edit `com.cowork-sync.python.plist` — update paths to match your environment:
   - `ProgramArguments`: path to `cowork_sync.py`
   - `WorkingDirectory`: the repo directory (where `config.json` lives)

2. Install and load the agent:
```bash
# Copy the plist to the LaunchAgents directory
cp com.cowork-sync.python.plist ~/Library/LaunchAgents/

# Load the agent (starts the 5-minute schedule)
launchctl load ~/Library/LaunchAgents/com.cowork-sync.python.plist

# Verify it's loaded
launchctl list | grep cowork-sync
```

**Management**:
```bash
launchctl start com.cowork-sync.python                                # run now (don't wait for interval)
cat /tmp/cowork-sync.log                                              # check output / errors
launchctl unload ~/Library/LaunchAgents/com.cowork-sync.python.plist  # stop the scheduled agent
```

**Change the interval**: edit `StartInterval` in the plist (value is in seconds, default 300 = 5 minutes), then unload and reload:
```bash
launchctl unload ~/Library/LaunchAgents/com.cowork-sync.python.plist
launchctl load ~/Library/LaunchAgents/com.cowork-sync.python.plist
```

**Uninstall**:
```bash
launchctl unload ~/Library/LaunchAgents/com.cowork-sync.python.plist
rm ~/Library/LaunchAgents/com.cowork-sync.python.plist
```

#### Linux (cron)

```bash
crontab -e
# Add this line (runs every 5 minutes):
*/5 * * * * cd /path/to/cowork-session-sync && python3 cowork_sync.py >> /tmp/cowork-sync.log 2>&1
```

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

## Output Structure

```
output_dir/
├── SESSION-INDEX.md          ← Catalog of all sessions (auto-generated)
├── CATCH-UP.md               ← Lightweight index grouped by project with topic lines
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

## Session Catch-Up (New Chat Bootstrap)

Every Cowork session starts with a blank context. This pipeline generates the pieces needed to restore continuity automatically.

### How it works

The sync script generates `CATCH-UP.md` on every run — a lightweight index of all sessions grouped by project, each with a topic line extracted from the first user message. Example:

```markdown
## my-infra-project

- **2026-02-20** friendly-wizardly-lamport (171 turns, $31.39): "upgrade the storage nodes to NVMe"
- **2026-02-19** festive-quirky-gauss (131 turns, $35.74): "debug the ceph rebalance stall"

## untagged

- **2026-02-16** clever-sweet-noether (1 turns, $0.09): "test session"
```

### Bootstrapping a new chat

Add a **catch-up protocol** to your global `CLAUDE.md` so every new Cowork session reads `CATCH-UP.md` and offers to restore context. The file `examples/catch-up-protocol.md` in this repo contains a ready-to-paste template.

**Setup (one-time):**

1. Locate your global `CLAUDE.md`:
   - Windows: `%APPDATA%\Claude\.claude\CLAUDE.md`
   - macOS: `~/Library/Application Support/Claude/.claude/CLAUDE.md`
2. Open `examples/catch-up-protocol.md` from this repo
3. Adapt the read mechanism to match how your Cowork sessions access the output directory (local path, mounted share, or MCP tool like ssh-relay)
4. Paste the adapted block into your `CLAUDE.md`

**What happens next:**

1. You open a new Cowork chat and say anything
2. Claude reads `CATCH-UP.md` (cheap — it's a few KB)
3. Claude presents your projects and recent sessions as a numbered list
4. You pick one (or say "fresh topic")
5. Claude reads the first ~50 lines of the selected distilled transcript for context
6. Work resumes — no manual context dumping

The distilled files (`distilled/*.md`) contain the full conversation text, structured with headers and tool summaries. The raw JSONL (`raw/*.jsonl`) is the lossless safety net if the distilled version is ever missing detail.

### Token cost

Reading `CATCH-UP.md` costs a few hundred tokens. Loading the header of a distilled file adds another few hundred. Total bootstrap overhead is typically under 1K tokens — negligible compared to a session that will run thousands.

## Troubleshooting

### "No new or modified sessions"
The script tracks files by SHA256 hash. If nothing changed since the last run, there's nothing to do. Use `--force` to re-process everything.

### "Sessions directory not found"
Anthropic moved the storage path. The script will list alternative paths it found. Update `sessions_dir` in your config.

### "Cannot reach server" (SMB output)
The NAS/server at the UNC path is unreachable. Check network connectivity and share permissions.

### Scheduled task runs but nothing happens
**macOS**: check `/tmp/cowork-sync.log` for errors.
**Linux**: check the cron log or the redirect target.
**Windows**: check `LastTaskResult`: `0` = success, non-zero = error.
```powershell
Get-ScheduledTaskInfo -TaskName 'CoworkSessionSync' | Select LastRunTime, LastTaskResult
```

### Unknown entry types warning
Non-fatal. Cowork added new entry types the script doesn't handle yet. The entries are skipped but everything else works. Check the repo for script updates.

## State File Compatibility

The Python script (`cowork_sync.py`) and the PowerShell script (`Sync-CoworkSessions.ps1`) share the same state file format. SHA256 hashes are uppercased in both implementations, so you can switch between runtimes without reprocessing all sessions.

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

## Architecture: Python Rewrite Plan

This section documents the design decisions and implementation details of the Python 3 rewrite (`cowork_sync.py`), which replaced PowerShell 7 as the primary runtime.

### Motivation

The original `Sync-CoworkSessions.ps1` requires installing PowerShell 7 (`pwsh`) on macOS and Linux. Python 3 is bundled with macOS 12.3+ and pre-installed on most Linux distributions, making it a zero-install dependency for the majority of users.

### Design Constraints

- **Python 3.8+ stdlib only** — no pip dependencies. The script must run on any system with a Python 3.8+ interpreter.
- **Behavioral parity** — the Python script must produce identical output (distilled Markdown, session index, state file) to the PowerShell version.
- **State file compatibility** — SHA256 hashes are uppercased to match PowerShell's `Get-FileHash` output, so users can switch runtimes without reprocessing.
- **PowerShell preserved** — `Sync-CoworkSessions.ps1` is kept as an alternative for Windows users who prefer it.

### Script Structure (`cowork_sync.py`)

Single-file, ~450 lines, procedural style with a `main()` entry point.

**CLI** (argparse):

| Flag | Description |
|------|-------------|
| `-c` / `--config` | Config file path (default: `config.json` next to script) |
| `--force` | Reprocess all sessions regardless of state |
| `--dry-run` | Preview without writing |
| `--check` | Validate config + format, exit |

**Functions** (same pipeline as PowerShell):

| Function | Purpose |
|----------|---------|
| `TermColor` class | Colored terminal output (`[+]` green, `[DRY]` yellow, etc.). Auto-detects TTY, enables VT100 on Windows 10+. |
| `expand_path()` | Cross-platform: `~` via `os.path.expanduser`, `%VAR%` via `os.path.expandvars` (Windows only) |
| `load_config()` | Parse JSON, expand paths, validate required fields, merge format defaults |
| `validate_output_path()` | UNC path check on Windows (ping), parent directory existence check |
| `validate_session_format()` | Recursive JSONL discovery, sample parsing, type validation, platform-specific alternative path hints |
| `file_sha256()` | `hashlib.sha256` with `.upper()` for PowerShell state file compatibility |
| `get_pending_sessions()` | Find new/changed sessions via SHA256 state comparison |
| `distill_session()` | JSONL to Markdown: extract user/assistant text, drop thinking/tool_use, build metadata header |
| `get_project_tags()` | Case-insensitive keyword substring matching against config dictionary |
| `update_index()` | Rebuild `SESSION-INDEX.md` with existing + new entries, sorted newest first |
| `load_state()` / `save_state()` | JSON read/write for the processing state file |
| `main()` | Orchestration: load, validate, discover, process, index, save state |

### Cross-Platform Path Expansion

| Pattern | Windows | macOS/Linux |
|---------|---------|-------------|
| `~` | `os.path.expanduser` (`C:\Users\username`) | `os.path.expanduser` (`/Users/...` or `/home/...`) |
| `%APPDATA%` | `os.path.expandvars` expands it | Left as-is (correct: produces "not found" error) |
| `$HOME` | `os.path.expandvars` expands it | `os.path.expandvars` expands it |

### JSONL Distillation Logic

Each `audit.jsonl` file contains one JSON object per line. Entry types handled:

| Entry type | Action |
|------------|--------|
| `system` (subtype `init`) | Extract model, start timestamp, session name from `cwd`, connected MCP servers |
| `system` (other subtypes) | Dropped (permission requests, etc.) |
| `user` | Text content extracted. Array content parsed for text parts + tool errors (truncated to 500 chars). Turn count incremented. |
| `assistant` | Only `type: "text"` blocks kept. Thinking blocks, tool_use JSON, signatures dropped. |
| `tool_use_summary` | Kept as blockquote: `> **Tool**: {summary}` |
| `result` | Cost accumulated, end timestamp captured |
| Unknown types | Counted, warned, skipped |

### Behavioral Parity Details

| Behavior | PowerShell | Python |
|----------|-----------|--------|
| Date prefix | `$f.LastWriteTime.ToString("yyyy-MM-dd")` | `datetime.fromtimestamp(st_mtime).strftime("%Y-%m-%d")` |
| Cost rounding | `[Math]::Round($cost, 4)` | `round(cost, 4)` |
| SHA256 case | `Get-FileHash` returns uppercase | `hexdigest().upper()` |
| File copy | `Copy-Item -Force` | `shutil.copy2()` (preserves metadata) |
| Encoding | `-Encoding UTF8` everywhere | `encoding="utf-8"` everywhere |
| Exit codes | `exit 0` / `exit 1` | `sys.exit(0)` / `sys.exit(1)` |
| Index sort | `Sort-Object -Property Date -Descending` | `sorted(..., key=lambda e: e["date"], reverse=True)` |
| Session name regex | `-match '/sessions/(.+)'` | `re.search(r'/sessions/(.+)', cwd)` |

### Files Created/Modified

**New files:**
- `cowork_sync.py` — Main Python script (primary runtime)
- `config.example.linux.json` — Linux config template (`~/.config/Claude/local-agent-mode-sessions`)
- `com.cowork-sync.python.plist` — macOS launchd agent using `/usr/bin/python3`

**Modified files:**
- `.gitignore` — Added `__pycache__/` and `*.pyc`
- `CLAUDE.md` — Added Linux platform, Python setup instructions, updated repo structure
- `README.md` — Restructured for Python-first, added Linux support

**Untouched files:**
- `Sync-CoworkSessions.ps1` — Kept for PowerShell users
- `Register-CoworkSync.ps1` — Windows Scheduled Task registration (PowerShell only)
- `com.cowork-sync.agent.plist` — macOS launchd agent (PowerShell alternative)
- `config.example.json` — Windows config template
- `config.example.macos.json` — macOS config template

### Verification

```bash
# Validate config + format
python3 cowork_sync.py --check

# Preview without writing
python3 cowork_sync.py --dry-run

# Full run
python3 cowork_sync.py

# Cross-runtime state compatibility test:
# 1. Run PowerShell version to populate state
# 2. Run Python version — should detect no new sessions (state hashes match)
```

## License

GPL-3.0 — see [LICENSE](LICENSE) for full text.

## Disclaimer

This tool parses an undocumented format. It is not affiliated with, endorsed by, or supported by Anthropic. Use at your own risk. Anthropic may change the session storage format at any time without notice.
