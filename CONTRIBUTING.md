# Contributing to unified-cowork

Contributions are welcome — bug reports, format discoveries, platform support, and code improvements.

## Getting Started

```bash
git clone https://github.com/yjjoeathome-byte/unified-cowork.git
cd unified-cowork
cp config.example.json config.json
# Edit config.json with your local paths
```

Verify your setup:

```bash
python3 cowork_sync.py --check
```

## Running Tests

```bash
python3 -m unittest test_cowork_sync -v
```

All 56 tests must pass before submitting a PR. The repo includes a pre-commit hook (`.project-hooks/pre-commit`) that runs the test suite automatically.

## Reporting Format Changes

Anthropic does not document the Cowork `audit.jsonl` session format (see [#27724](https://github.com/anthropics/claude-code/issues/27724)). If you notice the format has changed:

1. Run `python3 cowork_sync.py --check` and capture the output
2. Open an issue with the `--check` output, your platform, and what changed
3. If possible, include a redacted sample of the new format

Format discoveries are high-value contributions — they keep the project working for everyone.

## Submitting Changes

1. Fork the repo and create a branch from `main`
2. Make your changes — one concern per PR
3. Add or update tests for any new behavior
4. Run the full test suite: `python3 -m unittest test_cowork_sync -v`
5. Ensure `--check` still passes against real session data if you modified parsing logic
6. Submit a PR with a clear description of what and why

## Code Guidelines

- **Python 3.8+ stdlib only** — no pip dependencies. This is a hard constraint.
- Functions use `snake_case` (PEP 8)
- Security tests in `TestSecurity` are regression tests — if you fix a vulnerability, remove the corresponding `@expectedFailure` decorator (if any) and verify the test passes
- The PowerShell version (`Sync-CoworkSessions.ps1`) is maintained as an alternative but Python is primary

## What We're Looking For

- **Platform testing** — especially Linux distributions and edge cases on Windows
- **Format change detection** — if Anthropic changes the session storage layout
- **Security hardening** — input validation, path safety, output sanitization
- **Scheduling integrations** — systemd timers, Windows Task Scheduler improvements, container support

## What We're Not Looking For

- External runtime dependencies (no pip packages)
- Cloud-specific integrations (this is a local/NAS tool)
- LLM-based features (topic extraction stays heuristic, not inference)

## Security Issues

See [SECURITY.md](SECURITY.md) for reporting vulnerabilities. Do not open public issues for security bugs.
