# ============================================================
# Windows Static Deploy - C20A
# Target: main HEAD (500472e or newer)
# Campaign: C20A - Component API Truth
#   Bug 1: Btn primary variant -> gold/accent fill (27 callers fixed)
#   Bug 2: Badge label prop -> real text instead of "Unknown" (8 callers fixed)
#   Bug 3: --surface-1 / --surface-2 CSS tokens defined in both pages
# Generated: 2026-05-26 | NO SERVICE RESTART REQUIRED
# ============================================================
# Files to deploy (3 static files - no PZService restart needed):
#   dashboard-shared.js  -> C:\PZ\app\static\
#   dashboard.html       -> C:\PZ\app\static\
#   shipment-detail.html -> C:\PZ\app\static\
# ============================================================

$ErrorActionPreference = "Continue"

# -- Paths --
$SVC_STATIC  = "C:\PZ\app\static"
$REPO_SRC    = "C:\Users\Super Fashion\PZ APP\service\app\static"
$BAK_ROOT    = "C:\PZ\app\bak"

# -- STEP 0: Verify repo state --
Write-Host ""
Write-Host "=== STEP 0: Verify repo state ===" -ForegroundColor Cyan
Set-Location "C:\Users\Super Fashion\PZ APP"
git fetch origin
if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] git fetch failed" -ForegroundColor Red; exit 1 }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] git pull failed" -ForegroundColor Red; exit 1 }
$headSha = git rev-parse --short HEAD
Write-Host "HEAD after pull: $headSha" -ForegroundColor Green

# -- STEP 1: Verify C20A markers in source --
Write-Host ""
Write-Host "=== STEP 1: Verify C20A source markers ===" -ForegroundColor Cyan

$jsContent   = Get-Content "$REPO_SRC\dashboard-shared.js" -Raw
$dashContent = Get-Content "$REPO_SRC\dashboard.html" -Raw
$sdContent   = Get-Content "$REPO_SRC\shipment-detail.html" -Raw

$allOk = $true

# Bug 1: primary variant in Btn
@(
    "primary: { background: 'var(--accent)'",
    "C20A: added `primary` variant"
) | ForEach-Object {
    if ($jsContent -match [regex]::Escape($_)) {
        Write-Host "[OK] js marker: $_" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] js marker missing: $_" -ForegroundColor Red; $allOk = $false
    }
}

# Bug 2: label prop in Badge
@(
    "label || status || 'Unknown'",
    "function Badge({ status, label"
) | ForEach-Object {
    if ($jsContent -match [regex]::Escape($_)) {
        Write-Host "[OK] js marker: $_" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] js marker missing: $_" -ForegroundColor Red; $allOk = $false
    }
}

# Bug 3: --surface-1 / --surface-2 in dashboard.html
@("--surface-1:", "--surface-2:") | ForEach-Object {
    if ($dashContent -match [regex]::Escape($_)) {
        Write-Host "[OK] dashboard.html has: $_" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] dashboard.html missing: $_" -ForegroundColor Red; $allOk = $false
    }
}

# Bug 3: --surface-1 / --surface-2 in shipment-detail.html
@("--surface-1:", "--surface-2:") | ForEach-Object {
    if ($sdContent -match [regex]::Escape($_)) {
        Write-Host "[OK] shipment-detail.html has: $_" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] shipment-detail.html missing: $_" -ForegroundColor Red; $allOk = $false
    }
}

if (-not $allOk) {
    Write-Host "[ABORT] C20A source verification failed. Aborting deploy." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] All C20A markers confirmed in source." -ForegroundColor Green

# -- STEP 2: Backup current production files --
Write-Host ""
Write-Host "=== STEP 2: Backup ===" -ForegroundColor Cyan
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$bakDir = "$BAK_ROOT\c20a_static_$timestamp"
New-Item -ItemType Directory -Force -Path $bakDir | Out-Null
Copy-Item "$SVC_STATIC\dashboard-shared.js"  "$bakDir\dashboard-shared.js"  -ErrorAction SilentlyContinue
Copy-Item "$SVC_STATIC\dashboard.html"        "$bakDir\dashboard.html"        -ErrorAction SilentlyContinue
Copy-Item "$SVC_STATIC\shipment-detail.html"  "$bakDir\shipment-detail.html"  -ErrorAction SilentlyContinue
Write-Host "[OK] Backup: $bakDir" -ForegroundColor Green

# -- STEP 3: Deploy (no restart needed) --
Write-Host ""
Write-Host "=== STEP 3: Deploy C20A static files ===" -ForegroundColor Cyan
robocopy "$REPO_SRC" "$SVC_STATIC" "dashboard-shared.js" "dashboard.html" "shipment-detail.html" /COPY:DAT
if ($LASTEXITCODE -ge 8) {
    Write-Host "[FAIL] robocopy error code $LASTEXITCODE" -ForegroundColor Red
    exit 1
}
Write-Host " [1/3] dashboard-shared.js -> $SVC_STATIC\" -ForegroundColor Green
Write-Host " [2/3] dashboard.html -> $SVC_STATIC\" -ForegroundColor Green
Write-Host " [3/3] shipment-detail.html -> $SVC_STATIC\" -ForegroundColor Green
Write-Host "[OK] No PZService restart required for static files." -ForegroundColor Green

# -- STEP 4: Smoke verify deployed files --
Write-Host ""
Write-Host "=== STEP 4: Verify deployed files ===" -ForegroundColor Cyan
$jsD   = Get-Content "$SVC_STATIC\dashboard-shared.js" -Raw
$dashD = Get-Content "$SVC_STATIC\dashboard.html" -Raw
$sdD   = Get-Content "$SVC_STATIC\shipment-detail.html" -Raw
$smokeFail = $false

@("primary: { background: 'var(--accent)'", "label || status || 'Unknown'") | ForEach-Object {
    if ($jsD -match [regex]::Escape($_)) {
        Write-Host "[OK] deployed js: $_" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] deployed js missing: $_" -ForegroundColor Red; $smokeFail = $true
    }
}
@("--surface-1:", "--surface-2:") | ForEach-Object {
    if ($dashD -match [regex]::Escape($_)) {
        Write-Host "[OK] deployed dashboard.html: $_" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] deployed dashboard.html missing: $_" -ForegroundColor Red; $smokeFail = $true
    }
    if ($sdD -match [regex]::Escape($_)) {
        Write-Host "[OK] deployed shipment-detail.html: $_" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] deployed shipment-detail.html missing: $_" -ForegroundColor Red; $smokeFail = $true
    }
}

if ($smokeFail) {
    Write-Host "[FAIL] Deployed file verification failed - check copy." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " C20A STATIC DEPLOY COMPLETE - NO RESTART REQUIRED" -ForegroundColor Green
Write-Host " 3 files deployed: dashboard-shared.js, dashboard.html, shipment-detail.html" -ForegroundColor Green
Write-Host " Backup: $bakDir" -ForegroundColor Cyan
Write-Host " Rollback: robocopy `"$bakDir`" `"$SVC_STATIC`" dashboard-shared.js dashboard.html shipment-detail.html /COPY:DAT" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
