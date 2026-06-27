# Claude Session Stores — Where Everything Lives

A reverse-engineered map of where Claude writes session transcripts across its
two coding surfaces, on every OS, plus the auto-resolution algorithm that finds
them when Anthropic moves things. Reverse-engineered from observed behavior;
**undocumented and subject to change without notice.**

Last verified: **2026-06-27** on Windows 11 (Claude Desktop MSIX `Claude_pzs8sxrjxfjjc`, package version `1.15962.1.0`; Claude Code CLI).

---

## The two surfaces

Claude has two coding surfaces, and they are converging:

1. **Claude Desktop "</> Code"** — the agentic coding mode inside the desktop app, formerly branded **Cowork**. Internally still "local-agent-mode."
2. **Claude Code CLI** — the standalone terminal tool (`claude`).

They are not really separate: Desktop "</> Code" launches Claude Code *inside* the app. In one observed install, the Desktop store and a CLI project directory shared the **same session UUIDs** (`…claude-code-sessions-<uuid-A>…-<uuid-B>…`). Treat them as two storage layouts for one underlying engine.

---

## Surface 1 — Claude Desktop "</> Code" (`local-agent-mode-sessions`)

### Transcript file: `audit.jsonl`

One per session. Schema documented in
[cowork-audit-jsonl-format-reference.md](cowork-audit-jsonl-format-reference.md).

### Location by OS

| OS | Path to `local-agent-mode-sessions` |
|---|---|
| **Windows (MSIX / Store)** | `%LOCALAPPDATA%\Packages\Claude_<hash>\LocalCache\Roaming\Claude\local-agent-mode-sessions\` |
| **Windows (legacy / non-Store)** | `%APPDATA%\Claude\local-agent-mode-sessions\` |
| **macOS** | `~/Library/Application Support/Claude/local-agent-mode-sessions/` |
| **Linux** | `~/.config/Claude/local-agent-mode-sessions/` |

> **MSIX note.** The Microsoft Store build runs in a per-package sandbox. `Claude_<hash>` is the **package family name** (`Claude_pzs8sxrjxfjjc` on the verified machine) — the `<hash>` is a publisher ID, **stable across app updates**. The *full* package name carries the version (`Claude_1.15962.1.0_x64__pzs8sxrjxfjjc`) and changes on every update, so never key on it. Inside the sandbox, `LocalCache\Roaming` is the app's redirected `%APPDATA%`, so `LocalCache\Roaming\Claude\` is just the usual Electron `userData` directory.
>
> Find yours: `Get-ChildItem $env:LOCALAPPDATA\Packages\Claude_*` or `Get-AppxPackage *Claude* | Select PackageFamilyName`.

### The nested reality (this is not a flat directory)

`audit.jsonl` is **not** a direct child of `local-agent-mode-sessions`. Verified layout:

```
local-agent-mode-sessions/
  <container-uuid>/                       e.g. a1b2c3d4-1111-2222-3333-444455556666
    <home-uuid>/                          e.g. b2c3d4e5-7777-8888-9999-aaaabbbbcccc
      <prefix>_<session-uuid>/            e.g. local_1f2e3d4c-...
        audit.jsonl                       ← the transcript (depth 3)
  skills-plugin/                          ← non-session sibling, ignore
```

Two properties make this **hostile to hardcoding**, and the pipeline keys on neither:

- **Prefix churn.** The session-folder prefix is unstable. All of these were present *in one store at once*: `local_`, `ditto_`, the double-prefixed `local_ditto_`, and bare UUIDs with no prefix. `format.session_dir_prefix` is used only to *strip* the prefix for a cosmetic UUID; transcript discovery is by filename recursion, so prefix changes don't break it.
- **Variable depth.** `audit.jsonl` was found at **depth 3 and depth 4** in the same store. Never assume a fixed depth — recurse.

### Cost of enumeration

On the verified machine: **172 `audit.jsonl` files**, full recursive scan **~425 ms** across **~6,000 directory entries** (the tree also holds `backups/`, `debug/`, `agent/`, `cowork_plugins/`). The cost grows as those accumulate — a future optimization is to recurse only the `*_<uuid>` session subtrees.

---

## Surface 2 — Claude Code CLI (`~/.claude/projects`)

### Transcript file: `<session-uuid>.jsonl`

One file **per session**, named by session UUID, grouped into per-working-directory project folders.

### Location by OS

| OS | Path |
|---|---|
| **Windows** | `%USERPROFILE%\.claude\projects\<cwd-slug>\<session-uuid>.jsonl` |
| **macOS / Linux** | `~/.claude/projects/<cwd-slug>/<session-uuid>.jsonl` |

`<cwd-slug>` is the session's working directory with separators/colons flattened to `-`. Examples (verified):

```
C--Users-alice-projects-my-app
C--Users-alice-source-acme-api
C--Users-alice-AppData-Local-Packages-Claude-..-claude-code-sessions-<uuid>-..-<uuid>-..
```

On the verified machine: **359 `.jsonl` transcripts** across the project folders.

### Schema (distinct from `audit.jsonl`)

The CLI transcript is **a different format** from Desktop's `audit.jsonl`. One JSON object per line; top-level keys observed across a sample:

```
type, sessionId, uuid, parentUuid, message, messageId, timestamp, version,
cwd, gitBranch, userType, isMeta, isSidechain, isSnapshotUpdate, snapshot,
leafUuid, promptId, promptSource, permissionMode, mode, entrypoint, origin,
aiTitle, attachment
```

`type` values include `last-prompt`, `mode`, `user`, `assistant`, … Notable differences from `audit.jsonl`:

- Session identity is `sessionId` + a `parentUuid`-linked DAG of turns (supports branching / `isSidechain`), rather than a flat append log.
- Each turn carries `cwd` and `gitBranch` — useful project signal the Desktop format lacks.
- An `aiTitle` field often holds a model-generated session title (a ready-made summary).
- There is no separate `result` cost record in the same shape; cost accounting differs.

> **Confidence.** This is a *structural* survey of real files, not an exhaustive spec. It's enough to drive the roadmap distiller; corrections welcome via issue/PR. Distillation of this format is **not yet implemented** — the store is auto-located, but only Desktop `audit.jsonl` is currently distilled + indexed.

---

## Auto-resolution algorithm

Implemented in both engines: `Resolve-CoworkSessionsDir.ps1` (PowerShell) and
`resolve_sessions_dir()` in `cowork_sync.py` (Python). Triggered when
`sessions_dir` is `"auto"`, empty, or points somewhere that no longer exists.

### The invariant

Everything about the path is unstable *except this*: **a directory named
`local-agent-mode-sessions` containing transcript files (`audit.jsonl`) somewhere
beneath it.** That pair is the fingerprint. The resolver never keys on the
package version, the publisher hash (it globs it), the intermediate path, the
folder prefix, or the nesting depth.

### Cost-tiered, cached

| Tier | Strategy | Typical cost |
|---|---|---|
| **0 — Pin** | explicit literal path in config, if it validates | ~0 ms |
| **1 — Cache** | last-known-good path, re-validated | ~10 ms |
| **2 — Glob-probe** | per-OS candidate roots; on Windows `…\Packages\Claude_*\LocalCache\Roaming\Claude\local-agent-mode-sessions` | ~30 ms |
| **3 — Appx** (Win/PS) | `Get-AppxPackage *Claude*` → family name → bounded search under `…\Packages\<family>\LocalCache` | ~360 ms |
| **4 — Anchored discovery** | shallow-scan app-data roots for `*Claude*`/`*Anthropic*` dirs, bounded search within each | ~1 s (rare) |
| **5 — Pruned `$HOME` walk** | depth-capped, prune-listed; loud warning (PowerShell) | last resort |

Steady state is Tier 1 (cache hit). After a move you pay one Tier 2 probe, then
re-cache. Tiers 3–5 fire only when the cheap probes miss — and tiers 4–5 stay
bounded to Claude/Anthropic-named folders, so they never walk OneDrive,
Documents, or `node_modules`.

### Candidate roots by OS (Tier 2)

| OS | Probed candidates (first valid wins) |
|---|---|
| **Windows** | `%LOCALAPPDATA%\Packages\Claude_*\LocalCache\Roaming\Claude\local-agent-mode-sessions`, `%LOCALAPPDATA%\AnthropicClaude\…`, `%LOCALAPPDATA%\Claude\…`, `%APPDATA%\Claude\…` |
| **macOS** | `~/Library/Application Support/Claude/local-agent-mode-sessions` |
| **Linux** | `~/.config/Claude/local-agent-mode-sessions` |

### Validation predicate

A candidate is "real" only if it exists **and** a bounded scan finds ≥1
transcript artifact beneath it. The scan short-circuits at the first hit (lazy
`rglob` + `next()` in Python; `Get-ChildItem | Select -First 1` in PowerShell),
so validation is cheap even over the ~6,000-entry Desktop tree.

### Standalone use

```powershell
pwsh -File Resolve-CoworkSessionsDir.ps1     # prints the resolved path + timing
```
```python
from cowork_sync import resolve_sessions_dir
print(resolve_sessions_dir())                # or resolve_sessions_dir(refresh=True)
```

---

## Quick reference

```text
Desktop "</> Code"  →  <app-data>/Claude/local-agent-mode-sessions/**/audit.jsonl
Claude Code CLI     →  ~/.claude/projects/<cwd-slug>/<session-uuid>.jsonl

Windows app-data    →  %LOCALAPPDATA%\Packages\Claude_<hash>\LocalCache\Roaming
macOS app-data      →  ~/Library/Application Support
Linux app-data      →  ~/.config

Stable anchor       →  dir named "local-agent-mode-sessions" + audit.jsonl beneath
Never key on        →  package version · publisher hash · intermediate path ·
                       folder prefix (local_/ditto_/local_ditto_/bare) · depth
```
