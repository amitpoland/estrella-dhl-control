<#
.SYNOPSIS
    SOLE execution and rollback authority for PZ production deployment.

.DESCRIPTION
    Every path, filename and flag is read from windows_prod_v2.json. Nothing is
    hardcoded. Deployment is artifact-based and deterministic: the bytes that reach
    production are the bytes of an immutable, hash-manifested staged artifact -- never
    a live git tree. Rollback restores only from a manifest-validated backup and never
    mutates the certified source's git history.

    DELIBERATELY ONE FILE. Splitting execution across modules is how this repository
    accumulated 29 competing deployment scripts. One authority, one file.

.PARAMETER ReviewedSHA
    REQUIRED for any production write. The exact full 40-character commit SHA approved
    by the 7-agent pre-deploy gate. The deployed target is NEVER recomputed from a
    fresh origin/main read: the SHA the operator types is the SHA that ships, or
    nothing ships. Artifact, backup metadata, convergence, version file and validation
    are all bound to this value.

.PARAMETER WhatIf
    Zero-write plan. Requires no authorization, creates no lock, no artifact, no
    backup, and touches no service. Usable by reviewers and gate agents.

.PARAMETER Rollback
    Restore a previously created deployment unit. Requires -Unit.

.PARAMETER Unit
    Deployment unit identifier. Must match ^[0-9a-f]{40}-\d{8}-\d{6}$ -- no separators,
    no traversal, no rooted paths.

.PARAMETER Scope
    App | Engine | Both (default Both). Bound into the authorization and the unit.

.PARAMETER Bootstrap
    First-ever deploy: permits an absent prior production tree (no rollback target).

.PARAMETER ForceUnlock
    Release a lock whose recording process is provably gone. Requires -ReviewedSHA and
    prints the stale lock's contents for the audit trail.

.PARAMETER NoRun
    Dot-source the functions without executing. For tests only.

.NOTES
    OPERATOR-ONLY. Production writes require a signed, SHA-bound, single-use
    authorization artifact (.claude/hooks/deploy_authorization.py) whose key lives
    outside this repository. An agent that can read every file here still cannot mint
    one. pz-deploy-guard.py independently denies agent invocation by script name.
#>
[CmdletBinding()]
param(
    [string]$ReviewedSHA,
    [switch]$WhatIf,
    [switch]$Rollback,
    [string]$Unit,
    [ValidateSet("App", "Engine", "Both")][string]$Scope = "Both",
    [switch]$Bootstrap,
    [switch]$ForceUnlock,
    [switch]$NoRun
)

$ErrorActionPreference = "Stop"

$script:UNIT_RX = '^[0-9a-f]{40}-\d{8}-\d{6}$'
$script:SHA_RX = '^[0-9a-f]{40}$'

# ---------------------------------------------------------------- configuration
function Get-DeployConfig {
    param([string]$ConfigPath)
    if (-not $ConfigPath) { $ConfigPath = Join-Path $PSScriptRoot "windows_prod_v2.json" }
    if (-not (Test-Path $ConfigPath)) { throw "BLOCKED: config not found: $ConfigPath" }
    $cfg = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $required = @(
        "schema_version", "service", "source_root", "source_app", "runtime_app",
        "runtime_engine", "artifact_root", "backup_root", "version_file", "lock_file",
        "engine_files", "protected_dirs", "protected_files", "protected_runtime_paths",
        "forbidden_flags", "robocopy_fatal_exit", "robocopy_suspect_exit",
        "service_wait_seconds", "test_baseline_contract", "authorization_helper"
    )
    foreach ($k in $required) { if ($null -eq $cfg.$k) { throw "BLOCKED: config key missing: $k" } }
    if ($cfg.schema_version -ne 2) { throw "BLOCKED: unsupported config schema_version $($cfg.schema_version)" }

    # Empty protection arrays are catastrophic: /MIR convergence would DELETE production
    # storage, logs and cloudflared. A present-but-empty key must fail as hard as a
    # missing one.
    foreach ($k in @("engine_files", "protected_dirs", "protected_files", "protected_runtime_paths")) {
        if (@($cfg.$k).Count -lt 1) {
            throw "BLOCKED: config '$k' is present but EMPTY. Refusing: mirror convergence without protection would delete production runtime data."
        }
    }
    return $cfg
}

function Assert-Authorization {
    param($Cfg, [string]$Sha, [string]$Action, [string]$UnitScope)
    # Never called in plan mode -- a zero-write run needs no authorization.
    $helper = Join-Path (Split-Path $PSScriptRoot -Parent) $Cfg.authorization_helper
    if (-not (Test-Path $helper)) { throw "BLOCKED: authorization helper missing: $helper" }
    $pyExe = (Get-Command python -ErrorAction SilentlyContinue)
    if (-not $pyExe) { throw "BLOCKED: python not on PATH; cannot evaluate deploy authorization" }
    $out = & python $helper $Sha $Action $UnitScope 2>&1
    $code = $LASTEXITCODE
    Write-Host "  authorization: $out"
    if ($code -ne 0) {
        throw "BLOCKED: not authorized for $Action of $Sha (scope $UnitScope). Production writes require a signed, SHA-bound, single-use operator authorization. This step is operator-only."
    }
}

function Invoke-Robocopy {
    param($Cfg, [string]$Source, [string]$Dest, [string[]]$Extra, [string]$What, [switch]$InventoryClassified)
    foreach ($bad in $Cfg.forbidden_flags) {
        if ($Extra -contains $bad) { throw "BLOCKED: forbidden robocopy flag $bad in $What" }
    }
    Write-Host "  copy [$What] $Source -> $Dest $($Extra -join ' ')"
    if ($script:PlanOnly) { return }
    & robocopy $Source $Dest @Extra | Out-Null
    $code = $LASTEXITCODE
    if ($code -ge $Cfg.robocopy_fatal_exit) { throw "BLOCKED: $What failed, exit $code" }
    if ($code -ge $Cfg.robocopy_suspect_exit -and -not $InventoryClassified) {
        throw "BLOCKED: $What returned exit $code (mismatch) and was not inventory-classified"
    }
    Write-Host "  copy [$What] exit $code (accepted)"
}

function New-Manifest {
    param([string]$Root, [string]$OutFile)
    if ($script:PlanOnly) { Write-Host "  would write manifest $OutFile"; return }
    Get-ChildItem $Root -Recurse -File |
        Get-FileHash -Algorithm SHA256 |
        Select-Object @{n = "Rel"; e = { $_.Path.Substring($Root.Length).TrimStart('\') } }, Hash |
        Sort-Object Rel | Export-Csv $OutFile -NoTypeInformation -Encoding UTF8
    $n = @(Import-Csv $OutFile).Count
    if ($n -lt 1) { throw "BLOCKED: manifest $OutFile is empty - not a valid artifact" }
    Write-Host "  manifest $OutFile ($n files)"
}

function Test-AgainstManifest {
    param([string]$ManifestFile, [string]$Root, [string]$What, [switch]$Optional)
    if ($script:PlanOnly) { Write-Host "  would verify $What"; return $true }
    if (-not (Test-Path $ManifestFile)) {
        if ($Optional) { Write-Host "  $What : no manifest (component not in this unit) - skipped"; return $false }
        throw "BLOCKED: manifest missing for $What : $ManifestFile - unit is not restorable"
    }
    $bad = @()
    foreach ($row in Import-Csv $ManifestFile) {
        $dst = Join-Path $Root $row.Rel
        if (-not (Test-Path $dst)) { $bad += "MISSING: $($row.Rel)" }
        elseif ((Get-FileHash $dst -Algorithm SHA256).Hash -ne $row.Hash) { $bad += "MISMATCH: $($row.Rel)" }
    }
    if ($bad.Count) {
        $bad | Select-Object -First 20 | ForEach-Object { Write-Host "    $_" }
        throw "BLOCKED: $What failed manifest verification ($($bad.Count) discrepancies)"
    }
    Write-Host "  $What verified against manifest"
    return $true
}

function Set-ServiceState {
    param($Cfg, [ValidateSet("Stopped", "Running")][string]$Target)
    $svc = $Cfg.service
    if ($script:PlanOnly) { Write-Host "  would drive $svc to $Target"; return }
    if ($Target -eq "Stopped") { & sc.exe stop $svc | Out-Null } else { & sc.exe start $svc | Out-Null }
    $deadline = (Get-Date).AddSeconds($Cfg.service_wait_seconds)
    while ((Get-Service $svc).Status -ne $Target -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 1 }
    if ((Get-Service $svc).Status -ne $Target) {
        throw "BLOCKED: $svc did not reach $Target within $($Cfg.service_wait_seconds)s"
    }
    Write-Host "  $svc is $Target"
}

function Enter-DeployLock {
    param($Cfg)
    if ($script:PlanOnly) { Write-Host "  would take deploy lock (plan mode takes none)"; return }
    $lock = $Cfg.lock_file
    $dir = Split-Path $lock -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }

    if (Test-Path $lock) {
        $content = Get-Content $lock -Raw
        $lockPid = if ($content -match 'pid=(\d+)') { [int]$Matches[1] } else { 0 }
        $alive = $false
        if ($lockPid -gt 0) { $alive = $null -ne (Get-Process -Id $lockPid -ErrorAction SilentlyContinue) }
        if ($alive) {
            throw "BLOCKED: another deployment is running (pid $lockPid). Concurrent execution refused. Lock: $content"
        }
        if (-not $ForceUnlock) {
            throw "BLOCKED: a STALE lock exists - its process (pid $lockPid) is no longer running. Lock: $content`nIf no deploy is in progress, re-run with -ForceUnlock to clear it. If the service is stopped, roll back first: -Rollback -Unit <unit>."
        }
        Write-Host "  STALE LOCK CLEARED (audit): $content"
        Remove-Item $lock -Force
    }
    # O_EXCL-equivalent: fails if another writer won the race between the check above
    # and here, so the lock is not merely advisory.
    $fs = [System.IO.File]::Open($lock, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
    try {
        $bytes = [System.Text.Encoding]::ASCII.GetBytes("pid=$PID user=$env:USERNAME started=$(Get-Date -Format o)")
        $fs.Write($bytes, 0, $bytes.Length)
    }
    finally { $fs.Close() }
}

function Exit-DeployLock {
    param($Cfg)
    if (-not $script:PlanOnly -and (Test-Path $Cfg.lock_file)) { Remove-Item $Cfg.lock_file -Force }
}

function Get-ProtectedArgs {
    param($Cfg)
    $a = @("/XD"); $a += $Cfg.protected_dirs; $a += "/XF"; $a += $Cfg.protected_files
    return $a
}

function Write-VersionFile {
    param($Cfg, [string]$Sha)
    # SOLE writer of version_file. Consumed at runtime by
    # service/app/api/routes_webhooks_wfirma_status.py (_SHA_FILE), which reads it with
    # Python's utf-8 codec and .strip(). Out-File -Encoding utf8 on PowerShell 5.1
    # emits a BOM; Python's utf-8 codec does NOT strip it and ﻿ is not whitespace,
    # so the endpoint would serve "﻿<sha>". ASCII is exact for hex SHAs and
    # BOM-free by construction.
    if ($script:PlanOnly) { Write-Host "  would write version file = $Sha"; return }
    [System.IO.File]::WriteAllText($Cfg.version_file, $Sha, (New-Object System.Text.ASCIIEncoding))
    $check = [System.IO.File]::ReadAllBytes($Cfg.version_file)
    if ($check.Length -ge 3 -and $check[0] -eq 0xEF -and $check[1] -eq 0xBB -and $check[2] -eq 0xBF) {
        throw "BLOCKED: version file was written with a BOM - the status endpoint would serve a corrupted SHA"
    }
    Write-Host "  version file written (BOM-free) = $Sha"
}

function Read-VersionMarker {
    # Reads a version-marker file and returns the single 40-hex commit SHA it contains,
    # lowercased, tolerant of a BOM and surrounding whitespace (the same shape the
    # runtime status endpoint and Test-PZDeployClose.ps1 accept). Returns $null when the
    # file is absent, unreadable, or does not hold exactly one full SHA. It NEVER guesses:
    # an unrecognisable marker is $null, so callers fail closed rather than trusting a
    # partial or corrupt identity.
    param([string]$Path)
    if (-not $Path -or -not (Test-Path $Path)) { return $null }
    try { $bytes = [System.IO.File]::ReadAllBytes($Path) } catch { return $null }
    $text = [System.Text.Encoding]::UTF8.GetString($bytes)
    $val = $text.Trim([char]0xFEFF, ' ', "`r", "`n", "`t").ToLower()
    if ($val -match $script:SHA_RX) { return $val }
    return $null
}

# ---------------------------------------------------------------- phases
function Invoke-Preflight {
    param($Cfg)
    $SRC = $Cfg.source_root
    Write-Host "== Preflight: deploy-source identity =="
    if (-not (Test-Path (Join-Path $SRC ".git"))) { throw "BLOCKED: $SRC is not a git working tree" }
    $branch = & git -C $SRC branch --show-current
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED: git branch failed in $SRC" }
    if ($branch -ne "main") { throw "BLOCKED: deploy source is not on main (is '$branch')" }
    $dirty = & git -C $SRC status --porcelain
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED: git status failed in $SRC" }
    if ($dirty) { throw "BLOCKED: deploy source is dirty" }
    & git -C $SRC fetch origin | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED: git fetch failed - origin/main is unverifiable" }
    & git -C $SRC merge-base --is-ancestor HEAD origin/main
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED: $SRC has local-only commits or diverged from origin/main (Lesson D)" }
    Write-Host "  source OK: $SRC on '$branch', clean, no local-only commits"
}

function Assert-ReviewedTarget {
    <#
      The reviewed target is the SHA the OPERATOR supplies, never a value recomputed
      from a fresh origin/main read. The previous design captured the range on each
      invocation and compared it to itself, so anything pushed between the gate run
      and the deploy run shipped unreviewed. Here the binding is explicit.
    #>
    param($Cfg, [string]$Sha)
    $SRC = $Cfg.source_root
    if ($Sha -notmatch $script:SHA_RX) {
        throw "BLOCKED: -ReviewedSHA must be a full 40-character lowercase commit SHA (got '$Sha')"
    }
    & git -C $SRC cat-file -e "$Sha^{commit}" 2>$null
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED: $Sha does not exist in $SRC" }

    $current = (& git -C $SRC rev-parse HEAD).Trim()
    if ($current -eq $Sha) {
        Write-Host "  source already at reviewed target $Sha"
    }
    else {
        & git -C $SRC merge-base --is-ancestor $current $Sha
        if ($LASTEXITCODE -ne 0) { throw "BLOCKED: reviewed target $Sha is not a descendant of the current source HEAD $current" }
    }

    $remote = (& git -C $SRC rev-parse origin/main).Trim()
    if ($remote -ne $Sha) {
        & git -C $SRC merge-base --is-ancestor $Sha origin/main
        $isAncestor = ($LASTEXITCODE -eq 0)
        if ($isAncestor) {
            throw "BLOCKED: origin/main ($remote) has advanced BEYOND the reviewed target $Sha. Re-run the 7-agent gate against the new range; do not deploy a SHA the gate did not review."
        }
        throw "BLOCKED: reviewed target $Sha is not on origin/main (origin/main is $remote)"
    }

    Write-Host "== Reviewed range =="
    & git -C $SRC log --oneline "$current..$Sha"
    & git -C $SRC diff --name-status "$current..$Sha"

    if ($script:PlanOnly) { Write-Host "  would fast-forward to $Sha"; return }
    if ($current -ne $Sha) {
        & git -C $SRC merge --ff-only $Sha | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "BLOCKED: fast-forward to $Sha failed" }
    }
    $head = (& git -C $SRC rev-parse HEAD).Trim()
    if ($head -ne $Sha) { throw "BLOCKED: HEAD $head != reviewed target $Sha" }
    Write-Host "  certified source at reviewed target $Sha"
}

function New-ReleaseArtifact {
    param($Cfg, [string]$Sha)
    $art = Join-Path $Cfg.artifact_root "app-$Sha"
    Write-Host "== Stage immutable artifact =="
    if ((Test-Path $art) -and -not $script:PlanOnly) {
        throw "BLOCKED: artifact $art already exists - releases are immutable. If a previous deploy of this SHA failed, roll back with -Rollback -Unit <unit>, or remove the artifact deliberately before re-staging."
    }
    if (-not $script:PlanOnly) { New-Item -ItemType Directory -Path $art -Force | Out-Null }
    Invoke-Robocopy -Cfg $Cfg -Source $Cfg.source_app -Dest $art -Extra (@("/E", "/COPY:DAT") + (Get-ProtectedArgs -Cfg $Cfg)) -What "artifact staging"
    New-Manifest -Root $art -OutFile "$art.manifest.csv"
    return $art
}

function New-BackupUnit {
    param($Cfg, [string]$Sha, [string]$UnitScope)
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $unit = "$Sha-$stamp"
    $bak = Join-Path $Cfg.backup_root $unit
    Write-Host "== Pre-deploy backup (taken with the service STOPPED) =="
    $appPresent = (Test-Path $Cfg.runtime_app)
    $enginePresent = (Test-Path $Cfg.runtime_engine)
    if (-not $appPresent -and -not $Bootstrap) {
        throw "BLOCKED: $($Cfg.runtime_app) does not exist. A first-ever deploy requires -Bootstrap, which records that NO rollback target exists."
    }
    if (-not $script:PlanOnly) {
        New-Item -ItemType Directory -Path (Join-Path $bak "app") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $bak "engine") -Force | Out-Null
        # The pre-deploy production version marker is the SHA the bytes about to be backed
        # up ACTUALLY represent (restored_sha) - a DIFFERENT authority from $Sha, the
        # incoming deployment SHA (deployment_sha) that will later authorize a rollback.
        # It is read BEFORE any mutation, because the forward deploy rewrites the marker to
        # $Sha at the very end and this is the only moment the prior identity is visible.
        # An absent or unreadable marker is recorded as $null (never guessed): a later
        # rollback then fails closed rather than stamping the wrong identity.
        $restoredSha = if ($appPresent) { Read-VersionMarker -Path $Cfg.version_file } else { $null }
        # Surface the unrollbackable unit AT DEPLOY TIME. Without this the unit is minted
        # silently and the defect is only discovered mid-incident, when the rollback that
        # was supposed to be the remedy refuses. This is a warning, not a block: the
        # forward deploy is still correct, and blocking it would strand production on the
        # very state the operator is trying to leave.
        if ($appPresent -and -not $restoredSha) {
            Write-Warning "PROVENANCE: no readable pre-deploy version marker at $($Cfg.version_file). Unit $unit is being recorded WITHOUT a restored-content SHA and a rollback to it will be REFUSED until provenance is supplied from an independent record (see production_deployment_rule.md, 'Legacy unit recovery')."
        }
        # unit.json is written FIRST so a crash mid-backup still leaves the unit
        # self-describing; 'complete' is flipped only after both manifests exist. 'sha' is
        # retained for compatibility with units/readers minted before the split;
        # deployment_sha and restored_sha are the two explicit provenance authorities.
        [pscustomobject]@{
            unit = $unit; sha = $Sha; deployment_sha = $Sha; restored_sha = $restoredSha
            scope = $UnitScope; created = (Get-Date -Format o)
            app_backed_up = $appPresent; engine_backed_up = $enginePresent
            bootstrap = [bool]$Bootstrap; complete = $false
        } | ConvertTo-Json | Set-Content (Join-Path $bak "unit.json") -Encoding UTF8
        # A write-once, immutable snapshot of the pre-deploy marker. unit.json is rewritten
        # when 'complete' flips true, so this copy is the tamper-evident corroborating
        # source that Resolve-RestoredSha cross-checks at rollback time.
        if ($appPresent -and (Test-Path $Cfg.version_file)) {
            [System.IO.File]::WriteAllBytes((Join-Path $bak "version.pre.txt"), [System.IO.File]::ReadAllBytes($Cfg.version_file))
        }
    }
    if ($appPresent) {
        Invoke-Robocopy -Cfg $Cfg -Source $Cfg.runtime_app -Dest (Join-Path $bak "app") -Extra (@("/E", "/COPY:DAT") + (Get-ProtectedArgs -Cfg $Cfg)) -What "app backup"
        New-Manifest -Root (Join-Path $bak "app") -OutFile (Join-Path $bak "app.manifest.csv")
    }
    if ($enginePresent) {
        Invoke-Robocopy -Cfg $Cfg -Source $Cfg.runtime_engine -Dest (Join-Path $bak "engine") -Extra (@("/COPY:DAT") + $Cfg.engine_files) -What "engine backup"
        if (-not $script:PlanOnly) {
            foreach ($ef in $Cfg.engine_files) {
                if (-not (Test-Path (Join-Path $bak "engine\$ef"))) {
                    throw "BLOCKED: engine backup incomplete - $ef absent at backup time. A named-but-absent file exits robocopy 0/1 and would otherwise pass silently."
                }
            }
        }
        New-Manifest -Root (Join-Path $bak "engine") -OutFile (Join-Path $bak "engine.manifest.csv")
    }
    if (-not $script:PlanOnly) {
        $meta = Get-Content (Join-Path $bak "unit.json") -Raw | ConvertFrom-Json
        $meta.complete = $true
        $meta | ConvertTo-Json | Set-Content (Join-Path $bak "unit.json") -Encoding UTF8
    }
    Write-Host "  backup unit: $unit (scope=$UnitScope)"
    return @{ Unit = $unit; Path = $bak }
}

function Get-DestinationInventory {
    param($Cfg, [string]$ArtifactPath)
    Write-Host "== Destination-only inventory (gate for mirroring) =="
    if ($script:PlanOnly) { Write-Host "  would inventory extraneous paths"; return @() }
    if (-not (Test-Path $Cfg.runtime_app)) { return @() }
    $artFiles = @{}
    Get-ChildItem $ArtifactPath -Recurse -File | ForEach-Object {
        $artFiles[$_.FullName.Substring($ArtifactPath.Length).TrimStart('\')] = $true
    }
    $extra = @()
    foreach ($f in Get-ChildItem $Cfg.runtime_app -Recurse -File) {
        $rel = $f.FullName.Substring($Cfg.runtime_app.Length).TrimStart('\')
        if ($Cfg.protected_dirs -contains $rel.Split('\')[0]) { continue }
        if (-not $artFiles.ContainsKey($rel)) { $extra += $rel }
    }
    if ($extra.Count) {
        Write-Host "  $($extra.Count) destination-only path(s) will be REMOVED by convergence:"
        $extra | Select-Object -First 40 | ForEach-Object { Write-Host "    $_" }
    }
    else { Write-Host "  no destination-only paths" }
    return $extra
}

function Invoke-Converge {
    param($Cfg, [string]$ArtifactPath)
    Write-Host "== Converge production to the artifact =="
    Invoke-Robocopy -Cfg $Cfg -Source $ArtifactPath -Dest $Cfg.runtime_app -Extra (@("/MIR", "/COPY:DAT") + (Get-ProtectedArgs -Cfg $Cfg)) -What "application convergence" -InventoryClassified
}

function Invoke-EngineSync {
    param($Cfg)
    Write-Host "== Engine sync (Lesson J - separate copy) =="
    Invoke-Robocopy -Cfg $Cfg -Source $Cfg.source_root -Dest $Cfg.runtime_engine -Extra (@("/COPY:DAT") + $Cfg.engine_files) -What "engine sync"
    if ($script:PlanOnly) { return }
    foreach ($ef in $Cfg.engine_files) {
        $s = Join-Path $Cfg.source_root $ef
        $d = Join-Path $Cfg.runtime_engine $ef
        if (-not (Test-Path $s)) { throw "BLOCKED: engine source missing: $s" }
        if (-not (Test-Path $d)) { throw "BLOCKED: engine file missing at destination: $d" }
        if ((Get-FileHash $s -Algorithm SHA256).Hash -ne (Get-FileHash $d -Algorithm SHA256).Hash) {
            throw "BLOCKED: engine hash mismatch for $ef - production would run a stale calculation engine"
        }
        Write-Host "  engine OK: $ef"
    }
}

function Resolve-RestoredSha {
    # The SHA the backed-up bytes actually represent - the value production must advertise
    # in its version marker AFTER a restore. This is a DIFFERENT authority from the unit's
    # deployment SHA (which authorizes the rollback); conflating them is exactly the defect
    # this function prevents, because the old code stamped the newer deployment SHA over
    # older restored bytes. Trusted sources, in order:
    #   1. unit.json 'restored_sha' - recorded by New-BackupUnit before any mutation.
    #   2. the write-once 'version.pre.txt' snapshot captured beside the backup.
    # When both exist they MUST agree; a disagreement is unresolved provenance and is
    # refused rather than guessed. When NEITHER exists (a legacy unit created before
    # provenance tracking, or a marker unreadable at backup time) the rollback is REFUSED:
    # the operator must establish the pre-deploy SHA from an independent record. The
    # deployment SHA is deliberately NOT a fallback - silently stamping it was the bug.
    param($Meta, [string]$BackupPath, [string]$UnitId)
    $fromMeta = $null
    if ($Meta -and $Meta.restored_sha) {
        $cand = "$($Meta.restored_sha)".ToLower()
        if ($cand -match $script:SHA_RX) { $fromMeta = $cand }
    }
    $fromCopy = Read-VersionMarker -Path (Join-Path $BackupPath "version.pre.txt")

    if ($fromMeta -and $fromCopy -and $fromMeta -ne $fromCopy) {
        throw "BLOCKED: unit $UnitId has inconsistent restored-content evidence (unit.json restored_sha=$fromMeta vs version.pre.txt=$fromCopy). Refusing to guess which SHA the restored bytes represent; operator disposition required."
    }
    $restored = if ($fromMeta) { $fromMeta } elseif ($fromCopy) { $fromCopy } else { $null }
    if (-not $restored) {
        throw "BLOCKED: unit $UnitId records no restored-content SHA. This is a legacy backup unit created before rollback-provenance tracking, or its pre-deploy version marker was unreadable when the backup was taken. Rollback is refused so production cannot advertise a SHA that does not match the restored bytes. The unit's own deployment SHA (the unit-id prefix) is the deployment being rolled back FROM, not the restored content, and is NOT used as a fallback. Operator disposition required: establish the pre-deploy content SHA from an independent record - the deployment SHA of the immediately-preceding backup unit (the deploy this one replaced), or the last 'Test-PZDeployClose.ps1 -ExpectedSHA' output recorded before this unit's deploy - then restore and set the version marker to that value deliberately."
    }
    return $restored
}

function Invoke-Rollback {
    param($Cfg, [string]$UnitId)
    if (-not $UnitId) { throw "BLOCKED: -Rollback requires -Unit" }
    if ($UnitId -notmatch $script:UNIT_RX) {
        throw "BLOCKED: -Unit '$UnitId' is not a valid unit identifier (expected <40-hex-sha>-<yyyyMMdd>-<HHmmss>). Separators, rooted paths and traversal are refused."
    }
    $bak = Join-Path $Cfg.backup_root $UnitId
    Write-Host "== ROLLBACK from unit $UnitId =="
    if (-not (Test-Path $bak)) { throw "BLOCKED: backup unit not found: $bak" }

    $meta = $null
    if (Test-Path (Join-Path $bak "unit.json")) { $meta = Get-Content (Join-Path $bak "unit.json") -Raw | ConvertFrom-Json }
    if ($meta -and $meta.bootstrap -and -not (Test-Path (Join-Path $bak "app.manifest.csv"))) {
        throw "BLOCKED: unit $UnitId was a bootstrap deploy with no prior state to restore. Recovery is manual and operator-directed."
    }
    # AUTHORIZATION identity: the SHA whose deployment created this unit. This binding is
    # security-reviewed and unchanged - a rollback is authorized against the deployment SHA
    # recorded when the backup was taken, never against the restored-content SHA.
    # deployment_sha is the explicit field; 'sha' and the unit-id prefix are the
    # compatibility fallbacks for units minted before that field existed.
    $deploymentSha = if ($meta -and $meta.deployment_sha) { $meta.deployment_sha }
                     elseif ($meta -and $meta.sha) { $meta.sha }
                     else { $UnitId.Split('-')[0] }
    # The authorization identity is shape-validated before it is used to authorize
    # anything. Two of the three sources above are untrusted input - a hand-edited or
    # corrupt unit.json, and a directory name that only conventionally starts with a SHA -
    # so a malformed value must be refused here rather than reaching Assert-Authorization
    # as an unmatchable string or an empty binding.
    if ($deploymentSha -notmatch $script:SHA_RX) {
        throw "BLOCKED: unit $UnitId yields a malformed deployment SHA '$deploymentSha'. A rollback cannot be authorized against an unverifiable identity; correct the unit metadata from an independent record."
    }

    # RESTORED-CONTENT identity: the SHA the backed-up bytes represent, which production
    # must advertise after the restore. Established ONLY from trusted metadata; a unit that
    # cannot establish it is refused here, before the service is touched.
    $restoredSha = Resolve-RestoredSha -Meta $meta -BackupPath $bak -UnitId $UnitId

    if (-not $script:PlanOnly) { Assert-Authorization -Cfg $Cfg -Sha $deploymentSha -Action "rollback" -UnitScope $Scope }
    Enter-DeployLock -Cfg $Cfg
    # Tracks how far the rollback got, so the failure handler can state what production is
    # actually in rather than describing every possibility. Set immediately before each
    # transition, never after, so a throw inside a step is attributed to that step.
    $stage = "not started"
    try {
        Set-ServiceState -Cfg $Cfg -Target Stopped
        $stage = "service stopped; nothing restored yet"
        # Each component is independent: a unit that never carried an engine backup
        # must still restore its application tree.
        $didApp = Test-AgainstManifest -ManifestFile (Join-Path $bak "app.manifest.csv") -Root (Join-Path $bak "app") -What "backup app integrity" -Optional
        if ($didApp) {
            # /MIR deletes destination-only files before it finishes copying, so from here
            # until the verification below the tree is genuinely mid-overwrite. The stage
            # must say so DURING the step: a throw out of robocopy that still reported
            # "nothing restored yet" would tell the operator the tree is intact when it is
            # half-written - the one moment where that error is most costly.
            $stage = "service stopped; APP RESTORE IN PROGRESS - the application tree is mid-overwrite"
            Invoke-Robocopy -Cfg $Cfg -Source (Join-Path $bak "app") -Dest $Cfg.runtime_app -Extra (@("/MIR", "/COPY:DAT") + (Get-ProtectedArgs -Cfg $Cfg)) -What "app restore" -InventoryClassified
            [void](Test-AgainstManifest -ManifestFile (Join-Path $bak "app.manifest.csv") -Root $Cfg.runtime_app -What "restored application")
            $stage = "application tree restored and verified"
        }
        $didEngine = Test-AgainstManifest -ManifestFile (Join-Path $bak "engine.manifest.csv") -Root (Join-Path $bak "engine") -What "backup engine integrity" -Optional
        if ($didEngine) {
            $stage = "$stage; ENGINE RESTORE IN PROGRESS - engine files are mid-overwrite"
            Invoke-Robocopy -Cfg $Cfg -Source (Join-Path $bak "engine") -Dest $Cfg.runtime_engine -Extra (@("/COPY:DAT") + $Cfg.engine_files) -What "engine restore"
            [void](Test-AgainstManifest -ManifestFile (Join-Path $bak "engine.manifest.csv") -Root $Cfg.runtime_engine -What "restored engine")
        }
        if (-not $didApp -and -not $didEngine) { throw "BLOCKED: unit $UnitId contains no restorable component" }
        $stage = "files restored (app=$didApp engine=$didEngine); version marker NOT yet stamped"
        # Stamp the marker with the RESTORED-content SHA, not the deployment SHA. This is
        # the fix: production must advertise the identity of the bytes just restored, not
        # the SHA of the deployment being rolled back. The marker is the whole-deploy
        # identity (the forward deploy writes it unconditionally regardless of -Scope), so a
        # rollback restores it wholesale to the captured pre-deploy value for symmetry; it is
        # deliberately not re-derived per restored component.
        Write-VersionFile -Cfg $Cfg -Sha $restoredSha
        $stage = "files restored and version marker stamped; closure assertion pending"
        # Closure assertion: read the marker back and require it to equal restored_sha. A
        # mismatch means the advertised SHA and the restored bytes disagree - the exact
        # defect this path exists to prevent - so refuse to report success and leave the
        # service STOPPED for operator inspection rather than start on an inconsistent state.
        if (-not $script:PlanOnly) {
            $onDisk = Read-VersionMarker -Path $Cfg.version_file
            if ($onDisk -ne $restoredSha) {
                throw "BLOCKED: post-rollback version marker '$onDisk' does not equal the restored-content SHA '$restoredSha'. Production bytes and the advertised version disagree; the service is left STOPPED for operator inspection."
            }
        }
        # Past this point the restoration itself is DONE and proven: the bytes are back, the
        # marker matches them, and only starting the service remains. The catch block keys
        # its remedy off this phrase, because re-running a rollback that already succeeded
        # is not a remedy - see there.
        $stage = "files restored and version marker stamped; closure assertion PASSED; starting the service"
        Set-ServiceState -Cfg $Cfg -Target Running
        if (-not $script:PlanOnly) {
            Write-Host "ROLLBACK COMPLETE - unit $UnitId restored to content $restoredSha (deployment $deploymentSha; app=$didApp engine=$didEngine); service Running"
        }
        else {
            Write-Host "PLAN COMPLETE - nothing was written. Unit $UnitId would restore content $restoredSha (deployment $deploymentSha; app=$didApp engine=$didEngine); the marker and service are unchanged."
        }
    }
    catch {
        # A rollback is the remedy path: it runs when production is already wrong, and it
        # stops the service to do its work. A bare exception here leaves the operator with
        # a stopped service, an unknown degree of restoration, and no named next step -
        # the forward deploy states its recovery position explicitly and the remedy path
        # must not be the weaker of the two. Reporting only; the throw is preserved so the
        # exit code still fails and the lock still releases in the finally.
        Write-Host ""
        Write-Host "RECOVERY STATE: ROLLBACK_FAILED"
        Write-Host "  Rollback of unit $UnitId failed: $($_.Exception.Message)"
        Write-Host "  Position when it failed: $stage"
        if ($stage -eq "not started") {
            # The stop itself failed, so the service is in whatever state it already was and
            # nothing was restored. Asserting it is stopped would be false, and warning the
            # operator off starting it would be worse - production content is untouched.
            Write-Host "  Nothing was restored and the version marker was not touched; production content"
            Write-Host "  is unchanged. Check the service state first - stopping it is what failed."
            Write-Host "  Re-running the same rollback is the supported remedy - it restores and re-stamps"
            Write-Host "  from the same immutable unit, and requires a fresh rollback authorization artifact:"
            Write-Host "      Deploy-PZ.ps1 -Rollback -Unit $UnitId"
        }
        elseif ($stage -like "*closure assertion PASSED*") {
            # The restoration SUCCEEDED and was verified; only the service start failed.
            # Re-running would repeat identical work, hit the same startup failure, and burn
            # a second single-use authorization to achieve nothing. The remaining problem is
            # the service, not the provenance.
            Write-Host "  The restore SUCCEEDED and was verified: the tree is at content $restoredSha and the"
            Write-Host "  version marker agrees. Only starting the service failed."
            Write-Host "  Do NOT re-run the rollback - it would redo work that is already correct, fail the"
            Write-Host "  same way, and consume another single-use authorization. Diagnose the startup"
            Write-Host "  failure (service log, port $($Cfg.port), .env), then start the service directly."
        }
        else {
            Write-Host "  The service is STOPPED. Do NOT start it until the tree and the version marker agree."
            Write-Host "  Advertised identity should be content $restoredSha (deployment $deploymentSha)."
            Write-Host "  Re-running the same rollback is the supported remedy - it restores and re-stamps"
            Write-Host "  from the same immutable unit, and requires a fresh rollback authorization artifact:"
            Write-Host "      Deploy-PZ.ps1 -Rollback -Unit $UnitId"
        }
        Write-Host "  Do not stamp the version marker by hand; it has exactly one writer by design."
        throw
    }
    finally { Exit-DeployLock -Cfg $Cfg }
}

# ---------------------------------------------------------------- entry point
function Invoke-Deploy {
    param([switch]$PlanOnly)
    $script:PlanOnly = [bool]$PlanOnly
    $cfg = Get-DeployConfig
    if ($script:PlanOnly) { Write-Host "*** -WhatIf: PLAN ONLY - no writes, no lock, no service change, no authorization required ***" }

    if ($Rollback) { Invoke-Rollback -Cfg $cfg -UnitId $Unit; return }

    if (-not $ReviewedSHA) {
        throw "BLOCKED: -ReviewedSHA is required. Supply the exact SHA approved by the 7-agent gate; the deployed target is never inferred from origin/main."
    }
    Invoke-Preflight -Cfg $cfg
    Assert-ReviewedTarget -Cfg $cfg -Sha $ReviewedSHA
    if (-not $script:PlanOnly) { Assert-Authorization -Cfg $cfg -Sha $ReviewedSHA -Action "deploy" -UnitScope $Scope }

    # Lock BEFORE any mutable preparation so two operators cannot both stage or back up.
    Enter-DeployLock -Cfg $cfg
    try {
        Set-ServiceState -Cfg $cfg -Target Stopped
        $unit = $null
        try {
            $art = New-ReleaseArtifact -Cfg $cfg -Sha $ReviewedSHA
            $unit = New-BackupUnit -Cfg $cfg -Sha $ReviewedSHA -UnitScope $Scope
            Get-DestinationInventory -Cfg $cfg -ArtifactPath $art | Out-Null
        }
        catch {
            Write-Host ""
            Write-Host "RECOVERY STATE: SERVICE_STOPPED_NO_DEPLOY"
            Write-Host "  Preparation failed BEFORE production was modified: $($_.Exception.Message)"
            Write-Host "  Production files are unchanged. Safe restart:  sc.exe start $($cfg.service)"
            if ($unit) { Write-Host "  Or roll back:  Deploy-PZ.ps1 -Rollback -Unit $($unit.Unit)" }
            throw
        }
        # From here production IS being modified. A failure leaves a partially
        # converged tree, so the recovery state differs from the preparation phase and
        # must name the rollback unit explicitly -- an operator mid-incident should not
        # have to scroll back through robocopy output to find it.
        try {
            if ($Scope -ne "Engine") { Invoke-Converge -Cfg $cfg -ArtifactPath $art }
            if ($Scope -ne "App") { Invoke-EngineSync -Cfg $cfg }
            if ($Scope -ne "Engine") {
                [void](Test-AgainstManifest -ManifestFile "$art.manifest.csv" -Root $cfg.runtime_app -What "deployed application")
            }
            Write-VersionFile -Cfg $cfg -Sha $ReviewedSHA
            Set-ServiceState -Cfg $cfg -Target Running
        }
        catch {
            Write-Host ""
            Write-Host "RECOVERY STATE: PARTIAL_DEPLOY"
            Write-Host "  Production WAS being modified when this failed: $($_.Exception.Message)"
            Write-Host "  The service is STOPPED and the application tree may be partially converged."
            Write-Host "  DO NOT start the service on a partial tree. Roll back:"
            Write-Host "      Deploy-PZ.ps1 -Rollback -Unit $($unit.Unit)"
            Write-Host "  (a rollback authorization artifact for $ReviewedSHA is required)"
            throw
        }
    }
    finally { Exit-DeployLock -Cfg $cfg }

    if (-not $script:PlanOnly) {
        Write-Host ""
        Write-Host "DEPLOY COMPLETE  sha=$ReviewedSHA  unit=$($unit.Unit)  scope=$Scope"
        Write-Host "Validate:  Test-PZDeployClose.ps1 -ExpectedSHA $ReviewedSHA"
        Write-Host "Rollback:  Deploy-PZ.ps1 -Rollback -Unit $($unit.Unit)"
    }
    else {
        Write-Host ""
        Write-Host "PLAN COMPLETE - nothing was written. No unit exists; no rollback identifier is implied."
    }
}

if (-not $NoRun) { Invoke-Deploy -PlanOnly:$WhatIf }
