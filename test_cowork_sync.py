#!/usr/bin/env python3
"""Unit tests for cowork_sync.py — stdlib only (unittest + tempfile)."""

from __future__ import annotations

import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Import the module under test
import cowork_sync as cs


def _suppress_output():
    """Context-manager-free stdout suppression for setUp."""
    return patch("sys.stdout", new_callable=io.StringIO)


def _make_jsonl(entries: list[dict]) -> str:
    """Serialize a list of dicts into JSONL text."""
    return "\n".join(json.dumps(e) for e in entries) + "\n"


# Default format config matching production defaults
DEFAULT_FMT = {
    "session_dir_prefix": "local_",
    "transcript_filename": "audit.jsonl",
    "min_file_size_bytes": 10,
    "expected_entry_types": [
        "system", "user", "assistant", "result",
        "tool_use_summary", "rate_limit_event",
    ],
    "expected_init_fields": [
        "session_id", "model", "cwd", "mcp_servers",
    ],
}


# ============================================================================
# TestExpandPath
# ============================================================================
class TestExpandPath(unittest.TestCase):
    def test_tilde_expansion(self):
        result = cs.expand_path("~/Documents")
        self.assertFalse(result.startswith("~"))
        self.assertTrue(os.path.isabs(result))

    def test_empty_input(self):
        self.assertEqual(cs.expand_path(""), "")

    def test_absolute_path_unchanged(self):
        self.assertEqual(cs.expand_path("/usr/local/bin"), "/usr/local/bin")


# ============================================================================
# TestLoadConfig
# ============================================================================
class TestLoadConfig(unittest.TestCase):
    def test_valid_config(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = os.path.join(td, "config.json")
            with open(cfg_path, "w") as f:
                json.dump({
                    "sessions_dir": "/tmp/sessions",
                    "output_dir": "/tmp/output",
                }, f)

            with _suppress_output():
                cfg = cs.load_config(cfg_path)

            self.assertEqual(cfg["sessions_dir"], "/tmp/sessions")
            self.assertEqual(cfg["output_dir"], "/tmp/output")
            # Format defaults should be merged
            self.assertEqual(cfg["format"]["session_dir_prefix"], "local_")
            self.assertEqual(cfg["format"]["transcript_filename"], "audit.jsonl")
            self.assertIn("expected_entry_types", cfg["format"])
            self.assertIn("expected_init_fields", cfg["format"])
            self.assertIsInstance(cfg["project_tags"], dict)

    def test_missing_file_exits(self):
        with _suppress_output():
            with self.assertRaises(SystemExit) as ctx:
                cs.load_config("/nonexistent/config.json")
        self.assertEqual(ctx.exception.code, 1)

    def test_missing_sessions_dir_exits(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = os.path.join(td, "config.json")
            with open(cfg_path, "w") as f:
                json.dump({"output_dir": "/tmp/output"}, f)

            with _suppress_output():
                with self.assertRaises(SystemExit) as ctx:
                    cs.load_config(cfg_path)
            self.assertEqual(ctx.exception.code, 1)

    def test_missing_output_dir_exits(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = os.path.join(td, "config.json")
            with open(cfg_path, "w") as f:
                json.dump({"sessions_dir": "/tmp/sessions"}, f)

            with _suppress_output():
                with self.assertRaises(SystemExit) as ctx:
                    cs.load_config(cfg_path)
            self.assertEqual(ctx.exception.code, 1)

    def test_format_defaults_merged_with_user_overrides(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = os.path.join(td, "config.json")
            with open(cfg_path, "w") as f:
                json.dump({
                    "sessions_dir": "/tmp/s",
                    "output_dir": "/tmp/o",
                    "format": {"session_dir_prefix": "custom_"},
                }, f)

            with _suppress_output():
                cfg = cs.load_config(cfg_path)

            self.assertEqual(cfg["format"]["session_dir_prefix"], "custom_")
            # Other defaults still present
            self.assertEqual(cfg["format"]["transcript_filename"], "audit.jsonl")

    def test_tilde_expanded_in_paths(self):
        with tempfile.TemporaryDirectory() as td:
            cfg_path = os.path.join(td, "config.json")
            with open(cfg_path, "w") as f:
                json.dump({
                    "sessions_dir": "~/sessions",
                    "output_dir": "~/output",
                    "state_file": "~/state.json",
                }, f)

            with _suppress_output():
                cfg = cs.load_config(cfg_path)

            for key in ("sessions_dir", "output_dir", "state_file"):
                self.assertFalse(cfg[key].startswith("~"), f"{key} still has tilde")


# ============================================================================
# TestFileHash
# ============================================================================
class TestFileHash(unittest.TestCase):
    def test_known_content(self):
        with tempfile.NamedTemporaryFile(mode="wb", delete=False, suffix=".txt") as f:
            f.write(b"hello world\n")
            f.flush()
            path = f.name

        try:
            result = cs.file_sha256(path)
            expected = hashlib.sha256(b"hello world\n").hexdigest().upper()
            self.assertEqual(result, expected)
        finally:
            os.unlink(path)

    def test_empty_file(self):
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            path = f.name

        try:
            result = cs.file_sha256(path)
            expected = hashlib.sha256(b"").hexdigest().upper()
            self.assertEqual(result, expected)
        finally:
            os.unlink(path)

    def test_result_is_uppercase(self):
        with tempfile.NamedTemporaryFile(mode="wb", delete=False) as f:
            f.write(b"test")
            path = f.name

        try:
            result = cs.file_sha256(path)
            self.assertEqual(result, result.upper())
        finally:
            os.unlink(path)


# ============================================================================
# TestGetProjectTags
# ============================================================================
class TestGetProjectTags(unittest.TestCase):
    def test_empty_dict_returns_untagged(self):
        self.assertEqual(cs.get_project_tags("anything", {}), "untagged")

    def test_single_match(self):
        tags = {"backend": ["django", "flask"]}
        self.assertEqual(cs.get_project_tags("using django here", tags), "backend")

    def test_multi_match_sorted(self):
        tags = {"zeta": ["zzz"], "alpha": ["aaa"]}
        result = cs.get_project_tags("aaa and zzz", tags)
        self.assertEqual(result, "alpha, zeta")

    def test_case_insensitive(self):
        tags = {"web": ["React"]}
        self.assertEqual(cs.get_project_tags("I love REACT", tags), "web")

    def test_no_match_returns_untagged(self):
        tags = {"infra": ["terraform"]}
        self.assertEqual(cs.get_project_tags("nothing relevant", tags), "untagged")

    def test_first_keyword_match_wins_per_project(self):
        """Only one match per project, even if multiple keywords match."""
        tags = {"web": ["react", "nextjs"]}
        result = cs.get_project_tags("react and nextjs together", tags)
        self.assertEqual(result, "web")


# ============================================================================
# TestDistillSession
# ============================================================================
class TestDistillSession(unittest.TestCase):
    def _write_jsonl(self, td, entries):
        """Write entries to a JSONL file in td and return Path."""
        fp = os.path.join(td, "audit.jsonl")
        with open(fp, "w", encoding="utf-8") as f:
            f.write(_make_jsonl(entries))
        return Path(fp)

    def test_full_session(self):
        entries = [
            {
                "type": "system", "subtype": "init",
                "model": "claude-opus-4-20250514",
                "session_id": "abc123",
                "cwd": "/home/user/sessions/my-project",
                "mcp_servers": [
                    {"name": "mcp-git", "status": "connected"},
                    {"name": "mcp-docker", "status": "disconnected"},
                ],
                "_audit_timestamp": "2026-02-20T10:00:00Z",
            },
            {
                "type": "user",
                "message": {"content": "Hello Claude"},
            },
            {
                "type": "assistant",
                "message": {"content": [
                    {"type": "text", "text": "Hi there!"},
                ]},
            },
            {
                "type": "tool_use_summary",
                "summary": "Read file: main.py",
            },
            {
                "type": "result",
                "total_cost_usd": 0.05,
                "_audit_timestamp": "2026-02-20T10:05:00Z",
            },
        ]

        with tempfile.TemporaryDirectory() as td:
            fp = self._write_jsonl(td, entries)
            with _suppress_output():
                result = cs.distill_session(fp, "abc123def456", {}, DEFAULT_FMT)

        self.assertIsNotNone(result)
        md = result["markdown"]
        meta = result["meta"]

        # Metadata header
        self.assertIn("# Session:", md)
        self.assertIn("claude-opus-4-20250514", md)
        self.assertIn("abc123de...", md)
        self.assertIn("2026-02-20T10:00:00Z", md)
        self.assertIn("2026-02-20T10:05:00Z", md)
        self.assertIn("mcp-git", md)
        self.assertNotIn("mcp-docker", md)  # disconnected

        # Content
        self.assertIn("### User", md)
        self.assertIn("Hello Claude", md)
        self.assertIn("### Claude", md)
        self.assertIn("Hi there!", md)
        self.assertIn("> **Tool**: Read file: main.py", md)

        # Summary row in header
        self.assertIn("| Summary | Hello Claude |", md)

        # Meta
        self.assertEqual(meta["model"], "claude-opus-4-20250514")
        self.assertEqual(meta["turn_count"], 1)
        self.assertAlmostEqual(meta["total_cost"], 0.05)
        self.assertEqual(meta["first_message"], "Hello Claude")

    def test_empty_file_returns_none(self):
        with tempfile.TemporaryDirectory() as td:
            fp = os.path.join(td, "audit.jsonl")
            with open(fp, "w") as f:
                f.write("")
            with _suppress_output():
                result = cs.distill_session(Path(fp), "x", {}, DEFAULT_FMT)

        self.assertIsNone(result)

    def test_unknown_types_tracked(self):
        entries = [
            {"type": "user", "message": {"content": "test"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "reply"}]}},
            {"type": "brand_new_type", "data": "something"},
            {"type": "brand_new_type", "data": "again"},
        ]

        with tempfile.TemporaryDirectory() as td:
            fp = self._write_jsonl(td, entries)
            with _suppress_output():
                result = cs.distill_session(fp, "uuid1", {}, DEFAULT_FMT)

        self.assertIsNotNone(result)
        # The function should still produce output, just warn about unknown types

    def test_tool_error_extracted_and_truncated(self):
        long_error = "E" * 1000
        entries = [
            {
                "type": "user",
                "message": {"content": [
                    {"type": "tool_result", "is_error": True, "content": long_error},
                    {"text": "got an error", "type": "text"},
                ]},
            },
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "sorry"}]}},
        ]

        with tempfile.TemporaryDirectory() as td:
            fp = self._write_jsonl(td, entries)
            with _suppress_output():
                result = cs.distill_session(fp, "uuid2", {}, DEFAULT_FMT)

        self.assertIsNotNone(result)
        md = result["markdown"]
        self.assertIn("Tool Error", md)
        self.assertIn("[... truncated ...]", md)
        # The 1000-char error should be cut to 500
        self.assertNotIn("E" * 600, md)

    def test_project_tags_applied(self):
        entries = [
            {"type": "user", "message": {"content": "fix the django model"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "done"}]}},
        ]
        tags = {"backend": ["django"], "frontend": ["react"]}

        with tempfile.TemporaryDirectory() as td:
            fp = self._write_jsonl(td, entries)
            with _suppress_output():
                result = cs.distill_session(fp, "uuid3", tags, DEFAULT_FMT)

        self.assertIsNotNone(result)
        self.assertEqual(result["meta"]["project_tags"], "backend")

    def test_user_message_plain_string(self):
        """User message can be a plain string (not a dict)."""
        entries = [
            {"type": "user", "message": "plain string message"},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}},
        ]

        with tempfile.TemporaryDirectory() as td:
            fp = self._write_jsonl(td, entries)
            with _suppress_output():
                result = cs.distill_session(fp, "uuid4", {}, DEFAULT_FMT)

        self.assertIsNotNone(result)
        self.assertIn("plain string message", result["markdown"])

    def test_first_message_captured(self):
        """first_message is set from the first user turn only."""
        entries = [
            {"type": "user", "message": {"content": "First question"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "a1"}]}},
            {"type": "user", "message": {"content": "Second question"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "a2"}]}},
        ]

        with tempfile.TemporaryDirectory() as td:
            fp = self._write_jsonl(td, entries)
            with _suppress_output():
                result = cs.distill_session(fp, "uuid_fm", {}, DEFAULT_FMT)

        self.assertEqual(result["meta"]["first_message"], "First question")

    def test_first_message_truncated_at_80_chars(self):
        long_msg = "A" * 120
        entries = [
            {"type": "user", "message": {"content": long_msg}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}},
        ]

        with tempfile.TemporaryDirectory() as td:
            fp = self._write_jsonl(td, entries)
            with _suppress_output():
                result = cs.distill_session(fp, "uuid_trunc", {}, DEFAULT_FMT)

        fm = result["meta"]["first_message"]
        self.assertEqual(len(fm), 83)  # 80 + "..."
        self.assertTrue(fm.endswith("..."))

    def test_first_message_newlines_collapsed(self):
        entries = [
            {"type": "user", "message": {"content": "line one\nline two\nline three"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "ok"}]}},
        ]

        with tempfile.TemporaryDirectory() as td:
            fp = self._write_jsonl(td, entries)
            with _suppress_output():
                result = cs.distill_session(fp, "uuid_nl", {}, DEFAULT_FMT)

        self.assertEqual(result["meta"]["first_message"], "line one line two line three")

    def test_multiple_costs_summed(self):
        entries = [
            {"type": "user", "message": {"content": "q1"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "a1"}]}},
            {"type": "result", "total_cost_usd": 0.01},
            {"type": "user", "message": {"content": "q2"}},
            {"type": "assistant", "message": {"content": [{"type": "text", "text": "a2"}]}},
            {"type": "result", "total_cost_usd": 0.02},
        ]

        with tempfile.TemporaryDirectory() as td:
            fp = self._write_jsonl(td, entries)
            with _suppress_output():
                result = cs.distill_session(fp, "uuid5", {}, DEFAULT_FMT)

        self.assertAlmostEqual(result["meta"]["total_cost"], 0.03)


# ============================================================================
# TestGetPendingSessions
# ============================================================================
class TestGetPendingSessions(unittest.TestCase):
    def _setup_sessions(self, td, sessions):
        """Create session directories with audit.jsonl files.
        sessions: list of (uuid, content_bytes)
        Returns sessions_dir path.
        """
        sessions_dir = os.path.join(td, "sessions")
        for uuid, content in sessions:
            sdir = os.path.join(sessions_dir, f"local_{uuid}")
            os.makedirs(sdir)
            with open(os.path.join(sdir, "audit.jsonl"), "wb") as f:
                f.write(content)
        return sessions_dir

    def test_finds_new_sessions(self):
        content = b'{"type":"user","message":"hello"}\n' * 5
        with tempfile.TemporaryDirectory() as td:
            sd = self._setup_sessions(td, [("aaa", content), ("bbb", content)])
            pending = cs.get_pending_sessions(sd, DEFAULT_FMT, {}, False)

        self.assertEqual(len(pending), 2)
        uuids = {p["session_uuid"] for p in pending}
        self.assertEqual(uuids, {"aaa", "bbb"})

    def test_skips_below_min_size(self):
        small = b'{"t":1}\n'  # tiny
        big = b'{"type":"user","message":"hello"}\n' * 5

        fmt = {**DEFAULT_FMT, "min_file_size_bytes": 100}

        with tempfile.TemporaryDirectory() as td:
            sd = self._setup_sessions(td, [("small", small), ("big", big)])
            pending = cs.get_pending_sessions(sd, fmt, {}, False)

        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]["session_uuid"], "big")

    def test_skips_unchanged_hash(self):
        content = b'{"type":"user","message":"hello"}\n' * 5
        file_hash = hashlib.sha256(content).hexdigest().upper()

        with tempfile.TemporaryDirectory() as td:
            sd = self._setup_sessions(td, [("aaa", content)])
            state = {"aaa": file_hash}
            pending = cs.get_pending_sessions(sd, DEFAULT_FMT, state, False)

        self.assertEqual(len(pending), 0)

    def test_force_overrides_state(self):
        content = b'{"type":"user","message":"hello"}\n' * 5
        file_hash = hashlib.sha256(content).hexdigest().upper()

        with tempfile.TemporaryDirectory() as td:
            sd = self._setup_sessions(td, [("aaa", content)])
            state = {"aaa": file_hash}
            pending = cs.get_pending_sessions(sd, DEFAULT_FMT, state, True)

        self.assertEqual(len(pending), 1)

    def test_strips_prefix_from_uuid(self):
        content = b'{"type":"user","message":"hello"}\n' * 5

        with tempfile.TemporaryDirectory() as td:
            sd = self._setup_sessions(td, [("myuuid", content)])
            pending = cs.get_pending_sessions(sd, DEFAULT_FMT, {}, False)

        self.assertEqual(pending[0]["session_uuid"], "myuuid")


# ============================================================================
# TestValidateSessionFormat
# ============================================================================
class TestValidateSessionFormat(unittest.TestCase):
    def test_valid_dir_with_transcripts(self):
        entries = [
            {"type": "system", "subtype": "init", "session_id": "x",
             "model": "opus", "cwd": "/tmp", "mcp_servers": []},
            {"type": "user", "message": {"content": "hi"}},
        ]
        content = _make_jsonl(entries)

        with tempfile.TemporaryDirectory() as td:
            sdir = os.path.join(td, "local_abc123")
            os.makedirs(sdir)
            with open(os.path.join(sdir, "audit.jsonl"), "w") as f:
                f.write(content)

            with _suppress_output():
                result = cs.validate_session_format(td, DEFAULT_FMT)

        self.assertEqual(result["issues"], [])

    def test_missing_dir_returns_issue_with_hints(self):
        with _suppress_output():
            result = cs.validate_session_format(
                "/nonexistent/path/sessions", DEFAULT_FMT
            )

        self.assertTrue(len(result["issues"]) > 0)
        self.assertIn("not found", result["issues"][0])
        # Should have hints about alternative locations
        self.assertTrue(len(result["hints"]) > 0)

    def test_wrong_prefix_produces_issue(self):
        """Transcript exists but parent dir doesn't match expected prefix."""
        with tempfile.TemporaryDirectory() as td:
            sdir = os.path.join(td, "session_abc123")  # wrong prefix
            os.makedirs(sdir)
            content = _make_jsonl([{"type": "user", "message": "hi"}])
            with open(os.path.join(sdir, "audit.jsonl"), "w") as f:
                f.write(content)

            with _suppress_output():
                result = cs.validate_session_format(td, DEFAULT_FMT)

        prefix_issues = [i for i in result["issues"] if "prefix" in i.lower()]
        self.assertTrue(len(prefix_issues) > 0)

    def test_missing_transcript_filename(self):
        """Dir exists but no matching transcript files."""
        with tempfile.TemporaryDirectory() as td:
            sdir = os.path.join(td, "local_abc123")
            os.makedirs(sdir)
            # Write file with wrong name
            with open(os.path.join(sdir, "transcript.json"), "w") as f:
                f.write("{}")

            with _suppress_output():
                result = cs.validate_session_format(td, DEFAULT_FMT)

        self.assertTrue(len(result["issues"]) > 0)
        self.assertTrue(
            any("audit.jsonl" in i for i in result["issues"])
        )


# ============================================================================
# TestValidateOutputPath
# ============================================================================
class TestValidateOutputPath(unittest.TestCase):
    def test_existing_parent_returns_true(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "new_subdir")
            with _suppress_output():
                self.assertTrue(cs.validate_output_path(path))

    def test_missing_parent_returns_false(self):
        with _suppress_output():
            result = cs.validate_output_path(
                "/nonexistent/deeply/nested/path/output"
            )
        self.assertFalse(result)


# ============================================================================
# TestStatePersistence
# ============================================================================
class TestStatePersistence(unittest.TestCase):
    def test_save_then_load_roundtrip(self):
        state = {"abc123": "DEADBEEF", "xyz789": "CAFEBABE"}

        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "state.json")
            cs.save_state(state, path)
            loaded = cs.load_state(path)

        self.assertEqual(loaded, state)

    def test_load_missing_file_returns_empty_dict(self):
        result = cs.load_state("/nonexistent/state.json")
        self.assertEqual(result, {})

    def test_save_creates_parent_dirs(self):
        with tempfile.TemporaryDirectory() as td:
            path = os.path.join(td, "sub", "dir", "state.json")
            cs.save_state({"key": "val"}, path)
            self.assertTrue(os.path.isfile(path))


# ============================================================================
# TestUpdateIndex
# ============================================================================
class TestUpdateIndex(unittest.TestCase):
    def test_produces_valid_markdown_table(self):
        entries = [
            {
                "date": "2026-02-20",
                "session_name": "my-session",
                "model": "opus",
                "turns": 5,
                "cost": 0.12,
                "project_tags": "backend",
                "first_message": "Fix the login bug",
                "distilled_file": "distilled/2026-02-20_my-session.md",
                "raw_file": "raw/2026-02-20_my-session.jsonl",
            },
        ]

        with tempfile.TemporaryDirectory() as td:
            index_file = os.path.join(td, "SESSION-INDEX.md")
            with _suppress_output():
                cs.update_index(entries, index_file, dry_run=False)

            with open(index_file, "r") as f:
                content = f.read()

        self.assertIn("# Session Index", content)
        self.assertIn("| Date |", content)
        self.assertIn("| Summary |", content)
        self.assertIn("2026-02-20", content)
        self.assertIn("my-session", content)
        self.assertIn("Fix the login bug", content)
        self.assertIn("opus", content)
        self.assertIn("[distilled]", content)
        self.assertIn("[raw]", content)

    def test_sorted_newest_first(self):
        entries = [
            {
                "date": "2026-01-01", "session_name": "old",
                "model": "m", "turns": 1, "cost": 0,
                "project_tags": "", "first_message": "", "distilled_file": "d/old.md", "raw_file": "",
            },
            {
                "date": "2026-02-15", "session_name": "new",
                "model": "m", "turns": 1, "cost": 0,
                "project_tags": "", "first_message": "", "distilled_file": "d/new.md", "raw_file": "",
            },
        ]

        with tempfile.TemporaryDirectory() as td:
            index_file = os.path.join(td, "INDEX.md")
            with _suppress_output():
                cs.update_index(entries, index_file, dry_run=False)

            with open(index_file, "r") as f:
                content = f.read()

        # "new" should appear before "old" in the output
        pos_new = content.index("2026-02-15")
        pos_old = content.index("2026-01-01")
        self.assertLess(pos_new, pos_old)

    def test_dry_run_writes_nothing(self):
        entries = [
            {
                "date": "2026-02-20", "session_name": "s",
                "model": "m", "turns": 1, "cost": 0,
                "project_tags": "", "first_message": "", "distilled_file": "d/s.md", "raw_file": "",
            },
        ]

        with tempfile.TemporaryDirectory() as td:
            index_file = os.path.join(td, "INDEX.md")
            with _suppress_output():
                cs.update_index(entries, index_file, dry_run=True)

            self.assertFalse(os.path.exists(index_file))


# ============================================================================
# TestSecurity — documents known vulnerabilities (tests only, no fixes)
# ============================================================================
class TestSecurity(unittest.TestCase):
    """Security tests documenting known vulnerabilities.

    Tests marked @unittest.expectedFailure document vulnerabilities where the
    code is currently exploitable. They will "pass" (as xfail) until the
    vulnerability is fixed, at which point they'll start truly passing and
    the decorator should be removed.
    """

    def _write_jsonl(self, td, entries):
        fp = os.path.join(td, "audit.jsonl")
        with open(fp, "w", encoding="utf-8") as f:
            f.write(_make_jsonl(entries))
        return Path(fp)

    # ------------------------------------------------------------------
    # 1. OS Command Injection via UNC server name (Critical)
    # ------------------------------------------------------------------
    @unittest.expectedFailure
    def test_unc_path_shell_metacharacters_not_executed(self):
        """UNC server name with shell metacharacters must not be passed
        unquoted to os.system()."""
        with _suppress_output(), \
             patch("os.system", return_value=0) as mock_system:
            cs.validate_output_path("\\\\evil;rm -rf ~\\share\\path")

        if mock_system.called:
            cmd = mock_system.call_args[0][0]
            # The command must not contain unquoted shell metacharacters
            for meta in [";", "&", "|", "`", "$("]:
                self.assertNotIn(
                    meta, cmd,
                    f"Shell metacharacter {meta!r} passed unquoted to os.system: {cmd}"
                )

    @unittest.expectedFailure
    def test_unc_path_with_spaces_handled_safely(self):
        """UNC server name with spaces must be properly quoted in the
        shell command."""
        with _suppress_output(), \
             patch("os.system", return_value=0) as mock_system:
            cs.validate_output_path("\\\\my server\\share\\path")

        if mock_system.called:
            cmd = mock_system.call_args[0][0]
            # "my server" should appear quoted (single or double quotes,
            # or shlex-escaped) — not bare
            self.assertFalse(
                "ping" in cmd and "my server" in cmd
                and "'" not in cmd and '"' not in cmd,
                f"Unquoted space in os.system argument: {cmd}"
            )

    # ------------------------------------------------------------------
    # 2. Path Traversal via session UUID / cwd (High)
    # ------------------------------------------------------------------
    @unittest.expectedFailure
    def test_session_uuid_path_traversal(self):
        """Session dir named local_../../escape must not produce a UUID
        containing '..'."""
        content = b'{"type":"user","message":"hello"}\n' * 5

        with tempfile.TemporaryDirectory() as td:
            # Create a directory that simulates path traversal
            sessions_dir = os.path.join(td, "sessions")
            evil_dir = os.path.join(sessions_dir, "local_..%2F..%2Fescape")
            os.makedirs(evil_dir)
            with open(os.path.join(evil_dir, "audit.jsonl"), "wb") as f:
                f.write(content)

            # Also test literal ".." (create with os.makedirs won't traverse)
            evil_dir2 = os.path.join(sessions_dir, "local_....escape")
            os.makedirs(evil_dir2, exist_ok=True)
            with open(os.path.join(evil_dir2, "audit.jsonl"), "wb") as f:
                f.write(content)

            pending = cs.get_pending_sessions(sessions_dir, DEFAULT_FMT, {}, False)

        for item in pending:
            self.assertNotIn("..", item["session_uuid"],
                             f"Path traversal in session_uuid: {item['session_uuid']}")

    @unittest.expectedFailure
    def test_cwd_path_traversal_in_session_name(self):
        """A cwd containing '../' must not leak traversal into session_name."""
        entries = [
            {
                "type": "system", "subtype": "init",
                "model": "test-model", "session_id": "s1",
                "cwd": "/sessions/../../etc/passwd",
                "mcp_servers": [],
            },
            {"type": "user", "message": {"content": "hi"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "hello"}
            ]}},
        ]

        with tempfile.TemporaryDirectory() as td:
            fp = self._write_jsonl(td, entries)
            with _suppress_output():
                result = cs.distill_session(fp, "safe-uuid", {}, DEFAULT_FMT)

        self.assertIsNotNone(result)
        self.assertNotIn("..", result["session_name"],
                         f"Path traversal in session_name: {result['session_name']}")

    def test_output_filename_stays_within_output_dir(self):
        """Filename constructed from a traversal UUID must resolve inside
        the output directory, not escape it."""
        output_dir = "/output/archive"
        traversal_uuid = "../../etc/passwd"

        # Simulate the main loop's filename construction
        raw_name = f"2026-02-20_{traversal_uuid}.jsonl"
        raw_dest = os.path.join(output_dir, "raw", raw_name)
        distilled_name = f"2026-02-20_{traversal_uuid}.md"
        distilled_dest = os.path.join(output_dir, "distilled", distilled_name)

        # Resolve to absolute paths and check containment
        raw_resolved = os.path.realpath(raw_dest)
        distilled_resolved = os.path.realpath(distilled_dest)
        raw_parent = os.path.realpath(os.path.join(output_dir, "raw"))
        distilled_parent = os.path.realpath(os.path.join(output_dir, "distilled"))

        self.assertTrue(
            raw_resolved.startswith(raw_parent + os.sep) or raw_resolved == raw_parent,
            f"Raw path escapes output dir: {raw_resolved}"
        )
        self.assertTrue(
            distilled_resolved.startswith(distilled_parent + os.sep)
            or distilled_resolved == distilled_parent,
            f"Distilled path escapes output dir: {distilled_resolved}"
        )

    # ------------------------------------------------------------------
    # 3. JSONL Content Injection into Markdown (Medium)
    # ------------------------------------------------------------------
    @unittest.expectedFailure
    def test_pipe_in_model_does_not_break_table(self):
        """A model name containing '|' must not add extra columns to
        the Markdown header table."""
        entries = [
            {
                "type": "system", "subtype": "init",
                "model": "evil|model",
                "session_id": "s1", "cwd": "/tmp",
                "mcp_servers": [],
            },
            {"type": "user", "message": {"content": "hi"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "hello"}
            ]}},
        ]

        with tempfile.TemporaryDirectory() as td:
            fp = self._write_jsonl(td, entries)
            with _suppress_output():
                result = cs.distill_session(fp, "uuid-pipe", {}, DEFAULT_FMT)

        self.assertIsNotNone(result)
        md = result["markdown"]

        # Every data row in the header table should have exactly 3 pipe chars
        # (| Field | Value |) — start pipe, separator pipe, end pipe
        in_table = False
        for line in md.split("\n"):
            if line.startswith("| Field"):
                in_table = True
                continue
            if in_table and line.startswith("|---"):
                continue
            if in_table and line.startswith("|"):
                pipe_count = line.count("|")
                self.assertEqual(
                    pipe_count, 3,
                    f"Table row has {pipe_count} pipes (expected 3): {line}"
                )
            elif in_table:
                break  # end of table

    @unittest.expectedFailure
    def test_pipe_in_first_message_does_not_break_table(self):
        """A first user message containing '|' must not break the
        Markdown header table."""
        entries = [
            {"type": "user", "message": {"content": "choose A | B | C"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "ok"}
            ]}},
        ]

        with tempfile.TemporaryDirectory() as td:
            fp = self._write_jsonl(td, entries)
            with _suppress_output():
                result = cs.distill_session(fp, "uuid-pipe2", {}, DEFAULT_FMT)

        self.assertIsNotNone(result)
        md = result["markdown"]

        # Find the Summary row specifically
        for line in md.split("\n"):
            if "| Summary |" in line:
                pipe_count = line.count("|")
                self.assertEqual(
                    pipe_count, 3,
                    f"Summary row has {pipe_count} pipes (expected 3): {line}"
                )
                break

    @unittest.expectedFailure
    def test_pipe_in_summary_does_not_break_index(self):
        """An index entry with '|' in first_message must not add extra
        columns to the SESSION-INDEX.md table."""
        entries = [
            {
                "date": "2026-02-20",
                "session_name": "test-session",
                "model": "opus",
                "turns": 1,
                "cost": 0.01,
                "project_tags": "test",
                "first_message": "pick A | B | C",
                "distilled_file": "distilled/test.md",
                "raw_file": "raw/test.jsonl",
            },
        ]

        with tempfile.TemporaryDirectory() as td:
            index_file = os.path.join(td, "SESSION-INDEX.md")
            with _suppress_output():
                cs.update_index(entries, index_file, dry_run=False)

            with open(index_file, "r") as f:
                content = f.read()

        # The header row has 9 pipes: | Date | Session | Summary | Project(s) | Model | Turns | Cost | Files |
        header_pipe_count = None
        for line in content.split("\n"):
            if line.startswith("| Date |"):
                header_pipe_count = line.count("|")
                continue
            if line.startswith("|---"):
                continue
            if line.startswith("|") and header_pipe_count is not None:
                data_pipe_count = line.count("|")
                self.assertEqual(
                    data_pipe_count, header_pipe_count,
                    f"Data row pipe count ({data_pipe_count}) != header ({header_pipe_count}): {line}"
                )

    @unittest.expectedFailure
    def test_newline_in_tool_summary_contained(self):
        """A tool summary with embedded newlines and Markdown headings
        must not inject top-level headings into the output."""
        entries = [
            {"type": "user", "message": {"content": "do something"}},
            {
                "type": "tool_use_summary",
                "summary": "x\n\n### Injected\n\nevil",
            },
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "done"}
            ]}},
        ]

        with tempfile.TemporaryDirectory() as td:
            fp = self._write_jsonl(td, entries)
            with _suppress_output():
                result = cs.distill_session(fp, "uuid-inject", {}, DEFAULT_FMT)

        self.assertIsNotNone(result)
        md = result["markdown"]

        # "### Injected" must not appear as a standalone heading line.
        # It should either be escaped or remain inside a blockquote.
        for line in md.split("\n"):
            if line.strip() == "### Injected":
                self.fail(
                    "Injected heading appeared as a top-level line in output"
                )

    # ------------------------------------------------------------------
    # 4. Absolute Path in session_uuid overwrites arbitrary file (Medium)
    # ------------------------------------------------------------------
    @unittest.expectedFailure
    def test_absolute_path_session_uuid_contained(self):
        """os.path.join() with an absolute second argument returns just
        the absolute path — this must be guarded against."""
        # This documents the os.path.join hazard:
        # os.path.join("/output/archive", "/etc/passwd.jsonl")
        # returns "/etc/passwd.jsonl", not "/output/archive/etc/passwd.jsonl"
        result = os.path.join("/output/archive", "/etc/passwd.jsonl")

        # The vulnerable behavior is that result == "/etc/passwd.jsonl"
        # A secure implementation would keep the path under /output/archive
        self.assertTrue(
            result.startswith("/output/archive/"),
            f"os.path.join with absolute path escapes base: {result}"
        )

    # ------------------------------------------------------------------
    # 5. NUL byte in session name (Medium)
    # ------------------------------------------------------------------
    def test_null_byte_in_session_name(self):
        """A cwd containing a NUL byte must not silently truncate the
        session name."""
        entries = [
            {
                "type": "system", "subtype": "init",
                "model": "test-model", "session_id": "s1",
                "cwd": "/sessions/safe\x00evil",
                "mcp_servers": [],
            },
            {"type": "user", "message": {"content": "hi"}},
            {"type": "assistant", "message": {"content": [
                {"type": "text", "text": "hello"}
            ]}},
        ]

        with tempfile.TemporaryDirectory() as td:
            fp = self._write_jsonl(td, entries)
            with _suppress_output():
                result = cs.distill_session(fp, "uuid-nul", {}, DEFAULT_FMT)

        self.assertIsNotNone(result)
        name = result["session_name"]
        # The name should either reject the input, contain a sanitized
        # full version, or raise — but NOT silently truncate to just "safe"
        self.assertNotEqual(
            name, "safe",
            "Session name silently truncated at NUL byte"
        )


if __name__ == "__main__":
    unittest.main()
