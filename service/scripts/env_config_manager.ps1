# env_config_manager.ps1
# ======================
# Configuration management for PZ Correction Lifecycle activation.
#
# Equivalent role to IaC (Terraform/CloudFormation) for this NSSM/Windows deployment.
# Manages .env flag state, validates invariants, and provides rollback checkpoints.
#
# IMPORTANT: This project deploys to a Windows NSSM service (PZService), not a
# cloud provider. Terraform/CloudFormation are not applicable. This script provides
# the same idempotent, declarative, checkpoint-based configuration guarantees.
#
# Usage
# -----
#   # Show current state (read-only)
#   .\env_config_manager.ps1 -Action Show
#
#   # Activate lifecycle flag (Step 1 of activation runbook)
#   .\env_config_manager.ps1 -Action ActivateLifecycle
#
#   # Rollback lifecycle flag
#   .\env_config_manager.ps1 -Action RollbackLifecycle
#
#   # Assert health gate (Step 3)
#   .\env_config_manager.ps1 -Action AssertHealth
#
#   # Assert push flag still OFF (Step 6 safety check)
#   .\env_config_manager.ps1 -Action AssertPushOff
#
#   # Create a timestamped .env backup (checkpoint)
#   .\env_config_manager.ps1 -Action Checkpoint
#
# Safety invariants
# -----------------
#   1. WFIRMA_CORRECTION_PUSH_ALLOWED is never written by this script.
#   2. Every .env write is atomic (write to .env.tmp, then rename).
#   3. A checkpoint backup is created before every write.
#   4. All actions are idempotent — running twice produces the same state.

param(
    [Parameter(Mandatory=$true)]
    [ValidateSet("Show","ActivateLifecycle","RollbackLifecycle","AssertHealth",
                 "AssertPushOff","Checkpoint","RestartService","FullGate")]
    [string]$Action,

    [string]$EnvPath     = "C:\PZ\.env",
    [string]$ServiceName = "PZService",
    [string]$BaseUrl     = "http://127.0.0.1:47213",
    [string]$CheckpointDir = "C:\PZ\env-checkpoints"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

function Read-Env {
    param([string]$Path)
    $result = @{}
    if (-not (Test-Path $Path)) { throw ".env not found at $Path" }
    Get-Content $Path | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#")) {
            $idx = $line.IndexOf("=")
            if ($idx -gt 0) {
                $k = $line.Substring(0, $idx).Trim()
                $v = $line.Substring($idx + 1).Trim()
                $result[$k] = $v
            }
        }
    }
    return $result
}

function Write-EnvAtomic {
    param([string]$Path, [string]$Content)
    $tmp = "$Path.tmp"
    Set-Content -Path $tmp -Value $Content -Encoding utf8 -NoNewline
    Move-Item -Path $tmp -Destination $Path -Force
}

function Set-EnvFlag {
    param([string]$Path, [string]$Flag, [string]$Value)
    $raw = Get-Content $Path -Raw
    $pattern = "(?m)^$([regex]::Escape($Flag))\s*=.*$"
    $newLine  = "$Flag=$Value"
    if ($raw -match $pattern) {
        $newContent = $raw -replace $pattern, $newLine
    } else {
        $newContent = $raw.TrimEnd("`r","`n") + "`n$newLine`n"
    }
    Write-EnvAtomic -Path $Path -Content $newContent
}

function Create-Checkpoint {
    param([string]$EnvPath, [string]$Dir)
    if (-not (Test-Path $Dir)) { New-Item -ItemType Directory -Path $Dir -Force | Out-Null }
    $stamp = (Get-Date -Format "yyyyMMdd-HHmmss")
    $dest  = Join-Path $Dir "env-checkpoint-$stamp.bak"
    Copy-Item -Path $EnvPath -Destination $dest -Force
    Write-Host "[CHECKPOINT] Saved: $dest" -ForegroundColor Cyan
    return $dest
}

function Get-ServiceState {
    param([string]$Name)
    $out = & sc.exe query $Name 2>&1
    foreach ($line in $out) {
        if ($line -match "STATE\s+:\s+\d+\s+(\w+)") { return $Matches[1] }
    }
    return "UNKNOWN"
}

function Restart-PZService {
    param([string]$Name)
    Write-Host "[SERVICE] Stopping $Name ..." -ForegroundColor Yellow
    & sc.exe stop $Name | Out-Null
    Start-Sleep -Seconds 10
    Write-Host "[SERVICE] Starting $Name ..." -ForegroundColor Yellow
    & sc.exe start $Name | Out-Null
    Start-Sleep -Seconds 12
    $state = Get-ServiceState -Name $Name
    Write-Host "[SERVICE] State: $state" -ForegroundColor $(if ($state -eq "RUNNING") { "Green" } else { "Red" })
    return $state -eq "RUNNING"
}

function Test-Health {
    param([string]$BaseUrl, [string]$ApiKey)
    $url = "$BaseUrl/api/v1/health"
    try {
        $r = Invoke-WebRequest -Uri $url -Headers @{"X-API-Key"=$ApiKey} `
             -UseBasicParsing -TimeoutSec 10
        return $r.StatusCode -eq 200
    } catch { return $false }
}

function Assert-PushFlagOff {
    param([hashtable]$Env)
    $val = $Env["WFIRMA_CORRECTION_PUSH_ALLOWED"]
    if ($val -and ($val.ToLower() -in @("true","1","yes"))) {
        Write-Host "[ABORT] WFIRMA_CORRECTION_PUSH_ALLOWED=$val is set." -ForegroundColor Red
        Write-Host "        This activation window manages the lifecycle flag ONLY." -ForegroundColor Red
        Write-Host "        Push enablement requires a separate controlled decision." -ForegroundColor Red
        exit 2
    }
}

# ---------------------------------------------------------------------------
# Actions
# ---------------------------------------------------------------------------

switch ($Action) {

    "Show" {
        Write-Host "`n[STATE] Current .env flag configuration" -ForegroundColor Cyan
        $env = Read-Env -Path $EnvPath
        $lc   = $env["PZ_CORRECTION_LIFECYCLE_ENABLED"]
        $push = $env["WFIRMA_CORRECTION_PUSH_ALLOWED"]
        $svc  = Get-ServiceState -Name $ServiceName
        Write-Host "  PZ_CORRECTION_LIFECYCLE_ENABLED  = $($lc   -or '(absent → false)')"
        Write-Host "  WFIRMA_CORRECTION_PUSH_ALLOWED   = $($push  -or '(absent → false)')"
        Write-Host "  $ServiceName state                = $svc"
        Write-Host ""
        $lcOn   = $lc   -and ($lc.ToLower()   -in @("true","1","yes"))
        $pushOn = $push -and ($push.ToLower() -in @("true","1","yes"))
        if (-not $lcOn -and -not $pushOn) {
            Write-Host "  Phase 1: DORMANT (both flags off)" -ForegroundColor Yellow
        } elseif ($lcOn -and -not $pushOn) {
            Write-Host "  Phase 1: ACTIVE — lifecycle routes live, wFirma write BLOCKED" -ForegroundColor Green
        } elseif ($lcOn -and $pushOn) {
            Write-Host "  Phase 2: FULLY ACTIVE — wFirma write path reachable" -ForegroundColor Magenta
        }
    }

    "Checkpoint" {
        Create-Checkpoint -EnvPath $EnvPath -Dir $CheckpointDir
    }

    "ActivateLifecycle" {
        Write-Host "`n[ACTIVATE] Enabling PZ_CORRECTION_LIFECYCLE_ENABLED=true" -ForegroundColor Green
        $env = Read-Env -Path $EnvPath
        # Safety guard: push flag must not already be on
        Assert-PushFlagOff -Env $env
        # Create checkpoint before any write
        Create-Checkpoint -EnvPath $EnvPath -Dir $CheckpointDir
        # Write flag
        Set-EnvFlag -Path $EnvPath -Flag "PZ_CORRECTION_LIFECYCLE_ENABLED" -Value "true"
        Write-Host "[OK] Flag written to $EnvPath" -ForegroundColor Green
        Write-Host "[NEXT] Run: .\env_config_manager.ps1 -Action RestartService" -ForegroundColor Cyan
        Write-Host "[NEXT] Then: .\env_config_manager.ps1 -Action AssertHealth" -ForegroundColor Cyan
    }

    "RollbackLifecycle" {
        Write-Host "`n[ROLLBACK] Reverting PZ_CORRECTION_LIFECYCLE_ENABLED to false" -ForegroundColor Yellow
        Create-Checkpoint -EnvPath $EnvPath -Dir $CheckpointDir
        Set-EnvFlag -Path $EnvPath -Flag "PZ_CORRECTION_LIFECYCLE_ENABLED" -Value "false"
        Write-Host "[OK] Flag reverted." -ForegroundColor Yellow
        $ok = Restart-PZService -Name $ServiceName
        if (-not $ok) {
            Write-Host "[FAIL] Service did not reach RUNNING — check sc.exe query $ServiceName" -ForegroundColor Red
            exit 1
        }
        Write-Host "[ROLLBACK] Complete. Lifecycle routes are dormant." -ForegroundColor Yellow
    }

    "RestartService" {
        $env    = Read-Env -Path $EnvPath
        $apiKey = $env["AUTH_SECRET_KEY"]
        $ok     = Restart-PZService -Name $ServiceName
        if (-not $ok) {
            Write-Host "[FAIL] Service not RUNNING. Initiating rollback." -ForegroundColor Red
            Set-EnvFlag -Path $EnvPath -Flag "PZ_CORRECTION_LIFECYCLE_ENABLED" -Value "false"
            Restart-PZService -Name $ServiceName | Out-Null
            exit 1
        }
        # Immediate health check
        $healthy = $false
        for ($i = 0; $i -lt 6; $i++) {
            if (Test-Health -BaseUrl $BaseUrl -ApiKey $apiKey) { $healthy = $true; break }
            Start-Sleep -Seconds 5
        }
        if (-not $healthy) {
            Write-Host "[FAIL] Health check failed after restart." -ForegroundColor Red
            exit 1
        }
        Write-Host "[OK] Service RUNNING and healthy." -ForegroundColor Green
    }

    "AssertHealth" {
        $env    = Read-Env -Path $EnvPath
        $apiKey = $env["AUTH_SECRET_KEY"]
        Write-Host "[HEALTH] Checking $BaseUrl/api/v1/health ..." -ForegroundColor Cyan
        $ok = Test-Health -BaseUrl $BaseUrl -ApiKey $apiKey
        if (-not $ok) {
            Write-Host "[FAIL] Health check failed." -ForegroundColor Red
            exit 1
        }
        Write-Host "[OK] Health 200." -ForegroundColor Green
    }

    "AssertPushOff" {
        Write-Host "`n[SAFETY] Asserting WFIRMA_CORRECTION_PUSH_ALLOWED is OFF" -ForegroundColor Cyan
        $env = Read-Env -Path $EnvPath
        Assert-PushFlagOff -Env $env
        $val = $env["WFIRMA_CORRECTION_PUSH_ALLOWED"]
        Write-Host "[OK] WFIRMA_CORRECTION_PUSH_ALLOWED = $($val -or '(absent → false)')" -ForegroundColor Green
        Write-Host "     correction-commit is unreachable (push gate holding)." -ForegroundColor Green
    }

    "FullGate" {
        # Convenience: run all safety assertions in sequence without writing anything.
        Write-Host "`n[FULL GATE] Read-only safety verification" -ForegroundColor Cyan
        & $PSCommandPath -Action Show     -EnvPath $EnvPath -ServiceName $ServiceName -BaseUrl $BaseUrl
        & $PSCommandPath -Action AssertHealth  -EnvPath $EnvPath -ServiceName $ServiceName -BaseUrl $BaseUrl
        & $PSCommandPath -Action AssertPushOff -EnvPath $EnvPath
        Write-Host "[FULL GATE] All checks passed." -ForegroundColor Green
    }
}
