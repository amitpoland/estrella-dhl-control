# ══════════════════════════════════════════════════════════════════════════════
# PZ APP — Production Deploy Manifest
# SHA:       40c30f1 (squash of feat/phase2c-ai-governance-hardening)
# PR:        #359 (Phase 2C — AI Provider Pilot Readiness Hardening)
# Generated: 2026-05-24
# Gate:      7/7 GO (Lead Coordinator authorised)
# Tests:     86/86 pass (Mac pre-flight: 9 Phase 2C + 39 Phase 2B + 21 GW contract + 17 GW violation)
#
# WHAT THIS DEPLOY DOES:
#   1. Adds STARTUP_AI_AUDIT log block to main.py (after existing wFirma audit)
#   2. Fixes active_provider contradiction in routes_ai_advisory.py
#   3. Installs anthropic>=0.50.0 into the Windows venv
#
# WHAT THIS DEPLOY DOES NOT DO:
#   - No .env change
#   - No API key added
#   - No live LLM call enabled
#   - No AI flag changed (all remain OFF)
#   - No business writes (PZ/wFirma/DHL/customs/accounting)
#
# IMPORTANT: This is a TARGETED deploy (2 files + pip install).
#            Do NOT use /MIR or robocopy this branch.
#            The requirements.txt is NOT synced — pip install runs separately.
# ══════════════════════════════════════════════════════════════════════════════

# ── Step 1: Navigate and verify branch ───────────────────────────────────────
Set-Location "C:\Users\Super Fashion\PZ APP"
git status
git branch --show-current   # must be: main

# ── Step 2: Pull ──────────────────────────────────────────────────────────────
git pull --ff-only origin main
$pulledSHA = git rev-parse HEAD
Write-Host "Pulled SHA: $pulledSHA"
# Expected: 40c30f1...  (or the full SHA starting with 40c30f1)

if (-not ($pulledSHA -like "40c30f1*")) {
    Write-Warning "SHA mismatch — check git log before continuing"
}

# ── Step 3: Run tests ─────────────────────────────────────────────────────────
$env:PYTHONIOENCODING = "utf-8"

# PZ regression baseline (required: 160 pass)
python test_pz_regression.py
# Required: 160/160

# Carrier suite baseline (required: 381 pass)
Set-Location "C:\Users\Super Fashion\PZ APP\service"
python -m pytest tests/test_carrier_*.py -q
# Required: 381/381

# Phase 2C + Phase 2B AI governance suite
python -m pytest tests/test_phase2c_governance_hardening.py `
                 tests/test_phase2b_provider_selection.py `
                 tests/test_ai_gateway_contract.py `
                 tests/test_ai_gateway_violation.py -v
# Required: 86/86

Set-Location "C:\Users\Super Fashion\PZ APP"

# ── Step 4: Install anthropic package ────────────────────────────────────────
# requirements.txt is NOT synced by this targeted deploy; install manually.
# The package is already in requirements.txt on main (40c30f1).
python -m pip install "anthropic>=0.50.0"
Write-Host "anthropic install exit: $LASTEXITCODE"
if ($LASTEXITCODE -ne 0) { Write-Error "pip install failed — do not restart service"; exit 1 }

# ── Step 5: Sync targeted files only ─────────────────────────────────────────
# Two files changed in service/app/:
#   app/main.py                    <- STARTUP_AI_AUDIT block
#   app/api/routes_ai_advisory.py  <- active_provider fix
#
Copy-Item "service\app\main.py" "C:\PZ\app\main.py" -Force
Write-Host "Synced: main.py"

Copy-Item "service\app\api\routes_ai_advisory.py" "C:\PZ\app\api\routes_ai_advisory.py" -Force
Write-Host "Synced: routes_ai_advisory.py"

# ── Step 6: Restart PZService (Administrator shell required) ─────────────────
sc.exe stop PZService
$tries = 0
while ((Get-Service PZService).Status -ne 'Stopped' -and $tries -lt 15) {
    Start-Sleep -Seconds 1; $tries++
}
sc.exe start PZService
Start-Sleep -Seconds 10
sc.exe query PZService

# ── Step 7: Post-deploy verification ─────────────────────────────────────────
# Extract API key from .env
$k = (Get-Content "C:\PZ\.env" |
      Where-Object { $_ -match "^API_KEY=" } |
      ForEach-Object { $_.Split("=", 2)[1] })

# Health check
$health = (Invoke-WebRequest "http://127.0.0.1:47213/api/v1/health" -UseBasicParsing).StatusCode
Write-Host "Local health: $health"
# Expected: 200

# AI advisory status — must show active_provider=none + gateway_available=false
$statusRaw = (Invoke-WebRequest "http://127.0.0.1:47213/api/v1/ai/advisory/status" `
    -Headers @{"X-API-Key" = $k} -UseBasicParsing).Content
Write-Host "AI advisory status:"
Write-Host $statusRaw
# Expected fields (all safe):
#   "active_provider": "none"
#   "gateway_available": false
#   "ai_advisory_llm_enabled": false
#   "cowork_enabled": false

# STARTUP_AI_AUDIT must appear in stderr log
$auditLine = Get-Content "C:\PZ\logs\pz_stderr.log" -Tail 50 |
             Select-String "STARTUP_AI_AUDIT"
Write-Host "STARTUP_AI_AUDIT log:"
$auditLine
# Expected: "STARTUP_AI_AUDIT: all AI execution flags are OFF (safe defaults)."
# If any AI flag were accidentally ON it would say WARNING with flag names.

# Public health
$pubHealth = (Invoke-WebRequest "https://pz.estrellajewels.eu/api/v1/health" `
    -UseBasicParsing).StatusCode
Write-Host "Public health: $pubHealth"
# Expected: 200

# ── Required output ───────────────────────────────────────────────────────────
Write-Host "Pulled SHA:         $pulledSHA"
Write-Host "PZ tests:           [x/160]"
Write-Host "Carrier tests:      [x/381]"
Write-Host "AI gov tests:       86/86"
Write-Host "anthropic install:  [OK | FAIL]"
Write-Host "main.py synced:     [OK]"
Write-Host "routes synced:      [OK]"
Write-Host "Service status:     [RUNNING | ERROR]"
Write-Host "Local health:       [200 | ERROR]"
Write-Host "Public health:      [200 | ERROR]"
Write-Host "active_provider:    [none]  <-- must be 'none'"
Write-Host "STARTUP_AI_AUDIT:   [all OFF | WARNING: ...]"
Write-Host "Rollback:           git revert --no-edit 40c30f1"
Write-Host "READY / BLOCKED:"
