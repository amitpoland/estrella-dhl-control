# ============================================================
# Windows Production Deploy Script
# SHA: 1a74d6c (main HEAD 2026-05-23 — Phase 4 MDI Foundation)
# Previous production SHA: bf9a9ae (Phase 3 Proper, deployed 2026-05-23)
#
# PR #314 — feat(phase4): master data intelligence foundation
#
# Files deployed (3 new runtime files):
#
#   [1] NEW     service/app/services/master_data_intelligence.py
#       → C:\PZ\app\services\master_data_intelligence.py
#       Unified advisory scoring engine. 5-domain: customer/product/finishing/supplier/readiness.
#       llm_used=False hardcoded. Read-only. No Anthropic calls. Deterministic only.
#
#   [2] NEW     service/app/api/routes_mdi.py
#       → C:\PZ\app\api\routes_mdi.py
#       GET-only router at /api/v1/master-data/intelligence and /{domain}.
#       No POST/PUT/DELETE. Auth: require_api_key on both endpoints.
#
#   [3] MODIFIED service/app/main.py
#       → C:\PZ\app\main.py
#       +1 import (from .api.routes_mdi import router as mdi_router)
#       +1 include_router(mdi_router)  # Phase 4
#
# NOTE: Also included in this deploy (from prior PRs already on origin/main):
#   NEW service/app/services/global_pz_correction.py → C:\PZ\app\services\
#   MODIFIED service/app/api/routes_pz.py → C:\PZ\app\api\routes_pz.py
#   (These were on origin/main before PR #314 squash merge)
#
# PZService restart: REQUIRED (main.py changed — new router registered)
# Standard robocopy: YES — all files within service/app/**
# Lesson J: COMPLIANT — no engine-level root files
# ============================================================

# --- Pre-flight ---
Write-Host "=== Phase 4 MDI Deploy — SHA 1a74d6c ===" -ForegroundColor Cyan
Write-Host "Previous production SHA: bf9a9ae"
Write-Host ""

# Verify we are on the right SHA
cd "C:\Users\Super Fashion\PZ APP"
$currentSHA = git rev-parse HEAD 2>&1
Write-Host "Local HEAD: $currentSHA"

# Pull to 1a74d6c
git pull --ff-only origin main
$pulledSHA = git rev-parse HEAD 2>&1
Write-Host "After pull: $pulledSHA"
if ($pulledSHA -notmatch "1a74d6c") {
    Write-Host "WARN: SHA mismatch — expected 1a74d6c. Verify before sync." -ForegroundColor Yellow
}

# --- Sync service/app → C:\PZ\app ---
Write-Host ""
Write-Host "=== robocopy sync ===" -ForegroundColor Cyan
robocopy "C:\Users\Super Fashion\PZ APP\service\app" "C:\PZ\app" /E /XO `
  /XD __pycache__ .pytest_cache `
  /XF "*.pyc" "*.pyo" "*.zip"

$rc = $LASTEXITCODE
if ($rc -ge 4) {
    Write-Host "ERROR: robocopy exit code $rc — STOP. Do not restart service." -ForegroundColor Red
    exit 1
}
Write-Host "robocopy exit: $rc (0–3 = success)" -ForegroundColor Green

# --- Verify new files landed ---
Write-Host ""
Write-Host "=== File verification ===" -ForegroundColor Cyan
$files = @(
    "C:\PZ\app\services\master_data_intelligence.py",
    "C:\PZ\app\api\routes_mdi.py",
    "C:\PZ\app\main.py"
)
foreach ($f in $files) {
    if (Test-Path $f) {
        $size = (Get-Item $f).Length
        Write-Host "OK  $f ($size bytes)"
    } else {
        Write-Host "MISSING  $f" -ForegroundColor Red
    }
}

# Spot-check: confirm llm_used=False in deployed service
$mdiContent = Get-Content "C:\PZ\app\services\master_data_intelligence.py" -Raw
if ($mdiContent -match "llm_used=False") {
    Write-Host "OK  llm_used=False confirmed in deployed service"
} else {
    Write-Host "FAIL: llm_used=False NOT found in deployed service" -ForegroundColor Red
}

# Spot-check: confirm no POST routes in deployed router
$routerContent = Get-Content "C:\PZ\app\api\routes_mdi.py" -Raw
if ($routerContent -notmatch "@router\.post|@router\.put|@router\.delete") {
    Write-Host "OK  GET-only confirmed in deployed router"
} else {
    Write-Host "FAIL: write route found in deployed router" -ForegroundColor Red
}

# --- Restart PZService ---
Write-Host ""
Write-Host "=== PZService restart ===" -ForegroundColor Cyan
sc.exe stop PZService
$tries = 0
while ((Get-Service PZService).Status -ne 'Stopped' -and $tries -lt 15) {
    Start-Sleep -Seconds 1; $tries++
}
Write-Host "Service stopped after $tries s"

sc.exe start PZService
Start-Sleep -Seconds 10
sc.exe query PZService

# --- Health checks ---
Write-Host ""
Write-Host "=== Health checks ===" -ForegroundColor Cyan
$local = Invoke-WebRequest http://127.0.0.1:47213/api/v1/health -UseBasicParsing
Write-Host "Local health: $($local.StatusCode)"

$public = Invoke-WebRequest https://pz.estrellajewels.eu/api/v1/health -UseBasicParsing
Write-Host "Public health: $($public.StatusCode)"

# --- MDI smoke tests ---
Write-Host ""
Write-Host "=== MDI smoke tests ===" -ForegroundColor Cyan
$apiKey = (Get-Content "C:\PZ\.env" | Where-Object { $_ -match "^API_KEY=" } | ForEach-Object { $_.Split("=", 2)[1] })

# Full platform report
$mdiResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "MDI platform report: $($mdiResp.StatusCode)"
$mdiJson = $mdiResp.Content | ConvertFrom-Json
Write-Host "  llm_used: $($mdiJson.llm_used)"
Write-Host "  advisory_class: $($mdiJson.advisory_class)"
Write-Host "  platform_score: $($mdiJson.platform_score)"

# Customer domain
$custResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence/customer" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "MDI customer: $($custResp.StatusCode)"
$custJson = $custResp.Content | ConvertFrom-Json
Write-Host "  entity_count: $($custJson.entity_count)"
Write-Host "  completeness_score: $($custJson.completeness_score)"

# Product domain
$prodResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence/product" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "MDI product: $($prodResp.StatusCode)"

# Invalid domain (should 422)
try {
    $badResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence/badomain" `
        -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing -ErrorAction Stop
    Write-Host "FAIL: invalid domain should have 422 but got $($badResp.StatusCode)" -ForegroundColor Red
} catch {
    Write-Host "OK  Invalid domain → 422 as expected"
}

# --- Stderr tail ---
Write-Host ""
Write-Host "=== Last 20 lines of stderr log ===" -ForegroundColor Cyan
Get-Content C:\PZ\logs\pz_stderr.log -Tail 20

Write-Host ""
Write-Host "=== Deploy complete ===" -ForegroundColor Green
Write-Host "SHA deployed: 1a74d6c"
Write-Host "Rollback: git revert 1a74d6c --no-edit + robocopy + sc.exe restart"
