# unified-cowork

**One pipeline for every Claude coding surface.** Back up, distill, index, and *resume* your sessions from **Claude Code CLI** and **Claude Desktop "</> Code"** (formerly Cowork) — automatically, at near-zero token cost, and **self-healing** when Anthropic moves the session store.

> **On the name.** This started life as `cowork-session-sync`. Two things changed since: Anthropic rebranded Cowork to **"</> Code"** inside Claude Desktop, and the *same* session machinery now also backs the standalone **Claude Code CLI**. The repo keeps the `unified-cowork` name; the scope is all of them. They're converging anyway — Desktop "</> Code" is Claude Code running inside the desktop app, writing the same kind of transcripts.

---

## Why

Every new Claude session starts from a blank slate. You re-explain yesterday's work, re-paste context, re-hunt for that one decision you made three sessions ago. This tool watches your local session stores, archives the raw transcripts (your safety net), distills each into clean Markdown, and builds a **catch-up index** so a brand-new chat can pick up exactly where you left off.

### Try it in 10 seconds

Once the pipeline is running, open a **brand-new** chat and type:

```
catchup-bunny
```

Claude reads your session index, shows a numbered menu of past work grouped by project, and asks which to resume. Pick a number — you're back in context. No copy-paste, no file hunting, no re-explaining.

> **One phrase. Full session continuity across chats.** Total bootstrap cost: **under 1K tokens.**

---

## The two surfaces

|  | Claude Desktop **"</> Code"** (was Cowork) | **Claude Code CLI** |
|---|---|---|
| Transcript | `…/local-agent-mode-sessions/<uuid>/<uuid>/<prefix>_<uuid>/audit.jsonl` | `~/.claude/projects/<cwd-slug>/<session-uuid>.jsonl` |
| One file per | session (`audit.jsonl`) | session (`<uuid>.jsonl`) |
| Schema | `audit.jsonl` (`init` / `result` / `tool_use_summary` / …) | CLI transcript (`sessionId` / `parentUuid` / `gitBranch` / …) |
| Pipeline status | **Full** — back up, distill, index, catch-up | **Auto-located**; distillation on the [roadmap](#roadmap) |

The complete storage-location map for **every OS**, the nested-directory reality, and the reverse-engineered CLI schema live in **[SESSION-STORES.md](SESSION-STORES.md)**.

---

## Self-healing location — no more broken configs

Anthropic relocates the session store with some regularity: a Microsoft Store (MSIX) repackage, a new sandbox path, a renamed session-folder prefix. Historically each move silently broke the sync until you hand-edited `sessions_dir`.

Set `sessions_dir` to **`"auto"`** and the resolver finds the store wherever it went, keyed on the **one durable invariant**: *a directory named `local-agent-mode-sessions` with transcript files somewhere beneath it.* It is **cost-tiered and cached** — steady-state cost is a single directory probe; expensive discovery runs only after an actual move, and even then only inside Claude/Anthropic-named app-data folders, never a blind disk walk.

| Tier | Strategy | Typical cost |
|---|---|---|
| Cache | last-known-good path (re-validated) | ~10 ms |
| Glob-probe | `…\Packages\Claude_*\…\local-agent-mode-sessions` (publisher-hash-agnostic) | ~30 ms |
| Appx (Windows / PowerShell) | `Get-AppxPackage *Claude*` → bounded search under the package | ~360 ms |
| Anchored discovery | search **only** Claude/Anthropic-named app-data folders | ~1 s (rare) |

What it shrugs off — all **verified on a real machine, June 2026**:

- **MSIX version bumps** — the full package name carries the version (`Claude_1.15962.1.0_x64__…`); the resolver keys on the version-independent **family name** `Claude_pzs8sxrjxfjjc`.
- **Publisher-hash / family rename** — absorbed by the `Claude_*` glob and `Get-AppxPackage`.
- **Intermediate path** changes under `LocalCache\Roaming\Claude\`.
- **Session-folder prefix churn** — `local_`, `ditto_`, `local_ditto_`, and bare UUIDs were *all present in one store*. The pipeline never keys on the prefix.
- **Variable nesting depth** — `audit.jsonl` was found at depth 3 *and* 4 in the same store. Never keyed on a fixed depth.

Both engines ship the resolver: **PowerShell** (`Resolve-CoworkSessionsDir.ps1`) and **Python** (`resolve_sessions_dir()` in `cowork_sync.py`). Your configured literal path stays the fast happy-path; the resolver is a fail-safe that only activates when that path is empty, `"auto"`, or gone — so the happy path has **zero behavior change**.

---

## Requirements

- **Python 3.8+** (primary runtime — stdlib only, no pip dependencies)
  - macOS 12.3+: bundled as `/usr/bin/python3`
  - Linux: pre-installed on most distributions
  - Windows: [python.org](https://www.python.org/downloads/) or Microsoft Store
- **Claude Desktop** (with "</> Code") and/or **Claude Code CLI**

**Alternative runtime:** PowerShell 7+ (`pwsh`) — `Sync-CoworkSessions.ps1` is a full-parity port for users who prefer it (and is what the bundled Windows Scheduled Task runs).

---

## Setup

```bash
# 1. Clone
git clone https://github.com/yjjoeathome-byte/unified-cowork.git
cd unified-cowork

# 2. Create your config from the template for your OS
cp config.example.json config.json          # Windows
# cp config.example.macos.json config.json   # macOS
# cp config.example.linux.json config.json   # Linux
```

Then edit `config.json`:

- **`sessions_dir`** — leave it as **`"auto"`** (recommended) to let the resolver locate the store, or pin an explicit path (see [SESSION-STORES.md](SESSION-STORES.md)).
- **`output_dir`** — where archives + distilled transcripts go (a local path, or a UNC/SMB path for a NAS).

That's the whole setup. Environment variables (`%APPDATA%`, `%LOCALAPPDATA%`) are expanded on Windows; `~` is expanded on all platforms.

### Config reference

```jsonc
{
    // "auto" = let the resolver find the store (survives Anthropic moving it).
    // Or pin a literal path — see SESSION-STORES.md for per-OS locations.
    "sessions_dir": "auto",

    // Where to write archives + distilled transcripts.
    // Local:  "~/Documents/claude-sessions"
    // NAS:    "\\\\10.0.0.5\\share\\claude-sessions" (Windows UNC)
    //         "/Volumes/share/claude-sessions" (macOS) · "/mnt/nas/..." (Linux)
    "output_dir": "~/Documents/claude-sessions",

    // Optional state file (default is fine).
    "state_file": "~/.local/share/cowork-sync-state.json",

    // Optional: tag sessions by keyword (can be empty {}).
    "project_tags": {
        "backend":   ["django", "postgres", "celery"],
        "frontend":  ["react", "tailwind", "vite"]
    },

    // Format assumptions — only touch these if Anthropic changes the JSONL *schema*.
    // Location, prefix, and depth changes are handled automatically by the resolver.
    "format": {
        "session_dir_prefix": "local_",
        "transcript_filename": "audit.jsonl",
        "min_file_size_bytes": 1024,
        "expected_entry_types": ["system", "user", "assistant", "result", "tool_use_summary", "rate_limit_event"],
        "expected_init_fields": ["session_id", "model", "cwd", "mcp_servers"]
    }
}
```

### SMB / NAS output

**Windows:** use UNC paths (`\\server\share\...`). The script validates connectivity before writing. Mapped drive letters (`Z:`) may be unavailable in scheduled-task contexts — always use UNC.

**macOS:** mount first, then point `output_dir` at the mount.
```bash
mkdir -p /Volumes/share && mount_smbfs //user@10.0.0.5/share /Volumes/share
```

**Linux:** mount via CIFS (add to `/etc/fstab` for persistence).
```bash
sudo mount -t cifs //10.0.0.5/share /mnt/nas -o username=user,uid=$(id -u)
```

---

## Usage

```bash
python3 cowork_sync.py --check      # validate config + locate/verify the store
python3 cowork_sync.py --dry-run    # preview, write nothing
python3 cowork_sync.py              # run
python3 cowork_sync.py --force      # reprocess every session
python3 cowork_sync.py -c /path/to/config.json
```

> **Windows:** use `python` if that's how it's installed.

<details>
<summary>PowerShell alternative</summary>

```powershell
pwsh -ExecutionPolicy Bypass -File Sync-CoworkSessions.ps1 -Check
pwsh -ExecutionPolicy Bypass -File Sync-CoworkSessions.ps1 -DryRun
pwsh -ExecutionPolicy Bypass -File Sync-CoworkSessions.ps1
pwsh -ExecutionPolicy Bypass -File Sync-CoworkSessions.ps1 -Force
```

The PowerShell engine dot-sources `Resolve-CoworkSessionsDir.ps1` (kept next to it) for the `"auto"` / self-healing path. You can also run the resolver standalone to print the detected store:

```powershell
pwsh -File Resolve-CoworkSessionsDir.ps1
```
</details>

### Automated scheduling

<details>
<summary>macOS (launchd)</summary>

```bash
cp com.cowork-sync.python.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.cowork-sync.python.plist
launchctl list | grep cowork-sync
```
Edit `ProgramArguments` / `WorkingDirectory` to match your paths first. Interval is `StartInterval` (seconds, default 300). `launchctl start com.cowork-sync.python` runs it now; logs go to `/tmp/cowork-sync.log`.
</details>

<details>
<summary>Linux (cron)</summary>

```bash
crontab -e
# every 5 minutes:
*/5 * * * * cd /path/to/unified-cowork && python3 cowork_sync.py >> /tmp/cowork-sync.log 2>&1
```
</details>

<details>
<summary>Windows (Scheduled Task)</summary>

From an **elevated** PowerShell 7 prompt:
```powershell
pwsh -ExecutionPolicy Bypass -File Register-CoworkSync.ps1
pwsh -ExecutionPolicy Bypass -File Register-CoworkSync.ps1 -IntervalMinutes 10   # custom interval
```
Runs "whether logged on or not" — no window, no flash. Manage it:
```powershell
Get-ScheduledTaskInfo -TaskName 'CoworkSessionSync'
Start-ScheduledTask   -TaskName 'CoworkSessionSync'   # run now
Unregister-ScheduledTask -TaskName 'CoworkSessionSync'
```
> **Windows Hello users:** if you only have a PIN/biometric, set a password once (`net user <you> *`) — the task scheduler needs it. This doesn't disable Hello.

> **Repetition gotcha:** a `<Repetition>` trigger without a `<Duration>` can stop firing after one run on some Windows builds. `Register-CoworkSync.ps1` sets `RepetitionDuration` to "indefinitely" to avoid this.
</details>

---

## Output

```
output_dir/
├── SESSION-INDEX.md   ← catalog of all sessions (table, newest first)
├── CATCH-UP.md        ← project-grouped topic index for new-chat bootstrap
├── raw/               ← lossless transcript copies (your safety net)
│   └── 2026-06-27_gentle-river-3b9c.jsonl
└── distilled/         ← clean Markdown transcripts (what you read)
    └── 2026-06-27_gentle-river-3b9c.md
```

For each session the pipeline **archives** the raw transcript, **distills** it to Markdown (user messages, Claude's text, one-line tool summaries, a metadata header), **tags** it by project keyword, and **indexes** it. Distillation strips thinking blocks, tool-call JSON, permission prompts, signatures, and raw tool results — typically a **~95% size reduction** with all conversational content preserved.

### Distilled transcript

```markdown
# Session: gentle-river-3b9c

| Field | Value |
|-------|-------|
| Model | `claude-opus-4-8` |
| Session ID | `34c47d46...` |
| Started | 2026-06-27T09:15:00Z |
| User turns | 62 |
| Cost (USD) | $33.47 |
| MCP servers | filesystem, github |
| Summary | add rate limiting to the login endpoint |
| Projects | backend |
| Format version | 2026-02 |

---
### User
(message text)

### Claude
(response text)

> **Tool**: (one-line tool summary)
```

---

## Project tagging

Sessions are auto-tagged by scanning the distilled transcript for keywords (case-insensitive). A session can match multiple projects or none (`untagged`). Use specific terms — `"postgres"` beats `"database"`.

```json
"project_tags": {
    "backend":  ["django", "postgres", "celery"],
    "frontend": ["react", "tailwind", "vite"]
}
```

---

## Session catch-up (new-chat bootstrap)

The sync writes `CATCH-UP.md` — a lightweight, project-grouped index, each line a session with its first-message topic:

```markdown
## my-web-app
- **2026-06-22** f403658a (44 turns, $18.20): "fix the flaky checkout test"
- **2026-06-20** 81074e7c (71 turns, $24.09): "migrate the build from webpack to vite"
```

Add a **catch-up protocol** to your global `CLAUDE.md` so every new chat reads `CATCH-UP.md` and offers to restore context. A ready-to-paste template is in **[examples/catch-up-protocol.md](examples/catch-up-protocol.md)**. The flow: new chat → Claude reads `CATCH-UP.md` (cheap) → presents a numbered list → you pick one → Claude reads the first ~50 lines of that distilled transcript → work resumes.

---

## Format stability

This tool parses **undocumented, internal data formats**. Anthropic publishes no spec for either store, and may change them without notice.

Good news: **location, folder-prefix, and nesting-depth changes are now handled automatically** by the [resolver](#self-healing-location--no-more-broken-configs). What remains manual is the **JSONL schema** — and the script *detects and surfaces* schema drift instead of silently breaking. On every run it validates structure and a sample of entries, then prints specific diagnostics.

| Change | Handled by | Symptom / action |
|---|---|---|
| Storage path moved | **Resolver (automatic)** | `sessions_dir: "auto"` re-finds it |
| Folder prefix changed | **Pipeline (automatic)** | never keyed on prefix |
| Nesting depth changed | **Pipeline (automatic)** | recursive transcript discovery |
| Transcript file renamed | config | `No audit.jsonl found` → set `format.transcript_filename` |
| New entry types | non-fatal | `Unknown entry types: …` → entries skipped |
| JSONL → JSON | needs update | `Failed to parse JSONL line` → open an issue |
| Init fields renamed | config | `Init block missing fields` → set `format.expected_init_fields` |

**Format reference:** a complete reverse-engineered spec of the Desktop `audit.jsonl` format — every entry type, field inventories, annotated real examples — is in **[cowork-audit-jsonl-format-reference.md](cowork-audit-jsonl-format-reference.md)**. The Claude Code CLI transcript schema is documented in **[SESSION-STORES.md](SESSION-STORES.md)**.

If official documentation exists, please [open an issue](https://github.com/yjjoeathome-byte/unified-cowork/issues). See also the upstream request: [anthropics/claude-code#27724](https://github.com/anthropics/claude-code/issues/27724).

---

## Testing

```bash
python3 -m unittest test_cowork_sync -v
```

Stdlib only (`unittest` + `tempfile`) — no pytest. **59 tests** cover config loading, the self-healing resolver, distillation, index rebuild, and a `TestSecurity` suite of injection / path-traversal regressions.

---

## How it works

The engine recurses `sessions_dir` for `format.transcript_filename` (default `audit.jsonl`). Each match is one JSON-object-per-line transcript. Entry handling:

- `system`/`init` → session metadata (model, name, MCP servers, timestamps)
- `system`/`permission_*` → dropped (noise)
- `user` → text extracted (tool results dropped except errors)
- `assistant` → only `text` blocks kept (thinking, tool_use, signatures dropped)
- `tool_use_summary` → one-line blockquote
- `result` → cost + end timestamp

State is tracked by SHA-256 (uppercased for cross-runtime parity with PowerShell's `Get-FileHash`), so only changed files are reprocessed and you can switch between the Python and PowerShell engines freely.

Contributor notes — architecture, parity tables, and the Python rewrite rationale — live in [CLAUDE.md](CLAUDE.md).

---

## Roadmap

- **Claude Code CLI distillation** — the CLI store is already auto-located; distilling its `<uuid>.jsonl` schema (documented in [SESSION-STORES.md](SESSION-STORES.md)) into the same Markdown + index is next.
- **Python Appx tier** — the PowerShell resolver uses `Get-AppxPackage`; the Python resolver currently relies on the (sufficient) `Claude_*` glob.
- **Unified index across surfaces** — one `SESSION-INDEX.md` spanning Desktop "</> Code" and CLI sessions.

---

## License

GPL-3.0 — see [LICENSE](LICENSE).

## Disclaimer

This tool parses undocumented formats. It is not affiliated with, endorsed by, or supported by Anthropic. Anthropic may change session storage at any time without notice. Use at your own risk.
