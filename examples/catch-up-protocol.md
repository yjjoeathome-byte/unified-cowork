# Catch-Up Protocol — CLAUDE.md Template

Session catch-up with archive filtering and fast-path bootstrap.

**Location:**
- Windows: `%APPDATA%\Claude\.claude\CLAUDE.md`
- macOS: `~/Library/Application Support/Claude/.claude/CLAUDE.md`

**Prerequisites:**
- `Sync-CoworkSessions.ps1` running on a schedule (generates `SESSION-INDEX.md`)
- `SESSION-INDEX.md` accessible from within Cowork (local path, mounted share, or via MCP)
- `archived-sessions.txt` in the same directory as `SESSION-INDEX.md` (see below)

**Adapt the read mechanism** in the protocol and shortcut below to match your setup:
- Local/mounted share: use `Read` tool with the path
- NAS via MCP filesystem: use `mcp__filesystem__read_text_file`
- NAS via ssh-relay MCP: use `run_remote_command` to `cat` the file
- Other: adjust accordingly

---

## Architecture

The catch-up mechanism has three parts:

1. **CLAUDE.md trigger** — registers "catchup-bunny" as a shortcut with a fast-path rule
   that skips full project bootstrap
2. **Shortcut definition file** — contains the step-by-step execution logic
3. **archived-sessions.txt** — flat file listing sessions to exclude from the pick list

### Data flow

```
User says "catchup-bunny"
  → CLAUDE.md fast-path: skip project bootstrap
  → Read shortcut definition
  → Read SESSION-INDEX.md + archived-sessions.txt (single batch)
  → Triage: compute total / archived / active counts
  → Prompt: "Show active only (Cowork GUI) or all (including archived)?"
  → User chooses → display numbered list
  → User picks session(s) → load distilled file(s) → summarize
  → Post-catchup: offer to mark sessions as archived → append to archived-sessions.txt
```

### Key design decision: archive state is server-side

Claude Desktop stores the archive flag on Anthropic's servers, not in the local
filesystem. The local IndexedDB only contains chat drafts and editor state.
This means the sync script cannot detect archive status automatically.

`archived-sessions.txt` is maintained organically within the catchup-bunny flow
itself — after catching up, the user is offered to mark sessions as archived.
No separate tooling or manual file editing required.

---

## Template: CLAUDE.md Block

Add this to your `CLAUDE.md`. Adapt paths to your environment.

```markdown
## Session Catch-Up (trigger: "catchup-bunny")

Defined as a shortcut — see Shortcuts table below. Reads `SESSION-INDEX.md`,
filters out archived sessions via `cowork-sessions/archived-sessions.txt`,
presents a numbered pick list. Fast-path: skips full project bootstrap until
after selection.
```

And in the Shortcuts table:

```markdown
| Trigger | What it does | Definition |
|---|---|---|
| "catchup-bunny" | Session catch-up selector (fast-path, skips full bootstrap) | `<your-path>/shortcuts/catchup-bunny.md` |
```

If your CLAUDE.md has a bootstrap section, add the fast-path exception:

```markdown
**Fast-path exception:** If the user's first message is `catchup-bunny`, skip
the full bootstrap below. Instead, read and execute the shortcut at
`<your-path>/shortcuts/catchup-bunny.md`. Load project context only after the
user selects a session and work begins.
```

---

## Template: Shortcut Definition File

Save as `shortcuts/catchup-bunny.md` (or wherever your shortcuts live).
Adapt all paths to your environment.

```markdown
# catchup-bunny — Session Catchup Selector

**Trigger:** User says "catchup-bunny"

## Fast-Path Rule

This shortcut **short-circuits the full project bootstrap**. When "catchup-bunny"
is the first message in a session:
1. Read ONLY CLAUDE.md (already done by bootstrap rule)
2. Execute this shortcut immediately — do NOT read other project context files
3. Load project context only AFTER the user selects a session and work begins

## Steps

### 1. Read session index and archive list

Read these two files:
- `<your-path>/cowork-sessions/SESSION-INDEX.md`
- `<your-path>/cowork-sessions/archived-sessions.txt`

### 2. Filter

- Parse SESSION-INDEX.md table rows
- Exclude any session whose `YYYY-MM-DD_session-name` key appears in
  `archived-sessions.txt`
- The key format in the archive file is one entry per line: `YYYY-MM-DD_session-name`

### 3. Present

Display the **non-archived** sessions as a numbered table, newest first,
with columns: #, Date, Session, Project, Turns, Cost.

If no sessions remain after filtering, say:
"All sessions archived. Nothing to catch up on."

### 4. Wait for selection

User picks one or more numbers. Read the corresponding distilled markdown
file(s) from:
`<your-path>/cowork-sessions/distilled/YYYY-MM-DD_session-name.md`

Present a concise summary of each selected session.
```

---

## Template: archived-sessions.txt

Create an empty file (or pre-populate with sessions you've already reviewed):

```
# Archived sessions — one key per line (YYYY-MM-DD_session-name)
# Sessions listed here are excluded from catchup-bunny listing.
```

To archive a session after catching up, append its key:
```bash
echo "2026-02-15_my-session-name" >> cowork-sessions/archived-sessions.txt
```

---

## Migration from CATCH-UP.md

If you previously used the `CATCH-UP.md`-based protocol:

1. `SESSION-INDEX.md` replaces `CATCH-UP.md` as the session source — it has
   richer metadata (turns, cost, project tags)
2. `archived-sessions.txt` adds filtering that `CATCH-UP.md` never had
3. The old CLAUDE.md block that read `CATCH-UP.md` should be replaced with the
   templates above
4. `CATCH-UP.md` can be kept for reference or deleted — the sync script may
   still generate it, but catchup-bunny no longer reads it
