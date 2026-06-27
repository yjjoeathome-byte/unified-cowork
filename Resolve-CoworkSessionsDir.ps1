#Requires -Version 5.1
<#
.SYNOPSIS
    Resolve-CoworkSessionsDir — Robustly locate the Claude Cowork session store
    (the 'local-agent-mode-sessions' directory) no matter where Anthropic moves it.

.DESCRIPTION
    Anthropic periodically relocates / renames the Cowork session store. Observed
    churn (verified 2026-06-27) and how this resolver absorbs each one:

      | What changes                              | Absorbed by                          |
      |-------------------------------------------|--------------------------------------|
      | app version (package *full* name)         | PackageFamilyName (version-free)     |
      | publisher hash / family rename            | Claude_* glob + Get-AppxPackage      |
      | intermediate path (LocalCache\Roaming\..) | bounded search under the package     |
      | session-folder prefix (local_/ditto_/..)  | never keyed on prefix                |
      | nesting depth (seen 3 and 4)              | never keyed on a fixed depth         |

    The ONE durable invariant: a directory named 'local-agent-mode-sessions'
    with 'audit.jsonl' files somewhere beneath it. That pair is the fingerprint.

    Resolution is cost-tiered and cached, so steady-state cost is a single
    directory Test-Path (~1 ms). Expensive discovery runs ONLY after a real move,
    and even then it is anchored on Claude-named folders — never a blind disk walk.

    Tier 0  Pinned override        ~0 ms    explicit literal path, if valid
    Tier 1  Cache (last-known-good)~1 ms    Test-Path the remembered dir
    Tier 2  Glob-probe candidates  ~30 ms   %LOCALAPPDATA%\Packages\Claude_*\...
    Tier 3  Appx-anchored derive   ~360 ms  Get-AppxPackage -> bounded search
    Tier 4  Claude-anchored search ~variable shallow Claude/Anthropic anchors only
    Tier 5  Pruned %USERPROFILE%   last-resort, loud warning, depth/prune-capped

.PARAMETER Pinned
    Explicit literal path to force (Tier 0). Ignored if it fails validation.

.PARAMETER Refresh
    Ignore the cache and re-discover.

.OUTPUTS
    [string] full path to the sessions directory, or $null if not found.

.EXAMPLE
    . .\Resolve-CoworkSessionsDir.ps1
    $dir = Resolve-CoworkSessionsDir        # dot-source then call

.EXAMPLE
    pwsh -File .\Resolve-CoworkSessionsDir.ps1     # run directly, prints the path
#>
function Resolve-CoworkSessionsDir {
    [CmdletBinding()]
    param(
        [string]$Pinned,
        [string]$CacheFile = (Join-Path $env:LOCALAPPDATA 'cowork-sync-sessionsdir.cache'),
        [string]$Artifact  = 'audit.jsonl',
        [string]$RootName  = 'local-agent-mode-sessions',
        [switch]$Refresh
    )

    # --- Fingerprint predicate: a real sessions root has >=1 artifact beneath it.
    #     Get-ChildItem | Select -First 1 short-circuits, so this stops at the first hit.
    $isValid = {
        param($p)
        if (-not $p -or -not (Test-Path -LiteralPath $p -PathType Container)) { return $false }
        [bool](Get-ChildItem -LiteralPath $p -Recurse -Depth 5 -Filter $Artifact -File -ErrorAction SilentlyContinue |
               Select-Object -First 1)
    }

    # --- Tier 0: explicit pin ------------------------------------------------
    if ($Pinned -and (& $isValid $Pinned)) {
        return (Resolve-Path -LiteralPath $Pinned).Path
    }

    # --- Tier 1: cache (last-known-good) -------------------------------------
    if (-not $Refresh -and (Test-Path -LiteralPath $CacheFile)) {
        $cached = (Get-Content -LiteralPath $CacheFile -Raw -ErrorAction SilentlyContinue)
        if ($cached) { $cached = $cached.Trim() }
        if ($cached -and (& $isValid $cached)) { return $cached }
    }

    $found = $null

    # --- Tier 2: cheap glob-probe of known candidate roots (first valid wins)-
    $candidates = @(
        (Join-Path $env:LOCALAPPDATA "Packages\Claude_*\LocalCache\Roaming\Claude\$RootName"),  # Store/MSIX (current)
        (Join-Path $env:APPDATA      "Claude\$RootName"),                                        # legacy Electron userData
        (Join-Path $env:LOCALAPPDATA "AnthropicClaude\$RootName"),                               # possible Squirrel install
        (Join-Path $env:LOCALAPPDATA "Claude\$RootName")                                         # generic local
    )
    foreach ($pattern in $candidates) {
        $hit = Resolve-Path -Path $pattern -ErrorAction SilentlyContinue |
               Where-Object { Test-Path -LiteralPath $_.Path -PathType Container } |
               Select-Object -First 1 -ExpandProperty Path
        if ($hit -and (& $isValid $hit)) { $found = $hit; break }
    }

    # --- Tier 3: Appx-anchored derivation (robust to intermediate-path change)-
    if (-not $found) {
        foreach ($pkg in (Get-AppxPackage -Name '*Claude*' -ErrorAction SilentlyContinue)) {
            $localCache = Join-Path $env:LOCALAPPDATA "Packages\$($pkg.PackageFamilyName)\LocalCache"
            if (Test-Path -LiteralPath $localCache) {
                $hit = Get-ChildItem -LiteralPath $localCache -Recurse -Depth 4 -Directory -Filter $RootName -ErrorAction SilentlyContinue |
                       Select-Object -First 1 -ExpandProperty FullName
                if ($hit -and (& $isValid $hit)) { $found = $hit; break }
            }
        }
    }

    # --- Tier 4: Claude-anchored bounded discovery (never a blind walk) -------
    if (-not $found) {
        $anchorParents = @($env:LOCALAPPDATA, (Join-Path $env:LOCALAPPDATA 'Packages'), $env:APPDATA)
        $anchors = foreach ($r in $anchorParents) {
            Get-ChildItem -LiteralPath $r -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match 'Claude|Anthropic' }
        }
        $best = $null; $bestTime = [datetime]::MinValue
        foreach ($a in ($anchors | Sort-Object FullName -Unique)) {
            foreach ($n in (Get-ChildItem -LiteralPath $a.FullName -Recurse -Depth 5 -Directory -Filter $RootName -ErrorAction SilentlyContinue)) {
                $newest = Get-ChildItem -LiteralPath $n.FullName -Recurse -Depth 5 -Filter $Artifact -File -ErrorAction SilentlyContinue |
                          Sort-Object LastWriteTime -Descending | Select-Object -First 1
                if ($newest -and $newest.LastWriteTime -gt $bestTime) { $best = $n.FullName; $bestTime = $newest.LastWriteTime }
            }
        }
        if ($best) { $found = $best }
    }

    # --- Tier 5: pruned %USERPROFILE% walk (last resort, loud) ---------------
    if (-not $found) {
        Write-Warning "Cowork sessions dir not found via fast tiers — pruned %USERPROFILE% walk (structure changed fundamentally; consider updating Tier 2 candidates)."
        $prune = '\\(OneDrive|Documents|Downloads|Pictures|Music|Videos|node_modules|\.git|\.vscode|\.cache|Temp|Microsoft|INetCache|WebCache|GameBar)(\\|$)'
        $found = Get-ChildItem -LiteralPath $env:USERPROFILE -Recurse -Depth 6 -Directory -Filter $RootName -ErrorAction SilentlyContinue |
                 Where-Object { $_.FullName -notmatch $prune } |
                 Sort-Object LastWriteTime -Descending |
                 Select-Object -First 1 -ExpandProperty FullName
    }

    # --- Persist + return ----------------------------------------------------
    if ($found) {
        try { Set-Content -LiteralPath $CacheFile -Value $found -Encoding UTF8 -ErrorAction SilentlyContinue } catch { }
        return $found
    }
    return $null
}

# Run directly (not dot-sourced) -> print the resolved path + timing.
if ($MyInvocation.InvocationName -ne '.') {
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    $dir = Resolve-CoworkSessionsDir @args
    $sw.Stop()
    if ($dir) {
        Write-Host $dir
        Write-Host ("[resolved in {0} ms]" -f $sw.ElapsedMilliseconds) -ForegroundColor DarkGray
    } else {
        Write-Error "Cowork sessions directory not found."
        exit 1
    }
}
