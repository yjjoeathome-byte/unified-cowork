#!/usr/bin/env python3
"""
cowork_sync.py — Automated Claude Cowork session backup + distillation pipeline.

Discovers Cowork session transcripts (audit.jsonl files), copies them to an
output directory (local or SMB/NAS), and distills each into a clean Markdown
transcript. Optionally tags sessions with project keywords.

Reads all configuration from config.json (co-located with this script).
Run with --dry-run to preview without writing anything.

Requires: Python 3.8+ (stdlib only, no pip dependencies)
Config:   config.json (copy config.example.json and edit)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

FORMAT_VERSION = "2026-02"


# ============================================================================
# Colored terminal output
# ============================================================================
class TermColor:
    """Cross-platform colored output. Falls back to plain text when
    the output stream is not a TTY or on older Windows without VT support."""

    _CODES = {
        "green": "\033[32m",
        "yellow": "\033[33m",
        "red": "\033[31m",
        "cyan": "\033[36m",
        "darkcyan": "\033[36m",
        "white": "\033[97m",
        "gray": "\033[90m",
        "reset": "\033[0m",
    }

    def __init__(self) -> None:
        self.enabled = sys.stdout.isatty()
        if self.enabled and platform.system() == "Windows":
            # Enable VT100 sequences on Windows 10+
            try:
                import ctypes
                kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
                kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
            except Exception:
                self.enabled = False

    def _wrap(self, color: str, text: str) -> str:
        if not self.enabled:
            return text
        return f"{self._CODES.get(color, '')}{text}{self._CODES['reset']}"

    def ok(self, msg: str) -> None:
        print(self._wrap("green", f"[+] {msg}"))

    def dry(self, msg: str) -> None:
        print(self._wrap("yellow", f"[DRY] {msg}"))

    def warn(self, msg: str) -> None:
        print(self._wrap("yellow", f"[~] {msg}"))

    def error(self, msg: str) -> None:
        print(self._wrap("red", f"[!] {msg}"))

    def info(self, msg: str) -> None:
        print(self._wrap("darkcyan", f"[i] {msg}"))

    def status(self, msg: str) -> None:
        print(self._wrap("white", f"[*] {msg}"))

    def heading(self, msg: str) -> None:
        print(self._wrap("cyan", msg))

    def plain(self, msg: str) -> None:
        print(msg)

    def gray(self, msg: str) -> None:
        print(self._wrap("gray", f"[=] {msg}"))


tc = TermColor()
warning_count = 0


# ============================================================================
# Path expansion
# ============================================================================
def expand_path(p: str) -> str:
    """Expand ~ and %VAR% (Windows env vars) in a path string."""
    if not p:
        return p
    # Windows: expand %APPDATA% etc.
    if platform.system() == "Windows":
        p = os.path.expandvars(p)
    # All platforms: expand ~
    if p.startswith("~"):
        p = os.path.expanduser(p)
    return p


# ============================================================================
# Config loading
# ============================================================================
def load_config(config_file: str) -> dict:
    """Parse config.json, expand paths, validate required fields, merge format defaults."""
    if not os.path.isfile(config_file):
        example_path = os.path.join(os.path.dirname(config_file), "config.example.json")
        tc.error(f"Config file not found: {config_file}")
        if os.path.isfile(example_path):
            tc.warn("Copy config.example.json to config.json and edit it:")
            tc.warn("  cp config.example.json config.json")
        sys.exit(1)

    with open(config_file, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    # Expand env variables / tilde in path fields
    for key in ("sessions_dir", "output_dir", "state_file"):
        if key in cfg and cfg[key]:
            cfg[key] = expand_path(cfg[key])

    # Validate required fields
    for key in ("sessions_dir", "output_dir"):
        if not cfg.get(key):
            tc.error(f"Missing required config field: {key}")
            sys.exit(1)

    # Defaults for optional fields
    if not cfg.get("state_file"):
        if platform.system() == "Windows":
            cfg["state_file"] = os.path.join(
                os.environ.get("LOCALAPPDATA", ""), "cowork-sync-state.json"
            )
        else:
            cfg["state_file"] = os.path.expanduser(
                "~/.local/share/cowork-sync-state.json"
            )

    cfg.setdefault("project_tags", {})
    cfg.setdefault("format", {})

    # Format defaults
    fmt_defaults = {
        "session_dir_prefix": "local_",
        "transcript_filename": "audit.jsonl",
        "min_file_size_bytes": 1024,
        "expected_entry_types": [
            "system", "user", "assistant", "result", "tool_use_summary",
            "rate_limit_event",
        ],
        "expected_init_fields": [
            "session_id", "model", "cwd", "mcp_servers"
        ],
    }
    for k, v in fmt_defaults.items():
        cfg["format"].setdefault(k, v)

    return cfg


# ============================================================================
# Path validation (local + SMB/UNC)
# ============================================================================
def validate_output_path(path: str) -> bool:
    """Check UNC paths on Windows, parent existence on all platforms."""
    # UNC path check (Windows only)
    if path.startswith("\\\\"):
        parts = path.split("\\")
        # \\server\share -> parts = ['', '', 'server', 'share', ...]
        if len(parts) < 4 or not parts[2] or not parts[3]:
            tc.error(f"Invalid UNC path: {path}")
            tc.warn("  Expected format: \\\\server\\share\\path")
            return False
        server = parts[2]
        # Validate server name: reject shell metacharacters and path traversal
        if not re.match(r'^[a-zA-Z0-9._-]+$', server):
            tc.error(f"Invalid characters in UNC server name: {server}")
            return False
        # Attempt a lightweight connectivity check (subprocess, not shell)
        try:
            ping_args = (
                ["ping", "-n", "1", "-w", "3000", server]
                if platform.system() == "Windows"
                else ["ping", "-c", "1", "-W", "3", server]
            )
            ret = subprocess.run(
                ping_args, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, timeout=10
            ).returncode
        except (subprocess.TimeoutExpired, FileNotFoundError):
            ret = 1
        if ret != 0:
            tc.error(f"Cannot reach server: {server}")
            tc.warn(
                "  Check that the NAS/server is online and the SMB share is accessible."
            )
            return False

    # Parent directory check
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        tc.error(f"Parent path does not exist: {parent}")
        return False

    return True


# ============================================================================
# Format detection and validation
# ============================================================================
def validate_session_format(sessions_dir: str, fmt_cfg: dict) -> dict:
    """Validate that the session directory structure and JSONL content
    match expectations. Returns dict with 'issues' and 'hints' lists."""
    issues: list[str] = []
    hints: list[str] = []

    # --- Check if sessions_dir exists ---
    if not os.path.isdir(sessions_dir):
        issues.append(f"Sessions directory not found: {sessions_dir}")

        # Suggest alternative paths
        home = os.path.expanduser("~")
        if platform.system() == "Windows":
            base = os.environ.get("APPDATA", "")
            alternatives = [
                os.path.join(base, "Claude", "local-agent-mode-sessions"),
                os.path.join(base, "Claude", "claude-code-sessions"),
                os.path.join(base, "Claude Desktop", "sessions"),
                os.path.join(base, "Claude", "sessions"),
            ]
        elif platform.system() == "Darwin":
            base = os.path.join(home, "Library", "Application Support")
            alternatives = [
                os.path.join(base, "Claude", "local-agent-mode-sessions"),
                os.path.join(base, "Claude", "claude-code-sessions"),
                os.path.join(base, "Claude", "sessions"),
            ]
        else:
            alternatives = [
                os.path.join(home, ".config", "Claude", "local-agent-mode-sessions"),
                os.path.join(home, ".config", "Claude", "claude-code-sessions"),
                os.path.join(home, ".config", "Claude", "sessions"),
            ]

        found = [a for a in alternatives if os.path.isdir(a)]
        if found:
            hints.append("Found session data at alternative path(s):")
            for f in found:
                jsonl_count = sum(
                    1 for _ in Path(f).rglob("*.jsonl")
                )
                hints.append(f"  {f}")
                hints.append(f"  ({jsonl_count} .jsonl files found)")
            hints.append(
                "Update sessions_dir in config.json if Anthropic moved the storage location."
            )
        else:
            hints.append("No Claude session directories found in expected locations.")
            hints.append(
                "Cowork may not have been used yet, or the storage location has changed."
            )

        return {"issues": issues, "hints": hints}

    # --- Check for expected directory structure ---
    target_file = fmt_cfg["transcript_filename"]

    # Find all transcript files recursively
    transcripts = list(Path(sessions_dir).rglob(target_file))

    if not transcripts:
        issues.append(f"No '{target_file}' files found under {sessions_dir}")

        # Look for any JSONL files
        any_jsonl = list(Path(sessions_dir).rglob("*.jsonl"))
        if any_jsonl:
            names = sorted({f.name for f in any_jsonl[:5]})
            hints.append(f"Found .jsonl files with different names: {', '.join(names)}")
            hints.append("Anthropic may have renamed the transcript file.")
            hints.append("Update format.transcript_filename in config.json.")

        any_json = list(Path(sessions_dir).rglob("*.json"))
        if any_json and not any_jsonl:
            hints.append(
                "Found .json files (not .jsonl). Format may have changed to single-object JSON."
            )
            hints.append("This script currently expects JSONL (one JSON object per line).")

        return {"issues": issues, "hints": hints}

    # --- Validate nesting structure ---
    prefix = fmt_cfg["session_dir_prefix"]
    sample = transcripts[0]
    session_dir_name = sample.parent.name
    if not session_dir_name.startswith(prefix):
        issues.append(
            f"Session directory '{session_dir_name}' does not start with "
            f"expected prefix '{prefix}'"
        )
        hints.append("Anthropic may have changed the session folder naming convention.")
        hints.append("Update format.session_dir_prefix in config.json.")

    # --- Validate JSONL content of a sample file ---
    min_size = fmt_cfg["min_file_size_bytes"]
    sample_file = None
    for t in transcripts:
        if t.stat().st_size >= min_size:
            sample_file = t
            break

    if sample_file:
        found_types: list[str] = []
        found_init_fields: list[str] = []
        with open(sample_file, "r", encoding="utf-8") as f:
            for i, raw_line in enumerate(f):
                if i >= 20:
                    break
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                try:
                    obj = json.loads(raw_line)
                except json.JSONDecodeError as e:
                    issues.append(
                        f"Failed to parse JSONL line in {sample_file.name}: {e}"
                    )
                    hints.append("The transcript file format may no longer be JSONL.")
                    break

                entry_type = obj.get("type", "")
                if entry_type:
                    found_types.append(entry_type)

                if entry_type == "system" and obj.get("subtype") == "init":
                    for field in fmt_cfg["expected_init_fields"]:
                        if field in obj:
                            found_init_fields.append(field)

        # Check for unexpected types
        expected_types = set(fmt_cfg["expected_entry_types"])
        if found_types:
            unexpected = sorted({t for t in found_types if t not in expected_types})
            if unexpected:
                hints.append(f"Found unexpected entry types: {', '.join(unexpected)}")
                hints.append(
                    "These may be new Cowork features. The script will skip entries it doesn't recognize."
                )

        # Check init fields
        expected_init = set(fmt_cfg["expected_init_fields"])
        if found_init_fields:
            missing_init = sorted(expected_init - set(found_init_fields))
            if missing_init:
                hints.append(
                    f"Init block missing expected fields: {', '.join(missing_init)}"
                )
                hints.append("Session metadata extraction may be incomplete.")

    return {"issues": issues, "hints": hints}


# ============================================================================
# SHA256 hashing
# ============================================================================
def file_sha256(filepath: str) -> str:
    """Compute SHA256 hash of a file. Uppercased for PowerShell state compat."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest().upper()


# ============================================================================
# Discover pending sessions
# ============================================================================
def get_pending_sessions(
    sessions_dir: str, fmt_cfg: dict, state: dict, force: bool
) -> list[dict]:
    """Find new/changed sessions via SHA256 state comparison."""
    global warning_count
    target_file = fmt_cfg["transcript_filename"]
    prefix = fmt_cfg["session_dir_prefix"]
    min_size = fmt_cfg["min_file_size_bytes"]

    transcripts = list(Path(sessions_dir).rglob(target_file))

    pending = []
    for t in transcripts:
        if t.stat().st_size < min_size:
            continue

        file_hash = file_sha256(str(t))

        # Extract session UUID from parent folder name
        session_folder = t.parent.name
        session_uuid = session_folder
        if session_folder.startswith(prefix):
            session_uuid = session_folder[len(prefix):]

        # Sanitize UUID: reject path traversal, absolute paths, URL-encoded sequences
        session_uuid = session_uuid.replace("%2F", "/").replace("%2f", "/")
        session_uuid = session_uuid.replace("%5C", "\\").replace("%5c", "\\")
        if (".." in session_uuid
                or os.sep in session_uuid
                or "/" in session_uuid
                or session_uuid.startswith(os.sep)
                or os.path.isabs(session_uuid)):
            tc.warn(f"  Skipping session with suspicious UUID: {session_folder}")
            warning_count += 1
            continue

        key = session_uuid
        if force or key not in state or state[key] != file_hash:
            pending.append({
                "file": t,
                "hash": file_hash,
                "key": key,
                "session_uuid": session_uuid,
            })

    return pending


# ============================================================================
# Project tagging
# ============================================================================
def get_project_tags(text: str, tag_dictionary: dict) -> str:
    """Case-insensitive keyword substring matching. Returns comma-separated tags."""
    if not tag_dictionary:
        return "untagged"

    text_lower = text.lower()
    matched = []
    for project, keywords in tag_dictionary.items():
        for keyword in keywords:
            if keyword.lower() in text_lower:
                matched.append(project)
                break

    if not matched:
        return "untagged"
    return ", ".join(sorted(matched))



# ============================================================================
# Markdown sanitization
# ============================================================================
def escape_md_table_cell(value: str) -> str:
    """Escape pipe characters and collapse newlines for Markdown table cells."""
    if not value:
        return value
    # Replace pipes with escaped version
    value = value.replace("|", "\\|")
    # Collapse newlines to spaces (newlines break table rows)
    value = re.sub(r'[\r\n]+', ' ', value)
    return value.strip()


def sanitize_tool_summary(summary: str) -> str:
    """Remove Markdown structural elements from tool summaries to prevent injection."""
    if not summary:
        return summary
    # Collapse newlines — tool summaries should be single-line in blockquotes
    summary = re.sub(r'[\r\n]+', ' ', summary)
    # Strip leading # that would create headings
    summary = re.sub(r'#+\s', '', summary)
    return summary.strip()

# ============================================================================
# Distill audit.jsonl -> Markdown
# ============================================================================
def distill_session(
    filepath: Path, session_uuid: str, tag_dictionary: dict, fmt_cfg: dict
) -> dict | None:
    """Parse a JSONL transcript and produce a distilled Markdown document."""
    global warning_count

    entries = []
    parse_errors = 0

    with open(filepath, "r", encoding="utf-8") as f:
        for raw_line in f:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            try:
                entries.append(json.loads(raw_line))
            except json.JSONDecodeError:
                parse_errors += 1
                if parse_errors >= 10:
                    tc.error(
                        f"    Too many parse errors ({parse_errors}) "
                        "— file may not be JSONL"
                    )
                    return None
                continue

    if not entries:
        return None

    if parse_errors > 0:
        tc.warn(f"    {parse_errors} unparseable lines skipped")
        warning_count += 1

    meta = {
        "session_id": session_uuid,
        "session_name": "",
        "model": "",
        "start_time": "",
        "end_time": "",
        "total_cost": 0.0,
        "turn_count": 0,
        "mcp_servers": [],
        "project_tags": "",
        "first_message": "",
    }

    md_parts: list[str] = []
    unknown_types: dict[str, int] = {}
    expected_types = set(fmt_cfg["expected_entry_types"])

    for entry in entries:
        entry_type = entry.get("type", "")
        subtype = entry.get("subtype", "")

        # --- Init block ---
        if entry_type == "system" and subtype == "init" and not meta["model"]:
            meta["model"] = entry.get("model", "")
            if not meta["start_time"] and "_audit_timestamp" in entry:
                meta["start_time"] = entry["_audit_timestamp"]
            cwd = entry.get("cwd", "")
            m = re.search(r"/sessions/(.+)", cwd)
            if m:
                name = m.group(1)
                # Sanitize: strip path traversal, NUL bytes, control chars
                name = name.replace("\x00", "").replace("\0", "")
                name = re.sub(r'[\x00-\x1f]', '', name)
                if ".." not in name and not os.path.isabs(name):
                    meta["session_name"] = name
            mcp = entry.get("mcp_servers", [])
            if isinstance(mcp, list):
                meta["mcp_servers"] = [
                    s.get("name", "") for s in mcp
                    if isinstance(s, dict) and s.get("status") == "connected"
                ]
            continue

        # --- Skip noise ---
        if entry_type == "system":
            continue

        # --- Tool summaries ---
        if entry_type == "tool_use_summary":
            summary = sanitize_tool_summary(entry.get("summary", ""))
            if summary:
                md_parts.append(f"> **Tool**: {summary}")
                md_parts.append("")
            continue

        # --- User message ---
        if entry_type == "user" and "message" in entry:
            content = ""
            msg = entry["message"]

            if isinstance(msg, dict) and "content" in msg:
                msg_content = msg["content"]
                if isinstance(msg_content, str):
                    content = msg_content
                elif isinstance(msg_content, list):
                    parts_text = []
                    for part in msg_content:
                        if not isinstance(part, dict):
                            continue
                        if "text" in part:
                            parts_text.append(part["text"])
                        if (
                            part.get("type") == "tool_result"
                            and part.get("is_error")
                        ):
                            tool_content = ""
                            raw_content = part.get("content", "")
                            if isinstance(raw_content, str):
                                try:
                                    parsed = json.loads(raw_content)
                                    if isinstance(parsed, dict) and "content" in parsed:
                                        tool_content = parsed["content"]
                                    else:
                                        tool_content = raw_content
                                except json.JSONDecodeError:
                                    tool_content = raw_content
                            if len(tool_content) > 500:
                                tool_content = (
                                    tool_content[:500] + "\n[... truncated ...]"
                                )
                            parts_text.append(
                                f"> **Tool Error**: `{tool_content}`"
                            )
                    content = "\n".join(parts_text)

            # Fallback: message is a plain string
            if not content and isinstance(msg, str):
                content = msg
            # Fallback: message.content is a plain string
            if (
                not content
                and isinstance(msg, dict)
                and isinstance(msg.get("content"), str)
            ):
                content = msg["content"]

            content = content.strip()
            if content:
                if meta["turn_count"] == 0:
                    summary = re.sub(r"\s+", " ", content).strip()
                    if len(summary) > 80:
                        summary = summary[:80] + "..."
                    meta["first_message"] = summary
                meta["turn_count"] += 1
                md_parts.append("---")
                md_parts.append("### User")
                md_parts.append("")
                md_parts.append(content)
                md_parts.append("")
            continue

        # --- Assistant message: text blocks only ---
        if entry_type == "assistant" and "message" in entry:
            msg = entry["message"]
            if isinstance(msg, dict):
                msg_content = msg.get("content", [])
                if isinstance(msg_content, list):
                    for block in msg_content:
                        if (
                            isinstance(block, dict)
                            and block.get("type") == "text"
                            and "text" in block
                        ):
                            text = block["text"].strip()
                            if text:
                                md_parts.append("### Claude")
                                md_parts.append("")
                                md_parts.append(text)
                                md_parts.append("")
            continue

        # --- Result block ---
        if entry_type == "result":
            cost = entry.get("total_cost_usd")
            if cost is not None:
                try:
                    meta["total_cost"] += float(cost)
                except (ValueError, TypeError):
                    pass
            if "_audit_timestamp" in entry:
                meta["end_time"] = entry["_audit_timestamp"]
            continue

        # --- Track unknown entry types ---
        if entry_type and entry_type not in expected_types:
            unknown_types[entry_type] = unknown_types.get(entry_type, 0) + 1

    # Warn about unknown types
    if unknown_types:
        type_list = ", ".join(
            f"{t}(\u00d7{c})" for t, c in sorted(unknown_types.items())
        )
        tc.warn(f"    Unknown entry types: {type_list}")
        tc.warn(
            "    Cowork format may have new features. These entries were skipped."
        )
        warning_count += 1

    transcript = "\n".join(md_parts).strip()
    if not transcript:
        return None

    meta["project_tags"] = get_project_tags(transcript, tag_dictionary)

    # --- Build final document ---
    session_label = meta["session_name"] or session_uuid[:8]
    short_id = (
        session_uuid[:8] + "..." if len(session_uuid) >= 8 else session_uuid
    )
    mcp_str = ", ".join(meta["mcp_servers"])
    cost_str = f"${round(meta['total_cost'], 4)}"

    header_lines = [
        f"# Session: {session_label}",
        "",
        "| Field | Value |",
        "|-------|-------|",
        f"| Model | `{escape_md_table_cell(meta['model'])}` |",
        f"| Session ID | `{short_id}` |",
        f"| Started | {meta['start_time']} |",
        f"| Ended | {meta['end_time']} |",
        f"| User turns | {meta['turn_count']} |",
        f"| Cost (USD) | {cost_str} |",
        f"| MCP servers | {escape_md_table_cell(mcp_str)} |",
        f"| Summary | {escape_md_table_cell(meta['first_message'])} |",
        f"| Projects | {escape_md_table_cell(meta['project_tags'])} |",
        f"| Format version | {FORMAT_VERSION} |",
        "",
    ]

    return {
        "markdown": "\n".join(header_lines) + transcript,
        "meta": meta,
        "session_name": session_label,
    }


# ============================================================================
# Update session index
# ============================================================================
def update_index(
    index_entries: list[dict], index_file: str, dry_run: bool
) -> None:
    """Rebuild SESSION-INDEX.md with existing + new entries."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = (
        "# Session Index\n"
        "\n"
        "Auto-generated by cowork-session-sync. Newest first.\n"
        f"Last updated: {now}\n"
        "\n"
        "| Date | Session | Summary | Project(s) | Model | Turns | Cost | Files |\n"
        "|------|---------|---------|------------|-------|-------|------|-------|\n"
    )

    # Sort newest first
    sorted_entries = sorted(index_entries, key=lambda e: e.get("date", ""), reverse=True)
    rows = []
    for e in sorted_entries:
        file_links = f"[distilled]({e['distilled_file']})"
        if e.get("raw_file"):
            file_links += f" / [raw]({e['raw_file']})"
        # Escape pipe characters in user-sourced values
        esc = escape_md_table_cell
        rows.append(
            f"| {esc(e['date'])} | {esc(e['session_name'])} | {esc(e.get('first_message', ''))} "
            f"| {esc(e['project_tags'])} "
            f"| {esc(e['model'])} | {e['turns']} | ${e['cost']} | {file_links} |"
        )

    content = header + "\n".join(rows) + "\n"

    if dry_run:
        tc.dry(f"Would write index to: {index_file}")
    else:
        with open(index_file, "w", encoding="utf-8") as f:
            f.write(content)
        tc.info(f"Updated index: {index_file}")


# ============================================================================
# State load/save
# ============================================================================
def load_state(path: str) -> dict:
    if os.path.isfile(path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict, path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


# ============================================================================
# Main
# ============================================================================
def main() -> None:
    global warning_count

    parser = argparse.ArgumentParser(
        description="Cowork Session Sync — backup and distill Claude Cowork sessions."
    )
    parser.add_argument(
        "-c", "--config",
        default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json"),
        help="Path to config file (default: config.json next to this script)",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Reprocess all sessions regardless of state",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview without writing anything",
    )
    parser.add_argument(
        "--check", action="store_true",
        help="Validate config and session format, then exit",
    )
    args = parser.parse_args()

    tc.heading("=== Cowork Session Sync ===")

    # --- Load config ---
    cfg = load_config(args.config)
    sessions_dir = cfg["sessions_dir"]
    output_dir = cfg["output_dir"]
    state_file = cfg["state_file"]
    project_tags = cfg["project_tags"]
    fmt_cfg = cfg["format"]

    archive_dir = os.path.join(output_dir, "raw")
    distilled_dir = os.path.join(output_dir, "distilled")
    index_file = os.path.join(output_dir, "SESSION-INDEX.md")

    tc.plain(f"Source:    {sessions_dir}")
    tc.plain(f"Output:    {output_dir}")
    print()

    # --- Validate output path ---
    if not validate_output_path(output_dir):
        sys.exit(1)

    # --- Validate session format ---
    validation = validate_session_format(sessions_dir, fmt_cfg)
    if validation["issues"]:
        print()
        tc.error("FORMAT ISSUES DETECTED")
        tc.error("The Cowork session storage format may have changed.")
        print()
        for issue in validation["issues"]:
            tc.error(f"  ISSUE: {issue}")
        for hint in validation["hints"]:
            tc.warn(f"  HINT:  {hint}")
        print()
        tc.warn("Config knobs to adjust (in config.json -> format section):")
        tc.warn(f"  sessions_dir               — where Cowork stores sessions")
        tc.warn(
            f"  format.session_dir_prefix  — folder name prefix "
            f"(currently: '{fmt_cfg['session_dir_prefix']}')"
        )
        tc.warn(
            f"  format.transcript_filename — transcript file name "
            f"(currently: '{fmt_cfg['transcript_filename']}')"
        )
        sys.exit(1)

    if validation["hints"]:
        for hint in validation["hints"]:
            tc.warn(hint)
        warning_count += 1

    if args.check:
        transcript_count = len(list(Path(sessions_dir).rglob(fmt_cfg["transcript_filename"])))
        tc.ok("Config valid, session format recognized.")
        tc.ok(f"  {transcript_count} session transcript(s) found.")
        tc.ok(f"  {len(project_tags)} project tag rule(s) configured.")
        sys.exit(0)

    # --- Ensure output dirs ---
    for d in (archive_dir, distilled_dir):
        if not os.path.isdir(d):
            if args.dry_run:
                tc.dry(f"Would create: {d}")
            else:
                os.makedirs(d, exist_ok=True)
                tc.ok(f"Created: {d}")

    # --- Discover sessions ---
    state = load_state(state_file)
    pending = get_pending_sessions(sessions_dir, fmt_cfg, state, args.force)

    if not pending:
        tc.gray("No new or modified sessions.")
        sys.exit(0)

    tc.status(f"Found {len(pending)} session(s) to process")
    index_entries: list[dict] = []

    for item in pending:
        filepath: Path = item["file"]
        size_kb = round(filepath.stat().st_size / 1024, 1)
        print()
        tc.status(f"Processing: {item['session_uuid']} ({size_kb} KB)")

        # --- Distill ---
        result = distill_session(
            filepath, item["session_uuid"], project_tags, fmt_cfg
        )
        session_name = (
            result["session_name"] if result else item["session_uuid"][:8]
        )

        # --- Copy raw ---
        mtime = datetime.fromtimestamp(filepath.stat().st_mtime)
        date_prefix = mtime.strftime("%Y-%m-%d")
        raw_name = f"{date_prefix}_{session_name}.jsonl"
        raw_dest = os.path.join(archive_dir, raw_name)

        if args.dry_run:
            tc.dry(f"  Would copy raw -> {raw_dest}")
        else:
            shutil.copy2(str(filepath), raw_dest)
            tc.ok(f"  Raw archived -> {raw_dest}")

        # --- Write distilled ---
        if result is None:
            tc.warn(
                "  Empty or unparseable — raw archived, distillation skipped"
            )
            state[item["key"]] = item["hash"]
            continue

        distilled_name = f"{date_prefix}_{session_name}.md"
        distilled_dest = os.path.join(distilled_dir, distilled_name)

        if args.dry_run:
            tc.dry(f"  Would write distilled -> {distilled_dest}")
            tc.dry(
                f"  Turns: {result['meta']['turn_count']}, "
                f"Cost: ${round(result['meta']['total_cost'], 4)}, "
                f"Tags: {result['meta']['project_tags']}"
            )
        else:
            with open(distilled_dest, "w", encoding="utf-8") as f:
                f.write(result["markdown"])
            tc.ok(f"  Distilled -> {distilled_dest}")

            distilled_size = round(os.path.getsize(distilled_dest) / 1024, 1)
            ratio = round((distilled_size / size_kb) * 100) if size_kb > 0 else 0
            tc.info(f"  {size_kb} KB raw -> {distilled_size} KB distilled ({ratio}%)")
            tc.info(f"  Tags: {result['meta']['project_tags']}")

        index_entries.append({
            "date": date_prefix,
            "session_name": session_name,
            "model": result["meta"]["model"],
            "turns": result["meta"]["turn_count"],
            "cost": round(result["meta"]["total_cost"], 4),
            "project_tags": result["meta"]["project_tags"],
            "first_message": result["meta"]["first_message"],
            "distilled_file": f"distilled/{distilled_name}",
            "raw_file": f"raw/{raw_name}",
        })

        state[item["key"]] = item["hash"]

    # --- Rebuild index: include existing distilled files ---
    distilled_path = Path(distilled_dir)
    if distilled_path.is_dir():
        for df in sorted(distilled_path.glob("*.md")):
            rel = f"distilled/{df.name}"
            already = any(e["distilled_file"] == rel for e in index_entries)
            if already:
                continue

            # Parse header from existing distilled file
            model = turns = cost = tags = summary = ""
            with open(df, "r", encoding="utf-8") as f:
                for i, line in enumerate(f):
                    if i >= 20:
                        break
                    m_model = re.match(r"^\| Model \| `(.+)` \|", line)
                    if m_model:
                        model = m_model.group(1)
                    m_turns = re.match(r"^\| User turns \| (\d+) \|", line)
                    if m_turns:
                        turns = m_turns.group(1)
                    m_cost = re.match(r"^\| Cost .+ \| \$(.+) \|", line)
                    if m_cost:
                        cost = m_cost.group(1)
                    m_summary = re.match(r"^\| Summary \| (.+) \|", line)
                    if m_summary:
                        summary = m_summary.group(1).strip()
                    m_tags = re.match(r"^\| Projects \| (.+) \|", line)
                    if m_tags:
                        tags = m_tags.group(1).strip()

            date_match = re.match(r"^(\d{4}-\d{2}-\d{2})", df.name)
            date_part = date_match.group(1) if date_match else ""
            name_part = re.sub(r"^\d{4}-\d{2}-\d{2}_", "", df.stem)

            index_entries.append({
                "date": date_part,
                "session_name": name_part,
                "model": model,
                "turns": turns,
                "cost": cost,
                "project_tags": tags,
                "first_message": summary,
                "distilled_file": rel,
                "raw_file": "",
            })

    update_index(index_entries, index_file, args.dry_run)

    if not args.dry_run:
        save_state(state, state_file)

    print()
    if warning_count > 0:
        tc.warn(f"=== Done ({warning_count} warning(s)) ===")
    else:
        tc.heading("=== Done ===")


if __name__ == "__main__":
    main()
