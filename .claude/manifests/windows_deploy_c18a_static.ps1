# ============================================================
# Windows Static Deploy — C18A (PR #242)
# Target: main after C18A squash merge
# Campaign: C18A — Unified Proforma Builder Truth
# Generated: 2026-05-20 | NO SERVICE RESTART REQUIRED
# ============================================================
# Files to deploy (static only — no PZService restart needed):
#   shipment-detail.html -> C:\PZ\app\static\
# ============================================================
# Deploy order note:
#   If C13E is not yet deployed, deploy C13E first (restart required).
#   C14A + C15A + C16A + C17A + C18A can all be deployed in one pass (no restart).
#   Run this AFTER PR #242 merges to main.
# ============================================================

$ErrorActionPreference = "Stop"

# -- Paths --
$SVC_STATIC  = "C:\PZ\app\static"
$REPO_SRC    = "C:\Users\Super Fashion\PZ APP\service\app\static"
$BAK_ROOT    = "C:\PZ\app\bak"

# -- STEP 0: Pull latest main --
Write-Host "`n=== STEP 0: Verify repo state ===" -ForegroundColor Cyan
Set-Location "C:\Users\Super Fashion\PZ APP"
git fetch origin
git pull --ff-only origin main
$headSha = git rev-parse --short HEAD
Write-Host "HEAD after pull: $headSha" -ForegroundColor Green

# -- STEP 1: Verify C18A markers in source --
Write-Host "`n=== STEP 1: Verify C18A source markers ===" -ForegroundColor Cyan
$srcContent = Get-Content "$REPO_SRC\shipment-detail.html" -Raw
$markers = @(
    "c.ship_to_postal_code",
    "invState.total === ((invState.counts || {}).PURCHASE_TRANSIT || 0)",
    "draft-lines-empty-hint",
    "Reload items from warehouse data",
    "Link packing as sales",
    "btn-draft-intelligence",
    "draft-intelligence-panel",
    "workflow-cm-card-",
    "saveCmFields",
    "Saves to Customer Master only"
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
# Verify old wrong field is gone (only outside comments)
$badLines = ($srcContent -split "`n") | Where-Object {
    $_ -match "c\.ship_to_zip" -and
    $_ -notmatch "// C18A:" -and
    $_.Trim() -notmatch "^//"
}
if ($badLines) {
    Write-Host "[FAIL] c.ship_to_zip still present as active code" -ForegroundColor Red
    $allOk = $false
} else {
    Write-Host "[OK] c.ship_to_zip removed from active code" -ForegroundColor Green
}
if (-not $allOk) {
    Write-Host "[ABORT] C18A markers missing or wrong field present. Aborting." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] All C18A markers confirmed in source." -ForegroundColor Green

# -- STEP 2: Verify prior campaign markers still present --
Write-Host "`n=== STEP 2: Verify prior campaign markers ===" -ForegroundColor Cyan
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
    "Pending arrival",
    "warehouse-transit-note"
)
foreach ($m in $priorMarkers) {
    if ($srcContent -match [regex]::Escape($m)) {
        Write-Host "[OK] prior marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[WARN] prior marker missing: $m" -ForegroundColor Yellow
    }
}

# -- STEP 3: Backup current production file --
Write-Host "`n=== STEP 3: Backup ===" -ForegroundColor Cyan
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$bakDir = "$BAK_ROOT\c18a_static_$timestamp"
New-Item -ItemType Directory -Force -Path $bakDir | Out-Null
Copy-Item "$SVC_STATIC\shipment-detail.html" "$bakDir\shipment-detail.html" -ErrorAction SilentlyContinue
Write-Host "[OK] Backup: $bakDir\shipment-detail.html" -ForegroundColor Green

# -- STEP 4: Deploy (no restart needed) --
Write-Host "`n=== STEP 4: Deploy C18A static file ===" -ForegroundColor Cyan
robocopy "$REPO_SRC" "$SVC_STATIC" "shipment-detail.html" /COPY:DAT
Write-Host " [1/1] shipment-detail.html -> $SVC_STATIC\" -ForegroundColor Green
Write-Host "[OK] No PZService restart required for static files." -ForegroundColor Green

# -- STEP 5: Smoke verification --
Write-Host "`n=== STEP 5: Verify deployed file ===" -ForegroundColor Cyan
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
if ($smokeFail) {
    Write-Host "[FAIL] Deployed file verification failed — check copy." -ForegroundColor Red
    exit 1
}

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " C18A STATIC DEPLOY COMPLETE — NO RESTART REQUIRED" -ForegroundColor Green
Write-Host " Backup: $bakDir" -ForegroundColor Cyan
Write-Host " Rollback: robocopy $bakDir $SVC_STATIC shipment-detail.html /COPY:DAT" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
