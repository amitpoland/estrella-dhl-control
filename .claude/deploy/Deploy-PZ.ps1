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
        # unit.json is written FIRST so a crash mid-backup still leaves the unit
        # self-describing; 'complete' is flipped only after both manifests exist.
        [pscustomobject]@{
            unit = $unit; sha = $Sha; scope = $UnitScope; created = (Get-Date -Format o)
            app_backed_up = $appPresent; engine_backed_up = $enginePresent
            bootstrap = [bool]$Bootstrap; complete = $false
        } | ConvertTo-Json | Set-Content (Join-Path $bak "unit.json") -Encoding UTF8
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
    $sha = if ($meta -and $meta.sha) { $meta.sha } else { $UnitId.Split('-')[0] }

    if (-not $script:PlanOnly) { Assert-Authorization -Cfg $Cfg -Sha $sha -Action "rollback" -UnitScope $Scope }
    Enter-DeployLock -Cfg $Cfg
    try {
        Set-ServiceState -Cfg $Cfg -Target Stopped
        # Each component is independent: a unit that never carried an engine backup
        # must still restore its application tree.
        $didApp = Test-AgainstManifest -ManifestFile (Join-Path $bak "app.manifest.csv") -Root (Join-Path $bak "app") -What "backup app integrity" -Optional
        if ($didApp) {
            Invoke-Robocopy -Cfg $Cfg -Source (Join-Path $bak "app") -Dest $Cfg.runtime_app -Extra (@("/MIR", "/COPY:DAT") + (Get-ProtectedArgs -Cfg $Cfg)) -What "app restore" -InventoryClassified
            [void](Test-AgainstManifest -ManifestFile (Join-Path $bak "app.manifest.csv") -Root $Cfg.runtime_app -What "restored application")
        }
        $didEngine = Test-AgainstManifest -ManifestFile (Join-Path $bak "engine.manifest.csv") -Root (Join-Path $bak "engine") -What "backup engine integrity" -Optional
        if ($didEngine) {
            Invoke-Robocopy -Cfg $Cfg -Source (Join-Path $bak "engine") -Dest $Cfg.runtime_engine -Extra (@("/COPY:DAT") + $Cfg.engine_files) -What "engine restore"
            [void](Test-AgainstManifest -ManifestFile (Join-Path $bak "engine.manifest.csv") -Root $Cfg.runtime_engine -What "restored engine")
        }
        if (-not $didApp -and -not $didEngine) { throw "BLOCKED: unit $UnitId contains no restorable component" }
        Write-VersionFile -Cfg $Cfg -Sha $sha
        Set-ServiceState -Cfg $Cfg -Target Running
        Write-Host "ROLLBACK COMPLETE - unit $UnitId restored (app=$didApp engine=$didEngine); service Running"
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
        if ($Scope -ne "Engine") { Invoke-Converge -Cfg $cfg -ArtifactPath $art }
        if ($Scope -ne "App") { Invoke-EngineSync -Cfg $cfg }
        if ($Scope -ne "Engine") {
            [void](Test-AgainstManifest -ManifestFile "$art.manifest.csv" -Root $cfg.runtime_app -What "deployed application")
        }
        Write-VersionFile -Cfg $cfg -Sha $ReviewedSHA
        Set-ServiceState -Cfg $cfg -Target Running
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
