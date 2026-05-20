# ============================================================
# Windows Production Deploy Script — PR #235 (C13B)
# Target: origin/main f1b5bf4 (includes ca7de3c C13B merge)
# Campaign: C13B — parser body-cell fallback
# Generated: 2026-05-20 | Profile: windows_prod_v2
# Pre-deploy gate: 50/50 C13B tests PASS (Mac dev)
# ============================================================
# Files to deploy (2 runtime files ONLY):
#   routes_packing.py          -> C:\PZ\app\api\
#   invoice_packing_extractor.py -> C:\PZ\app\services\
# ============================================================
# NOTE: This script uses sc.exe for PZService control (no admin role check).
# Prereqs: PR #233 (routes_proforma.py) + PR #234 (inventory_*.py) already deployed.
# ============================================================

$ErrorActionPreference = "Stop"

# ── Paths ───────────────────────────────────────────────────
$APP_ROOT = "C:\PZ\app"
$REPO_SRC = "C:\Users\Super Fashion\PZ APP\service"
$BAK_ROOT = "C:\PZ\app\bak"

# ── STEP 0: Pre-deploy safety check ─────────────────────────
Write-Host "`n=== STEP 0: Verify repo state ===" -ForegroundColor Cyan
Set-Location "C:\Users\Super Fashion\PZ APP"
git fetch origin
git pull --ff-only origin main
$headSha = git rev-parse --short HEAD
Write-Host "HEAD after pull: $headSha" -ForegroundColor Green
# Expect f1b5bf4 or later (ca7de3c is the C13B feature commit)
if ($headSha -notmatch "f1b5bf4|ca7de3c") {
    Write-Host "WARNING: HEAD $headSha — verify C13B is included via: git log --oneline -5" -ForegroundColor Yellow
}

# ── STEP 1: Verify C13B markers in source ───────────────────
Write-Host "`n=== STEP 1: Verify C13B source markers ===" -ForegroundColor Cyan
$packingContent = Get-Content "$REPO_SRC\app\api\routes_packing.py" -Raw
if ($packingContent -match "client_name_resolution") {
    Write-Host "[OK] routes_packing.py has client_name_resolution wiring" -ForegroundColor Green
} else {
    Write-Host "[FAIL] routes_packing.py missing C13B marker — aborting" -ForegroundColor Red
    exit 1
}
$extractorContent = Get-Content "$REPO_SRC\app\services\invoice_packing_extractor.py" -Raw
if ($extractorContent -match "client_name_resolution") {
    Write-Host "[OK] invoice_packing_extractor.py has client_name_resolution key" -ForegroundColor Green
} else {
    Write-Host "[FAIL] invoice_packing_extractor.py missing C13B marker — aborting" -ForegroundColor Red
    exit 1
}

# ── STEP 2: Verify C12+C13A already deployed (regression guard) ─
Write-Host "`n=== STEP 2: Verify C12+C13A already active ===" -ForegroundColor Cyan
$proformaContent = Get-Content "$APP_ROOT\api\routes_proforma.py" -Raw -ErrorAction SilentlyContinue
if ($proformaContent -match "can_preview") {
    Write-Host "[OK] C12 routes_proforma.py deployed (can_preview present)" -ForegroundColor Green
} else {
    Write-Host "[WARN] C12 routes_proforma.py may not be deployed — check deploy_delta_pr233.md" -ForegroundColor Yellow
}
$inventoryContent = Get-Content "$APP_ROOT\services\inventory_batch_state.py" -Raw -ErrorAction SilentlyContinue
if ($inventoryContent -match "synthetic") {
    Write-Host "[OK] C13A inventory_batch_state.py deployed (synthetic present)" -ForegroundColor Green
} else {
    Write-Host "[WARN] C13A inventory_batch_state.py may not be deployed — check deploy_delta_pr234.md" -ForegroundColor Yellow
}

# ── STEP 3: Backup current production files ──────────────────
Write-Host "`n=== STEP 3: Backup current production files ===" -ForegroundColor Cyan
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$bakDir = "$BAK_ROOT\pr235_$timestamp"
New-Item -ItemType Directory -Force -Path "$bakDir\api" | Out-Null
New-Item -ItemType Directory -Force -Path "$bakDir\services" | Out-Null

Copy-Item "$APP_ROOT\api\routes_packing.py" "$bakDir\api\routes_packing.py" -ErrorAction SilentlyContinue
Copy-Item "$APP_ROOT\services\invoice_packing_extractor.py" "$bakDir\services\invoice_packing_extractor.py" -ErrorAction SilentlyContinue
Write-Host "[OK] Backup created at: $bakDir" -ForegroundColor Green

# ── STEP 4: Service interrogate (baseline) ───────────────────
Write-Host "`n=== STEP 4: PZService baseline state ===" -ForegroundColor Cyan
sc.exe interrogate PZService
$baselineState = (sc.exe query PZService | Select-String "STATE").ToString().Trim()
Write-Host "Baseline: $baselineState" -ForegroundColor Cyan

# ── STEP 5: Stop PZService ───────────────────────────────────
Write-Host "`n=== STEP 5: Stop PZService ===" -ForegroundColor Cyan
sc.exe stop PZService
Start-Sleep -Seconds 5
$stopState = (sc.exe query PZService | Select-String "STATE").ToString().Trim()
Write-Host "After stop: $stopState" -ForegroundColor Cyan

# ── STEP 6: Deploy 2 files ───────────────────────────────────
Write-Host "`n=== STEP 6: Deploy PR #235 files ===" -ForegroundColor Cyan

robocopy "$REPO_SRC\app\api" "$APP_ROOT\api" "routes_packing.py" /COPY:DAT
Write-Host " [1/2] routes_packing.py -> $APP_ROOT\api\" -ForegroundColor Green

robocopy "$REPO_SRC\app\services" "$APP_ROOT\services" "invoice_packing_extractor.py" /COPY:DAT
Write-Host " [2/2] invoice_packing_extractor.py -> $APP_ROOT\services\" -ForegroundColor Green

# ── STEP 7: Verify deployed file markers ────────────────────
Write-Host "`n=== STEP 7: Verify deployed file markers ===" -ForegroundColor Cyan
$deployedPacking = Get-Content "$APP_ROOT\api\routes_packing.py" -Raw
if ($deployedPacking -match "client_name_resolution") {
    Write-Host "[OK] Deployed routes_packing.py has C13B wiring" -ForegroundColor Green
} else {
    Write-Host "[FAIL] Deployed routes_packing.py missing C13B marker — check robocopy" -ForegroundColor Red
    sc.exe start PZService
    exit 1
}
$deployedExtractor = Get-Content "$APP_ROOT\services\invoice_packing_extractor.py" -Raw
if ($deployedExtractor -match "client_name_resolution") {
    Write-Host "[OK] Deployed invoice_packing_extractor.py has C13B key" -ForegroundColor Green
} else {
    Write-Host "[FAIL] Deployed extractor missing C13B marker" -ForegroundColor Red
    sc.exe start PZService
    exit 1
}

# ── STEP 8: Start PZService ──────────────────────────────────
Write-Host "`n=== STEP 8: Start PZService ===" -ForegroundColor Cyan
sc.exe start PZService
Start-Sleep -Seconds 8
sc.exe interrogate PZService
$runState = (sc.exe query PZService | Select-String "STATE").ToString().Trim()
Write-Host "After start: $runState" -ForegroundColor Cyan

if ($runState -notmatch "4  RUNNING") {
    Write-Host "[FAIL] PZService not running — initiating rollback" -ForegroundColor Red
    robocopy "$bakDir\api"      "$APP_ROOT\api"      "routes_packing.py"              /COPY:DAT
    robocopy "$bakDir\services" "$APP_ROOT\services" "invoice_packing_extractor.py"   /COPY:DAT
    sc.exe start PZService
    Write-Host "Rollback complete from $bakDir" -ForegroundColor Yellow
    exit 1
}
Write-Host "[OK] PZService STATE 4 RUNNING" -ForegroundColor Green

# ── STEP 9: Health checks ────────────────────────────────────
Write-Host "`n=== STEP 9: Health checks ===" -ForegroundColor Cyan
$h1 = Invoke-WebRequest -Uri "http://localhost:47213/health" -UseBasicParsing -TimeoutSec 10
Write-Host "/health: $($h1.StatusCode)" -ForegroundColor $(if ($h1.StatusCode -eq 200) { "Green" } else { "Red" })

$h2 = Invoke-WebRequest -Uri "http://localhost:47213/api/v1/health" -UseBasicParsing -TimeoutSec 10
Write-Host "/api/v1/health: $($h2.StatusCode) — $($h2.Content)" -ForegroundColor $(if ($h2.StatusCode -eq 200) { "Green" } else { "Red" })

# ── STEP 10: C13A regression smoke ──────────────────────────
Write-Host "`n=== STEP 10: C13A regression smoke ===" -ForegroundColor Cyan
try {
    $c13a = Invoke-WebRequest -Uri "http://localhost:47213/api/v1/inventory/state/SHIPMENT_4218922912_2026-05_9040dd39" -UseBasicParsing -TimeoutSec 10
    $c13aJson = $c13a.Content | ConvertFrom-Json
    Write-Host "synthetic: $($c13aJson.synthetic) | source: $($c13aJson.source) | total: $($c13aJson.total)" -ForegroundColor $(if ($c13aJson.synthetic -eq $true) { "Green" } else { "Yellow" })
} catch {
    Write-Host "[WARN] C13A smoke failed: $_" -ForegroundColor Yellow
}

# ── STEP 11: C13B marker smoke ───────────────────────────────
Write-Host "`n=== STEP 11: C13B marker smoke ===" -ForegroundColor Cyan
$deployedRoutes = Get-Content "$APP_ROOT\api\routes_packing.py" -Raw
Write-Host "client_name_resolution wiring: $($deployedRoutes -match 'client_name_resolution')" -ForegroundColor $(if ($deployedRoutes -match 'client_name_resolution') { "Green" } else { "Red" })
Write-Host "Pass 5 body fallback: $($deployedRoutes -match 'Pass 5')" -ForegroundColor $(if ($deployedRoutes -match 'Pass 5') { "Green" } else { "Red" })
Write-Host "_guess_client_from_preamble calls: $(([regex]::Matches($deployedRoutes, '_guess_client_from_preamble')).Count)" -ForegroundColor Green

# ── STEP 12: DHL/wFirma flags confirmation ───────────────────
Write-Host "`n=== STEP 12: Confirm DHL/wFirma flags unchanged ===" -ForegroundColor Cyan
$routesPacking = Get-Content "$APP_ROOT\api\routes_packing.py" -Raw
Write-Host "No WFIRMA_CREATE_PZ_ALLOWED in routes_packing: $(-not ($routesPacking -match 'WFIRMA_CREATE_PZ_ALLOWED'))" -ForegroundColor Green
Write-Host "No queue_email in routes_packing: $(-not ($routesPacking -match 'queue_email'))" -ForegroundColor Green

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " C13B DEPLOY COMPLETE — PR #235" -ForegroundColor Green
Write-Host " Backup: $bakDir" -ForegroundColor Cyan
Write-Host " Rollback: robocopy $bakDir\api $APP_ROOT\api routes_packing.py /COPY:DAT" -ForegroundColor Yellow
Write-Host "          robocopy $bakDir\services $APP_ROOT\services invoice_packing_extractor.py /COPY:DAT" -ForegroundColor Yellow
Write-Host "          sc.exe start PZService" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "PARSER SMOKE (for invoice 178 orphan file):" -ForegroundColor Cyan
Write-Host "  Upload EJL-26-27-178-Packing list of shipment-1pc-16-05-26-Client.xlsx" -ForegroundColor White
Write-Host "  If Excel body has 'Client: Diamond Point' in top-12 rows:" -ForegroundColor White
Write-Host "  -> suggested_client_name: 'Diamond Point', client_name_resolution: 'preamble'" -ForegroundColor Green
Write-Host "  If no body label found:" -ForegroundColor White
Write-Host "  -> suggested_client_name: '', client_name_resolution: 'none' (assign manually)" -ForegroundColor Yellow
