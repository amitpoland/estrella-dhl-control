# ============================================================
# Windows Static Deploy - C19A (PR #243)
# Target: main after C19A squash merge
# Campaign: C19A - Single Authority Renderer
# Generated: 2026-05-20 | NO SERVICE RESTART REQUIRED
# ============================================================
# Files to deploy (static only - no PZService restart needed):
#   shipment-detail.html -> C:\PZ\app\static\
# ============================================================
# Deploy order note:
#   C13E first (restart required if not yet deployed).
#   C14A + C15A + C16A + C17A + C18A + C19A in one pass (no restart).
#   Run AFTER PR #243 merges to main.
# ============================================================

$ErrorActionPreference = "Continue"

# -- Paths --
$SVC_STATIC  = "C:\PZ\app\static"
$REPO_SRC    = "C:\Users\Super Fashion\PZ APP\service\app\static"
$BAK_ROOT    = "C:\PZ\app\bak"

# -- STEP 0: Pull latest main --
Write-Host ""
Write-Host "=== STEP 0: Verify repo state ===" -ForegroundColor Cyan
Set-Location "C:\Users\Super Fashion\PZ APP"
git fetch origin
if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] git fetch failed" -ForegroundColor Red; exit 1 }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] git pull failed" -ForegroundColor Red; exit 1 }
$headSha = git rev-parse --short HEAD
Write-Host "HEAD after pull: $headSha" -ForegroundColor Green

# -- STEP 1: Verify C19A markers in source --
Write-Host ""
Write-Host "=== STEP 1: Verify C19A source markers ===" -ForegroundColor Cyan
$srcContent = Get-Content "$REPO_SRC\shipment-detail.html" -Raw
if (-not $srcContent) {
    Write-Host "[FAIL] Could not read source file" -ForegroundColor Red
    exit 1
}

$markers = @(
    "draft-lines-empty-hint",
    "Reload items from warehouse data",
    "draft-visibility-panel",
    "btn-draft-visibility",
    "c.ship_to_postal_code",
    "invState.total === ((invState.counts || {}).PURCHASE_TRANSIT || 0)",
    "workflow-cm-card-",
    "saveCmFields",
    "Saves to Customer Master only",
    "legacy-pz-details",
    "legacy-reservation-details"
)

$allOk = $true
foreach ($m in $markers) {
    if ($srcContent -match [regex]::Escape($m)) {
        Write-Host "[OK] marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] marker missing: $m" -ForegroundColor Red
        $allOk = $false
    }
}

# Verify intelligence dead code is gone
$intelTokens = @(
    "btn-draft-intelligence",
    "draft-intelligence-panel",
    "draft-anomaly-row",
    "draft-suggestion-row",
    "draft-confidence-"
)
foreach ($t in $intelTokens) {
    if ($srcContent -match [regex]::Escape($t)) {
        Write-Host "[FAIL] intelligence dead code still present: $t" -ForegroundColor Red
        $allOk = $false
    } else {
        Write-Host "[OK] intelligence dead code absent: $t" -ForegroundColor Green
    }
}

if (-not $allOk) {
    Write-Host "[ABORT] C19A source verification failed. Aborting." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] All C19A markers confirmed in source." -ForegroundColor Green

# -- STEP 2: Verify prior campaign markers --
Write-Host ""
Write-Host "=== STEP 2: Verify prior campaign markers ===" -ForegroundColor Cyan
$priorMarkers = @(
    "isTransit ? 'In transit' : (r.current_location",
    "invState.counts.PURCHASE_TRANSIT",
    "cm-clients-",
    "setCm",
    "customer-master",
    "link-packing-doc-needs-client-",
    "link-packing-doc-unassigned-",
    "sales-transit-context-banner",
    "orphan-assignment-cta",
    "Pending arrival"
)
foreach ($m in $priorMarkers) {
    if ($srcContent -match [regex]::Escape($m)) {
        Write-Host "[OK] prior marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[WARN] prior marker missing: $m" -ForegroundColor Yellow
    }
}

# -- STEP 3: Backup current production file --
Write-Host ""
Write-Host "=== STEP 3: Backup ===" -ForegroundColor Cyan
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$bakDir = "$BAK_ROOT\c19a_static_$timestamp"
New-Item -ItemType Directory -Force -Path $bakDir | Out-Null
Copy-Item "$SVC_STATIC\shipment-detail.html" "$bakDir\shipment-detail.html" -ErrorAction SilentlyContinue
Write-Host "[OK] Backup: $bakDir\shipment-detail.html" -ForegroundColor Green

# -- STEP 4: Deploy (no restart needed) --
Write-Host ""
Write-Host "=== STEP 4: Deploy C19A static file ===" -ForegroundColor Cyan
robocopy "$REPO_SRC" "$SVC_STATIC" "shipment-detail.html" /COPY:DAT
if ($LASTEXITCODE -ge 8) {
    Write-Host "[FAIL] robocopy error code $LASTEXITCODE - check copy" -ForegroundColor Red
    exit 1
}
Write-Host " [1/1] shipment-detail.html -> $SVC_STATIC\" -ForegroundColor Green
Write-Host "[OK] No PZService restart required for static files." -ForegroundColor Green

# -- STEP 5: Smoke verification --
Write-Host ""
Write-Host "=== STEP 5: Verify deployed file ===" -ForegroundColor Cyan
$deployedContent = Get-Content "$SVC_STATIC\shipment-detail.html" -Raw
$smokeFail = $false
foreach ($m in $markers) {
    if ($deployedContent -match [regex]::Escape($m)) {
        Write-Host "[OK] deployed file has: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] deployed file missing: $m" -ForegroundColor Red
        $smokeFail = $true
    }
}
foreach ($t in $intelTokens) {
    if ($deployedContent -match [regex]::Escape($t)) {
        Write-Host "[FAIL] deployed file still has dead code: $t" -ForegroundColor Red
        $smokeFail = $true
    } else {
        Write-Host "[OK] deployed file clean: $t" -ForegroundColor Green
    }
}
if ($smokeFail) {
    Write-Host "[FAIL] Deployed file verification failed - check copy." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " C19A STATIC DEPLOY COMPLETE - NO RESTART REQUIRED" -ForegroundColor Green
Write-Host " Backup: $bakDir" -ForegroundColor Cyan
Write-Host " Rollback: robocopy $bakDir $SVC_STATIC shipment-detail.html /COPY:DAT" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
