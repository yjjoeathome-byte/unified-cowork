# Catch-Up Protocol — CLAUDE.md Template

Paste the block below into your global `CLAUDE.md` to enable automatic session
catch-up on every new Cowork chat.

**Location:**
- Windows: `%APPDATA%\Claude\.claude\CLAUDE.md`
- macOS: `~/Library/Application Support/Claude/.claude/CLAUDE.md`

**Prerequisites:**
- `Sync-CoworkSessions.ps1` running on a schedule (generates `CATCH-UP.md`)
- `CATCH-UP.md` accessible from within Cowork (local path, mounted share, or via MCP)

**Adapt the read mechanism** in the protocol below to match your setup:
- Local/mounted share: use `Read` tool with the path to `CATCH-UP.md`
- NAS via ssh-relay MCP: use `run_remote_command` to `cat` the file
- Other: adjust accordingly

---

## Template (copy below this line into CLAUDE.md)

```markdown
## Session Catch-Up Protocol

On the first interaction of every new conversation, execute the following:

1. Read the catch-up index from [ADAPT: your CATCH-UP.md path or retrieval method].
   Example for ssh-relay: `cat /path/to/cowork-sessions/CATCH-UP.md` via ssh-relay on [host].
   Example for local: Read `/path/to/cowork-sessions/CATCH-UP.md`.

2. Present the projects and recent sessions as a compact numbered list, grouped by project.
   Include the date, session name, and topic for each. Do not dump the raw file.

3. Ask: "Which project or session would you like to continue, or is this a fresh topic?"

4. If the user picks a project/session, read the first 50 lines of the corresponding
   distilled file to load session context. Do not load the full transcript.

5. Proceed with the loaded context. Do not re-explain what you loaded — just work.

Constraints:
- Do not load CATCH-UP.md unless this is the first interaction in the conversation.
- Do not load distilled files unless the user explicitly picks a session.
- If the catch-up index is unreachable (network, permissions), note it once and proceed normally.
```
