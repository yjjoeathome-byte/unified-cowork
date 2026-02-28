# Catch-Up Protocol — CLAUDE.md Template

Session catch-up with archive filtering, readable session titles, and fast-path bootstrap.

**Location:**
- Windows: `%APPDATA%\Claude\.claude\CLAUDE.md`
- macOS: `~/Library/Application Support/Claude/.claude/CLAUDE.md`

**Prerequisites:**
- `Sync-CoworkSessions.ps1` running on a schedule (generates `SESSION-INDEX.md` and `CATCH-UP.md`)
- `SESSION-INDEX.md`, `CATCH-UP.md`, and `archived-sessions.txt` accessible from within Cowork
- Adapt the read mechanism below to match your setup (local path, MCP filesystem, ssh-relay, etc.)

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
  → Read SESSION-INDEX.md + archived-sessions.txt + CATCH-UP.md (single batch)
  → Parse sessions from index, topics from CATCH-UP.md, exclusions from archive list
  → Synthesize readable titles from raw topics (heuristic compression)
  → Triage: compute total / archived / active counts (with sanity check)
  → Prompt: "Show active only (Cowork GUI) or all (including archived)?"
  → User chooses → display numbered list with synthesized titles
  → User picks session(s) → load distilled file(s) → summarize
  → Post-catchup: offer to mark sessions as archived → append to archived-sessions.txt
```

### Key design decisions

**Archive state is server-side.** Claude Desktop stores the archive flag on
Anthropic's servers, not in the local filesystem. The local IndexedDB only
contains chat drafts and editor state. `archived-sessions.txt` is maintained
organically within the catchup-bunny flow — no separate tooling needed.

**Session titles are synthesized at display time.** Cowork's internal codenames
(e.g. `stoic-serene-gauss`) are meaningless to users. `CATCH-UP.md` contains
the first user message as a raw topic. The shortcut instructs Claude to
compress each raw topic into a 5–8 word readable title using heuristics:
- Bootstrap boilerplate → `Project bootstrap session`
- Trigger-only messages (`catchup-bunny`, `let's talk`) → `(bootstrap attempt)` / `(quick chat)`
- File uploads (`<uploaded_files>`) → `File/config review`
- Questions → extract the question
- Everything else → compress to action + object

Codenames are never shown to the user — they're only used internally for
key matching and file lookups.

**Rendering uses numbered lists, not tables.** Cowork UI does not reliably
render markdown tables. The session list uses a numbered list format instead.

---

## Template: CLAUDE.md Block

Add this to your `CLAUDE.md`. Adapt paths to your environment.

```markdown
## Session Catch-Up (trigger: "catchup-bunny")

Defined as a shortcut — see Shortcuts table below. Reads `SESSION-INDEX.md`,
`CATCH-UP.md`, and `archived-sessions.txt` to present a filtered, titled
session pick list. Fast-path: skips full project bootstrap until after selection.
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

### 1. Read session data

Read these three files in a single batch:
- `<your-path>/cowork-sessions/SESSION-INDEX.md` — session metadata (dates, turns, cost)
- `<your-path>/cowork-sessions/archived-sessions.txt` — exclusion list
- `<your-path>/cowork-sessions/CATCH-UP.md` — raw topics (first user message per session)

### 2. Triage

**Parse index:** Extract table rows from SESSION-INDEX.md → session keys (`YYYY-MM-DD_session-name`)
**Parse topics:** Extract quoted topic strings from CATCH-UP.md → synthesize 5–8 word titles
**Parse exclusions:** Read archived-sessions.txt (skip `#` comments and blank lines)
**Filter:** sessions NOT in exclusion set = active; sessions IN = archived
**Sanity check:** active + archived must equal total

### 3. Prompt

> **{total} sessions in index, {archived} archived, {active} active.**
> 1. Show only active sessions
> 2. Show all sessions (including archived)

### 4. Present — numbered list format

Display the chosen set as a numbered list, newest first:

1. Synthesized title here
   project-tag · N turns · $X.XX

2. Another synthesized title
   project-tag · N turns · $X.XX

Codenames are NOT shown. They are used only internally for file lookups.

### 5. Load and summarize

User picks numbers → read distilled markdown files → present concise summary.

### 6. Post-catchup archive offer

After catchup, offer to mark sessions as archived → append keys to archived-sessions.txt.
```

---

## Template: archived-sessions.txt

Create an empty file (or pre-populate with sessions you've already reviewed):

```
# Archived sessions — one key per line (YYYY-MM-DD_session-name)
# Sessions listed here are excluded from catchup-bunny listing.
```

---

## Known Limitations

- The sync script skips locked `audit.jsonl` files (currently-open sessions). Active sessions
  won't appear until closed or the lock is released.
- Sessions started since the last sync run (every 5 minutes) will be missing.
- The Claude Desktop sidebar may show more sessions than catchup-bunny because
  the sidebar is live and the index is a periodic snapshot.

## Migration from CATCH-UP.md-only Protocol

If you previously used CATCH-UP.md as the sole session source:

1. `SESSION-INDEX.md` is now the primary metadata source (turns, cost, project tags)
2. `CATCH-UP.md` is now used for topic extraction only — it provides the raw first-user-message
   that gets compressed into readable titles
3. `archived-sessions.txt` adds filtering that the old protocol never had
4. The old CLAUDE.md block that read only CATCH-UP.md should be replaced with the templates above
