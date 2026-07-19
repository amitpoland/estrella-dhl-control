<#
.SYNOPSIS
    SOLE execution and rollback authority for PZ production deployment.

.DESCRIPTION
    Every path, filename, and flag is read from windows_prod_v2.json. Nothing is
    hardcoded. Deployment is artifact-based and deterministic: the bytes that reach
    production are the bytes of an immutable, hash-manifested staged artifact -- never
    a live git tree. Rollback restores only from a manifest-validated backup and never
    mutates the certified source's git history.

    DELIBERATELY ONE FILE. Splitting execution across modules is how this repository
    accumulated 29 competing deployment scripts. One authority, one file.

.PARAMETER WhatIf
    Plan only. Prints every action and writes nothing.

.PARAMETER Rollback
    Restore a previously created deployment unit. Requires -Unit.

.PARAMETER Unit
    Deployment unit identifier (directory name under backup_root).

.PARAMETER Scope
    App | Engine | Both (default Both). Recorded in the unit so a rollback restores
    exactly the scope that was deployed.

.PARAMETER Bootstrap
    First-ever deploy: permits an absent prior production tree (no rollback target).

.PARAMETER NoRun
    Dot-source the functions without executing. For tests only.

.NOTES
    OPERATOR-ONLY. Production-write phases refuse to run unless the operator token
    named by config.operator_token_env is present in the environment. The agent
    cannot derive it. pz-deploy-guard.py independently denies agent invocation.
#>
[CmdletBinding()]
param(
    [switch]$WhatIf,
    [switch]$Rollback,
    [string]$Unit,
    [ValidateSet("App", "Engine", "Both")][string]$Scope = "Both",
    [switch]$Bootstrap,
    [switch]$NoRun
)

$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------- configuration
function Get-DeployConfig {
    param([string]$ConfigPath)
    if (-not $ConfigPath) {
        $ConfigPath = Join-Path $PSScriptRoot "windows_prod_v2.json"
    }
    if (-not (Test-Path $ConfigPath)) { throw "BLOCKED: config not found: $ConfigPath" }
    $cfg = Get-Content $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $required = @(
        "schema_version", "service", "source_root", "source_app", "runtime_app",
        "runtime_engine", "artifact_root", "backup_root", "version_file", "lock_file",
        "engine_files", "protected_dirs", "protected_files", "forbidden_flags",
        "robocopy_fatal_exit", "robocopy_suspect_exit", "service_wait_seconds",
        "test_baseline_contract", "operator_token_env"
    )
    foreach ($k in $required) {
        if ($null -eq $cfg.$k) { throw "BLOCKED: config key missing: $k" }
    }
    if ($cfg.schema_version -ne 2) { throw "BLOCKED: unsupported config schema_version $($cfg.schema_version)" }
    if (-not $cfg.engine_files.Count) { throw "BLOCKED: engine_files is empty" }
    return $cfg
}

function Assert-OperatorToken {
    param($Cfg)
    $name = $Cfg.operator_token_env
    $val = [Environment]::GetEnvironmentVariable($name)
    if ([string]::IsNullOrWhiteSpace($val)) {
        throw "BLOCKED: production write requires the operator token in `$env:$name. This step is operator-only; an agent must not perform it."
    }
}

function Invoke-Robocopy {
    param($Cfg, [string]$Source, [string]$Dest, [string[]]$Extra, [string]$What, [switch]$InventoryClassified)
    foreach ($bad in $Cfg.forbidden_flags) {
        if ($Extra -contains $bad) { throw "BLOCKED: forbidden robocopy flag $bad in $What" }
    }
    Write-Host "  robocopy [$What] $Source -> $Dest $($Extra -join ' ')"
    if ($script:PlanOnly) { return }
    & robocopy $Source $Dest @Extra | Out-Null
    $code = $LASTEXITCODE
    if ($code -ge $Cfg.robocopy_fatal_exit) { throw "BLOCKED: $What failed, robocopy exit $code" }
    if ($code -ge $Cfg.robocopy_suspect_exit -and -not $InventoryClassified) {
        throw "BLOCKED: $What returned robocopy exit $code (mismatch) and was not inventory-classified"
    }
    Write-Host "  robocopy [$What] exit $code (accepted)"
}

function New-Manifest {
    param([string]$Root, [string]$OutFile)
    if ($script:PlanOnly) { Write-Host "  would write manifest $OutFile"; return }
    Get-ChildItem $Root -Recurse -File |
        Get-FileHash -Algorithm SHA256 |
        Select-Object @{n = "Rel"; e = { $_.Path.Substring($Root.Length).TrimStart('\') } }, Hash |
        Sort-Object Rel | Export-Csv $OutFile -NoTypeInformation -Encoding UTF8
    $n = @(Import-Csv $OutFile).Count
    if ($n -lt 1) { throw "BLOCKED: manifest $OutFile is empty - refusing to treat this as a valid artifact" }
    Write-Host "  manifest $OutFile ($n files)"
}

function Test-AgainstManifest {
    param([string]$ManifestFile, [string]$Root, [string]$What)
    if ($script:PlanOnly) { Write-Host "  would verify $What against $ManifestFile"; return }
    if (-not (Test-Path $ManifestFile)) { throw "BLOCKED: manifest missing for $What : $ManifestFile - unit is not restorable" }
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
    $lock = $Cfg.lock_file
    if ($script:PlanOnly) { return }
    $dir = Split-Path $lock -Parent
    if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    if (Test-Path $lock) {
        throw "BLOCKED: another deployment holds the lock ($lock): $(Get-Content $lock -Raw). Concurrent execution is refused."
    }
    "pid=$PID user=$env:USERNAME started=$(Get-Date -Format o)" | Set-Content $lock -Encoding UTF8
}

function Exit-DeployLock {
    param($Cfg)
    if (-not $script:PlanOnly -and (Test-Path $Cfg.lock_file)) { Remove-Item $Cfg.lock_file -Force }
}

function Get-RequiredCounts {
    param($Cfg, [string]$RepoRoot)
    $contract = Join-Path $RepoRoot $Cfg.test_baseline_contract
    if (-not (Test-Path $contract)) { throw "BLOCKED: test-baseline contract not found: $contract" }
    $carrier = (Select-String -Path $contract -Pattern '\|\s*Carrier suite\s*\|[^|]*\|\s*\*\*(\d+)\*\*').Matches[0].Groups[1].Value
    if (-not $carrier) { throw "BLOCKED: cannot read required carrier count from $contract" }
    return @{ Carrier = [int]$carrier; Contract = $contract }
}

function Get-ProtectedArgs {
    param($Cfg)
    $a = @()
    if ($Cfg.protected_dirs.Count) { $a += "/XD"; $a += $Cfg.protected_dirs }
    if ($Cfg.protected_files.Count) { $a += "/XF"; $a += $Cfg.protected_files }
    return $a
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

    # Behind origin is the NORMAL pre-deploy state and is allowed; the fast-forward
    # happens after the gate. Ahead or diverged means local-only commits -> blocked.
    & git -C $SRC merge-base --is-ancestor HEAD origin/main
    if ($LASTEXITCODE -ne 0) {
        throw "BLOCKED: $SRC has local-only commits or has diverged from origin/main (Lesson D). Reconcile before deploying."
    }
    Write-Host "  source OK: $SRC on '$branch', clean, no local-only commits"
}

function Get-IncomingRange {
    param($Cfg)
    $SRC = $Cfg.source_root
    $current = (& git -C $SRC rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED: cannot resolve HEAD" }
    $target = (& git -C $SRC rev-parse origin/main).Trim()
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED: cannot resolve origin/main" }
    if ($current -eq $target) {
        Write-Host "NOTHING TO DEPLOY - $SRC is already at origin/main ($target)"
        return $null
    }
    Write-Host "== Incoming range =="
    Write-Host "  CURRENT_HEAD = $current"
    Write-Host "  TARGET_HEAD  = $target   <-- immutable reviewed target"
    & git -C $SRC log --oneline "$current..$target"
    & git -C $SRC diff --name-status "$current..$target"
    return @{ Current = $current; Target = $target }
}

function Assert-ReviewedTarget {
    param($Cfg, [string]$ReviewedTarget)
    $SRC = $Cfg.source_root
    & git -C $SRC fetch origin | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED: fetch failed - cannot confirm review target" }
    $now = (& git -C $SRC rev-parse origin/main).Trim()
    if ($now -ne $ReviewedTarget) {
        throw "BLOCKED: origin/main advanced during review ($ReviewedTarget -> $now). Re-run the gate. NEVER deploy a SHA the gate did not review."
    }
    if ($script:PlanOnly) { Write-Host "  would fast-forward $SRC to $ReviewedTarget"; return }
    & git -C $SRC merge --ff-only $ReviewedTarget | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED: fast-forward to $ReviewedTarget failed" }
    $head = (& git -C $SRC rev-parse HEAD).Trim()
    if ($head -ne $ReviewedTarget) { throw "BLOCKED: HEAD $head != reviewed target $ReviewedTarget" }
    Write-Host "  certified source advanced to reviewed target $ReviewedTarget"
}

function New-ReleaseArtifact {
    param($Cfg, [string]$Sha)
    $art = Join-Path $Cfg.artifact_root "app-$Sha"
    Write-Host "== Stage immutable artifact =="
    if ((Test-Path $art) -and -not $script:PlanOnly) {
        throw "BLOCKED: artifact $art already exists - releases are immutable, never re-staged"
    }
    if (-not $script:PlanOnly) { New-Item -ItemType Directory -Path $art -Force | Out-Null }
    Invoke-Robocopy -Cfg $Cfg -Source $Cfg.source_app -Dest $art `
        -Extra (@("/E", "/COPY:DAT") + (Get-ProtectedArgs -Cfg $Cfg)) -What "artifact staging"
    New-Manifest -Root $art -OutFile "$art.manifest.csv"
    return $art
}

function New-BackupUnit {
    param($Cfg, [string]$Sha, [string]$UnitScope)
    $stamp = Get-Date -Format "yyyyMMdd-HHmmss"
    $unit = "$Sha-$stamp"
    $bak = Join-Path $Cfg.backup_root $unit
    Write-Host "== Pre-deploy backup (the ONLY rollback source) =="
    if (-not $script:PlanOnly) {
        New-Item -ItemType Directory -Path (Join-Path $bak "app") -Force | Out-Null
        New-Item -ItemType Directory -Path (Join-Path $bak "engine") -Force | Out-Null
    }

    $appPresent = (Test-Path $Cfg.runtime_app)
    if (-not $appPresent) {
        if (-not $Bootstrap) {
            throw "BLOCKED: $($Cfg.runtime_app) does not exist. First-ever deploy requires -Bootstrap, which records that NO rollback target exists."
        }
        Write-Host "  BOOTSTRAP: no prior application tree - no rollback target will exist"
    }
    else {
        Invoke-Robocopy -Cfg $Cfg -Source $Cfg.runtime_app -Dest (Join-Path $bak "app") `
            -Extra (@("/E", "/COPY:DAT") + (Get-ProtectedArgs -Cfg $Cfg)) -What "app backup"
        New-Manifest -Root (Join-Path $bak "app") -OutFile (Join-Path $bak "app.manifest.csv")
    }

    $enginePresent = (Test-Path $Cfg.runtime_engine)
    if ($enginePresent) {
        Invoke-Robocopy -Cfg $Cfg -Source $Cfg.runtime_engine -Dest (Join-Path $bak "engine") `
            -Extra (@("/COPY:DAT") + $Cfg.engine_files) -What "engine backup"
        if (-not $script:PlanOnly) {
            foreach ($ef in $Cfg.engine_files) {
                if (-not (Test-Path (Join-Path $bak "engine\$ef"))) {
                    throw "BLOCKED: engine backup incomplete - $ef absent from $($Cfg.runtime_engine) at backup time. A named-but-absent file exits robocopy 0/1 and would otherwise pass silently."
                }
            }
        }
        New-Manifest -Root (Join-Path $bak "engine") -OutFile (Join-Path $bak "engine.manifest.csv")
    }
    elseif (-not $Bootstrap) {
        throw "BLOCKED: $($Cfg.runtime_engine) does not exist. Use -Bootstrap for a first-ever engine deploy."
    }

    if (-not $script:PlanOnly) {
        [pscustomobject]@{
            unit = $unit; sha = $Sha; scope = $UnitScope; created = (Get-Date -Format o)
            app_backed_up = $appPresent; engine_backed_up = $enginePresent; bootstrap = [bool]$Bootstrap
        } | ConvertTo-Json | Set-Content (Join-Path $bak "unit.json") -Encoding UTF8
    }
    Write-Host "  backup unit: $bak (scope=$UnitScope)"
    return @{ Unit = $unit; Path = $bak; AppBackedUp = $appPresent; EngineBackedUp = $enginePresent }
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
        $top = $rel.Split('\')[0]
        if ($Cfg.protected_dirs -contains $top) { continue }
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
    Invoke-Robocopy -Cfg $Cfg -Source $ArtifactPath -Dest $Cfg.runtime_app `
        -Extra (@("/MIR", "/COPY:DAT") + (Get-ProtectedArgs -Cfg $Cfg)) `
        -What "application convergence" -InventoryClassified
}

function Invoke-EngineSync {
    param($Cfg)
    Write-Host "== Engine sync (Lesson J - separate copy) =="
    Invoke-Robocopy -Cfg $Cfg -Source $Cfg.source_root -Dest $Cfg.runtime_engine `
        -Extra (@("/COPY:DAT") + $Cfg.engine_files) -What "engine sync"
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

function Write-VersionFile {
    param($Cfg, [string]$Sha)
    # SOLE writer of version_file. Consumed at runtime by
    # service/app/api/routes_webhooks_wfirma_status.py (_SHA_FILE) and pinned by
    # service/tests/test_wfirma_status.py. Never remove without migrating that contract.
    if ($script:PlanOnly) { Write-Host "  would write $($Cfg.version_file) = $Sha"; return }
    $Sha | Out-File -FilePath $Cfg.version_file -Encoding utf8 -NoNewline
    Write-Host "  version file written: $($Cfg.version_file) = $Sha"
}

function Invoke-Rollback {
    param($Cfg, [string]$UnitId)
    if (-not $UnitId) { throw "BLOCKED: -Rollback requires -Unit" }
    $bak = Join-Path $Cfg.backup_root $UnitId
    Write-Host "== ROLLBACK from unit $UnitId =="
    if (-not (Test-Path $bak)) { throw "BLOCKED: backup unit not found: $bak" }
    $meta = $null
    if (Test-Path (Join-Path $bak "unit.json")) {
        $meta = Get-Content (Join-Path $bak "unit.json") -Raw | ConvertFrom-Json
    }
    if ($meta -and $meta.bootstrap) {
        throw "BLOCKED: unit $UnitId was a bootstrap deploy - there is NO prior state to restore. Recovery is manual and must be operator-directed."
    }

    Assert-OperatorToken -Cfg $Cfg
    Enter-DeployLock -Cfg $Cfg
    try {
        Set-ServiceState -Cfg $Cfg -Target Stopped

        if (-not $meta -or $meta.app_backed_up) {
            Test-AgainstManifest -ManifestFile (Join-Path $bak "app.manifest.csv") -Root (Join-Path $bak "app") -What "backup app tree (pre-restore integrity)"
            Invoke-Robocopy -Cfg $Cfg -Source (Join-Path $bak "app") -Dest $Cfg.runtime_app `
                -Extra (@("/MIR", "/COPY:DAT") + (Get-ProtectedArgs -Cfg $Cfg)) `
                -What "app restore" -InventoryClassified
            Test-AgainstManifest -ManifestFile (Join-Path $bak "app.manifest.csv") -Root $Cfg.runtime_app -What "restored application"
        }

        if (-not $meta -or $meta.engine_backed_up) {
            Test-AgainstManifest -ManifestFile (Join-Path $bak "engine.manifest.csv") -Root (Join-Path $bak "engine") -What "backup engine (pre-restore integrity)"
            Invoke-Robocopy -Cfg $Cfg -Source (Join-Path $bak "engine") -Dest $Cfg.runtime_engine `
                -Extra (@("/COPY:DAT") + $Cfg.engine_files) -What "engine restore"
            Test-AgainstManifest -ManifestFile (Join-Path $bak "engine.manifest.csv") -Root $Cfg.runtime_engine -What "restored engine"
        }

        if ($meta -and $meta.sha) { Write-VersionFile -Cfg $Cfg -Sha $meta.sha }
        Set-ServiceState -Cfg $Cfg -Target Running
        Write-Host "ROLLBACK COMPLETE - unit $UnitId restored and $($Cfg.service) is Running"
    }
    finally { Exit-DeployLock -Cfg $Cfg }
}

# ---------------------------------------------------------------- entry point
function Invoke-Deploy {
    param([switch]$PlanOnly)
    $script:PlanOnly = [bool]$PlanOnly
    $cfg = Get-DeployConfig
    if ($script:PlanOnly) { Write-Host "*** -WhatIf: PLAN ONLY, nothing will be written ***" }

    if ($Rollback) { Invoke-Rollback -Cfg $cfg -UnitId $Unit; return }

    Invoke-Preflight -Cfg $cfg
    $range = Get-IncomingRange -Cfg $cfg
    if ($null -eq $range) { return }

    Write-Host ""
    Write-Host "=============================================================="
    Write-Host " DEPLOYMENT_READY_AWAITING_GATE"
    Write-Host " Run the 7-agent pre-deploy gate against the range above:"
    Write-Host "   $($range.Current)..$($range.Target)"
    Write-Host " No production write has occurred. Re-run with the operator token"
    Write-Host " present once the Lead Coordinator has issued written approval."
    Write-Host "=============================================================="
    Assert-OperatorToken -Cfg $cfg

    Assert-ReviewedTarget -Cfg $cfg -ReviewedTarget $range.Target
    $counts = Get-RequiredCounts -Cfg $cfg -RepoRoot $cfg.source_root
    Write-Host "  required carrier pass count (from $($counts.Contract)): $($counts.Carrier)"

    $art = New-ReleaseArtifact -Cfg $cfg -Sha $range.Target
    $unit = New-BackupUnit -Cfg $cfg -Sha $range.Target -UnitScope $Scope
    Get-DestinationInventory -Cfg $cfg -ArtifactPath $art | Out-Null

    Enter-DeployLock -Cfg $cfg
    try {
        Set-ServiceState -Cfg $cfg -Target Stopped
        if ($Scope -ne "Engine") { Invoke-Converge -Cfg $cfg -ArtifactPath $art }
        if ($Scope -ne "App") { Invoke-EngineSync -Cfg $cfg }
        if ($Scope -ne "Engine") {
            Test-AgainstManifest -ManifestFile "$art.manifest.csv" -Root $cfg.runtime_app -What "deployed application"
        }
        Write-VersionFile -Cfg $cfg -Sha $range.Target
        Set-ServiceState -Cfg $cfg -Target Running
    }
    finally { Exit-DeployLock -Cfg $cfg }

    Write-Host ""
    Write-Host "DEPLOY COMPLETE  sha=$($range.Target)  unit=$($unit.Unit)  scope=$Scope"
    Write-Host "Validate:  Test-PZDeployClose.ps1 -ExpectedSHA $($range.Target)"
    Write-Host "Rollback:  Deploy-PZ.ps1 -Rollback -Unit $($unit.Unit)"
}

if (-not $NoRun) { Invoke-Deploy -PlanOnly:$WhatIf }
