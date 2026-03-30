# cowork-session-sync — Automated Claude Cowork session backup + distillation
# Copyright (C) 2026  yjjoeathome-byte
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

#Requires -Version 7.0
<#
.SYNOPSIS
    Sync-CoworkSessions — Automated Claude Cowork session backup + distillation pipeline.

.DESCRIPTION
    Discovers Cowork session transcripts (audit.jsonl files), copies them to an
    output directory (local or SMB/NAS), and distills each into a clean Markdown
    transcript. Optionally tags sessions with project keywords.

    Reads all configuration from config.json (co-located with this script).
    Run with -DryRun to preview without writing anything.

.NOTES
    Requires: PowerShell 7+
    Config:   config.json (copy config.example.json and edit)
    Repo:     https://github.com/YOUR-USERNAME/cowork-session-sync
#>

[CmdletBinding()]
param(
    # Path to config file (default: config.json next to this script)
    [string]$ConfigFile = (Join-Path $PSScriptRoot "config.json"),

    # If set, process all sessions regardless of state
    [switch]$Force,

    # Dry run: show what would happen without writing anything
    [switch]$DryRun,

    # Validate config and session structure, then exit
    [switch]$Check
)

$ErrorActionPreference = "Stop"
$Script:WarningCount = 0
$Script:FormatVersion = "2026-02"  # Expected Cowork format era
$Script:ScriptVersion = "2026-02-27.1"  # Bump on every functional change

# ============================================================================
# Config loading
# ============================================================================
function Load-Config {
    if (-not (Test-Path $ConfigFile)) {
        $examplePath = Join-Path $PSScriptRoot "config.example.json"
        Write-Host "[!] Config file not found: $ConfigFile" -ForegroundColor Red
        if (Test-Path $examplePath) {
            Write-Host "    Copy config.example.json to config.json and edit it:" -ForegroundColor Yellow
            Write-Host "    cp config.example.json config.json" -ForegroundColor Yellow
        }
        exit 1
    }

    $raw = Get-Content $ConfigFile -Raw -Encoding UTF8
    $cfg = $raw | ConvertFrom-Json -AsHashtable

    # Expand environment variables in paths
    foreach ($key in @("sessions_dir", "output_dir", "state_file")) {
        if ($cfg.ContainsKey($key) -and $cfg[$key]) {
            # Windows: expand %APPDATA% etc.
            $cfg[$key] = [Environment]::ExpandEnvironmentVariables($cfg[$key])
            # macOS/Linux: expand ~ to home directory
            if ($cfg[$key].StartsWith("~")) {
                $cfg[$key] = $cfg[$key].Replace("~", [Environment]::GetFolderPath("UserProfile"))
            }
        }
    }

    # Validate required fields
    $required = @("sessions_dir", "output_dir")
    foreach ($key in $required) {
        if (-not $cfg.ContainsKey($key) -or -not $cfg[$key]) {
            Write-Host "[!] Missing required config field: $key" -ForegroundColor Red
            exit 1
        }
    }

    # Defaults for optional fields
    if (-not $cfg.ContainsKey("state_file") -or -not $cfg["state_file"]) {
        $cfg["state_file"] = Join-Path $env:LOCALAPPDATA "cowork-sync-state.json"
    }
    if (-not $cfg.ContainsKey("project_tags")) {
        $cfg["project_tags"] = @{}
    }
    if (-not $cfg.ContainsKey("format")) {
        $cfg["format"] = @{}
    }

    # Format defaults (the knobs users can tweak if Cowork changes)
    $fmtDefaults = @{
        "session_dir_prefix"   = "local_"
        "transcript_filename"  = "audit.jsonl"
        "min_file_size_bytes"  = 1024
        "expected_entry_types" = @("system", "user", "assistant", "result", "tool_use_summary", "rate_limit_event")
        "expected_init_fields" = @("session_id", "model", "cwd", "mcp_servers")
    }
    foreach ($k in $fmtDefaults.Keys) {
        if (-not $cfg["format"].ContainsKey($k)) {
            $cfg["format"][$k] = $fmtDefaults[$k]
        }
    }

    return $cfg
}

# ============================================================================
# Path validation (local + SMB)
# ============================================================================
function Test-OutputPath {
    param([string]$Path)

    # UNC path: test connectivity first
    if ($Path -match '^\\\\') {
        $parts = $Path -split '\\'
        # \\server\share → parts[2]=server, parts[3]=share
        if ($parts.Count -lt 4) {
            Write-Host "[!] Invalid UNC path: $Path" -ForegroundColor Red
            Write-Host "    Expected format: \\\\server\share\path" -ForegroundColor Yellow
            return $false
        }
        $server = $parts[2]
        $testConn = Test-Connection -TargetName $server -Count 1 -TimeoutSeconds 3 -Quiet -ErrorAction SilentlyContinue
        if (-not $testConn) {
            Write-Host "[!] Cannot reach server: $server" -ForegroundColor Red
            Write-Host "    Check that the NAS/server is online and the SMB share is accessible." -ForegroundColor Yellow
            return $false
        }
    }

    # Test if parent exists (or can be created)
    $parent = Split-Path $Path -Parent
    if ($parent -and -not (Test-Path $parent)) {
        Write-Host "[!] Parent path does not exist: $parent" -ForegroundColor Red
        return $false
    }

    return $true
}

# ============================================================================
# Format detection and validation
# ============================================================================
function Test-SessionFormat {
    param(
        [string]$SessionsDir,
        [hashtable]$FormatConfig
    )

    $issues = @()
    $hints = @()

    # --- Check if sessions_dir exists ---
    if (-not (Test-Path $SessionsDir)) {
        $issues += "Sessions directory not found: $SessionsDir"

        # Suggest alternative paths
        $alternatives = @(
            "$env:APPDATA\Claude\local-agent-mode-sessions",
            "$env:APPDATA\Claude\claude-code-sessions",
            "$env:APPDATA\Claude Desktop\sessions",
            "$env:APPDATA\Claude\sessions"
        )
        $found = $alternatives | Where-Object { Test-Path $_ }
        if ($found) {
            $hints += "Found session data at alternative path(s):"
            foreach ($f in $found) {
                $hints += "  $f"
                $count = (Get-ChildItem -Path $f -Recurse -Filter "*.jsonl" -File -ErrorAction SilentlyContinue).Count
                $hints += "  ($count .jsonl files found)"
            }
            $hints += "Update sessions_dir in config.json if Anthropic moved the storage location."
        } else {
            $hints += "No Claude session directories found under $env:APPDATA\Claude\"
            $hints += "Cowork may not have been used yet, or the storage location has changed."
            $hints += "Check for new directories: Get-ChildItem '$env:APPDATA\Claude' -Directory"
        }

        return @{ Issues = $issues; Hints = $hints }
    }

    # --- Check for expected directory structure ---
    $prefix = $FormatConfig["session_dir_prefix"]
    $targetFile = $FormatConfig["transcript_filename"]

    # Find all transcript files
    $transcripts = Get-ChildItem -Path $SessionsDir -Filter $targetFile -File -Recurse -ErrorAction SilentlyContinue

    if (-not $transcripts -or $transcripts.Count -eq 0) {
        $issues += "No '$targetFile' files found under $SessionsDir"

        # Look for any JSONL files as an alternative
        $anyJsonl = Get-ChildItem -Path $SessionsDir -Filter "*.jsonl" -File -Recurse -ErrorAction SilentlyContinue
        if ($anyJsonl) {
            $names = $anyJsonl | Select-Object -First 5 | ForEach-Object { $_.Name }
            $hints += "Found .jsonl files with different names: $($names -join ', ')"
            $hints += "Anthropic may have renamed the transcript file."
            $hints += "Update format.transcript_filename in config.json."
        }

        $anyJson = Get-ChildItem -Path $SessionsDir -Filter "*.json" -File -Recurse -ErrorAction SilentlyContinue
        if ($anyJson -and -not $anyJsonl) {
            $hints += "Found .json files (not .jsonl). Format may have changed to single-object JSON."
            $hints += "This script currently expects JSONL (one JSON object per line)."
        }

        return @{ Issues = $issues; Hints = $hints }
    }

    # --- Validate nesting structure ---
    $sampleTranscript = $transcripts | Select-Object -First 1
    $sessionDir = $sampleTranscript.Directory.Name
    if (-not $sessionDir.StartsWith($prefix)) {
        $issues += "Session directory '$sessionDir' does not start with expected prefix '$prefix'"
        $hints += "Anthropic may have changed the session folder naming convention."
        $hints += "Update format.session_dir_prefix in config.json."
    }

    # --- Validate JSONL content of a sample file ---
    $sampleFile = $transcripts | Where-Object { $_.Length -ge $FormatConfig["min_file_size_bytes"] } | Select-Object -First 1
    if ($sampleFile) {
        $firstLines = Get-Content $sampleFile.FullName -TotalCount 20 -Encoding UTF8
        $foundTypes = @()
        $foundInitFields = @()
        foreach ($line in $firstLines) {
            $line = $line.Trim()
            if (-not $line) { continue }
            try {
                $obj = $line | ConvertFrom-Json
                if ($obj.PSObject.Properties['type']) {
                    $foundTypes += $obj.type
                }
                if ($obj.type -eq "system" -and $obj.PSObject.Properties['subtype'] -and $obj.subtype -eq "init") {
                    foreach ($field in $FormatConfig["expected_init_fields"]) {
                        if ($obj.PSObject.Properties[$field]) {
                            $foundInitFields += $field
                        }
                    }
                }
            } catch {
                $issues += "Failed to parse JSONL line in $($sampleFile.Name): $($_.Exception.Message)"
                $hints += "The transcript file format may no longer be JSONL."
                break
            }
        }

        # Check for missing expected types
        $expectedTypes = $FormatConfig["expected_entry_types"]
        $missingTypes = $expectedTypes | Where-Object { $_ -notin $foundTypes }
        if ($missingTypes -and $foundTypes.Count -gt 0) {
            # Only warn if we found some types but not all (first 20 lines won't have everything)
            $unexpectedTypes = $foundTypes | Where-Object { $_ -notin $expectedTypes } | Select-Object -Unique
            if ($unexpectedTypes) {
                $hints += "Found unexpected entry types: $($unexpectedTypes -join ', ')"
                $hints += "These may be new Cowork features. The script will skip entries it doesn't recognize."
            }
        }

        # Check init fields
        $expectedInit = $FormatConfig["expected_init_fields"]
        $missingInit = $expectedInit | Where-Object { $_ -notin $foundInitFields }
        if ($missingInit -and $foundInitFields.Count -gt 0) {
            $hints += "Init block missing expected fields: $($missingInit -join ', ')"
            $hints += "Session metadata extraction may be incomplete."
        }
    }

    return @{ Issues = $issues; Hints = $hints }
}

# ============================================================================
# Ensure directories exist
# ============================================================================
function Ensure-Dirs {
    param([string]$ArchiveDir, [string]$DistilledDir)

    foreach ($dir in @($ArchiveDir, $DistilledDir)) {
        if (-not (Test-Path $dir)) {
            if ($DryRun) {
                Write-Host "[DRY] Would create: $dir" -ForegroundColor Yellow
            } else {
                New-Item -ItemType Directory -Path $dir -Force | Out-Null
                Write-Host "[+] Created: $dir" -ForegroundColor Green
            }
        }
    }
}

# ============================================================================
# Load/save processing state
# ============================================================================
function Load-State {
    param([string]$Path)
    if (Test-Path $Path) {
        return (Get-Content $Path -Raw | ConvertFrom-Json -AsHashtable)
    }
    return @{}
}

function Save-State {
    param([hashtable]$State, [string]$Path)
    $parent = Split-Path $Path -Parent
    if ($parent -and -not (Test-Path $parent)) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $State | ConvertTo-Json -Depth 3 | Set-Content $Path -Encoding UTF8
}

# ============================================================================
# Discover pending sessions
# ============================================================================
function Get-PendingSessions {
    param(
        [string]$SessionsDir,
        [hashtable]$FormatConfig,
        [hashtable]$State
    )

    $targetFile = $FormatConfig["transcript_filename"]
    $prefix = $FormatConfig["session_dir_prefix"]
    $minSize = $FormatConfig["min_file_size_bytes"]

    $transcripts = Get-ChildItem -Path $SessionsDir -Filter $targetFile -File -Recurse -ErrorAction SilentlyContinue

    $pending = @()
    foreach ($f in $transcripts) {
        if ($f.Length -lt $minSize) { continue }

        # Try direct hash first; on lock failure, copy-then-hash (active sessions)
        $hash = $null
        $sourceFile = $f  # default: use original file for distillation
        try {
            $hash = (Get-FileHash -Path $f.FullName -Algorithm SHA256).Hash
        } catch {
            # File is locked by an active Cowork session — snapshot it
            try {
                $tmpPath = Join-Path ([System.IO.Path]::GetTempPath()) "cowork-sync-$([guid]::NewGuid().ToString('N')).jsonl"
                Copy-Item -Path $f.FullName -Destination $tmpPath -Force
                $hash = (Get-FileHash -Path $tmpPath -Algorithm SHA256).Hash
                # Create a FileInfo wrapper so downstream code works identically
                $sourceFile = Get-Item $tmpPath
                Write-Host "[~] Active session snapshotted via temp copy: $($f.Directory.Name)" -ForegroundColor DarkYellow
            } catch {
                Write-Host "[~] Skipping truly inaccessible file: $($f.FullName)" -ForegroundColor DarkYellow
                $Script:WarningCount++
                continue
            }
        }

        # Extract session UUID from parent folder
        $sessionFolder = $f.Directory.Name
        $sessionUuid = $sessionFolder -replace "^$([regex]::Escape($prefix))", ''

        $key = $sessionUuid
        if ($Force -or -not $State.ContainsKey($key) -or $State[$key] -ne $hash) {
            $pending += @{
                File        = $sourceFile
                Hash        = $hash
                Key         = $key
                SessionUuid = $sessionUuid
            }
        } else {
            # Hash matched state — no change. Clean up temp file if we made one.
            if ($sourceFile.Name -match '^cowork-sync-' -and (Test-Path $sourceFile.FullName)) {
                Remove-Item $sourceFile.FullName -Force -ErrorAction SilentlyContinue
            }
        }
    }
    return $pending
}

# ============================================================================
# Project tagging
# ============================================================================
function Get-ProjectTags {
    param(
        [string]$Text,
        [hashtable]$TagDictionary
    )

    if ($TagDictionary.Count -eq 0) { return "untagged" }

    $matched = @()
    foreach ($project in $TagDictionary.Keys) {
        foreach ($keyword in $TagDictionary[$project]) {
            if ($Text.IndexOf($keyword, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
                $matched += $project
                break
            }
        }
    }

    if ($matched.Count -eq 0) { return "untagged" }
    return ($matched | Sort-Object) -join ", "
}

# ============================================================================
# Distill audit.jsonl → Markdown
# ============================================================================
function Distill-Session {
    param(
        [System.IO.FileInfo]$File,
        [string]$SessionUuid,
        [hashtable]$TagDictionary,
        [hashtable]$FormatConfig
    )

    $lines = Get-Content $File.FullName -Encoding UTF8
    $entries = @()
    $parseErrors = 0
    foreach ($line in $lines) {
        $line = $line.Trim()
        if ($line -eq "") { continue }
        try {
            $obj = $line | ConvertFrom-Json
            $entries += $obj
        } catch {
            $parseErrors++
            if ($parseErrors -ge 10) {
                Write-Host "    [!] Too many parse errors ($parseErrors) — file may not be JSONL" -ForegroundColor Red
                return $null
            }
            continue
        }
    }

    if ($entries.Count -eq 0) { return $null }

    if ($parseErrors -gt 0) {
        Write-Host "    [~] $parseErrors unparseable lines skipped" -ForegroundColor DarkYellow
        $Script:WarningCount++
    }

    $meta = @{
        SessionId   = $SessionUuid
        SessionName = ""
        Model       = ""
        StartTime   = ""
        EndTime     = ""
        TotalCost   = 0.0
        TurnCount   = 0
        McpServers  = @()
        ProjectTags = ""
        Topic       = ""
    }

    $md = [System.Text.StringBuilder]::new()
    $unknownTypes = @{}

    foreach ($entry in $entries) {
        $type = $entry.type
        $subtype = if ($entry.PSObject.Properties['subtype']) { $entry.subtype } else { "" }

        # --- Init block ---
        if ($type -eq "system" -and $subtype -eq "init" -and $meta.Model -eq "") {
            $meta.Model = if ($entry.PSObject.Properties['model']) { $entry.model } else { "" }
            if (-not $meta.StartTime -and $entry.PSObject.Properties['_audit_timestamp']) {
                $meta.StartTime = $entry._audit_timestamp
            }
            if ($entry.PSObject.Properties['cwd'] -and $entry.cwd -match '/sessions/(.+)') {
                $meta.SessionName = $Matches[1]
            }
            $meta.McpServers = @()
            if ($entry.PSObject.Properties['mcp_servers']) {
                foreach ($srv in $entry.mcp_servers) {
                    if ($srv.status -eq "connected") {
                        $meta.McpServers += $srv.name
                    }
                }
            }
            continue
        }

        # --- Skip noise ---
        if ($type -eq "system" -and $subtype -in @("permission_request", "permission_response")) { continue }
        if ($type -eq "system") { continue }  # Skip other system messages

        # --- Tool summaries ---
        if ($type -eq "tool_use_summary") {
            $summary = if ($entry.PSObject.Properties['summary']) { $entry.summary } else { "" }
            if ($summary) {
                [void]$md.AppendLine("> **Tool**: $summary")
                [void]$md.AppendLine("")
            }
            continue
        }

        # --- User message ---
        if ($type -eq "user" -and $entry.PSObject.Properties['message']) {
            $content = ""
            $msg = $entry.message
            if ($msg.PSObject.Properties['content']) {
                if ($msg.content -is [string]) {
                    $content = $msg.content
                } elseif ($msg.content -is [array]) {
                    foreach ($part in $msg.content) {
                        if ($part.PSObject.Properties['text']) {
                            $content += $part.text + "`n"
                        }
                        if ($part.PSObject.Properties['type'] -and $part.type -eq "tool_result") {
                            if ($part.PSObject.Properties['is_error'] -and $part.is_error) {
                                $toolContent = ""
                                if ($part.PSObject.Properties['content'] -and $part.content -is [string]) {
                                    $parsed = $null
                                    try { $parsed = $part.content | ConvertFrom-Json } catch {}
                                    if ($parsed -and $parsed.PSObject.Properties['content']) {
                                        $toolContent = $parsed.content
                                    } else {
                                        $toolContent = $part.content
                                    }
                                }
                                if ($toolContent.Length -gt 500) {
                                    $toolContent = $toolContent.Substring(0, 500) + "`n[... truncated ...]"
                                }
                                $content += "> **Tool Error**: ``$toolContent```n"
                            }
                        }
                    }
                }
            }

            if (-not $content -and $entry.PSObject.Properties['message'] -and $entry.message -is [string]) {
                $content = $entry.message
            }
            if (-not $content -and $entry.PSObject.Properties['message'] -and
                $entry.message.PSObject.Properties['content'] -and $entry.message.content -is [string]) {
                $content = $entry.message.content
            }

            $content = $content.Trim()
            if ($content) {
                $meta.TurnCount++
                # Capture first user message as session topic
                if (-not $meta.Topic) {
                    $topicText = $content -replace '[\r\n]+', ' '
                    if ($topicText.Length -gt 120) {
                        $topicText = $topicText.Substring(0, 117) + "..."
                    }
                    $meta.Topic = $topicText
                }
                [void]$md.AppendLine("---")
                [void]$md.AppendLine("### User")
                [void]$md.AppendLine("")
                [void]$md.AppendLine($content)
                [void]$md.AppendLine("")
            }
            continue
        }

        # --- Assistant message: text blocks only ---
        if ($type -eq "assistant" -and $entry.PSObject.Properties['message']) {
            $msg = $entry.message
            if ($msg.PSObject.Properties['content'] -and $msg.content -is [array]) {
                foreach ($block in $msg.content) {
                    if ($block.PSObject.Properties['type'] -and $block.type -eq "text" -and $block.PSObject.Properties['text']) {
                        $text = $block.text.Trim()
                        if ($text) {
                            [void]$md.AppendLine("### Claude")
                            [void]$md.AppendLine("")
                            [void]$md.AppendLine($text)
                            [void]$md.AppendLine("")
                        }
                    }
                }
            }
            continue
        }

        # --- Result block ---
        if ($type -eq "result") {
            if ($entry.PSObject.Properties['total_cost_usd']) {
                $meta.TotalCost += [double]$entry.total_cost_usd
            }
            if ($entry.PSObject.Properties['_audit_timestamp']) {
                $meta.EndTime = $entry._audit_timestamp
            }
            continue
        }

        # --- Track unknown entry types (potential format changes) ---
        $expectedTypes = $FormatConfig["expected_entry_types"]
        if ($type -and $type -notin $expectedTypes) {
            if (-not $unknownTypes.ContainsKey($type)) { $unknownTypes[$type] = 0 }
            $unknownTypes[$type]++
        }
    }

    # Warn about unknown types
    if ($unknownTypes.Count -gt 0) {
        $typeList = ($unknownTypes.GetEnumerator() | ForEach-Object { "$($_.Key)(×$($_.Value))" }) -join ", "
        Write-Host "    [~] Unknown entry types: $typeList" -ForegroundColor DarkYellow
        Write-Host "    [~] Cowork format may have new features. These entries were skipped." -ForegroundColor DarkYellow
        $Script:WarningCount++
    }

    $transcript = $md.ToString().Trim()
    if (-not $transcript) { return $null }

    $meta.ProjectTags = Get-ProjectTags -Text $transcript -TagDictionary $TagDictionary

    # --- Build final document ---
    $header = [System.Text.StringBuilder]::new()
    $sessionLabel = if ($meta.SessionName) { $meta.SessionName } else { $SessionUuid.Substring(0, [Math]::Min(8, $SessionUuid.Length)) }
    [void]$header.AppendLine("# Session: $sessionLabel")
    [void]$header.AppendLine("")
    [void]$header.AppendLine("| Field | Value |")
    [void]$header.AppendLine("|-------|-------|")
    [void]$header.AppendLine("| Model | ``$($meta.Model)`` |")
    $shortId = if ($meta.SessionId.Length -ge 8) { $meta.SessionId.Substring(0, 8) + "..." } else { $meta.SessionId }
    [void]$header.AppendLine("| Session ID | ``$shortId`` |")
    [void]$header.AppendLine("| Started | $($meta.StartTime) |")
    [void]$header.AppendLine("| Ended | $($meta.EndTime) |")
    [void]$header.AppendLine("| User turns | $($meta.TurnCount) |")
    [void]$header.AppendLine("| Cost (USD) | `$$([Math]::Round($meta.TotalCost, 4)) |")
    [void]$header.AppendLine("| MCP servers | $($meta.McpServers -join ', ') |")
    [void]$header.AppendLine("| Projects | $($meta.ProjectTags) |")
    [void]$header.AppendLine("| Format version | $Script:FormatVersion |")
    [void]$header.AppendLine("")

    return @{
        Markdown    = $header.ToString() + $transcript
        Meta        = $meta
        SessionName = $sessionLabel
    }
}

# ============================================================================
# Update session index
# ============================================================================
function Update-Index {
    param(
        [array]$IndexEntries,
        [string]$IndexFile
    )

    $header = @"
# Session Index

Auto-generated by [cowork-session-sync](https://github.com/YOUR-USERNAME/cowork-session-sync). Newest first.
Last updated: $(Get-Date -Format "yyyy-MM-dd HH:mm:ss")

| Date | Session | Project(s) | Model | Turns | Cost | Files |
|------|---------|------------|-------|-------|------|-------|
"@

    $rows = ""
    foreach ($e in ($IndexEntries | Sort-Object -Property Date -Descending)) {
        $fileLinks = "[distilled]($($e.DistilledFile))"
        if ($e.RawFile) { $fileLinks += " / [raw]($($e.RawFile))" }
        $rows += "| $($e.Date) | $($e.SessionName) | $($e.ProjectTags) | $($e.Model) | $($e.Turns) | `$$($e.Cost) | $fileLinks |`n"
    }

    $content = $header + $rows
    if ($DryRun) {
        Write-Host "[DRY] Would write index to: $IndexFile" -ForegroundColor Yellow
    } else {
        $content | Set-Content $IndexFile -Encoding UTF8
        Write-Host "[+] Updated index: $IndexFile" -ForegroundColor Cyan
    }
}

# ============================================================================
# Generate catch-up index (CATCH-UP.md)
# ============================================================================
function Update-CatchUp {
    param(
        [array]$IndexEntries,
        [string]$CatchUpFile
    )

    # Group entries by project tag, sorted by date descending
    $sorted = $IndexEntries | Sort-Object -Property Date -Descending
    $byProject = @{}
    foreach ($e in $sorted) {
        $tags = if ($e.ProjectTags) { $e.ProjectTags } else { "untagged" }
        foreach ($tag in ($tags -split ',\s*')) {
            $tag = $tag.Trim()
            if (-not $byProject.ContainsKey($tag)) { $byProject[$tag] = @() }
            $byProject[$tag] += $e
        }
    }

    $sb = [System.Text.StringBuilder]::new()
    [void]$sb.AppendLine("# Session Catch-Up Index")
    [void]$sb.AppendLine("")
    [void]$sb.AppendLine("Auto-generated by Sync-CoworkSessions. Consumed by the catch-up protocol in CLAUDE.md.")
    [void]$sb.AppendLine("Last updated: $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')")
    [void]$sb.AppendLine("")

    # Named projects first, then untagged
    $projectNames = $byProject.Keys | Where-Object { $_ -ne "untagged" } | Sort-Object
    if ($byProject.ContainsKey("untagged")) { $projectNames = @($projectNames) + @("untagged") }

    foreach ($project in $projectNames) {
        [void]$sb.AppendLine("## $project")
        [void]$sb.AppendLine("")
        foreach ($e in $byProject[$project]) {
            $topic = if ($e.Topic) { $e.Topic } else { "(no topic captured)" }
            $cost = if ($e.Cost) { "`$$($e.Cost)" } else { "" }
            $turns = if ($e.Turns) { "$($e.Turns) turns" } else { "" }
            $detail = @($turns, $cost) | Where-Object { $_ } | ForEach-Object { $_ }
            $detailStr = if ($detail) { " ($($detail -join ', '))" } else { "" }
            [void]$sb.AppendLine("- **$($e.Date)** $($e.SessionName)${detailStr}: `"$topic`"")
        }
        [void]$sb.AppendLine("")
    }

    if ($DryRun) {
        Write-Host "[DRY] Would write catch-up index to: $CatchUpFile" -ForegroundColor Yellow
    } else {
        $sb.ToString() | Set-Content $CatchUpFile -Encoding UTF8
        Write-Host "[+] Updated catch-up index: $CatchUpFile" -ForegroundColor Cyan
    }
}

# ============================================================================
# Main
# ============================================================================
Write-Host "=== Cowork Session Sync ===" -ForegroundColor Cyan

# --- Load config ---
$cfg = Load-Config
$sessionsDir = $cfg["sessions_dir"]
$outputDir   = $cfg["output_dir"]
$stateFile   = $cfg["state_file"]
$projectTags = $cfg["project_tags"]
$formatCfg   = $cfg["format"]

$archiveDir   = Join-Path $outputDir "raw"
$distilledDir = Join-Path $outputDir "distilled"
$indexFile    = Join-Path $outputDir "SESSION-INDEX.md"
$catchUpFile  = Join-Path $outputDir "CATCH-UP.md"

Write-Host "Source:    $sessionsDir"
Write-Host "Output:    $outputDir"
Write-Host ""

# --- Deployment drift check ---
# If this script is running from the output dir (deployed copy), compare against
# the repo copy to detect version skew. Warns loudly but does not abort.
$repoScriptPath = Join-Path $PSScriptRoot "..\unified-cowork-repo\Sync-CoworkSessions.ps1"
if (($PSScriptRoot -ne (Split-Path $repoScriptPath -Parent)) -and (Test-Path $repoScriptPath)) {
    $repoContent = Get-Content $repoScriptPath -Raw -ErrorAction SilentlyContinue
    if ($repoContent -and $repoContent -match '\$Script:ScriptVersion\s*=\s*"([^"]+)"') {
        $repoVersion = $Matches[1]
        if ($repoVersion -ne $Script:ScriptVersion) {
            Write-Host ""
            Write-Host "[!] DEPLOYMENT DRIFT DETECTED" -ForegroundColor Red
            Write-Host "    Running version:  $Script:ScriptVersion" -ForegroundColor Red
            Write-Host "    Repo version:     $repoVersion" -ForegroundColor Red
            Write-Host "    This script is a stale copy. Copy the repo version to: $PSCommandPath" -ForegroundColor Yellow
            Write-Host ""
            $Script:WarningCount++
        }
    }
}

# --- Validate output path ---
if (-not (Test-OutputPath -Path $outputDir)) {
    exit 1
}

# --- Validate session format ---
$validation = Test-SessionFormat -SessionsDir $sessionsDir -FormatConfig $formatCfg
if ($validation.Issues.Count -gt 0) {
    Write-Host "" -ForegroundColor Red
    Write-Host "[!] FORMAT ISSUES DETECTED" -ForegroundColor Red
    Write-Host "    The Cowork session storage format may have changed." -ForegroundColor Red
    Write-Host "" -ForegroundColor Red
    foreach ($issue in $validation.Issues) {
        Write-Host "    ISSUE: $issue" -ForegroundColor Red
    }
    foreach ($hint in $validation.Hints) {
        Write-Host "    HINT:  $hint" -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "    Config knobs to adjust (in config.json → format section):" -ForegroundColor Yellow
    Write-Host "      sessions_dir          — where Cowork stores sessions" -ForegroundColor Yellow
    Write-Host "      format.session_dir_prefix  — folder name prefix (currently: '$($formatCfg['session_dir_prefix'])')" -ForegroundColor Yellow
    Write-Host "      format.transcript_filename — transcript file name (currently: '$($formatCfg['transcript_filename'])')" -ForegroundColor Yellow
    Write-Host ""
    Write-Host "    If the format changed significantly, check the repo for updates:" -ForegroundColor Yellow
    Write-Host "    https://github.com/YOUR-USERNAME/cowork-session-sync/issues" -ForegroundColor Yellow
    exit 1
}

if ($validation.Hints.Count -gt 0) {
    foreach ($hint in $validation.Hints) {
        Write-Host "[~] $hint" -ForegroundColor DarkYellow
    }
    $Script:WarningCount++
}

if ($Check) {
    Write-Host "[OK] Config valid, session format recognized." -ForegroundColor Green
    $transcriptCount = (Get-ChildItem -Path $sessionsDir -Filter $formatCfg["transcript_filename"] -File -Recurse -ErrorAction SilentlyContinue).Count
    Write-Host "     $transcriptCount session transcript(s) found." -ForegroundColor Green
    Write-Host "     $($projectTags.Count) project tag rule(s) configured." -ForegroundColor Green
    exit 0
}

# --- Ensure output dirs ---
Ensure-Dirs -ArchiveDir $archiveDir -DistilledDir $distilledDir

# --- Discover sessions ---
$state = Load-State -Path $stateFile
$pending = Get-PendingSessions -SessionsDir $sessionsDir -FormatConfig $formatCfg -State $state

if ($pending.Count -eq 0) {
    Write-Host "[=] No new or modified sessions." -ForegroundColor DarkGray
    exit 0
}

Write-Host "[*] Found $($pending.Count) session(s) to process" -ForegroundColor Yellow
$indexEntries = @()

foreach ($item in $pending) {
    $f = $item.File
    $sizeKB = [Math]::Round($f.Length / 1KB, 1)
    Write-Host ""
    Write-Host "[*] Processing: $($item.SessionUuid) ($sizeKB KB)" -ForegroundColor White

    # --- Distill (to get session name for archive filename) ---
    $result = Distill-Session -File $f -SessionUuid $item.SessionUuid -TagDictionary $projectTags -FormatConfig $formatCfg
    $sessionName = if ($result -and $result.SessionName) { $result.SessionName } else { $item.SessionUuid.Substring(0, 8) }

    # --- Copy raw ---
    $datePrefix = $f.LastWriteTime.ToString("yyyy-MM-dd")
    $rawName = "${datePrefix}_${sessionName}.jsonl"
    $rawDest = Join-Path $archiveDir $rawName

    if ($DryRun) {
        Write-Host "    [DRY] Would copy raw -> $rawDest" -ForegroundColor Yellow
    } else {
        Copy-Item -Path $f.FullName -Destination $rawDest -Force
        Write-Host "    [+] Raw archived -> $rawDest" -ForegroundColor Green
    }

    # --- Write distilled ---
    if ($null -eq $result) {
        Write-Host "    [!] Empty or unparseable — raw archived, distillation skipped" -ForegroundColor DarkYellow
        $state[$item.Key] = $item.Hash
        # Clean up temp snapshot on early exit too
        if ($f.Name -match '^cowork-sync-' -and (Test-Path $f.FullName)) {
            Remove-Item $f.FullName -Force -ErrorAction SilentlyContinue
        }
        continue
    }

    $distilledName = "${datePrefix}_${sessionName}.md"
    $distilledDest = Join-Path $distilledDir $distilledName

    if ($DryRun) {
        Write-Host "    [DRY] Would write distilled -> $distilledDest" -ForegroundColor Yellow
        Write-Host "    [DRY] Turns: $($result.Meta.TurnCount), Cost: `$$([Math]::Round($result.Meta.TotalCost, 4)), Tags: $($result.Meta.ProjectTags)" -ForegroundColor Yellow
    } else {
        $result.Markdown | Set-Content $distilledDest -Encoding UTF8
        Write-Host "    [+] Distilled -> $distilledDest" -ForegroundColor Green

        $distilledSize = [Math]::Round((Get-Item $distilledDest).Length / 1KB, 1)
        $ratio = if ($sizeKB -gt 0) { [Math]::Round(($distilledSize / $sizeKB) * 100, 0) } else { 0 }
        Write-Host "    [i] $sizeKB KB raw -> $distilledSize KB distilled ($ratio%)" -ForegroundColor DarkCyan
        Write-Host "    [i] Tags: $($result.Meta.ProjectTags)" -ForegroundColor DarkCyan
    }

    $indexEntries += @{
        Date          = $datePrefix
        SessionName   = $sessionName
        Model         = $result.Meta.Model
        Turns         = $result.Meta.TurnCount
        Cost          = [Math]::Round($result.Meta.TotalCost, 4)
        ProjectTags   = $result.Meta.ProjectTags
        Topic         = $result.Meta.Topic
        DistilledFile = "distilled/$distilledName"
        RawFile       = "raw/$rawName"
    }

    $state[$item.Key] = $item.Hash

    # Clean up temp snapshot if this was a locked-file copy
    if ($f.Name -match '^cowork-sync-' -and (Test-Path $f.FullName)) {
        Remove-Item $f.FullName -Force -ErrorAction SilentlyContinue
    }
}

# --- Rebuild index: include existing distilled files ---
$allDistilled = Get-ChildItem -Path $distilledDir -Filter "*.md" -File -ErrorAction SilentlyContinue
foreach ($df in $allDistilled) {
    $alreadyIndexed = $indexEntries | Where-Object { $_.DistilledFile -eq "distilled/$($df.Name)" }
    if (-not $alreadyIndexed) {
        $head = Get-Content $df.FullName -TotalCount 40 -Encoding UTF8
        $model = ""; $turns = ""; $cost = ""; $tags = ""; $topic = ""
        $inUserBlock = $false
        foreach ($l in $head) {
            if ($l -match '^\| Model \| `(.+)` \|') { $model = $Matches[1] }
            if ($l -match '^\| User turns \| (\d+) \|') { $turns = $Matches[1] }
            if ($l -match '^\| Cost .+ \| \$(.+) \|') { $cost = $Matches[1] }
            if ($l -match '^\| Projects \| (.+) \|') { $tags = $Matches[1].Trim() }
            # Extract first user message as topic
            if ($l -match '^### User') { $inUserBlock = $true; continue }
            if ($inUserBlock -and $l.Trim() -and -not $topic) {
                $topic = $l.Trim() -replace '[\r\n]+', ' '
                if ($topic.Length -gt 120) { $topic = $topic.Substring(0, 117) + "..." }
                $inUserBlock = $false
            }
        }
        $datePart = if ($df.Name -match '^(\d{4}-\d{2}-\d{2})') { $Matches[1] } else { "" }
        $namePart = $df.BaseName -replace '^\d{4}-\d{2}-\d{2}_', ''

        $indexEntries += @{
            Date          = $datePart
            SessionName   = $namePart
            Model         = $model
            Turns         = $turns
            Cost          = $cost
            ProjectTags   = $tags
            Topic         = $topic
            DistilledFile = "distilled/$($df.Name)"
            RawFile       = ""
        }
    }
}

Update-Index -IndexEntries $indexEntries -IndexFile $indexFile
Update-CatchUp -IndexEntries $indexEntries -CatchUpFile $catchUpFile

if (-not $DryRun) {
    Save-State -State $state -Path $stateFile
}

Write-Host ""
if ($Script:WarningCount -gt 0) {
    Write-Host "=== Done ($($Script:WarningCount) warning(s)) ===" -ForegroundColor Yellow
} else {
    Write-Host "=== Done ===" -ForegroundColor Cyan
}
