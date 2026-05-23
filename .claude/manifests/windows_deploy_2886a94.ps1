# ============================================================
# Windows Production Deploy Script
# SHA: 2886a94 (main HEAD 2026-05-23 — Phase 5 Product/Finishing Intelligence)
# Previous production SHA: 7c2bf0a (PR #315, GlobalPZCorrectionProposalCard)
#
# CUMULATIVE DEPLOY: This deploys Phase 4 + Phase 5 if production is still at 7c2bf0a.
# If production is already at 1a74d6c (Phase 4 deployed), this deploys Phase 5 only.
#
# PR #316 — feat(phase5): product/finishing intelligence foundation
#
# Files deployed (1 modified runtime file):
#
#   [1] MODIFIED  service/app/services/master_data_intelligence.py
#       → C:\PZ\app\services\master_data_intelligence.py
#       Phase 5 additions: description quality scoring, near-duplicate detection,
#       ProductLocal coverage, metal/stone compatibility advisory.
#       llm_used=False hardcoded. Read-only. No Anthropic calls. Deterministic only.
#
# NOTE: Also included cumulatively (if starting from 7c2bf0a):
#   NEW  service/app/services/master_data_intelligence.py  (Phase 4, PR #314)
#   NEW  service/app/api/routes_mdi.py                     (Phase 4, PR #314)
#   MODIFIED service/app/main.py                           (Phase 4, PR #314)
#
# PZService restart: REQUIRED (master_data_intelligence.py changed)
# Standard robocopy: YES — all files within service/app/**
# Lesson J: COMPLIANT — no engine-level root files
# ============================================================

# --- Pre-flight ---
Write-Host "=== Phase 5 Product/Finishing Intelligence Deploy — SHA 2886a94 ===" -ForegroundColor Cyan
Write-Host "Previous production SHA: 7c2bf0a (or 1a74d6c if Phase 4 was already deployed)"
Write-Host ""

# Verify we are on the right SHA
cd "C:\Users\Super Fashion\PZ APP"
$currentSHA = git rev-parse HEAD 2>&1
Write-Host "Local HEAD: $currentSHA"

# Pull to 2886a94
git pull --ff-only origin main
$pulledSHA = git rev-parse HEAD 2>&1
Write-Host "After pull: $pulledSHA"
if ($pulledSHA -notmatch "2886a94") {
    Write-Host "WARN: SHA mismatch — expected 2886a94. Verify before sync." -ForegroundColor Yellow
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

# --- Verify key files landed ---
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

# Spot-check Phase 4: confirm llm_used=False in deployed service
$mdiContent = Get-Content "C:\PZ\app\services\master_data_intelligence.py" -Raw
if ($mdiContent -match "llm_used=False") {
    Write-Host "OK  llm_used=False confirmed in deployed service"
} else {
    Write-Host "FAIL: llm_used=False NOT found in deployed service" -ForegroundColor Red
}

# Spot-check Phase 5: confirm _desc_quality helper present
if ($mdiContent -match "_desc_quality") {
    Write-Host "OK  Phase 5 _desc_quality helper confirmed in deployed service"
} else {
    Write-Host "FAIL: Phase 5 _desc_quality NOT found — old service deployed" -ForegroundColor Red
}

# Spot-check Phase 5: confirm _metal_stone_compat_warnings present
if ($mdiContent -match "_metal_stone_compat_warnings") {
    Write-Host "OK  Phase 5 _metal_stone_compat_warnings confirmed in deployed service"
} else {
    Write-Host "FAIL: Phase 5 compat warnings NOT found — old service deployed" -ForegroundColor Red
}

# Spot-check Phase 5: confirm list_product_local imported
if ($mdiContent -match "list_product_local") {
    Write-Host "OK  list_product_local import confirmed in deployed service"
} else {
    Write-Host "FAIL: list_product_local NOT found — Phase 5 not deployed" -ForegroundColor Red
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

# --- MDI smoke tests (Phase 4 + Phase 5 verification) ---
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

# Product domain — Phase 5 fields
$prodResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence/product" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "MDI product: $($prodResp.StatusCode)"
$prodJson = $prodResp.Content | ConvertFrom-Json
Write-Host "  entity_count: $($prodJson.entity_count)"
Write-Host "  completeness_score: $($prodJson.completeness_score)"
# Phase 5 details
if ($prodJson.details.description_quality) {
    $dq = $prodJson.details.description_quality
    Write-Host "  [Phase5] description_quality: none=$($dq.none) poor=$($dq.poor) ok=$($dq.ok) good=$($dq.good)"
} else {
    Write-Host "  WARN: description_quality not present — Phase 5 may not be deployed" -ForegroundColor Yellow
}
Write-Host "  [Phase5] product_local_coverage_pct: $($prodJson.details.product_local_coverage_pct)"

# Finishing domain — Phase 5 fields
$finResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence/finishing" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "MDI finishing: $($finResp.StatusCode)"
$finJson = $finResp.Content | ConvertFrom-Json
Write-Host "  entity_count: $($finJson.entity_count)"
# Phase 5 details
Write-Host "  [Phase5] stone_keyword_coverage_count: $($finJson.details.stone_keyword_coverage_count)"
$cwCount = ($finJson.details.metal_stone_compat_warnings | Measure-Object).Count
Write-Host "  [Phase5] metal_stone_compat_warnings count: $cwCount"

# Customer domain
$custResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence/customer" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "MDI customer: $($custResp.StatusCode)"

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
Write-Host "SHA deployed: 2886a94"
Write-Host "Rollback: git revert 2886a94 --no-edit + robocopy + sc.exe restart"
