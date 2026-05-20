# ============================================================
# Windows Static-File Deploy — C14A (PR #237)
# Target: main after C14A squash merge
# Campaign: C14A — Lapis Commercial Workflow Truth Correction
# Generated: 2026-05-20 | No service restart required
# ============================================================
# Files to deploy (1 static file):
#   shipment-detail.html  -> C:\PZ\app\static\
# ============================================================
# NOTE: C14A supersedes C13D for shipment-detail.html.
#       If C13D static deploy has NOT yet been run, run THIS
#       script instead — it includes all C13D + C14A changes.
#       dashboard.html was changed in C13D only; deploy it
#       from windows_deploy_c13d_static.ps1 if not yet done.
#
# Static files do not require PZService restart.
# Operator must hard-refresh browser (Ctrl+Shift+R) after copy.
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

# ── STEP 1: Verify C14A markers in source ───────────────────
Write-Host "`n=== STEP 1: Verify C14A source markers ===" -ForegroundColor Cyan
$detailContent = Get-Content "$REPO_SRC\shipment-detail.html" -Raw
$markers = @(
    "PROFORMA_NOT_LINKED",
    "proforma-not-linked-panel",
    "sales-transit-context-banner",
    "sales-qty-reconciliation",
    "orphan-assignment-cta",
    "Pending arrival",
    "C14A: transit detection"
)
$allOk = $true
foreach ($m in $markers) {
    if ($detailContent -match [regex]::Escape($m)) {
        Write-Host "[OK] marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] marker missing: $m" -ForegroundColor Red
        $allOk = $false
    }
}
if (-not $allOk) {
    Write-Host "[ABORT] C14A markers missing — wrong repo version? Aborting." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] All C14A markers confirmed in source." -ForegroundColor Green

# ── STEP 2: Verify C13D markers also present (cumulative) ───
Write-Host "`n=== STEP 2: Verify C13D cumulative markers ===" -ForegroundColor Cyan
$c13dMarkers = @("PURCHASE_TRANSIT", "isTransit", "displayMissing", "warehouse-transit-note")
foreach ($m in $c13dMarkers) {
    if ($detailContent -match [regex]::Escape($m)) {
        Write-Host "[OK] C13D marker: $m" -ForegroundColor Green
    } else {
        Write-Host "[WARN] C13D marker missing: $m — unexpected" -ForegroundColor Yellow
    }
}

# ── STEP 3: Backup current production file ──────────────────
Write-Host "`n=== STEP 3: Backup current static file ===" -ForegroundColor Cyan
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$bakDir = "$BAK_ROOT\c14a_static_$timestamp"
New-Item -ItemType Directory -Force -Path $bakDir | Out-Null
Copy-Item "$APP_STATIC\shipment-detail.html" "$bakDir\shipment-detail.html" -ErrorAction SilentlyContinue
Write-Host "[OK] Backup: $bakDir\shipment-detail.html" -ForegroundColor Green

# ── STEP 4: Deploy shipment-detail.html ─────────────────────
Write-Host "`n=== STEP 4: Deploy C14A static file ===" -ForegroundColor Cyan
robocopy "$REPO_SRC" "$APP_STATIC" "shipment-detail.html" /COPY:DAT
Write-Host " [1/1] shipment-detail.html -> $APP_STATIC\" -ForegroundColor Green

# ── STEP 5: Verify deployed markers ─────────────────────────
Write-Host "`n=== STEP 5: Verify deployed file ===" -ForegroundColor Cyan
$deployed = Get-Content "$APP_STATIC\shipment-detail.html" -Raw
foreach ($m in $markers) {
    $present = $deployed -match [regex]::Escape($m)
    Write-Host "$m : $present" -ForegroundColor $(if ($present) { 'Green' } else { 'Red' })
}

# ── STEP 6: No service restart needed ───────────────────────
Write-Host "`n=== STEP 6: Static deploy complete ===" -ForegroundColor Cyan
Write-Host "PZService restart NOT required." -ForegroundColor Green
Write-Host "ACTION: hard-refresh browser (Ctrl+Shift+R) on pz.estrellajewels.eu" -ForegroundColor Yellow

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " C14A STATIC DEPLOY COMPLETE" -ForegroundColor Green
Write-Host " Backup: $bakDir" -ForegroundColor Cyan
Write-Host " Rollback: robocopy $bakDir $APP_STATIC shipment-detail.html /COPY:DAT" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "POST-DEPLOY SMOKE (browser) — batch SHIPMENT_4218922912_2026-05_9040dd39:" -ForegroundColor Cyan
Write-Host "  Sales tab > 'View Proforma' button:" -ForegroundColor White
Write-Host "    Expected: blue info panel 'No linked proforma yet' — NOT a red error" -ForegroundColor White
Write-Host "  Sales tab > top of client group area:" -ForegroundColor White
Write-Host "    Expected: blue transit context banner 'Inventory location: In transit'" -ForegroundColor White
Write-Host "  Sales tab > per-line status badge for transit packing lines:" -ForegroundColor White
Write-Host "    Expected: amber 'Pending arrival' badge — NOT blue 'In transit'" -ForegroundColor White
Write-Host "  Sales tab > qty reconciliation (inside transit banner):" -ForegroundColor White
Write-Host "    Expected: Transit pieces: 30 | Invoice units: 46 | Difference: 16" -ForegroundColor White
Write-Host "  Sales tab > bottom of section:" -ForegroundColor White
Write-Host "    Expected: orphan CTA 'Missing a packing line?' note" -ForegroundColor White
