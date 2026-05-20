# ============================================================
# Windows Static Deploy — C16A (PR #240)
# Target: main after C16A squash merge
# Campaign: C16A — Lapis UX Truth Redesign
# Generated: 2026-05-20 | NO SERVICE RESTART REQUIRED
# ============================================================
# Files to deploy (static only — no PZService restart needed):
#   shipment-detail.html -> C:\PZ\app\static\
# ============================================================
# Deploy order note:
#   If C13E is not yet deployed, deploy C13E first (restart required).
#   C14A + C15A + C16A can all be deployed in one pass (no restart).
# ============================================================

$ErrorActionPreference = "Stop"

# ── Paths ───────────────────────────────────────────────────
$SVC_STATIC  = "C:\PZ\app\static"
$REPO_SRC    = "C:\Users\Super Fashion\PZ APP\service\app\static"
$BAK_ROOT    = "C:\PZ\app\bak"

# ── STEP 0: Pull latest main ─────────────────────────────────
Write-Host "`n=== STEP 0: Verify repo state ===" -ForegroundColor Cyan
Set-Location "C:\Users\Super Fashion\PZ APP"
git fetch origin
git pull --ff-only origin main
$headSha = git rev-parse --short HEAD
Write-Host "HEAD after pull: $headSha" -ForegroundColor Green

# ── STEP 1: Verify C16A markers in source ───────────────────
Write-Host "`n=== STEP 1: Verify C16A source markers ===" -ForegroundColor Cyan
$srcContent = Get-Content "$REPO_SRC\shipment-detail.html" -Raw
$markers = @(
    "isTransit ? 'In transit' : (r.current_location || '—')",
    "invState.counts.PURCHASE_TRANSIT",
    "cm-clients-",
    "cm-clients-main-",
    "workflow-cm-row-",
    "setCm",
    "customer-master"
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
if (-not $allOk) {
    Write-Host "[ABORT] C16A markers missing — wrong repo version? Aborting." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] All C16A markers confirmed in source." -ForegroundColor Green

# ── STEP 2: Verify C15A + C14A markers still present ─────────
Write-Host "`n=== STEP 2: Verify prior campaign markers ===" -ForegroundColor Cyan
$priorMarkers = @(
    "link-packing-doc-needs-client-",
    "link-packing-doc-unassigned-",
    "Action required",
    "create in wFirma first",
    "sales-transit-context-banner",
    "orphan-assignment-cta",
    "sales-qty-reconciliation",
    "Pending arrival"
)
foreach ($m in $priorMarkers) {
    if ($srcContent -match [regex]::Escape($m)) {
        Write-Host "[OK] prior marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[WARN] prior marker missing: $m" -ForegroundColor Yellow
    }
}

# ── STEP 3: Backup current production file ──────────────────
Write-Host "`n=== STEP 3: Backup ===" -ForegroundColor Cyan
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$bakDir = "$BAK_ROOT\c16a_static_$timestamp"
New-Item -ItemType Directory -Force -Path $bakDir | Out-Null
Copy-Item "$SVC_STATIC\shipment-detail.html" "$bakDir\shipment-detail.html" -ErrorAction SilentlyContinue
Write-Host "[OK] Backup: $bakDir\shipment-detail.html" -ForegroundColor Green

# ── STEP 4: Deploy (no restart needed) ──────────────────────
Write-Host "`n=== STEP 4: Deploy C16A static file ===" -ForegroundColor Cyan
robocopy "$REPO_SRC" "$SVC_STATIC" "shipment-detail.html" /COPY:DAT
Write-Host " [1/1] shipment-detail.html -> $SVC_STATIC\" -ForegroundColor Green
Write-Host "[OK] No PZService restart required for static files." -ForegroundColor Green

# ── STEP 5: Smoke verification ──────────────────────────────
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
Write-Host " C16A STATIC DEPLOY COMPLETE — NO RESTART REQUIRED" -ForegroundColor Green
Write-Host " Backup: $bakDir" -ForegroundColor Cyan
Write-Host " Rollback: robocopy $bakDir $SVC_STATIC shipment-detail.html /COPY:DAT" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
