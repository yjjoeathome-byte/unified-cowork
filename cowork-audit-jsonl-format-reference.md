# Cowork `audit.jsonl` — Reverse-Engineered Session Format Reference

> **Status:** Community-documented, reverse-engineered from observation. Not endorsed by Anthropic.
> **Format era:** `2026-02` (Claude Code 2.1.34–2.1.41, Cowork Research Preview)
> **Author:** [yjjoeathome-byte](https://github.com/yjjoeathome-byte) — maintainer of [unified-cowork](https://github.com/yjjoeathome-byte/unified-cowork)
> **Last verified:** 2026-02-21

---

## Why this document exists

Anthropic's Cowork product has no official documentation for its session transcript format. The [official position](https://support.anthropic.com/en/articles/11066105-about-claude-s-cowork-feature) is: *"Claude does not retain memory from previous Cowork sessions."* Each session starts blank.

This document fills the gap by describing the `audit.jsonl` format as observed through building a parser that has processed 80+ MB of real session data across dozens of sessions. It exists so that anyone building tooling around Cowork transcripts — archival, search, analytics, context restoration — doesn't have to reverse-engineer the format from scratch.

**Stability warning:** This format is undocumented and can change without notice. See [Format Change Detection](#format-change-detection) for how to handle that.

---

## Storage Layout

### Location

| Platform | Path |
|----------|------|
| Windows (MSIX/Store) | `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\local-agent-mode-sessions\` |
| Windows (legacy) | `%APPDATA%\Claude\local-agent-mode-sessions\` |
| macOS    | `~/Library/Application Support/Claude/local-agent-mode-sessions/` *(unverified — inferred from standard Electron app data path; community confirmation welcome)* |

> **Windows MSIX note (March 2026):** Anthropic began distributing Claude Desktop via the Microsoft Store (MSIX package). This moves app data from `%APPDATA%\Claude\` to `%LOCALAPPDATA%\Packages\Claude_<hash>\LocalCache\Roaming\Claude\`. The `<hash>` suffix (e.g., `pzs8sxrjxfjjc`) is derived from Anthropic's publisher certificate and should be stable across installations of the same signed package.

### Directory structure

```
local-agent-mode-sessions/
├── local_<session-uuid>/
│   └── audit.jsonl          ← the transcript
├── local_<session-uuid>/
│   └── audit.jsonl
└── ...
```

Each Cowork session creates a directory with the prefix `local_` followed by a UUID. Inside is a single file: `audit.jsonl`.

**Naming convention:** Cowork assigns each session a human-readable name (e.g., `tender-eager-fermat`, `sleepy-charming-ramanujan`) using an adjective-adjective-scientist pattern. This name appears in the `cwd` field of the init block as `/sessions/<session-name>` but is *not* the directory name on disk — the directory uses the UUID.

### File characteristics

- Format: JSONL (one JSON object per line, newline-delimited)
- Encoding: UTF-8
- Growth: append-only during a session; file is locked while Cowork is active
- Size range observed: 4 KB (1-turn "hi" session) to 14 MB (225-turn deep work session)

---

## Entry Types

Every line in `audit.jsonl` is a JSON object with a `type` field. Six entry types have been observed:

| Type | Purpose | Signal or noise? |
|------|---------|-------------------|
| `system` | Session init, permissions, internal events | **Init is signal**, permissions are noise |
| `user` | Human messages and tool results returned to Claude | **Signal** |
| `assistant` | Claude's responses (text, thinking, tool calls) | **Text is signal**, thinking/tool_use are noise |
| `tool_use_summary` | One-line summary of what a tool did | **Signal** (compact) |
| `result` | Turn completion: cost, timing, usage stats | **Metadata signal** |
| `rate_limit_event` | API rate limiting occurred (speculative — defined in config but not yet observed in the wild) | Noise (operational) |

### Entry: `system` (subtype: `init`)

The first `system` entry with `subtype: "init"` is the session metadata block. It appears once at session start and again after each user message (Cowork re-emits it as context).

```jsonc
{
  "type": "system",
  "subtype": "init",
  "cwd": "/sessions/tender-eager-fermat",        // session name lives here
  "session_id": "281a2e36-...",                   // internal session UUID
  "model": "claude-opus-4-6",                     // model used
  "claude_code_version": "2.1.34",                // Cowork/Claude Code version
  "permissionMode": "default",
  "tools": ["Task", "Bash", "Read", "Write", ...], // available tools (long array)
  "mcp_servers": [                                 // connected MCP servers
    {"name": "filesystem", "status": "connected"},
    {"name": "kubernetes", "status": "connected"}
  ],
  "agents": ["Bash", "general-purpose", "Plan", ...],
  "skills": ["debug", "anthropic-skills:docx", ...],
  "plugins": [{"name": "anthropic-skills", "path": "/sessions/.../mnt/.skills"}],
  "slash_commands": ["compact", "cost", "review", ...],
  "apiKeySource": "none",
  "output_style": "default",
  "fast_mode_state": "off",                       // not always present
  "uuid": "5eb45713-...",
  "_audit_timestamp": "2026-02-11T13:56:53.573Z"
}
```

**Key fields for tooling:**
- `model` — which Claude model ran the session
- `cwd` — extract session name from `/sessions/<n>`
- `mcp_servers` — which integrations were active (filter by `status: "connected"`)
- `claude_code_version` — useful for tracking format changes across versions
- `_audit_timestamp` — session start time

**Noise:** The `tools` array is typically 50–80 entries long and enumerates every available tool including all MCP tool names. It's useful for debugging MCP connectivity but not for transcript reconstruction.

### Entry: `system` (subtype: `permission_request` / `permission_response`)

Permission pairs bracket every tool call. They record what tool was invoked, what the user approved, and whether it was a one-time or "always allow" grant.

```jsonc
// Request
{
  "type": "system",
  "subtype": "permission_request",
  "tool_name": "mcp__filesystem__list_directory",
  "tool_input": {"path": "\\\\10.255.10.193\\..."},
  "uuid": "e9c88351-...",
  "session_id": "281a2e36-...",
  "_audit_timestamp": "2026-02-11T13:57:48.325Z"
}

// Response
{
  "type": "system",
  "subtype": "permission_response",
  "tool_name": "mcp__filesystem__list_directory",
  "decision": "always",      // "always" or "once"
  "granted": true,
  "uuid": "e9c88351-...",    // matches the request UUID
  "session_id": "281a2e36-...",
  "_audit_timestamp": "2026-02-11T13:58:13.146Z"
}
```

**For distillation:** Pure noise. These are the single largest source of bloat in long sessions. A 225-turn session can have hundreds of permission pairs that add zero conversational content. Safe to strip entirely.

### Entry: `user`

User messages come in two forms: direct human input, and tool results being returned to Claude.

**Human message:**
```jsonc
{
  "type": "user",
  "uuid": "cd6f4828-...",
  "session_id": "cc79cd3f-...",
  "parent_tool_use_id": null,          // null = direct human input
  "message": {
    "role": "user",
    "content": "what is my home directory"  // string for simple messages
  },
  "_audit_timestamp": "2026-02-17T00:43:49.218Z"
}
```

**Tool result (returned to Claude after tool execution):**
```jsonc
{
  "type": "user",
  "parent_tool_use_id": null,
  "session_id": "281a2e36-...",
  "message": {
    "role": "user",
    "content": [                        // array for structured content
      {
        "tool_use_id": "toolu_019aoF...",
        "type": "tool_result",
        "content": "/sessions/tender-eager-fermat",
        "is_error": false
      }
    ]
  },
  "tool_use_result": {                  // redundant structured version
    "stdout": "/sessions/tender-eager-fermat",
    "stderr": "",
    "interrupted": false,
    "isImage": false
  },
  "_audit_timestamp": "2026-02-11T13:56:59.113Z"
}
```

**Key distinction:** `parent_tool_use_id: null` with string content = human typed this. Array content with `type: "tool_result"` = machine-generated tool output being fed back to Claude.

**For distillation:** Human messages are always signal. Tool results are mostly noise (the `tool_use_summary` entry provides a compressed version), except for error results (`is_error: true`) which indicate failures worth preserving.

### Entry: `assistant`

Assistant entries contain Claude's response blocks. A single logical response may span multiple `assistant` entries (streamed chunks that share the same `message.id`).

The `message.content` array can contain three block types:

**Text block (signal):**
```jsonc
{
  "type": "text",
  "text": "The home directory inside this VM session is `/sessions/tender-eager-fermat`..."
}
```

**Thinking block (noise for archival):**
```jsonc
{
  "type": "thinking",
  "thinking": "The user is asking about their home directory...",
  "signature": "EuQCCkYICxgCKkAKsZRKtu89e8rB..."  // cryptographic signature
}
```

**Tool use block (noise — duplicates the tool_use_summary):**
```jsonc
{
  "type": "tool_use",
  "id": "toolu_019aoFPySsymfdGD73p1Hpwq",
  "name": "Bash",
  "input": {"command": "echo $HOME", "description": "Print home directory"}
}
```

**Usage metadata** (nested in `message.usage`):
```jsonc
"usage": {
  "input_tokens": 3,
  "cache_creation_input_tokens": 12634,
  "cache_read_input_tokens": 24102,
  "output_tokens": 2,
  "service_tier": "standard",
  "cache_creation": {
    "ephemeral_5m_input_tokens": 12634,
    "ephemeral_1h_input_tokens": 0
  }
}
```

**For distillation:** Extract only `type: "text"` blocks. Thinking blocks are large (often longer than the visible response) and contain cryptographic signatures that are meaningless outside the API. Tool use blocks duplicate information that appears more compactly in `tool_use_summary` entries.

### Entry: `tool_use_summary`

A one-line human-readable summary of what a tool invocation accomplished. Generated by a secondary model (observed: `claude-haiku-4-5`) after the tool completes.

```jsonc
{
  "type": "tool_use_summary",
  "summary": "Identified home directory path successfully",
  "preceding_tool_use_ids": ["toolu_019aoFPySsymfdGD73p1Hpwq"],
  "session_id": "281a2e36-...",
  "uuid": "1d04e4e2-...",
  "_audit_timestamp": "2026-02-11T13:57:04.091Z"
}
```

**For distillation:** High signal density. One sentence replaces the full tool_use block + tool_result block + permission pairs. This is the entry type that makes ~95% compression possible.

### Entry: `result`

Marks the completion of a conversational turn (one user message → full Claude response cycle).

```jsonc
{
  "type": "result",
  "subtype": "success",
  "is_error": false,
  "duration_ms": 10632,
  "duration_api_ms": 11881,
  "num_turns": 2,                      // API turns within this exchange
  "result": "The home directory...",    // final text (duplicate of assistant text)
  "total_cost_usd": 0.21581175,
  "usage": {
    "input_tokens": 4,
    "cache_creation_input_tokens": 28859,
    "cache_read_input_tokens": 55940,
    "output_tokens": 232,
    "server_tool_use": {
      "web_search_requests": 0,
      "web_fetch_requests": 0
    }
  },
  "modelUsage": {                       // per-model cost breakdown
    "claude-opus-4-6": {
      "inputTokens": 5,
      "outputTokens": 428,
      "cacheReadInputTokens": 126606,
      "cacheCreationInputTokens": 2036,
      "costUSD": 0.086753,
      "contextWindow": 200000,
      "maxOutputTokens": 32000
    },
    "claude-haiku-4-5-20251001": {      // used for tool_use_summary generation
      "inputTokens": 568,
      "outputTokens": 20,
      "costUSD": 0.000668
    }
  },
  "permission_denials": [],
  "session_id": "281a2e36-...",
  "_audit_timestamp": "2026-02-11T13:58:34.884Z"
}
```

**For distillation:** Extract `total_cost_usd` and `_audit_timestamp` (session end time) for metadata. The `result` text field is a duplicate of the last assistant text block — skip it. The `modelUsage` breakdown reveals that Haiku is used for summarization, which is useful for understanding billing.

---

## Compression Rationale

The distillation strategy strips five categories of content:

| Category | Why it's noise | Typical share of file size |
|----------|---------------|---------------------------|
| Thinking blocks | Internal reasoning + cryptographic signatures; not shown to user | 30–40% |
| Tool use JSON | Full input/output of every tool call; replaced by `tool_use_summary` | 20–30% |
| Permission pairs | Every tool call has a request+response pair; pure approval records | 10–15% |
| Duplicate init blocks | Re-emitted after every user message; identical content | 5–15% |
| Usage/token metadata | Per-turn billing detail; aggregated into session-level cost | 5–10% |

**Observed compression ratios** from real sessions (distilled sizes estimated):

| Session | Raw size | Distilled size (est.) | Ratio |
|---------|----------|-----------------------|-------|
| 225 turns, deep work | 13.84 MB | ~700 KB | ~5% |
| 131 turns, handoff work | 8.87 MB | ~450 KB | ~5% |
| 75 turns, mixed | 5.69 MB | ~280 KB | ~5% |
| 2 turns, minimal | 23 KB | ~2 KB | ~9% |

The ratio is consistent at roughly **95% reduction** for substantive sessions. Short sessions compress less because the init block is a larger fraction of total content.

---

## Format Change Detection

This format is undocumented and **will** change. The `unified-cowork` parser includes config-driven detection for the following change vectors:

| What might change | Detection method | Config knob |
|-------------------|-----------------|-------------|
| Storage directory path | Check if `sessions_dir` exists; scan for alternative paths under `%APPDATA%\Claude\` | `sessions_dir` |
| Directory prefix | Check if session folders start with expected prefix | `format.session_dir_prefix` |
| Transcript filename | Check if expected filename exists; scan for other `.jsonl` or `.json` files | `format.transcript_filename` |
| Entry types | Track unknown `type` values encountered during parsing | `format.expected_entry_types` |
| Init block fields | Check for missing expected fields in `system/init` entries | `format.expected_init_fields` |
| File format (JSONL→JSON) | Detect parse failures on first lines | Structural |

**Philosophy:** Detect and report, don't silently fail. If the format changes, the parser should tell you *what* changed and *which config knob* to adjust, not produce corrupt output.

### Known schema versions

| Claude Code version | Observed changes |
|--------------------|-----------------|
| 2.1.34 | Baseline observation. |
| 2.1.41 | `fast_mode_state` field added to init. `agents` and `skills` arrays added to init. `rate_limit_event` type defined in config schema but not yet observed in captured sessions. |

---

## Common Pitfalls

**File locking:** Cowork holds `audit.jsonl` open while a session is active. Attempting to read or hash the file will fail. The parser should catch the access error and skip the session rather than crashing.

**Duplicate session names:** The human-readable session name (from `cwd`) is reused across multiple sessions over time. A session named `zen-modest-clarke` on Feb 11 and another `zen-modest-clarke` on Feb 20 are different sessions with different UUIDs. Always use the UUID as the primary key.

**Multipart assistant entries:** A single Claude response may be split across 2–3 `assistant` entries sharing the same `message.id`. The first chunk may contain only a thinking block, the second the text, the third a tool call. Parsers that assume one entry = one response will miss content or double-count.

**Init block repetition:** The `system/init` block is re-emitted after every user message, not just at session start. In a 225-turn session, this means ~225 copies of the init block. A naive parser that doesn't deduplicate will inflate metadata extraction.

**Content polymorphism:** The `message.content` field in `user` entries can be either a string (simple message) or an array (structured content with tool results). Parsers must handle both forms.

---

## Related Projects

| Project | Approach | Scope |
|---------|----------|-------|
| [unified-cowork](https://github.com/yjjoeathome-byte/unified-cowork) | External batch pipeline; archives + distills + generates catch-up index | Cowork `audit.jsonl` |
| [memory-bridge](https://github.com/anthropics/claude-code/pull/27140) | In-process plugin; consolidates context at compaction time | Claude Code session JSONL |
| [Cozempic](https://github.com/anthropics/claude-code/issues/20367) | Context loss mitigation via deduplication and checkpointing | Claude Code |

**Note:** Cowork's `audit.jsonl` (inside `local-agent-mode-sessions/`) and Claude Code's session JSONL (on the host filesystem) are related but not identical formats. This document covers only the Cowork format.

---

## Contributing

If you observe format changes (new entry types, missing fields, renamed directories), please [open an issue](https://github.com/yjjoeathome-byte/unified-cowork/issues) with:

1. Your `claude_code_version` (from the init block)
2. The specific change observed
3. A sanitized sample line (strip personal content, keep structure)

---

*This document was produced by analyzing 83 MB of raw Cowork session transcripts using the [unified-cowork](https://github.com/yjjoeathome-byte/unified-cowork) parser. The format knowledge was extracted from the parser's own source code and validated against real session data — including a session where the tool documented itself.*
