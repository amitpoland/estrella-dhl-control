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

.PARAMETER Release
    ONE-COMMAND operator flow. Resolves the current origin/main SHA itself, validates
    the seven-agent gate evidence at the configured standard path (gate_evidence_file),
    proves what production actually runs (the marker is evidence, never authority),
    automatically chooses NO-OP / DEPLOY / RECONCILE, mints and consumes the signed
    authorization internally ONLY AFTER the read-only identity checks pass, deploys,
    restarts, runs the closure validation, and prints exactly one final status:
    ALREADY CURRENT, DEPLOYED, ROLLED BACK, or FAILED SAFE.

    Only four conditions block a release: (1) the seven-agent verdict is not GO,
    (2) production runtime identity cannot be proven, (3) backup/copy verification
    fails, (4) the service is not healthy after the deploy. Everything else resolves
    automatically. CI is not consulted; inherited-red CI never blocks. Requires the
    operator signing key (PZ_DEPLOY_AUTH_KEY_FILE) in the shell - the internal mint
    uses the same external key and the same single-use artifacts as the manual flow.
    Production writes also require Windows Administrator: a non-elevated -Release
    self-elevates once via UAC before any authorization is minted or consumed, then
    the elevated child re-runs this same script. Declining UAC is FAILED SAFE with
    production untouched and no authorization ceremony. No per-PR BAT or second
    deploy script. -ReviewedSHA / -Reconcile / -Rollback remain available as
    advanced/debug modes; a normal operator should never need them.

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
    First-ever deploy: permits an ABSENT or genuinely EMPTY prior production tree (no
    rollback target). It fails closed against an existing non-empty tree: bootstrap is
    the only path that skips the identity gate, so allowing it there would let a
    mislabelled backup be minted over an unverified runtime. Use -Reconcile instead.

.PARAMETER Reconcile
    OPERATOR-ONLY repair for a production tree whose bytes do not match its recorded
    version marker. Requires -FromSha (the identity the runtime ACTUALLY has) and
    -ToSha (the reviewed target to converge to). Unlike -Bootstrap it does not skip
    the identity gate - it PROVES the runtime is -FromSha, twice, and refuses if it is
    not. Authorization is bound to the ordered pair, so a signature for one direction
    cannot repair a different drift.

.PARAMETER FromSha
    -Reconcile only. The commit whose application tree production currently holds. It
    is asserted, never assumed: if the runtime does not verify against it byte-for-byte
    (by git object id) nothing is stopped, backed up, or written.

.PARAMETER ToSha
    -Reconcile only. The reviewed commit to converge production to. Must be on
    origin/main and must be the source tree's HEAD.

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
    [switch]$Release,
    [switch]$WhatIf,
    [switch]$Rollback,
    [string]$Unit,
    [ValidateSet("App", "Engine", "Both")][string]$Scope = "Both",
    [switch]$Bootstrap,
    [switch]$Reconcile,
    [string]$FromSha,
    [string]$ToSha,
    [switch]$ForceUnlock,
    [switch]$NoRun,
    # Internal: elevated child transcript path. Set only by Request-AdministratorElevationIfNeeded.
    # Must resolve under %LOCALAPPDATA%\PZ-deploy\logs\deploy-*.log — never an arbitrary path.
    [string]$DeployLog
)

$ErrorActionPreference = "Stop"

$script:UNIT_RX = '^[0-9a-f]{40}-\d{8}-\d{6}$'
$script:SHA_RX = '^[0-9a-f]{40}$'

# ---------------------------------------------------------------- privilege
function Test-IsAdministrator {
    <#
      Windows token authority only. Username heuristics are refused: membership in
      the built-in Administrators role is what sc.exe / production writes require.
    #>
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return [bool]$principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Get-DeployElevationArgumentList {
    <#
      Structural rebuild of THIS script's supported switches only. Never concatenates
      an unvalidated command string. SHA / Unit values are shape-checked before they
      are passed through; Scope is ValidateSet-bound at the param block.
    #>
    param([string]$LogPath)
    $scriptPath = $PSCommandPath
    if (-not $scriptPath) { $scriptPath = $MyInvocation.MyCommand.Path }
    if (-not $scriptPath -or -not (Test-Path -LiteralPath $scriptPath)) {
        throw "BLOCKED: cannot resolve Deploy-PZ.ps1 path for Administrator elevation."
    }
    if ((Split-Path -LiteralPath $scriptPath -Leaf) -ne 'Deploy-PZ.ps1') {
        throw "BLOCKED: elevation refused - resolved script '$(Split-Path -LiteralPath $scriptPath -Leaf)' is not Deploy-PZ.ps1 (sole execution authority)."
    }

    $tokens = [System.Collections.Generic.List[string]]::new()
    [void]$tokens.Add('-NoProfile')
    [void]$tokens.Add('-ExecutionPolicy')
    [void]$tokens.Add('Bypass')
    [void]$tokens.Add('-File')
    [void]$tokens.Add($scriptPath)

    if ($Release) { [void]$tokens.Add('-Release') }
    if ($Rollback) { [void]$tokens.Add('-Rollback') }
    if ($Reconcile) { [void]$tokens.Add('-Reconcile') }
    if ($Bootstrap) { [void]$tokens.Add('-Bootstrap') }
    if ($ForceUnlock) { [void]$tokens.Add('-ForceUnlock') }

    if ($ReviewedSHA) {
        if ($ReviewedSHA -notmatch $script:SHA_RX) {
            throw "BLOCKED: elevation refused - -ReviewedSHA is not a full 40-character commit SHA."
        }
        [void]$tokens.Add('-ReviewedSHA')
        [void]$tokens.Add($ReviewedSHA.ToLower())
    }
    if ($Unit) {
        if ($Unit -notmatch $script:UNIT_RX) {
            throw "BLOCKED: elevation refused - -Unit is not a valid unit identifier."
        }
        [void]$tokens.Add('-Unit')
        [void]$tokens.Add($Unit)
    }
    if ($FromSha) {
        if ($FromSha -notmatch $script:SHA_RX) {
            throw "BLOCKED: elevation refused - -FromSha is not a full 40-character commit SHA."
        }
        [void]$tokens.Add('-FromSha')
        [void]$tokens.Add($FromSha.ToLower())
    }
    if ($ToSha) {
        if ($ToSha -notmatch $script:SHA_RX) {
            throw "BLOCKED: elevation refused - -ToSha is not a full 40-character commit SHA."
        }
        [void]$tokens.Add('-ToSha')
        [void]$tokens.Add($ToSha.ToLower())
    }
    # Always pin Scope explicitly so App|Engine|Both survives elevation exactly.
    if ($Scope -notin @('App', 'Engine', 'Both')) {
        throw "BLOCKED: elevation refused - -Scope '$Scope' is not App|Engine|Both."
    }
    [void]$tokens.Add('-Scope')
    [void]$tokens.Add($Scope)

    if ($LogPath) {
        Assert-CanonicalDeployLogPath -LogFilePath $LogPath
        [void]$tokens.Add('-DeployLog')
        [void]$tokens.Add($LogPath)
    }

    # -WhatIf and -NoRun are never elevated: plan mode needs no privilege; -NoRun is tests-only.
    return ,$tokens.ToArray()
}

function Assert-CanonicalDeployLogPath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LogFilePath
    )
    if ($LogFilePath -match '\.\.') {
        throw "BLOCKED: -DeployLog refuses path traversal."
    }
    $leaf = Split-Path -LiteralPath $LogFilePath -Leaf
    if ($leaf -notmatch '^deploy-\d{8}-\d{6}-\d{3}\.log$') {
        throw "BLOCKED: -DeployLog leaf must match deploy-yyyyMMdd-HHmmss-fff.log."
    }
    $expectedRoot = [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA 'PZ-deploy\logs'))
    $full = [System.IO.Path]::GetFullPath($LogFilePath)
    $prefix = $expectedRoot.TrimEnd('\') + '\'
    if (-not ($full.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase))) {
        throw "BLOCKED: -DeployLog must resolve under %LOCALAPPDATA%\PZ-deploy\logs (got '$full')."
    }
}

function Assert-DeployAuthEnvSurvivesElevation {
    <#
      Start-Process -Verb RunAs does not inherit process-scoped $env: from the parent.
      User/Machine env (setx) is loaded into the elevated child. Fail closed BEFORE UAC
      when the signing-key paths exist only as process-scoped values.
    #>
    foreach ($name in @('PZ_DEPLOY_AUTH_KEY_FILE', 'PZ_DEPLOY_AUTH_DIR')) {
        $user = [Environment]::GetEnvironmentVariable($name, 'User')
        $machine = [Environment]::GetEnvironmentVariable($name, 'Machine')
        $proc = [Environment]::GetEnvironmentVariable($name, 'Process')
        if ($user -or $machine) { continue }
        if ($proc) {
            throw "FAILED SAFE: $name is set only in this process. UAC elevation starts a new elevated shell that does not inherit process-scoped env. Persist with setx (User-level), open a new shell, then re-run. Production untouched. Authorization not minted."
        }
        throw "FAILED SAFE: $name is not set at User or Machine scope (required for elevated Deploy-PZ). Use setx as documented by sign_deploy_authorization.py. Production untouched. Authorization not minted."
    }
}

function ConvertTo-ProcessArgumentString {
    param([Parameter(Mandatory)][string[]]$Tokens)
    # Quote only when needed; escape embedded quotes. Prevents path/arg injection via spaces.
    return (($Tokens | ForEach-Object {
        $t = [string]$_
        if ($t -match '[\s"]') {
            '"' + ($t -replace '(\\*)"','$1$1\"') + '"'
        } else {
            $t
        }
    }) -join ' ')
}

function Request-AdministratorElevationIfNeeded {
    <#
      Privilege proof BEFORE authorization. Non-elevated production-write invocations
      must not reach Invoke-ReleaseMint / Assert-Authorization / Set-ServiceState.
      One UAC transition maximum: an already-Administrator process returns and continues.
      The elevated child is THIS same Deploy-PZ.ps1 with structurally rebuilt arguments.
    #>
    if ($script:PlanOnly) { return }
    if (Test-IsAdministrator) {
        Write-Host "== Privilege: Administrator proven (token) =="
        return
    }

    Write-Host "== ELEVATION REQUIRED: production write needs Administrator; requesting UAC =="
    Write-Host "  Authorization will NOT be minted in this (non-elevated) process."
    Assert-DeployAuthEnvSurvivesElevation

    $logDir = Join-Path $env:LOCALAPPDATA 'PZ-deploy\logs'
    if (-not (Test-Path -LiteralPath $logDir)) {
        New-Item -ItemType Directory -Path $logDir -Force | Out-Null
    }
    $logPath = Join-Path $logDir ("deploy-{0}.log" -f (Get-Date -Format 'yyyyMMdd-HHmmss-fff'))
    Assert-CanonicalDeployLogPath -LogFilePath $logPath
    Write-Host "  Elevated transcript: $logPath"

    $tokens = Get-DeployElevationArgumentList -LogPath $logPath
    $argString = ConvertTo-ProcessArgumentString -Tokens $tokens
    $psExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
    if (-not (Test-Path -LiteralPath $psExe)) {
        throw "BLOCKED: Windows PowerShell host not found at $psExe; cannot request UAC elevation."
    }

    $proc = $null
    try {
        $proc = Start-Process -FilePath $psExe -Verb RunAs -ArgumentList $argString -Wait -PassThru
    }
    catch {
        $msg = [string]$_.Exception.Message
        if ($msg -match '(?i)cancel') {
            throw "FAILED SAFE: Administrator elevation was declined. Production untouched. Authorization not minted."
        }
        throw "FAILED SAFE: Administrator elevation failed ($msg). Production untouched. Authorization not minted."
    }
    if ($null -eq $proc) {
        throw "FAILED SAFE: Administrator elevation was declined. Production untouched. Authorization not minted."
    }
    # Replay the elevated child's canonical transcript into this console so the operator
    # who typed -Release sees RELEASE RESULT / FAILED SAFE without a second log authority.
    if (Test-Path -LiteralPath $logPath) {
        Write-Host ""
        Write-Host "---- elevated Deploy-PZ transcript ($logPath) ----"
        Get-Content -LiteralPath $logPath | ForEach-Object { Write-Host $_ }
        Write-Host "---- end transcript ----"
    }
    else {
        Write-Host "WARNING: elevated transcript missing at $logPath; see the elevated console window for RELEASE RESULT."
    }
    # Propagate the elevated child's exit code. Do NOT claim DEPLOYED from a successful UAC launch.
    # Never continue into mint/consume/stop in this unelevated parent.
    exit [int]$proc.ExitCode
}

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
        "service_wait_seconds", "test_baseline_contract", "authorization_helper",
        "gate_evidence_file"
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
    param($Cfg, [string]$Sha, [string]$Action, [string]$UnitScope, [string]$SourceSha)
    # Never called in plan mode -- a zero-write run needs no authorization.
    $helper = Join-Path (Split-Path $PSScriptRoot -Parent) $Cfg.authorization_helper
    if (-not (Test-Path $helper)) { throw "BLOCKED: authorization helper missing: $helper" }
    $pyExe = (Get-Command python -ErrorAction SilentlyContinue)
    if (-not $pyExe) { throw "BLOCKED: python not on PATH; cannot evaluate deploy authorization" }
    # -SourceSha is passed ONLY for reconcile, where the helper binds the signature to the
    # ordered pair. Passing it for any other action is refused by the helper, so the two
    # call shapes cannot be confused for one another.
    if ($SourceSha) { $out = & python $helper $Sha $Action $UnitScope $SourceSha 2>&1 }
    else { $out = & python $helper $Sha $Action $UnitScope 2>&1 }
    $code = $LASTEXITCODE
    Write-Host "  authorization: $out"
    if ($code -ne 0) {
        $what = if ($SourceSha) { "$Action of $SourceSha -> $Sha" } else { "$Action of $Sha" }
        throw "BLOCKED: not authorized for $what (scope $UnitScope). Production writes require a signed, SHA-bound, single-use operator authorization. This step is operator-only."
    }
}

function Invoke-ReleaseMint {
    <#
      -Release only: mint the signed single-use authorization INTERNALLY, using the same
      operator-only signer, the same external key, and the same store as the manual flow.
      This removes the separate copy/paste signing command, not the signature: the signer
      still refuses without the key (which lives outside the repository, in the operator's
      shell), still validates the gate evidence, and still binds action/scope/direction.
      Called ONLY after Administrator privilege is proven (Request-AdministratorElevationIfNeeded
      at Invoke-Deploy entry) AND after the read-only identity checks have passed, so a failed
      identity or missing privilege never wastes a single-use jti.
    #>
    param($Cfg, [string]$Sha, [string]$Action, [string]$UnitScope, [string]$FromSha)
    if ($script:PlanOnly) { Write-Host "  would mint $Action authorization for $Sha"; return }
    $signer = Join-Path $PSScriptRoot "..\hooks\sign_deploy_authorization.py"
    if (-not (Test-Path $signer)) { throw "BLOCKED: signer missing: $signer" }
    $mintArgs = @($signer, $Sha, $Action, $UnitScope, "--ttl", "60")
    if ($Action -ne "rollback") { $mintArgs += @("--gate-evidence", $Cfg.gate_evidence_file) }
    if ($FromSha) { $mintArgs += @("--from-sha", $FromSha) }
    & python @mintArgs
    if ($LASTEXITCODE -ne 0) {
        throw "BLOCKED: could not mint the $Action authorization (signer exit $LASTEXITCODE). The signing key (PZ_DEPLOY_AUTH_KEY_FILE) must be available in this shell and the gate evidence at $($Cfg.gate_evidence_file) must be a valid seven-agent GO for $Sha."
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
    # ALREADY_TARGET: do not call sc.exe.
    $current = (Get-Service $svc).Status
    if ($current -eq $Target) {
        Write-Host "  $svc is already $Target"
        return
    }
    $verb = if ($Target -eq "Stopped") { "stop" } else { "start" }
    # Preserve native exit authority. Do NOT redirect sc.exe stderr with 2>&1 under
    # ErrorActionPreference=Stop — that wraps NativeCommandError and throws before
    # $LASTEXITCODE is readable (same pattern as the git identity-gate cat-file call).
    # Exit code is authority; OpenService/ControlService text usually lands on host stderr.
    $scOut = & sc.exe $verb $svc | Out-String
    $scCode = $LASTEXITCODE
    if ($scCode -ne 0) {
        $after = (Get-Service $svc).Status
        if ($after -ne $Target) {
            # SC_REJECTED / ACCESS_DENIED: fail immediately; never wait out service_wait_seconds.
            $trimmed = "$scOut".Trim()
            if (-not $trimmed) {
                $trimmed = "(sc.exe produced no stdout; see host stderr for OpenService/ControlService text)"
            }
            $hint = ""
            if ($scCode -eq 5) {
                # ACCESS_DENIED defense-in-depth: self-elevation should have run before mint.
                # Never widen service ACLs; never use a per-PR BAT as the permanent fix.
                $hint = " Access Denied (exit 5): Deploy-PZ should have self-elevated via UAC before authorization; re-run from an elevated Administrator shell if needed; do not widen service ACLs."
            }
            throw "BLOCKED: sc.exe $verb $svc failed (exit $scCode); service remained $after. $trimmed.$hint"
        }
        # Rare: non-zero exit but service already at target — treat as accepted.
    }
    # SC_ACCEPTED: wait for actual target state.
    $deadline = (Get-Date).AddSeconds($Cfg.service_wait_seconds)
    while ((Get-Service $svc).Status -ne $Target -and (Get-Date) -lt $deadline) { Start-Sleep -Seconds 1 }
    $final = (Get-Service $svc).Status
    if ($final -ne $Target) {
        # SC_ACCEPTED_BUT_STATE_TIMEOUT: genuine transition/shutdown stall, not Access Denied.
        throw "BLOCKED: $svc did not reach $Target within $($Cfg.service_wait_seconds)s (sc.exe $verb returned success; service remained $final -- STOP_PENDING hang or application shutdown stall, not a discarded sc.exe failure)"
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
        # A LIVE lock always blocks. A stale lock (its pid provably gone) is cleared
        # automatically under -Release - a dead process cannot be mid-write, and making
        # the operator re-run with -ForceUnlock is ceremony, not safety. The clear is
        # audited either way. Outside -Release the explicit -ForceUnlock is still
        # required, preserving the deliberate two-step for manual/advanced modes.
        if (-not $ForceUnlock -and -not $script:ReleaseMode) {
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

function Get-ReparseSafeFiles {
    <#
      Enumerate every file under $Root, refusing to walk a reparse point (junction,
      directory symlink, mount point) instead of following it.

      Why not Get-ChildItem -Recurse: in PS 5.1 -Recurse DESCENDS through directory
      junctions. Two failure modes follow. (1) A junction pointing outside the runtime
      tree drags foreign files into the comparison, where they surface as EXTRANEOUS -
      fail-closed, but the operator is told the wrong thing about their own tree.
      (2) A junction pointing at an ancestor is an unbounded recursion; the gate never
      returns a verdict at all. Detecting reparse points AFTER -Recurse has started is
      too late for (2), because the loop is already running. So the traversal is
      explicit and iterative, and every entry is tested BEFORE it is descended into.

      A reparse point anywhere in the runtime application tree is refused outright
      rather than skipped: the tree is supposed to be a robocopied artifact of real
      files, so a link in it means production was assembled by something other than
      this script, and its identity cannot be proven from what is stored underneath.

      -SkipTopLevel names first-level directories that are excluded from the comparison
      anyway (protected runtime state: storage, logs, ...). They are not descended into,
      so a link inside operator-managed runtime state cannot block a deploy - the gate
      only asserts over the tree it actually compares.

      Enumeration uses -Force so a HIDDEN junction cannot evade the check, but hidden
      and system ENTRIES are then skipped, which keeps the returned file set identical
      to the non-Force recursion this replaced.
    #>
    param([string]$Root, [string[]]$SkipTopLevel)

    $rootNorm = "$Root".TrimEnd('\', '/')
    $rootItem = Get-Item -LiteralPath $rootNorm -Force
    if ($rootItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
        throw "BLOCKED: the production application root '$rootNorm' is a reparse point (junction/symlink), not a real directory. The tree that would be verified is not the tree that is stored; refusing an unprovable identity comparison."
    }

    $files = New-Object System.Collections.Generic.List[object]
    $queue = New-Object System.Collections.Generic.Queue[string]
    $queue.Enqueue($rootNorm)

    while ($queue.Count -gt 0) {
        $dir = $queue.Dequeue()
        foreach ($child in @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction Stop)) {
            # Reparse test FIRST - before the hidden/system filter and before any descent.
            if ($child.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw "BLOCKED: reparse point (junction/symlink) inside the production application tree: '$($child.FullName)'. Production is expected to be a robocopied tree of real files; a link means it was assembled by something other than this deployment authority and its identity cannot be verified. Remove the link or reconcile production from a known SHA."
            }
            if ($child.Attributes -band [System.IO.FileAttributes]::Hidden) { continue }
            if ($child.Attributes -band [System.IO.FileAttributes]::System) { continue }
            if ($child.PSIsContainer) {
                $rel = $child.FullName.Substring($rootNorm.Length).TrimStart('\', '/').Replace('\', '/')
                if ($rel -and ($SkipTopLevel -contains $rel.Split('/')[0])) { continue }
                $queue.Enqueue($child.FullName)
            }
            else { $files.Add($child) }
        }
    }
    return $files
}

# ---------------------------------------------------------------- phases
function Assert-ProductionMatchesRecordedSha {
    <#
      Read-only production identity gate. Proves that the CURRENT production application
      tree is exactly the tree of the commit recorded in the production version marker,
      BEFORE the deploy stops the service, stages an artifact, or takes a backup.

      Why it exists: New-BackupUnit records restored_sha by READING the version marker
      (Read-VersionMarker) - it does not re-derive that SHA from the bytes it backs up. If
      production were a HYBRID (marker says commit X but some files are actually commit Y -
      e.g. an out-of-band copy that bypassed this script) the backup would be labelled X
      while holding non-X bytes, and a later rollback would stamp production with a SHA that
      does not match its own files. This gate makes that state fail closed at the TOP of the
      deploy instead of minting a mislabelled, effectively-unrollbackable unit. It is the
      upstream guarantee that makes 'restored_sha = Read-VersionMarker' trustworthy.

      Method (EOL-robust): the deploy artifact is robocopied from a working tree, so runtime
      text files carry the platform CRLF while git blobs are LF - a raw byte compare would
      false-mismatch on every text file. Instead compare git object ids. 'git ls-tree -r
      <sha>' gives the committed blob id of every tracked application file; running the same
      repo's 'git hash-object' over each runtime file applies the IDENTICAL autocrlf clean
      filter, so a byte-correct file yields the same id regardless of line endings. Any
      missing, differing, or extraneous runtime file is a mismatch.

      Fails closed and never guesses: an absent/invalid marker, a marker SHA absent from the
      source repository, or any single file discrepancy all throw BLOCKED - an identity is
      never inferred from a partial match. Protected runtime paths (storage, logs, .env,
      __pycache__, ... from protected_dirs/protected_files, plus the leaves of
      protected_runtime_paths) are excluded on BOTH sides - consistent with, though
      mechanically distinct from, the robocopy /XD convergence exclusions: they are runtime
      state, never part of the committed tree, and would otherwise always read as extraneous.
      Also requires core.autocrlf 'true'/'input' so the clean filter normalises CRLF->LF;
      otherwise the object-id compare is inconclusive and the gate fails closed. Read-only in EVERY mode
      including plan mode - it is a pure inspection and takes no lock, writes nothing, and
      drives no service.
    #>
    param($Cfg, [string]$ExpectSha)
    Write-Host "== Production identity gate (runtime bytes vs recorded version marker) =="

    if ($ExpectSha) {
        # Reconciliation asserts against an OPERATOR-SUPPLIED identity instead of the marker,
        # because the whole premise of that mode is that the marker is the thing that is wrong.
        # This is not a weakening: the comparison below is byte-for-byte identical, and the
        # supplied SHA is bound by a signed authorization covering exactly this direction.
        #
        # Two callers pass -ExpectSha, and neither substitutes a claim for the marker:
        #   -Reconcile, above; and the runtime no-op path, which has ALREADY passed the
        #   marker-anchored gate and re-runs this proof against the reviewed target before
        #   advancing the marker to it. That second call ADDS a proof rather than replacing
        #   one - it is what stops a wrong no-op verdict from laundering drift into a
        #   "verified" identity. A normal deploy that converges bytes still never passes it.
        if ($ExpectSha -notmatch $script:SHA_RX) {
            throw "BLOCKED: -ExpectSha '$ExpectSha' is not a full 40-character lowercase commit SHA; refusing to assert production identity against an unresolvable value."
        }
        $recorded = $ExpectSha
        Write-Host "  asserting against the supplied identity $recorded (reconciliation; the version marker is NOT trusted here)"
    }
    else {
        $recorded = Read-VersionMarker -Path $Cfg.version_file
        if (-not $recorded) {
            throw "BLOCKED: production version marker $($Cfg.version_file) is absent or does not hold a single 40-hex commit SHA. Production identity is unverifiable; refusing to deploy over an unknown tree. Establish the true production SHA (operator-authorised reconciliation) before deploying."
        }
    }

    $SRC = $Cfg.source_root
    if (-not (Test-Path (Join-Path $SRC ".git"))) { throw "BLOCKED: $SRC is not a git working tree; production identity cannot be verified" }
    # The EOL-robust object-id compare is only sound if git's clean filter normalises the
    # runtime CRLF back to the committed LF. That normalisation happens ONLY when core.autocrlf
    # is 'true' or 'input'. With 'false' (or unset resolving to false) hash-object would hash
    # the raw CRLF bytes and every text file would false-mismatch - an inconclusive comparison
    # that must fail closed, never silently pass or silently over-block. git config exits 1 with
    # no stderr when the key is unset, so no redirection is needed (see the note below).
    $autocrlf = & git -C $SRC config core.autocrlf
    if ($LASTEXITCODE -ne 0) { $autocrlf = "" }
    $autocrlf = "$autocrlf".Trim().ToLowerInvariant()
    if ($autocrlf -ne "true" -and $autocrlf -ne "input") {
        throw "BLOCKED: git core.autocrlf in $SRC is '$autocrlf' (need 'true' or 'input'). The identity gate compares git object ids and relies on the clean filter normalising the runtime CRLF to the committed LF; without it every text file would false-mismatch. Refusing an inconclusive comparison. Set core.autocrlf before deploying."
    }
    # No stderr redirection on native git: 2>$null / 2>&1 in PS 5.1 wraps stderr in a
    # NativeCommandError that THROWS under ErrorActionPreference=Stop before $LASTEXITCODE is
    # read. The exit code alone is the authority here; any git stderr is informational.
    & git -C $SRC cat-file -e "$recorded^{commit}" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "BLOCKED: the production version marker records $recorded, which is not a commit in $SRC. The recorded identity cannot be resolved to a tree; refusing to deploy. Fetch the commit or reconcile production identity first."
    }
    if (-not (Test-Path $Cfg.runtime_app)) {
        throw "BLOCKED: production application tree $($Cfg.runtime_app) does not exist; it cannot be verified against $recorded."
    }

    # The application subtree, addressed by the SAME relative path git uses - derived from
    # config, never a literal: source_app MUST live under source_root.
    $rootNorm = "$SRC".TrimEnd('\', '/')
    $appNorm = "$($Cfg.source_app)".TrimEnd('\', '/')
    if (-not $appNorm.StartsWith($rootNorm, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "BLOCKED: source_app '$appNorm' is not under source_root '$rootNorm'; the tracked application tree is unaddressable"
    }
    $relPrefix = $appNorm.Substring($rootNorm.Length).TrimStart('\', '/').Replace('\', '/')
    if (-not $relPrefix) { throw "BLOCKED: source_app equals source_root; the application subtree is unaddressable" }

    $protDirs = @($Cfg.protected_dirs)
    $protFiles = @($Cfg.protected_files)
    # Belt-and-suspenders against config divergence: protected_runtime_paths is a SEPARATE key
    # (absolute runtime paths the deploy must never converge). Its leaves are normally also
    # named in protected_dirs/protected_files, but if an operator adds one there and omits it
    # here, an otherwise-protected top-level runtime path could read as EXTRANEOUS and block a
    # legitimate deploy. Fold each leaf into the exclusion set so the two keys cannot diverge.
    foreach ($p in @($Cfg.protected_runtime_paths)) {
        if (-not $p) { continue }
        $leaf = ("$p" -split '[\\/]')[-1]
        if ($leaf -and ($protDirs -notcontains $leaf)) { $protDirs += $leaf }
    }

    # EXPECTED: committed blob id per app-relative path at the recorded SHA.
    #
    # Ordinal dictionaries, NOT PowerShell hashtables. @{} compares keys CASE-INSENSITIVELY.
    # Git is case-SENSITIVE, so a commit may legitimately track both 'Foo.py' and 'foo.py';
    # in a hashtable those two collapse into one key and the second silently overwrites the
    # first. The comparison would then be short by a file, and - worse - a runtime file that
    # is genuinely absent would be masked by its case-twin instead of reported MISSING. Exact
    # lookups are therefore ordinal, and case folding is tracked in a SEPARATE dictionary used
    # for nothing but detecting the collision.
    $expected = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([System.StringComparer]::Ordinal)
    $expectedFold = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([System.StringComparer]::OrdinalIgnoreCase)
    $lsRaw = & git -C $SRC ls-tree -r $recorded -- $relPrefix
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED: git ls-tree failed for $recorded -- '$relPrefix' (exit $LASTEXITCODE)" }
    foreach ($line in @($lsRaw)) {
        if (-not $line) { continue }
        # <mode> SP <type> SP <oid> TAB <path>
        if ($line -notmatch '^\S+\s+(\S+)\s+(\S+)\t(.+)$') { continue }
        $type = $Matches[1]; $oid = $Matches[2]; $path = $Matches[3]
        if ($type -ne 'blob') { continue }   # skip trees/submodules; the app tree has none
        # Defensive: the '-- $relPrefix' pathspec is component-safe (it never returns a sibling
        # such as 'service/app_v2/...'), but never Substring a path that is not actually under
        # the prefix - a future git surprise would otherwise mint a corrupt app-relative key.
        if (-not ("$path/").StartsWith("$relPrefix/", [System.StringComparison]::Ordinal)) { continue }
        $appRel = $path.Substring($relPrefix.Length).TrimStart('/')
        $first = $appRel.Split('/')[0]
        if ($protDirs -contains $first) { continue }
        $leaf = $appRel.Split('/')[-1]
        $isProt = $false
        foreach ($pat in $protFiles) { if ($leaf -like $pat) { $isProt = $true; break } }
        if ($isProt) { continue }
        # Collision block, BEFORE any comparison. Two tracked paths that fold to the same
        # Windows name cannot both exist in the runtime tree, so at most one of them can ever
        # be verified and the other is indistinguishable from a deleted file. That is an
        # unverifiable tree by construction - refuse it rather than compare it.
        if ($expectedFold.ContainsKey($appRel)) {
            throw "BLOCKED: commit $recorded tracks two application paths that collide under Windows' case-insensitive filesystem: '$($expectedFold[$appRel])' and '$appRel'. Only one can exist in the runtime tree, so production identity cannot be proven either way. Refusing an unverifiable comparison."
        }
        $expected[$appRel] = $oid
        $expectedFold[$appRel] = $appRel
    }
    if ($expected.Count -lt 1) {
        throw "BLOCKED: recorded SHA $recorded has no tracked files under '$relPrefix'; it cannot be the production application tree"
    }

    # ACTUAL: hash-object every non-protected runtime file (autocrlf clean filter => blob id).
    $runtimeRootNorm = "$($Cfg.runtime_app)".TrimEnd('\', '/')
    $relList = New-Object System.Collections.Generic.List[string]
    $absList = New-Object System.Collections.Generic.List[string]
    foreach ($f in @(Get-ReparseSafeFiles -Root $Cfg.runtime_app -SkipTopLevel $protDirs)) {
        $appRel = $f.FullName.Substring($runtimeRootNorm.Length).TrimStart('\', '/').Replace('\', '/')
        $first = $appRel.Split('/')[0]
        if ($protDirs -contains $first) { continue }
        $leaf = $appRel.Split('/')[-1]
        $isProt = $false
        foreach ($pat in $protFiles) { if ($leaf -like $pat) { $isProt = $true; break } }
        if ($isProt) { continue }
        $relList.Add($appRel)
        $absList.Add($f.FullName)
    }

    # ATTRIBUTE CONTEXT. A blob id is not a property of bytes alone: .gitattributes can add a
    # clean filter, force text/eol conversion, or set working-tree-encoding, and those rules are
    # keyed on the REPOSITORY-RELATIVE path. The runtime files live OUTSIDE the work tree, so a
    # bare 'git hash-object <C:\runtime\...>' matches no attribute pattern and silently hashes
    # with default rules - against committed blobs that were written WITH those rules. If a
    # future '* text=auto' (or any filter) is committed, every text file would then false-
    # mismatch and the gate would block a correct deploy. So: ask git what attributes actually
    # apply to the tracked paths. None configured -> the fast chunked form is provably
    # equivalent. Any configured -> hash each file under its repository path with --path=, so
    # the identical rules apply on both sides. Never hash a runtime path without repo context.
    $attrsConfigured = $false
    if ($relList.Count -gt 0) {
        $probeArr = @($relList | ForEach-Object { "$relPrefix/$_" })
        $chunk = 200
        for ($start = 0; $start -lt $probeArr.Count -and -not $attrsConfigured; $start += $chunk) {
            $end = [Math]::Min($start + $chunk, $probeArr.Count) - 1
            $pbatch = @($probeArr[$start..$end])
            $attrRaw = @(& git -C $SRC check-attr text eol working-tree-encoding filter ident -- @pbatch)
            if ($LASTEXITCODE -ne 0) { throw "BLOCKED: git check-attr failed while resolving attribute context for the application tree (exit $LASTEXITCODE); the object-id comparison would be unsound. Refusing." }
            foreach ($line in $attrRaw) {
                if (-not $line) { continue }
                # '<path>: <attr>: <value>' - a path may itself contain ': ', so read from the
                # RIGHT: the value is the last field and the attribute name the one before it.
                $parts = "$line" -split ': '
                if ($parts.Count -lt 3) { continue }
                if ($parts[-1] -ne 'unspecified') { $attrsConfigured = $true; break }
            }
        }
    }

    $actual = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([System.StringComparer]::Ordinal)
    $actualFold = New-Object 'System.Collections.Generic.Dictionary[string,string]' ([System.StringComparer]::OrdinalIgnoreCase)
    if ($absList.Count -gt 0 -and $attrsConfigured) {
        Write-Host "  attribute context: .gitattributes rules apply to the application tree; hashing each file under its repository path"
        for ($i = 0; $i -lt $absList.Count; $i++) {
            $oid = & git -C $SRC hash-object --path="$relPrefix/$($relList[$i])" $absList[$i]
            if ($LASTEXITCODE -ne 0) { throw "BLOCKED: git hash-object failed while hashing production file '$($relList[$i])' under its repository path (exit $LASTEXITCODE)" }
            $actual[$relList[$i]] = "$oid".Trim()
        }
    }
    elseif ($absList.Count -gt 0) {
        # Hash every runtime file with git hash-object (same repo => same autocrlf clean
        # filter as the committed blobs). Paths go as ARGUMENTS in bounded chunks, not via
        # --stdin-paths: piping paths to a native command in PS 5.1 can prepend an encoding
        # BOM to the first line (git then cannot open it), and a single call risks the
        # command-line length limit. Chunked args sidestep both; PS quotes spaced paths.
        $absArr = $absList.ToArray()
        $relArr = $relList.ToArray()
        $chunk = 200
        for ($start = 0; $start -lt $absArr.Count; $start += $chunk) {
            $end = [Math]::Min($start + $chunk, $absArr.Count) - 1
            $batch = @($absArr[$start..$end])
            $oids = @(& git -C $SRC hash-object @batch)
            if ($LASTEXITCODE -ne 0) { throw "BLOCKED: git hash-object failed while hashing production files (exit $LASTEXITCODE)" }
            if ($oids.Count -ne $batch.Count) {
                throw "BLOCKED: production identity gate could not hash every file ($($oids.Count) ids for $($batch.Count) paths); refusing an inconclusive comparison"
            }
            for ($j = 0; $j -lt $batch.Count; $j++) { $actual[$relArr[$start + $j]] = "$($oids[$j])".Trim() }
        }
    }
    foreach ($rel in $actual.Keys) { $actualFold[$rel] = $rel }

    $mismatch = @(); $missing = @(); $extra = @(); $caseDiff = @()
    foreach ($rel in $expected.Keys) {
        if ($actual.ContainsKey($rel)) {
            if ($actual[$rel] -ne $expected[$rel]) { $mismatch += $rel }
        }
        elseif ($actualFold.ContainsKey($rel)) {
            # Same name, different case. Not MISSING (the bytes may be right) and not
            # EXTRANEOUS (it is a tracked file) - it is a distinct, blocking defect: the
            # runtime path does not equal the committed path, so a case-sensitive consumer
            # (an import, a URL route) can resolve differently in production than in the
            # commit that was reviewed.
            $caseDiff += "$rel (runtime holds '$($actualFold[$rel])')"
        }
        else { $missing += $rel }
    }
    foreach ($rel in $actual.Keys) {
        # A runtime file already reported as CASE-DIFFERS is not also EXTRANEOUS.
        if (-not $expected.ContainsKey($rel) -and -not $expectedFold.ContainsKey($rel)) { $extra += $rel }
    }

    $problems = $missing.Count + $mismatch.Count + $extra.Count + $caseDiff.Count
    Write-Host "  recorded=$recorded tracked=$($expected.Count) runtime=$($actual.Count) changed=$($mismatch.Count) missing=$($missing.Count) extraneous=$($extra.Count) case-differs=$($caseDiff.Count)"
    if ($problems -gt 0) {
        @(
            ($mismatch | ForEach-Object { "CHANGED: $_" })
            ($missing | ForEach-Object { "MISSING: $_" })
            ($extra | ForEach-Object { "EXTRANEOUS: $_" })
            ($caseDiff | ForEach-Object { "CASE-DIFFERS: $_" })
        ) | Select-Object -First 40 | ForEach-Object { Write-Host "    $_" }
        throw "BLOCKED: PRODUCTION IDENTITY MISMATCH - the runtime application tree does not match its recorded version marker $recorded ($($mismatch.Count) changed, $($missing.Count) missing, $($extra.Count) extraneous, $($caseDiff.Count) case-differs). Production is a HYBRID: deploying now would back these bytes up under the WRONG SHA, and a later rollback would stamp an identity that does not match the files. Refusing. Reconcile production to a known SHA (operator-authorised reconciliation) before deploying."
    }
    Write-Host "  production identity verified: runtime application tree == recorded marker $recorded ($($expected.Count) files)"
}

function Get-SourceRelativePath {
    # Repo-relative, forward-slashed pathspec for git, derived from the configured absolute
    # path. Never written literally: source_app is the configuration authority, and a
    # hardcoded second copy here could drift out of agreement with the bytes robocopy
    # actually stages -- a runtime-difference check consulting a stale path would report
    # "nothing changed" about a directory the deploy does not even copy.
    param($Cfg, [string]$Absolute)
    $root = $Cfg.source_root.TrimEnd('\', '/')
    $abs = $Absolute.TrimEnd('\', '/')
    if (-not $abs.ToLowerInvariant().StartsWith("$root\".ToLowerInvariant())) {
        throw "BLOCKED: configured deploy source '$Absolute' is not inside source_root '$($Cfg.source_root)'. No repo-relative pathspec can be derived, and a comparison over an unresolvable path would silently compare NOTHING and report a false no-op."
    }
    return $abs.Substring($root.Length + 1).Replace('\', '/')
}

function Test-RuntimeUnchanged {
    <#
      Does the reviewed target differ, in the bytes this deploy would actually copy, from
      the commit production is already running? Asked AFTER the identity gate, so the
      "from" side is a proven identity and not merely a marker's claim.

      Why a git question and not a path classifier: a deploy/no-deploy rules table is a
      second source of truth that can drift away from source_app, and it drifts toward
      "we skipped a deploy that mattered". This asks the only question the deploy cares
      about -- do the staged bytes differ -- so it cannot disagree with what the deploy does.

      Fail-safe direction. Every uncertainty resolves to $false (deploy normally), never to
      a no-op: a tracked file under a protected dir is excluded from the artifact yet still
      counted as a difference here, and a missing or drifted runtime engine file is a
      difference too. The one thing NOT tolerated is an inconclusive git result -- the
      artifact is staged from this same working tree, so a git failure here is not a reason
      to proceed with a full deploy, it is a reason to stop.

      Engine files are hashed, not trusted. The identity gate proves the runtime APPLICATION
      tree; runtime_engine has no marker-backed proof at all, so "git says these two commits
      carry identical engine files" would say nothing about what production actually holds.
      Out-of-band drift there is invisible to a pure commit-to-commit diff, so the bytes are
      compared directly. Drift means "not a no-op", and the normal path repairs it.
    #>
    param($Cfg, [string]$FromSha, [string]$ToSha, [string]$UnitScope)
    Write-Host "== Runtime difference check ($FromSha -> $ToSha, scope $UnitScope) =="
    $SRC = $Cfg.source_root
    if ($FromSha -notmatch $script:SHA_RX -or $ToSha -notmatch $script:SHA_RX) {
        throw "BLOCKED: the runtime difference check needs two full 40-character commit SHAs (got '$FromSha' -> '$ToSha'). Refusing to infer a no-op from an unresolvable identity."
    }

    $paths = @()
    if ($UnitScope -ne "Engine") { $paths += Get-SourceRelativePath -Cfg $Cfg -Absolute $Cfg.source_app }
    if ($UnitScope -ne "App") { $paths += @($Cfg.engine_files) }
    if ($paths.Count -lt 1) {
        throw "BLOCKED: scope '$UnitScope' produced no comparison paths. An empty pathspec makes 'git diff' compare the WHOLE tree, which is not the question being asked."
    }
    Write-Host "  comparing: $($paths -join ', ')"

    # No stderr redirection on native git (see the identity gate's note): 2>$null in PS 5.1
    # throws a NativeCommandError before $LASTEXITCODE can be read. --quiet exits 0 for no
    # differences and 1 for differences; anything else is an error, never a verdict.
    & git -C $SRC diff --quiet $FromSha $ToSha -- $paths
    $code = $LASTEXITCODE
    if ($code -eq 1) {
        Write-Host "  runtime differences present - proceeding with the full deploy"
        # Write-Host only: native git stdout must NOT enter the success output stream.
        # In Windows PowerShell 5.1, any uncaptured pipeline output is part of the
        # function's return value, so `if (Test-RuntimeUnchanged …)` would see a
        # non-empty array (name-status lines + $false) and wrongly take the NO-OP
        # path on a real delta — the 2026-08-07 consolidation deploy failure mode.
        & git -C $SRC diff --name-status $FromSha $ToSha -- $paths | ForEach-Object { Write-Host "  $_" }
        return $false
    }
    if ($code -ne 0) {
        throw "BLOCKED: 'git diff --quiet' exited $code in $SRC - the comparison is inconclusive. That is not a reason to fall back to a full deploy: the release artifact is staged from this same working tree, so a git failure here casts doubt on the bytes that would ship. Resolve the source repository state first."
    }

    if ($UnitScope -ne "App") {
        foreach ($ef in $Cfg.engine_files) {
            $s = Join-Path $SRC $ef
            $d = Join-Path $Cfg.runtime_engine $ef
            if (-not (Test-Path $s)) { throw "BLOCKED: engine source missing: $s" }
            if (-not (Test-Path $d)) {
                Write-Host "  engine file absent from the runtime engine directory - NOT a no-op"
                return $false
            }
            if ((Get-FileHash $s -Algorithm SHA256).Hash -ne (Get-FileHash $d -Algorithm SHA256).Hash) {
                Write-Host "  engine bytes in production differ from source (out-of-band drift) - NOT a no-op"
                return $false
            }
            Write-Host "  engine unchanged and byte-identical in production: $ef"
        }
    }

    Write-Host "  no runtime differences: this deploy would copy the bytes production already has"
    return $true
}

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
    # -RestoredSha is the ONE supported override of the marker-derived provenance, and it
    # exists solely for Invoke-Reconcile, which runs against a runtime whose marker is KNOWN
    # to be false. It is not a caller's assertion: the reconcile path supplies it only after
    # Assert-ProductionMatchesRecordedSha has PROVED the runtime is that commit, twice, by
    # git object id. Every other caller must leave it empty so the marker remains the only
    # source of restored-content identity.
    param($Cfg, [string]$Sha, [string]$UnitScope, [string]$RestoredSha)
    if ($RestoredSha -and $RestoredSha -notmatch $script:SHA_RX) {
        throw "BLOCKED: -RestoredSha '$RestoredSha' is not a full 40-character commit SHA. A backup unit's restored-content identity is never recorded from an unresolvable value."
    }
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
        # HARDENING: reading restored_sha from the marker is only SOUND because
        # Assert-ProductionMatchesRecordedSha ran at the top of Invoke-Deploy and proved the
        # runtime bytes about to be backed up ARE the tree of this marker. That gate is the
        # load-bearing guarantee here; without it a HYBRID tree (marker X, bytes partly Y)
        # would be backed up and mislabelled X. Do NOT drop the gate call and keep this line -
        # that reintroduces exactly the provenance-integrity defect this backup relies on it
        # to prevent.
        # RECONCILE EXCEPTION: when -RestoredSha is supplied the marker on disk is the FALSE
        # value being repaired, so reading it would record the very lie this operation exists
        # to correct. The supplied identity has been proved against the runtime bytes by the
        # identity gate immediately above this call, which is a STRONGER guarantee than the
        # marker read - it is derived from the bytes themselves, not from a claim about them.
        # NAMING IS LOAD-BEARING: this local is deliberately NOT called $restoredSha.
        # PowerShell variable names are case-INSENSITIVE, so `$restoredSha = ...` would
        # silently overwrite the $RestoredSha PARAMETER, and every later test of the
        # parameter would then be reading the resolved value instead. Two concrete defects
        # that caused: an ordinary marker-derived deploy was labelled mode='reconcile', and
        # - because the parameter carries a [string] constraint - the no-marker case
        # recorded restored_sha as '' rather than null, contradicting the 'never guessed'
        # promise above. Keep the two names distinct.
        $restoredIdentity = if ($RestoredSha) { $RestoredSha } elseif ($appPresent) { Read-VersionMarker -Path $Cfg.version_file } else { $null }
        # Surface the unrollbackable unit AT DEPLOY TIME. Without this the unit is minted
        # silently and the defect is only discovered mid-incident, when the rollback that
        # was supposed to be the remedy refuses. This is a warning, not a block: the
        # forward deploy is still correct, and blocking it would strand production on the
        # very state the operator is trying to leave.
        if ($appPresent -and -not $restoredIdentity) {
            Write-Warning "PROVENANCE: no readable pre-deploy version marker at $($Cfg.version_file). Unit $unit is being recorded WITHOUT a restored-content SHA and a rollback to it will be REFUSED until provenance is supplied from an independent record (see production_deployment_rule.md, 'Legacy unit recovery')."
        }
        # 'mode' records HOW this unit came to exist, so an auditor reading a backup directory
        # can tell a routine pre-deploy snapshot from the one taken while repairing a runtime
        # whose marker was wrong. It is descriptive metadata only - no code branches on it.
        $unitMode = if ($RestoredSha) { "reconcile" } else { "deploy" }
        # unit.json is written FIRST so a crash mid-backup still leaves the unit
        # self-describing; 'complete' is flipped only after both manifests exist. 'sha' is
        # retained for compatibility with units/readers minted before the split;
        # deployment_sha and restored_sha are the two explicit provenance authorities.
        [pscustomobject]@{
            unit = $unit; sha = $Sha; deployment_sha = $Sha; restored_sha = $restoredIdentity
            scope = $UnitScope; created = (Get-Date -Format o)
            app_backed_up = $appPresent; engine_backed_up = $enginePresent
            bootstrap = [bool]$Bootstrap; mode = $unitMode; complete = $false
        } | ConvertTo-Json | Set-Content (Join-Path $bak "unit.json") -Encoding UTF8
        # A write-once, immutable snapshot of the pre-deploy marker. unit.json is rewritten
        # when 'complete' flips true, so this copy is the tamper-evident corroborating
        # source that Resolve-RestoredSha cross-checks at rollback time.
        if ($appPresent -and $RestoredSha) {
            # Reconcile: copying the on-disk marker here would snapshot the false identity and
            # then DISAGREE with unit.json, which Resolve-RestoredSha treats as unresolved
            # provenance - permanently refusing every rollback to this unit. Snapshot the
            # proved identity instead, in the exact byte shape Write-VersionFile emits so both
            # corroborating sources parse identically.
            [System.IO.File]::WriteAllText((Join-Path $bak "version.pre.txt"), $RestoredSha, (New-Object System.Text.ASCIIEncoding))
        }
        elseif ($appPresent -and (Test-Path $Cfg.version_file)) {
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

function Invoke-Reconcile {
    <#
      OPERATOR-AUTHORISED REPAIR of a production tree whose bytes do not match its recorded
      version marker.

      Why this exists inside the deployment authority. The identity gate correctly refuses to
      deploy over a hybrid runtime, but refusing is only half a control: an operator facing a
      blocked deploy has to fix the marker somehow, and every route available before this mode
      existed was worse than the defect. -Bootstrap skipped the gate and would mint a backup
      labelled with the OLD marker while holding the CURRENT bytes. Editing version.txt by hand
      breaks the single-writer rule and asserts an identity nobody proved. Copying files into
      production directly is how the drift happened in the first place. The repair therefore
      belongs here, under the same lock, the same authorization, and the same proof the deploy
      path uses - not in an external procedure.

      What it guarantees, in order:
        1. Authorization is bound to the ACTION and to BOTH SHAs. A generic permission to
           "reconcile" is insufficient and is refused by the helper: the signature covers the
           ordered pair, so an artifact minted for one drift cannot repair a different one.
        2. Everything runs under the deployment lock.
        3. The gate PROVES the runtime is -FromSha (by git object id, the same comparison the
           deploy gate makes) before anything is stopped or written.
        4. That proof is REPEATED immediately before the backup is created, so the unit is
           minted from a runtime proven at the moment of minting, not one proven earlier.
        5. Backup metadata records restored_sha = -FromSha - the identity just proved, not the
           marker, which is the thing known to be false.
        6. Convergence uses only the approved -ToSha artifact.
        7. The converged tree is verified against -ToSha, by object id, not merely against the
           artifact manifest.
        8. version.txt is stamped ONLY after that verification passes.
        9. Any failure before the final verification leaves the OLD marker intact and produces
           no trusted target-labelled state: a unit minted mid-run carries the proved FromSha
           as its restored content, so it is a real rollback target rather than a mislabelled
           one.

      It is NOT a substitute for a deploy: it demands the operator already knows, and can
      prove, what production actually is. If -FromSha is wrong, nothing happens.
    #>
    param($Cfg, [string]$From, [string]$To)

    if (-not $From -or $From -notmatch $script:SHA_RX) {
        throw "BLOCKED: -Reconcile requires -FromSha as a full 40-character commit SHA - the identity production ACTUALLY holds right now. It is proved against the runtime bytes, never assumed; if you do not know it, run with -WhatIf against candidate SHAs first."
    }
    if (-not $To -or $To -notmatch $script:SHA_RX) {
        throw "BLOCKED: -Reconcile requires -ToSha as a full 40-character commit SHA - the reviewed commit to converge production to."
    }
    if ($From -eq $To) {
        throw "BLOCKED: -FromSha and -ToSha are identical, so there is nothing to reconcile. If production already matches its marker, deploy normally; if the marker is wrong but the bytes are right, that is still a reconcile - supply the marker's value as -FromSha only when the BYTES are that commit."
    }
    if ($Bootstrap) {
        throw "BLOCKED: -Bootstrap and -Reconcile are mutually exclusive. -Bootstrap asserts there is no prior tree and skips the identity gate; -Reconcile asserts there IS one and proves it. Combining them would discard the proof this mode exists to make."
    }
    if ($ReviewedSHA) {
        throw "BLOCKED: -Reconcile takes -ToSha, not -ReviewedSHA. Two candidate targets in one invocation is exactly the ambiguity that must never reach a production write."
    }

    $SRC = $Cfg.source_root
    Write-Host "== RECONCILE production identity: $From -> $To =="
    Write-Host "  This mode does NOT skip the identity gate. It proves the runtime is $From,"
    Write-Host "  twice, and writes nothing if that proof fails."

    # ---- source preconditions (read-only; no git history is mutated on this path) ----
    if (-not (Test-Path (Join-Path $SRC ".git"))) {
        throw "BLOCKED: $SRC is not a git working tree; a reconciliation target cannot be verified."
    }
    & git -C $SRC cat-file -e "$From^{commit}"
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED: -FromSha $From is not a commit in $SRC; the claimed current identity is unverifiable." }
    & git -C $SRC cat-file -e "$To^{commit}"
    if ($LASTEXITCODE -ne 0) { throw "BLOCKED: -ToSha $To is not a commit in $SRC." }
    $dirty = & git -C $SRC status --porcelain
    if ($dirty) {
        throw "BLOCKED: $SRC has uncommitted changes. The artifact is staged from this working tree, so production would receive bytes that are not the reviewed commit."
    }
    # HEAD is REQUIRED to already be the target. Unlike the deploy path, reconcile never
    # fast-forwards the source: it is invoked because production is in an unproven state, and
    # moving the certified tree in the same breath would make it impossible to say afterwards
    # which tree the operator actually reviewed.
    $head = (& git -C $SRC rev-parse HEAD).Trim()
    if ($head -ne $To) {
        throw "BLOCKED: $SRC HEAD is $head but -ToSha is $To. Reconcile stages from the working tree and deliberately never moves HEAD; check the source out at the reviewed target first."
    }
    & git -C $SRC fetch origin | Out-Null
    & git -C $SRC merge-base --is-ancestor $To origin/main
    if ($LASTEXITCODE -ne 0) {
        throw "BLOCKED: -ToSha $To is not contained in origin/main. Reconciliation converges production only to a reviewed, merged commit - it is a repair path, not a way to ship unreviewed code past the deploy preconditions."
    }
    Write-Host "  source verified: $SRC is clean at $To, which is contained in origin/main"

    # ---- authorization: MOVED, not removed. The single Assert-Authorization call for
    # ---- reconcile now sits INSIDE the lock, immediately after PROOF 1 (see below),
    # ---- so a failed identity proof can no longer consume the single-use artifact.
    # ---- Consuming it here - before the runtime was proven to be -FromSha - burned a
    # ---- jti on every wrong guess and made the operator re-mint for nothing.
    Enter-DeployLock -Cfg $Cfg
    # Position tracker, set immediately before each transition so a throw is attributed to the
    # step it happened in - the operator must never be told "nothing was written" about a tree
    # that is mid-overwrite.
    $stage = "not started"
    try {
        # PROOF 1: under the lock, service still Running, nothing touched. -ExpectSha overrides
        # the marker precisely because the marker is the artefact being repaired.
        Assert-ProductionMatchesRecordedSha -Cfg $Cfg -ExpectSha $From
        $stage = "runtime PROVED to be $From; nothing stopped, staged or written"
        # ---- authorization: the ordered pair, consumed only AFTER the identity proof,
        # ---- under the lock, immediately before the first mutation (the service stop).
        # ---- A failed proof must never cost a single-use jti: the previous design
        # ---- evaluated the artifact before proving the runtime, so a wrong -FromSha
        # ---- consumed the token and THEN refused, leaving the operator to re-mint.
        if ($script:ReleaseMode) { Invoke-ReleaseMint -Cfg $Cfg -Sha $To -Action "reconcile" -UnitScope $Scope -FromSha $From }
        if (-not $script:PlanOnly) { Assert-Authorization -Cfg $Cfg -Sha $To -Action "reconcile" -UnitScope $Scope -SourceSha $From }
        Set-ServiceState -Cfg $Cfg -Target Stopped
        $stage = "service stopped; production content untouched"
        $unit = $null
        try {
            $art = New-ReleaseArtifact -Cfg $Cfg -Sha $To
            # PROOF 2, immediately before the backup. Between proof 1 and this line the service
            # was stopped and an artifact staged; a backup is a provenance record and must be
            # minted from a runtime proven AT THE MOMENT OF MINTING. Without this repetition the
            # window between the two is exactly the TOCTOU that produces a mislabelled unit -
            # the single defect this whole mode exists to avoid creating.
            Assert-ProductionMatchesRecordedSha -Cfg $Cfg -ExpectSha $From
            $stage = "service stopped; runtime re-proved as $From immediately before backup"
            $unit = New-BackupUnit -Cfg $Cfg -Sha $To -UnitScope $Scope -RestoredSha $From
            $script:LastUnit = $unit.Unit
            Get-DestinationInventory -Cfg $Cfg -ArtifactPath $art | Out-Null
        }
        catch {
            Write-Host ""
            Write-Host "RECOVERY STATE: RECONCILE_BLOCKED_NO_WRITE"
            Write-Host "  Preparation failed BEFORE production content was modified: $($_.Exception.Message)"
            Write-Host "  Position when it failed: $stage"
            Write-Host "  Production files and the version marker are unchanged. The marker still reads"
            Write-Host "  its previous value, which is correct: nothing was converged."
            Write-Host "  If the identity proof is what failed, -FromSha does not describe this runtime."
            Write-Host "  Establish what production actually is before retrying - do NOT reach for -Bootstrap,"
            Write-Host "  which would skip the proof and mint a mislabelled backup."
            Write-Host "  Safe restart:  sc.exe start $($Cfg.service)"
            throw
        }
        try {
            $stage = "backup unit $($unit.Unit) minted with restored_sha=$From; PRODUCTION CONVERGENCE IN PROGRESS - the application tree is mid-overwrite"
            if ($Scope -ne "Engine") { Invoke-Converge -Cfg $Cfg -ArtifactPath $art }
            if ($Scope -ne "App") { Invoke-EngineSync -Cfg $Cfg }
            if ($Scope -ne "Engine") {
                [void](Test-AgainstManifest -ManifestFile "$art.manifest.csv" -Root $Cfg.runtime_app -What "reconciled application")
            }
            $stage = "production converged and manifest-verified; version marker NOT yet stamped"
            # PROOF 3 - the point of the operation. The manifest proves the tree equals the
            # ARTIFACT; this proves it equals the COMMIT, by git object id, which is exactly the
            # comparison the next ordinary deploy will make. Stamping the marker before this
            # passed would re-create the defect under a new SHA.
            if (-not $script:PlanOnly) {
                Assert-ProductionMatchesRecordedSha -Cfg $Cfg -ExpectSha $To
            }
            else {
                Write-Host "  would verify the converged tree against $To before stamping the marker"
            }
            $stage = "production converged and PROVED to be $To; stamping the version marker"
            Write-VersionFile -Cfg $Cfg -Sha $To
            if (-not $script:PlanOnly) {
                $onDisk = Read-VersionMarker -Path $Cfg.version_file
                if ($onDisk -ne $To) {
                    throw "BLOCKED: post-reconcile version marker '$onDisk' does not equal the converged identity '$To'. The advertised SHA and the production bytes disagree - the exact defect this mode repairs - so the service is left STOPPED for operator inspection."
                }
            }
            $stage = "reconciled, verified and stamped; starting the service"
            Set-ServiceState -Cfg $Cfg -Target Running
            if (-not $script:PlanOnly) {
                Write-Host "RECONCILE COMPLETE - production is $To and its version marker agrees; rollback unit $($unit.Unit) holds the pre-reconcile tree as content $From; service Running"
            }
            else {
                Write-Host "PLAN COMPLETE - nothing was written. Production would converge $From -> $To; the marker and service are unchanged."
            }
        }
        catch {
            Write-Host ""
            Write-Host "RECOVERY STATE: RECONCILE_FAILED"
            Write-Host "  Production WAS being modified when this failed: $($_.Exception.Message)"
            Write-Host "  Position when it failed: $stage"
            Write-Host "  The service is STOPPED and the application tree may be partially converged."
            Write-Host "  The version marker was NOT advanced unless the failure occurred after stamping,"
            Write-Host "  so it does not falsely advertise $To."
            Write-Host "  DO NOT start the service on a partial tree. Roll back:"
            Write-Host "      Deploy-PZ.ps1 -Rollback -Unit $($unit.Unit)"
            Write-Host "  That unit restores content $From and re-stamps the marker to it, returning"
            Write-Host "  production to a state whose bytes and marker agree (a rollback authorization"
            Write-Host "  artifact for $To is required)."
            throw
        }
    }
    finally { Exit-DeployLock -Cfg $Cfg }
}

# ---------------------------------------------------------------- entry point
function Invoke-DeployMain {
    <#
      The ordinary deploy body, shared by -ReviewedSHA (operator supplies the target) and
      -Release (the target is the resolved origin/main tip, bound to the gate evidence).

      AUTHORIZATION ORDERING: the single-use authorization is consumed INSIDE the lock,
      AFTER the production identity gate has passed and after the no-op decision is made -
      immediately before the first production write of whichever branch runs. The previous
      design evaluated (and consumed) it before the identity proof, so a failed identity
      check burned a minted jti for nothing. A read-only failure must never cost a token.
    #>
    param($cfg, [string]$TargetSha)

    # Lock BEFORE any mutable preparation so two operators cannot both stage or back up.
    Enter-DeployLock -Cfg $cfg
    try {
        # Prove production IS the tree its version marker claims, BEFORE the service is
        # stopped, an artifact is staged, or a backup is taken. Read-only and taken under the
        # deploy lock (closes the read/backup TOCTOU). A mismatch throws out through the
        # finally below (lock released) with the service still Running and nothing on
        # production touched, so a HYBRID tree can never be backed up and mislabelled by
        # New-BackupUnit. Skipped only for -Bootstrap, where there is no prior tree to verify.
        # Runs in plan mode too - it writes nothing.
        if (-not $Bootstrap) {
            try { Assert-ProductionMatchesRecordedSha -Cfg $cfg }
            catch {
                Write-Host ""
                Write-Host "RECOVERY STATE: IDENTITY_GATE_BLOCKED"
                Write-Host "  Production was NOT modified and the service is still Running: $($_.Exception.Message)"
                Write-Host "  Nothing was stopped, staged, or backed up, and no rollback unit was minted (correctly)."
                Write-Host "  Reconcile production to a known SHA (operator-authorised) before retrying the deploy."
                throw
            }
        }
        else {
            # -Bootstrap is the ONLY path that skips the identity gate, so it is exactly the
            # path an operator reaches for when the gate blocks. Auditing that with a warning
            # was not enough: a warning still proceeds into New-BackupUnit, which mints a unit
            # labelled with the OLD marker while holding the CURRENT bytes - the precise
            # rollback-provenance defect the gate exists to prevent. Bootstrap therefore means
            # "there is no prior tree", and that is now asserted rather than assumed.
            # A missing or genuinely empty runtime tree may bootstrap; anything else fails closed
            # and is told to use -Reconcile, which repairs identity WITHOUT skipping the proof.
            if (Test-Path $cfg.runtime_app) {
                $existing = @(Get-ChildItem -LiteralPath $cfg.runtime_app -Recurse -File -Force -ErrorAction SilentlyContinue)
                if ($existing.Count -gt 0) {
                    throw "BLOCKED: -Bootstrap was used against an EXISTING, NON-EMPTY production tree at $($cfg.runtime_app) ($($existing.Count) files). -Bootstrap is for a first-ever deploy only and skips the production identity gate; using it here would back up an unverified tree under the deployment SHA and destroy rollback provenance. If production identity is wrong, repair it with the operator-authorised reconciliation mode (-Reconcile -FromSha <actual> -ToSha <target>), which proves identity instead of skipping it."
                }
            }
            Write-Host "== Production identity gate skipped (-Bootstrap: no prior tree) =="
        }

        # Runtime no-op short-circuit. A merge that changed only tests, docs or CI cannot
        # alter the staged bytes -- the artifact is built from source_app plus engine_files
        # and nothing else -- so stopping the service, staging, mirroring and restarting
        # would be an outage-shaped way of copying identical files over themselves.
        #
        # Deliberately placed AFTER the identity gate: the comparison is only meaningful
        # because the "from" side has just been PROVEN to be what production runs. Asking
        # this question against an unverified marker would decide "nothing to do" from a
        # claim rather than a fact. -Bootstrap has no prior tree and no marker, so it never
        # takes this path.
        if (-not $Bootstrap) {
            $recordedSha = Read-VersionMarker -Path $cfg.version_file
            if (Test-RuntimeUnchanged -Cfg $cfg -FromSha $recordedSha -ToSha $TargetSha -UnitScope $Scope) {
                Write-Host ""
                Write-Host "== RUNTIME NO-OP: the reviewed target changes nothing this deploy would copy =="
                # The marker advances only if production bytes ARE the target tree. The diff
                # above is a claim about two commits; this is a proof about the actual runtime.
                # Were that comparison ever wrong, advancing the marker would launder real
                # drift into a "verified" identity and the next deploy would gate against a
                # lie -- the one failure this optimisation could plausibly cause. So the
                # existing gate is re-run against the target instead of trusting the shortcut.
                Assert-ProductionMatchesRecordedSha -Cfg $cfg -ExpectSha $TargetSha
                # Marker advance is a production write: authorization is consumed HERE,
                # after both proofs, immediately before the only write this branch makes.
                if ($script:ReleaseMode) { Invoke-ReleaseMint -Cfg $cfg -Sha $TargetSha -Action "deploy" -UnitScope $Scope }
                if (-not $script:PlanOnly) { Assert-Authorization -Cfg $cfg -Sha $TargetSha -Action "deploy" -UnitScope $Scope }
                Write-VersionFile -Cfg $cfg -Sha $TargetSha
                Write-Host ""
                if ($script:PlanOnly) {
                    Write-Host "PLAN COMPLETE - runtime no-op. Nothing was written; no unit exists."
                }
                else {
                    Write-Host "RUNTIME NO-OP COMPLETE  from=$recordedSha  to=$TargetSha  scope=$Scope"
                    Write-Host "  Service NOT stopped. No artifact staged. No files copied. Service NOT restarted."
                    Write-Host "  No backup unit was created: no application byte changed, so there is nothing to restore"
                    Write-Host "  and no rollback identifier is implied. The version marker moved and nothing else did."
                    Write-Host "  Previous marker was $recordedSha; reverting it is an operator-authorised reconciliation."
                    Write-Host "  Validate:  Test-PZDeployClose.ps1 -ExpectedSHA $TargetSha"
                }
                return
            }
        }

        # Real deploy: authorization is consumed HERE - after the identity gate, after the
        # no-op decision, immediately before the first mutation (the service stop).
        if ($script:ReleaseMode) { Invoke-ReleaseMint -Cfg $cfg -Sha $TargetSha -Action "deploy" -UnitScope $Scope }
        if (-not $script:PlanOnly) { Assert-Authorization -Cfg $cfg -Sha $TargetSha -Action "deploy" -UnitScope $Scope }
        Set-ServiceState -Cfg $cfg -Target Stopped
        $unit = $null
        try {
            $art = New-ReleaseArtifact -Cfg $cfg -Sha $TargetSha
            $unit = New-BackupUnit -Cfg $cfg -Sha $TargetSha -UnitScope $Scope
            $script:LastUnit = $unit.Unit
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
            Write-VersionFile -Cfg $cfg -Sha $TargetSha
            Set-ServiceState -Cfg $cfg -Target Running
        }
        catch {
            Write-Host ""
            Write-Host "RECOVERY STATE: PARTIAL_DEPLOY"
            Write-Host "  Production WAS being modified when this failed: $($_.Exception.Message)"
            Write-Host "  The service is STOPPED and the application tree may be partially converged."
            Write-Host "  DO NOT start the service on a partial tree. Roll back:"
            Write-Host "      Deploy-PZ.ps1 -Rollback -Unit $($unit.Unit)"
            Write-Host "  (a rollback authorization artifact for $TargetSha is required)"
            throw
        }
    }
    finally { Exit-DeployLock -Cfg $cfg }

    if (-not $script:PlanOnly) {
        Write-Host ""
        Write-Host "DEPLOY COMPLETE  sha=$TargetSha  unit=$($unit.Unit)  scope=$Scope"
        Write-Host "Validate:  Test-PZDeployClose.ps1 -ExpectedSHA $TargetSha"
        Write-Host "Rollback:  Deploy-PZ.ps1 -Rollback -Unit $($unit.Unit)"
    }
    else {
        Write-Host ""
        Write-Host "PLAN COMPLETE - nothing was written. No unit exists; no rollback identifier is implied."
    }
}

function Invoke-ReleaseFlow {
    <#
      ONE-COMMAND RELEASE. The operator's whole workflow is `-Release`.

      Exactly four hard blockers, each named in the output when it fires:
        1. The seven-agent verdict is not GO (gate evidence at the configured path).
        2. Production runtime identity cannot be proven against origin/main history.
        3. Backup / copy / manifest verification fails (enforced by the inner paths).
        4. The service is not healthy after the deploy (closure validation fails).
      Everything else - stale markers, reconcile-vs-deploy selection, SHA choreography,
      signing ceremony, no-op detection, stale dead-process locks - resolves internally.
      CI is deliberately not consulted; an inherited-red CI is not a production risk.

      Prints exactly ONE final status: ALREADY CURRENT / DEPLOYED / ROLLED BACK /
      FAILED SAFE. FAILED SAFE always means production is either untouched or left
      stopped-and-described by the inner recovery states; nothing is silently half-done.
    #>
    param($Cfg)
    $script:ReleaseMode = $true
    $script:LastUnit = $null
    $SRC = $Cfg.source_root
    $status = $null
    $failReason = ""
    try {
        # ---- read-only phase: no lock, no mint, no writes -------------------------
        Invoke-Preflight -Cfg $Cfg
        $target = (& git -C $SRC rev-parse origin/main).Trim().ToLower()
        if ($LASTEXITCODE -ne 0 -or $target -notmatch $script:SHA_RX) {
            throw "BLOCKED: could not resolve origin/main to a commit SHA in $SRC."
        }
        Write-Host "== RELEASE target: origin/main = $target =="

        # HARD BLOCKER 1 - the seven-agent gate evidence must be a GO for exactly this
        # target. Validated read-only FIRST, so missing or stale evidence costs nothing:
        # no probe, no mint, no lock. The signer re-validates the same file at mint time
        # and binds its digest into the signature, so this early check can never
        # substitute for the signed one - it only fails faster.
        $evidence = Join-Path $PSScriptRoot "..\hooks\gate_evidence.py"
        if (-not (Test-Path $evidence)) { throw "BLOCKED: gate evidence validator missing: $evidence" }
        & python $evidence $Cfg.gate_evidence_file $target
        if ($LASTEXITCODE -ne 0) {
            throw "BLOCKED (hard blocker 1/4): the gate evidence at $($Cfg.gate_evidence_file) is not a valid seven-agent GO for $target. Run the seven-agent gate against this SHA and write its evidence there; nothing was probed, minted, locked, or written."
        }

        # Bind the certified source to the resolved target. Reuses the exact reviewed-
        # target discipline of the manual flow (including the 'advanced BEYOND' refusal,
        # which cannot fire here because the target IS the origin/main tip just read).
        Assert-ReviewedTarget -Cfg $Cfg -Sha $target

        # HARD BLOCKER 2 - prove what production actually runs. The marker is EVIDENCE
        # (a candidate probed after the target), never authority: the proof is the byte
        # comparison, and a wrong marker just means the next candidate is tried. The
        # candidate list is bounded, explicit, and comes from origin/main history that
        # touched the bytes this deploy copies.
        $marker = Read-VersionMarker -Path $Cfg.version_file
        $appRel = Get-SourceRelativePath -Cfg $Cfg -Absolute $Cfg.source_app
        $recent = @(& git -C $SRC rev-list -n 30 origin/main -- $appRel @($Cfg.engine_files))
        if ($LASTEXITCODE -ne 0) { throw "BLOCKED: git rev-list failed while enumerating identity candidates." }
        $candidates = @(@($target) + @($marker) + $recent |
            Where-Object { $_ -and "$_" -match $script:SHA_RX } | Select-Object -Unique)
        $actualSha = $null
        foreach ($cand in $candidates) {
            try {
                Assert-ProductionMatchesRecordedSha -Cfg $Cfg -ExpectSha $cand
                $actualSha = $cand
                break
            }
            catch {
                Write-Host "  identity probe: runtime is NOT $($cand.Substring(0, 12)) - trying the next candidate"
            }
        }
        if (-not $actualSha) {
            throw "BLOCKED (hard blocker 2/4): production runtime identity could not be proven. The application tree at $($Cfg.runtime_app) matches neither the target, the version marker, nor any of the last $($recent.Count) origin/main commits that touched the deployed paths. -Release refuses to write over an unproven tree. Establish the true identity and repair with the advanced -Reconcile mode."
        }
        Write-Host "  production identity PROVEN: runtime is $actualSha"

        # ---- decide, then act. Authorization is minted and consumed by the inner path,
        # ---- always after its own re-proof and always before its first write. --------
        if ($actualSha -eq $target) {
            if (Test-RuntimeUnchanged -Cfg $Cfg -FromSha $target -ToSha $target -UnitScope $Scope) {
                if ($marker -eq $target) {
                    Write-Host "  runtime bytes, engine files and version marker all already match $target"
                    $status = "ALREADY CURRENT"
                    return
                }
                # Bytes are the target; only the marker lies. Repair it under the full
                # discipline: lock, re-proof, signed single-use authorization, stamp,
                # read-back. No service restart - no runtime byte changed.
                Write-Host "  runtime bytes already match $target; correcting the stale version marker (service untouched)"
                Enter-DeployLock -Cfg $Cfg
                try {
                    Assert-ProductionMatchesRecordedSha -Cfg $Cfg -ExpectSha $target
                    if ($script:ReleaseMode) { Invoke-ReleaseMint -Cfg $Cfg -Sha $target -Action "deploy" -UnitScope $Scope }
                    if (-not $script:PlanOnly) { Assert-Authorization -Cfg $Cfg -Sha $target -Action "deploy" -UnitScope $Scope }
                    Write-VersionFile -Cfg $Cfg -Sha $target
                    if (-not $script:PlanOnly) {
                        $onDisk = Read-VersionMarker -Path $Cfg.version_file
                        if ($onDisk -ne $target) { throw "BLOCKED: marker read-back '$onDisk' != '$target' after the stamp." }
                    }
                }
                finally { Exit-DeployLock -Cfg $Cfg }
                $status = "ALREADY CURRENT"
                return
            }
            # Bytes match but an engine file drifted: fall through to the ordinary
            # deploy, whose engine sync repairs drift and whose no-op check will not fire.
        }

        # Pre-mint the ROLLBACK authorization while everything is still healthy: minting
        # one mid-incident costs time, and rollback is deliberately evidence-exempt.
        if (-not $script:PlanOnly) { Invoke-ReleaseMint -Cfg $Cfg -Sha $target -Action "rollback" -UnitScope $Scope }

        if ($actualSha -eq $marker -or $actualSha -eq $target) {
            # Marker agrees with the proven bytes (or bytes are already the target with
            # engine drift): the ordinary deploy path handles it, including the no-op
            # shortcut, with authorization consumed after its own identity gate.
            Invoke-DeployMain -cfg $Cfg -TargetSha $target
        }
        else {
            # Proven bytes disagree with the marker: production is a HYBRID. This is the
            # reconcile case, selected and DIRECTED automatically from the PROVEN
            # identity - the operator no longer chooses a mode or supplies a direction.
            Write-Host "== auto-selected RECONCILE: marker says '$marker' but runtime is proven $actualSha =="
            Invoke-Reconcile -Cfg $Cfg -From $actualSha -To $target
        }

        # HARD BLOCKER 4 - the release is not done until the closure validation passes:
        # version marker, artifact manifest, engine hashes, protected paths, service
        # Running, authenticated health endpoints, rollback unit present.
        if (-not $script:PlanOnly) {
            Write-Host "== Closure validation (automatic) =="
            $closure = Join-Path $PSScriptRoot "Test-PZDeployClose.ps1"
            & powershell -NoProfile -ExecutionPolicy Bypass -File $closure -ExpectedSHA $target
            if ($LASTEXITCODE -ne 0) {
                throw "BLOCKED (hard blocker 4/4): closure validation failed after the deploy - the service or a close-condition is not healthy. See the FAIL lines above; the release is NOT closed."
            }
        }
        $status = "DEPLOYED"
    }
    catch {
        $failReason = $_.Exception.Message
        # If a production write had begun, a backup unit exists - attempt the automatic
        # rollback with the pre-minted artifact. The inner recovery states have already
        # described the exact position; this is the remedy, not the diagnosis.
        if ($script:LastUnit -and -not $script:PlanOnly) {
            Write-Host ""
            Write-Host "== RELEASE: write phase failed; attempting automatic rollback to unit $($script:LastUnit) =="
            try {
                Invoke-Rollback -Cfg $Cfg -UnitId $script:LastUnit
                $status = "ROLLED BACK"
            }
            catch {
                Write-Host "  automatic rollback ALSO failed: $($_.Exception.Message)"
                $status = "FAILED SAFE"
            }
        }
        else {
            $status = "FAILED SAFE"
        }
    }
    finally {
        Write-Host ""
        Write-Host "================================================================"
        Write-Host "RELEASE RESULT: $status"
        if ($status -eq "FAILED SAFE") {
            Write-Host "  reason: $failReason"
            Write-Host "  Nothing is silently half-done: production is either untouched (read-only phase"
            Write-Host "  failures write nothing) or left in the exact described recovery state above."
        }
        if ($status -eq "ROLLED BACK") {
            Write-Host "  the deploy failed and production was restored from unit $($script:LastUnit)."
            Write-Host "  original failure: $failReason"
        }
        Write-Host "================================================================"
    }
    if ($status -ne "DEPLOYED" -and $status -ne "ALREADY CURRENT") {
        throw "RELEASE did not complete: $status - $failReason"
    }
}

function Invoke-Deploy {
    param([switch]$PlanOnly)
    $script:PlanOnly = [bool]$PlanOnly
    $transcriptStarted = $false
    if ($DeployLog) {
        # Elevated child only: path was minted by the unelevated parent under LOCALAPPDATA.
        Assert-CanonicalDeployLogPath -LogFilePath $DeployLog
        $logDir = Split-Path -LiteralPath $DeployLog -Parent
        if (-not (Test-Path -LiteralPath $logDir)) {
            New-Item -ItemType Directory -Path $logDir -Force | Out-Null
        }
        Start-Transcript -Path $DeployLog -Force | Out-Null
        $transcriptStarted = $true
    }
    try {
        if ($script:PlanOnly) {
            Write-Host "*** -WhatIf: PLAN ONLY - no writes, no lock, no service change, no authorization required ***"
        }
        else {
            # Privilege BEFORE mint/consume/service: non-elevated parents terminate here after
            # UAC without touching authorization. Elevated children prove Administrator and continue.
            Request-AdministratorElevationIfNeeded
        }
        $cfg = Get-DeployConfig

        if ($Release) {
            # One-command mode is deliberately incompatible with every manual override: a
            # release that also accepted a hand-picked SHA or direction would be the manual
            # flow wearing the automatic flow's name.
            if ($ReviewedSHA -or $Reconcile -or $Rollback -or $Bootstrap -or $FromSha -or $ToSha -or $Unit) {
                throw "BLOCKED: -Release takes no target, mode, or direction parameters. It resolves origin/main, proves the runtime identity, and selects NO-OP / DEPLOY / RECONCILE itself. Use the advanced modes directly if you need manual control."
            }
            Invoke-ReleaseFlow -Cfg $cfg
            return
        }

        if ($Rollback) { Invoke-Rollback -Cfg $cfg -UnitId $Unit; return }
        if ($Reconcile) { Invoke-Reconcile -Cfg $cfg -From $FromSha -To $ToSha; return }
        # -FromSha / -ToSha are meaningless outside reconcile, and silently ignoring them is how an
        # operator ends up believing a direction was enforced when the run was an ordinary deploy.
        if ($FromSha -or $ToSha) {
            throw "BLOCKED: -FromSha / -ToSha are only valid with -Reconcile. An ordinary deploy converges to -ReviewedSHA and makes no claim about the identity it started from; accepting these here would advertise a proof that never ran."
        }

        if (-not $ReviewedSHA) {
            throw "BLOCKED: -ReviewedSHA is required. Supply the exact SHA approved by the 7-agent gate, or use -Release for the one-command flow; the deployed target of a manual deploy is never inferred from origin/main."
        }
        Invoke-Preflight -Cfg $cfg
        Assert-ReviewedTarget -Cfg $cfg -Sha $ReviewedSHA
        Invoke-DeployMain -cfg $cfg -TargetSha $ReviewedSHA
    }
    finally {
        if ($transcriptStarted) {
            try { Stop-Transcript | Out-Null } catch { }
        }
    }
}

if (-not $NoRun) { Invoke-Deploy -PlanOnly:$WhatIf }
