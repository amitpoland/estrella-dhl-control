# ============================================================
# Windows Static-File Deploy — C13D (PR #236)
# Target: origin/main 92acdc2 (C13D squash merge)
# Campaign: C13D — Transit-aware inventory semantics
# Generated: 2026-05-20 | No service restart required
# ============================================================
# Files to deploy (2 static files ONLY):
#   shipment-detail.html  -> C:\PZ\app\static\
#   dashboard.html        -> C:\PZ\app\static\
# ============================================================
# NOTE: Static files do not require PZService restart.
# Operator must hard-refresh browser (Ctrl+Shift+R) after copy.
# Deploy AFTER C13B backend files (#235) or together.
# ============================================================

$ErrorActionPreference = "Stop"

# ── Paths ───────────────────────────────────────────────────
$APP_STATIC = "C:\PZ\app\static"
$REPO_SRC   = "C:\Users\Super Fashion\PZ APP\service\app\static"
$BAK_ROOT   = "C:\PZ\app\bak"

# ── STEP 0: Pull latest main ─────────────────────────────────
Write-Host "`n=== STEP 0: Verify repo state ===" -ForegroundColor Cyan
Set-Location "C:\Users\Super Fashion\PZ APP"
git fetch origin
git pull --ff-only origin main
$headSha = git rev-parse --short HEAD
Write-Host "HEAD after pull: $headSha" -ForegroundColor Green
if ($headSha -notmatch "92acdc2") {
    Write-Host "WARNING: HEAD $headSha — verify C13D is included via: git log --oneline -5" -ForegroundColor Yellow
}

# ── STEP 1: Verify C13D markers in source ───────────────────
Write-Host "`n=== STEP 1: Verify C13D source markers ===" -ForegroundColor Cyan
$detailContent = Get-Content "$REPO_SRC\shipment-detail.html" -Raw
if ($detailContent -match "PURCHASE_TRANSIT" -and $detailContent -match "isTransit" -and $detailContent -match "displayMissing") {
    Write-Host "[OK] shipment-detail.html has C13D markers (PURCHASE_TRANSIT, isTransit, displayMissing)" -ForegroundColor Green
} else {
    Write-Host "[FAIL] shipment-detail.html missing C13D markers — aborting" -ForegroundColor Red
    exit 1
}
$dashContent = Get-Content "$REPO_SRC\dashboard.html" -Raw
if ($dashContent -match "PURCHASE_TRANSIT" -and $dashContent -match "stLabel" -and $dashContent -match "in_transit") {
    Write-Host "[OK] dashboard.html has C13D markers (PURCHASE_TRANSIT, stLabel, in_transit)" -ForegroundColor Green
} else {
    Write-Host "[FAIL] dashboard.html missing C13D markers — aborting" -ForegroundColor Red
    exit 1
}

# ── STEP 2: Backup current production static files ──────────
Write-Host "`n=== STEP 2: Backup current static files ===" -ForegroundColor Cyan
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$bakDir = "$BAK_ROOT\c13d_static_$timestamp"
New-Item -ItemType Directory -Force -Path $bakDir | Out-Null
Copy-Item "$APP_STATIC\shipment-detail.html" "$bakDir\shipment-detail.html" -ErrorAction SilentlyContinue
Copy-Item "$APP_STATIC\dashboard.html"       "$bakDir\dashboard.html"       -ErrorAction SilentlyContinue
Write-Host "[OK] Backup created at: $bakDir" -ForegroundColor Green

# ── STEP 3: Deploy 2 static files ───────────────────────────
Write-Host "`n=== STEP 3: Deploy C13D static files ===" -ForegroundColor Cyan
robocopy "$REPO_SRC" "$APP_STATIC" "shipment-detail.html" /COPY:DAT
Write-Host " [1/2] shipment-detail.html -> $APP_STATIC\" -ForegroundColor Green
robocopy "$REPO_SRC" "$APP_STATIC" "dashboard.html" /COPY:DAT
Write-Host " [2/2] dashboard.html -> $APP_STATIC\" -ForegroundColor Green

# ── STEP 4: Verify deployed markers ─────────────────────────
Write-Host "`n=== STEP 4: Verify deployed file markers ===" -ForegroundColor Cyan
$deployedDetail = Get-Content "$APP_STATIC\shipment-detail.html" -Raw
Write-Host "isTransit present:      $($deployedDetail -match 'isTransit')"       -ForegroundColor $(if ($deployedDetail -match 'isTransit') { 'Green' } else { 'Red' })
Write-Host "displayMissing present: $($deployedDetail -match 'displayMissing')"  -ForegroundColor $(if ($deployedDetail -match 'displayMissing') { 'Green' } else { 'Red' })
Write-Host "in_transit label:       $($deployedDetail -match 'In transit / Awaiting')" -ForegroundColor $(if ($deployedDetail -match 'In transit / Awaiting') { 'Green' } else { 'Red' })
$deployedDash = Get-Content "$APP_STATIC\dashboard.html" -Raw
Write-Host "stLabel present:        $($deployedDash -match 'stLabel')"           -ForegroundColor $(if ($deployedDash -match 'stLabel') { 'Green' } else { 'Red' })
Write-Host "PURCHASE_TRANSIT label: $($deployedDash -match 'In transit')"        -ForegroundColor $(if ($deployedDash -match 'In transit') { 'Green' } else { 'Red' })

# ── STEP 5: No service restart needed ───────────────────────
Write-Host "`n=== STEP 5: Static deploy complete — no restart needed ===" -ForegroundColor Cyan
Write-Host "Static files are served directly. PZService restart NOT required." -ForegroundColor Green
Write-Host "Operator action: hard-refresh browser (Ctrl+Shift+R) on pz.estrellajewels.eu" -ForegroundColor Yellow

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " C13D STATIC DEPLOY COMPLETE" -ForegroundColor Green
Write-Host " Backup: $bakDir" -ForegroundColor Cyan
Write-Host " Rollback: robocopy $bakDir $APP_STATIC shipment-detail.html /COPY:DAT" -ForegroundColor Yellow
Write-Host "          robocopy $bakDir $APP_STATIC dashboard.html /COPY:DAT" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "POST-DEPLOY SMOKE (browser):" -ForegroundColor Cyan
Write-Host "  Open shipment detail for SHIPMENT_4218922912_2026-05_9040dd39" -ForegroundColor White
Write-Host "  Warehouse tab: lifecycle badge should show 'In transit / Awaiting warehouse receive' (blue)" -ForegroundColor White
Write-Host "  Warehouse tab: Missing scans section should show blue transit note, not red table" -ForegroundColor White
Write-Host "  Sales tab: piece badges should show 'In transit' (blue) not 'Missing scan' (red)" -ForegroundColor White
Write-Host "  Dashboard piece drawer: PURCHASE_TRANSIT state should display 'In transit' not raw code" -ForegroundColor White
