# ============================================================
# Windows Production Deploy Script — Phase 2 Advisory LLM
# Origin/main target: #TBD_SHA  (fill after PR merges)
# Campaign: AI Governance Phase 2
#   - service/app/services/ai_advisory.py (MODIFIED — LLM path added)
#   - service/app/api/routes_ai_advisory.py (MODIFIED — /status endpoint added)
# Generated: 2026-05-24 | Profile: windows_prod_v2
# Pre-deploy gate: 7-agent gate REQUIRED before use
#   Tests to pass: PZ 160+  Carrier 381+  AI advisory 82/82
#
# GOVERNANCE:
#   ai_advisory_llm_enabled    = False  (deploy off — NEVER change for initial deploy)
#   ai_advisory_budget_usd_per_day = 1.0
#   ai_advisory_cache_ttl_seconds  = 300
#   All Phase 1 contracts unchanged — llm_used=False by default.
# ============================================================
# OPERATOR: Read every section before executing.
# Execute sequentially — do NOT skip any step.
# This script requires an elevated (Administrator) PowerShell session.
# ============================================================

$ErrorActionPreference = "Stop"

# ── Paths ───────────────────────────────────────────────────
$PYTHON   = "C:\Users\Super Fashion\AppData\Local\Programs\Python\Python39\python.exe"
$PZ_ROOT  = "C:\PZ"
$APP_ROOT = "C:\PZ\app"
$REPO_SRC = "C:\Users\Super Fashion\PZ APP\service"

# ── STEP 0: Pre-deploy safety check ─────────────────────────
Write-Host "`n=== STEP 0: Pre-deploy safety check ===" -ForegroundColor Cyan
Set-Location "C:\Users\Super Fashion\PZ APP"
$ahead = git log --oneline "origin/main..HEAD" 2>&1
if ($ahead -and $ahead.Trim()) {
    Write-Host "WARNING: Windows HEAD is ahead of origin/main:" -ForegroundColor Yellow
    Write-Host $ahead
    Write-Host "Review local commits before pulling. If unexpected, STOP and investigate." -ForegroundColor Red
    Read-Host "Press Enter to continue after review, or Ctrl+C to abort"
} else {
    Write-Host "Windows is at or behind origin/main — no local-only commits." -ForegroundColor Green
}

# ── STEP 1: Git pull ─────────────────────────────────────────
Write-Host "`n=== STEP 1: git pull --ff-only origin main ===" -ForegroundColor Cyan
git fetch origin
git pull --ff-only origin main
$headSha = git rev-parse --short HEAD
Write-Host "HEAD after pull: $headSha" -ForegroundColor Green
# Note: replace #TBD_SHA below once PR merges
# if ($headSha -ne "#TBD_SHA") {
#     Write-Host "NOTE: HEAD is $headSha (expected #TBD_SHA). If Phase 2 SHA is ancestor, fine." -ForegroundColor Yellow
# }

# ── STEP 2: Confirm service directories exist ────────────────
Write-Host "`n=== STEP 2: Ensure target directories exist ===" -ForegroundColor Cyan
foreach ($dir in @("$APP_ROOT\services", "$APP_ROOT\api")) {
    if (-not (Test-Path $dir)) {
        New-Item -ItemType Directory -Path $dir | Out-Null
        Write-Host "Created $dir" -ForegroundColor Green
    } else {
        Write-Host "$dir already exists" -ForegroundColor Gray
    }
}

# ── STEP 3: Stop service ─────────────────────────────────────
Write-Host "`n=== STEP 3: nssm stop PZService ===" -ForegroundColor Cyan
nssm stop PZService
Start-Sleep -Seconds 3
$status = nssm status PZService
Write-Host "Service status: $status"
if ($status -notmatch "SERVICE_STOPPED") {
    Write-Host "ERROR: PZService did not stop. Aborting." -ForegroundColor Red
    exit 1
}

# ── STEP 4: Backup current app ───────────────────────────────
Write-Host "`n=== STEP 4: Backup current app to C:\PZ\app\bak ===" -ForegroundColor Cyan
if (-not (Test-Path "$APP_ROOT\bak")) {
    New-Item -ItemType Directory -Path "$APP_ROOT\bak" | Out-Null
}
robocopy "$APP_ROOT" "$APP_ROOT\bak" /E /COPY:DAT /XD "$APP_ROOT\bak" /XD "$APP_ROOT\__pycache__" /NFL /NDL /NJH
Write-Host "Backup complete." -ForegroundColor Green

# ── STEP 5: Deploy 2 files ───────────────────────────────────
Write-Host "`n=== STEP 5: Deploy Phase 2 files ===" -ForegroundColor Cyan

# File 1 — MODIFIED: ai_advisory.py (Phase 2 LLM path added)
robocopy "$REPO_SRC\app\services" "$APP_ROOT\services" "ai_advisory.py" /COPY:DAT
if ($LASTEXITCODE -gt 3) { Write-Host "ERROR robocopy [1/2] exit $LASTEXITCODE" -ForegroundColor Red; exit 1 }
Write-Host " [1/2] ai_advisory.py (MODIFIED — Phase 2 LLM) → $APP_ROOT\services\" -ForegroundColor Green

# File 2 — MODIFIED: routes_ai_advisory.py (/status endpoint added)
robocopy "$REPO_SRC\app\api" "$APP_ROOT\api" "routes_ai_advisory.py" /COPY:DAT
if ($LASTEXITCODE -gt 3) { Write-Host "ERROR robocopy [2/2] exit $LASTEXITCODE" -ForegroundColor Red; exit 1 }
Write-Host " [2/2] routes_ai_advisory.py (MODIFIED — /status endpoint) → $APP_ROOT\api\" -ForegroundColor Green

Write-Host "All 2 files deployed." -ForegroundColor Green

# ── STEP 6: Start service ─────────────────────────────────────
Write-Host "`n=== STEP 6: nssm start PZService ===" -ForegroundColor Cyan
nssm start PZService
Start-Sleep -Seconds 10
$status = nssm status PZService
Write-Host "Service status: $status"
if ($status -notmatch "SERVICE_RUNNING") {
    Write-Host "ERROR: PZService did not start. Check nssm logs. Rollback available." -ForegroundColor Red
    Write-Host "ROLLBACK: robocopy C:\PZ\app\bak C:\PZ\app /E /COPY:DAT /XD C:\PZ\app\bak" -ForegroundColor Yellow
    exit 1
}

# ── STEP 7: Health checks ─────────────────────────────────────
Write-Host "`n=== STEP 7: Health checks ===" -ForegroundColor Cyan
Start-Sleep -Seconds 3

$healthUrls = @(
    "http://127.0.0.1:47213/api/v1/health",
    "https://pz.estrellajewels.eu/api/v1/health"
)
foreach ($url in $healthUrls) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 15
        Write-Host "  OK  $url — HTTP $($r.StatusCode)" -ForegroundColor Green
    } catch {
        Write-Host "  FAIL $url — $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "ROLLBACK: robocopy C:\PZ\app\bak C:\PZ\app /E /COPY:DAT /XD C:\PZ\app\bak" -ForegroundColor Yellow
        exit 1
    }
}

# ── STEP 8: Phase 2 contract verification ────────────────────
Write-Host "`n=== STEP 8: Phase 2 route probe ===" -ForegroundColor Cyan

# 8a: advisory/workflow-blockers — must still have llm_used=false (flag is off)
try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:47213/api/v1/ai/advisory/workflow-blockers/TEST" `
        -UseBasicParsing -TimeoutSec 10
    $body = $r.Content | ConvertFrom-Json
    Write-Host "  workflow-blockers route: HTTP $($r.StatusCode)" -ForegroundColor Green
    if ($body.llm_used -eq $false) {
        Write-Host "  CONTRACT OK: llm_used=false (flag off by default)" -ForegroundColor Green
    } else {
        Write-Host "  CONTRACT VIOLATION: llm_used is not false — LLM flag should be OFF at deploy time!" -ForegroundColor Red
        exit 1
    }
    if ($body.advisory_class -eq "R") {
        Write-Host "  CONTRACT OK: advisory_class=R" -ForegroundColor Green
    }
    # Phase 2 fields present
    if ($null -ne $body.source) { Write-Host "  Phase 2 field 'source' present: $($body.source)" -ForegroundColor Green }
    if ($null -ne $body.model_used) { Write-Host "  Phase 2 field 'model_used' present (should be null): $($body.model_used)" -ForegroundColor Green }
} catch {
    $code = $_.Exception.Response.StatusCode.Value__
    if ($code -eq 403) {
        Write-Host "  Route mounted (403 = auth gate — expected without API key)" -ForegroundColor Green
    } elseif ($code -in @(503, 400)) {
        Write-Host "  Route mounted (HTTP $code — expected for test batch_id)" -ForegroundColor Green
    } elseif ($code -eq 404) {
        Write-Host "  FAIL: 404 — advisory route NOT mounted. Check main.py import." -ForegroundColor Red
        exit 1
    } else {
        Write-Host "  NOTE: HTTP $code — $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# 8b: NEW /status endpoint — Phase 2 addition
try {
    $r2 = Invoke-WebRequest -Uri "http://127.0.0.1:47213/api/v1/ai/advisory/status" `
        -UseBasicParsing -TimeoutSec 10
    $body2 = $r2.Content | ConvertFrom-Json
    Write-Host "  /status route: HTTP $($r2.StatusCode)" -ForegroundColor Green
    Write-Host "  ai_advisory_llm_enabled: $($body2.ai_advisory_llm_enabled)" -ForegroundColor Green
    if ($body2.ai_advisory_llm_enabled -eq $true) {
        Write-Host "  WARNING: ai_advisory_llm_enabled=true — LLM is active! Confirm this is intentional." -ForegroundColor Red
    } else {
        Write-Host "  CONTRACT OK: LLM disabled at deploy time" -ForegroundColor Green
    }
    Write-Host "  model: $($body2.model)" -ForegroundColor Green
    Write-Host "  budget_usd_per_day: $($body2.budget_usd_per_day)" -ForegroundColor Green
    Write-Host "  spent_usd_today: $($body2.spent_usd_today)" -ForegroundColor Green
    Write-Host "  budget_ok: $($body2.budget_ok)" -ForegroundColor Green
} catch {
    $code = $_.Exception.Response.StatusCode.Value__
    if ($code -eq 403) {
        Write-Host "  /status route mounted (403 = auth gate — expected without API key)" -ForegroundColor Green
    } elseif ($code -eq 404) {
        Write-Host "  FAIL: /status returns 404 — Phase 2 route not deployed correctly!" -ForegroundColor Red
        exit 1
    } else {
        Write-Host "  NOTE: HTTP $code — $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# ── STEP 9: Grep deployed files for Phase 2 markers ─────────
Write-Host "`n=== STEP 9: Verify deployed file content ===" -ForegroundColor Cyan
$markerAdvisory = Select-String -Path "$APP_ROOT\services\ai_advisory.py" -Pattern "batch_readiness\+llm" -Quiet
if ($markerAdvisory) {
    Write-Host "  ai_advisory.py: Phase 2 marker 'batch_readiness+llm' present" -ForegroundColor Green
} else {
    Write-Host "  FAIL: ai_advisory.py missing Phase 2 marker — may be stale" -ForegroundColor Red
    exit 1
}
$markerRoute = Select-String -Path "$APP_ROOT\api\routes_ai_advisory.py" -Pattern "/status" -Quiet
if ($markerRoute) {
    Write-Host "  routes_ai_advisory.py: Phase 2 /status route present" -ForegroundColor Green
} else {
    Write-Host "  FAIL: routes_ai_advisory.py missing /status route — may be stale" -ForegroundColor Red
    exit 1
}

# ── STEP 10: stderr log tail ──────────────────────────────────
Write-Host "`n=== STEP 10: Recent stderr log ===" -ForegroundColor Cyan
$stderrLog = "$PZ_ROOT\logs\pz_stderr.log"
if (Test-Path $stderrLog) {
    Get-Content $stderrLog -Tail 20
} else {
    Write-Host "  $stderrLog not found" -ForegroundColor Gray
}
Write-Host "Review for any ERROR or ImportError lines." -ForegroundColor Yellow

# ── STEP 11: Smoke checks (manual) ────────────────────────────
Write-Host "`n=== STEP 11: Smoke checks (manual) ===" -ForegroundColor Cyan
Write-Host "  [ ] Dashboard loads at https://pz.estrellajewels.eu"
Write-Host "  [ ] No regressions on existing PZ / proforma / DHL routes"
Write-Host "  [ ] Advisory page still works: https://pz.estrellajewels.eu/static/ai-advisory-v2.html"
Write-Host "  [ ] Enter a real batch_id → advisory result appears (llm_used=false, source=batch_readiness)"
Write-Host "  [ ] GET /api/v1/ai/advisory/status returns ok:true, ai_advisory_llm_enabled:false"
Write-Host "  [ ] Phase 2 fields present in workflow-blockers response: generated_at, model_used, source"

Write-Host "`n=== PHASE 2 DEPLOY COMPLETE ===" -ForegroundColor Green
Write-Host "  Files deployed: 2"
Write-Host "  Modified routes: GET /api/v1/ai/advisory/workflow-blockers/{batch_id}"
Write-Host "  New route:       GET /api/v1/ai/advisory/status"
Write-Host "  LLM flag:        OFF (ai_advisory_llm_enabled=False)"
Write-Host "  Rollback:        robocopy C:\PZ\app\bak C:\PZ\app /E /COPY:DAT /XD C:\PZ\app\bak"
Write-Host "  To ENABLE LLM (requires operator decision + .env change):"
Write-Host "    Set AI_ADVISORY_LLM_ENABLED=True in C:\PZ\.env"
Write-Host "    Set ANTHROPIC_API_KEY=<key> in C:\PZ\.env"
Write-Host "    Restart PZService"
Write-Host "    Monitor: GET /api/v1/ai/advisory/status → ai_advisory_llm_enabled:true"
