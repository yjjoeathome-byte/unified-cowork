# Security Policy

## What This Tool Handles

cowork-session-sync processes Cowork session transcripts that may contain:

- Infrastructure details (hostnames, IP addresses, network topology)
- Tool outputs (shell commands, file contents, database queries)
- API keys, tokens, or credentials that were pasted into or returned by Cowork
- Employer-specific information, internal project names, business logic
- MCP server configurations and connection details

**Treat your `raw/` and `distilled/` directories as sensitive data.** They contain everything you said to Claude and everything Claude said back — including tool outputs you may not have reviewed line by line.

## Recommendations

- **Never commit session data to git.** The `.gitignore` excludes `raw/`, `distilled/`, `SESSION-INDEX.md`, and `config.json` by default. Do not override this.
- **Restrict output directory permissions.** If writing to a NAS or shared storage, ensure only your user account has read access.
- **Review distilled transcripts before sharing.** Even sanitized transcripts may contain sensitive context you didn't notice during the session.
- **Rotate credentials that appeared in sessions.** If you pasted an API key or token during a Cowork session, assume it's now in the raw archive. Rotate it.
- **`config.json` contains your infrastructure paths.** NAS IPs, share names, directory structures. Keep it out of version control (already in `.gitignore`).

## The Script Itself

- Runs locally. No network calls except to the output directory (local or SMB/NFS).
- No telemetry, no analytics, no outbound connections.
- `Register-CoworkSync.ps1` stores your Windows password in the Windows Task Scheduler credential store (standard OS facility, encrypted at rest). The password is zeroed from memory immediately after registration.
- State tracking (`cowork-sync-state.json`) contains only file paths and SHA256 hashes — no session content.

## Reporting a Vulnerability

If you find a security issue in the script itself (path traversal, credential leak, injection via malformed JSONL, etc.):

1. **Do not open a public issue.**
2. Email: *(add your contact here, or use GitHub's private vulnerability reporting)*
3. Include: what you found, how to reproduce it, and what you think the impact is.

I'll respond within 72 hours.
