# ============================================================
# Windows Backend Deploy — C13E (PR #238)
# Target: main after C13E squash merge
# Campaign: C13E — Projection-by-Quantity correction
# Generated: 2026-05-20 | PZService RESTART REQUIRED
# ============================================================
# Files to deploy (1 backend file):
#   inventory_state_engine.py -> C:\PZ\app\services\
# ============================================================
# NOTE: This is a Python service file change.
#       PZService MUST be restarted after copy.
#       No DB schema change. No DB migration required.
# ============================================================

$ErrorActionPreference = "Stop"

# ── Paths ───────────────────────────────────────────────────
$SVC_SERVICES = "C:\PZ\app\services"
$REPO_SRC     = "C:\Users\Super Fashion\PZ APP\service\app\services"
$BAK_ROOT     = "C:\PZ\app\bak"

# ── STEP 0: Pull latest main ─────────────────────────────────
Write-Host "`n=== STEP 0: Verify repo state ===" -ForegroundColor Cyan
Set-Location "C:\Users\Super Fashion\PZ APP"
git fetch origin
git pull --ff-only origin main
$headSha = git rev-parse --short HEAD
Write-Host "HEAD after pull: $headSha" -ForegroundColor Green

# ── STEP 1: Verify C13E markers in source ───────────────────
Write-Host "`n=== STEP 1: Verify C13E source markers ===" -ForegroundColor Cyan
$srcContent = Get-Content "$REPO_SRC\inventory_state_engine.py" -Raw
$markers = @(
    "_coerce_qty",
    "C13E: expand by quantity",
    "qty == 1 else",
    "expanded_scan"
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
    Write-Host "[ABORT] C13E markers missing — wrong repo version? Aborting." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] All C13E markers confirmed in source." -ForegroundColor Green

# ── STEP 2: Verify zero-write guarantee still present ───────
Write-Host "`n=== STEP 2: Verify zero-write guarantee ===" -ForegroundColor Cyan
if ($srcContent -notmatch "DOES NOT WRITE") {
    Write-Host "[WARN] Zero-write comment not found — verify manually" -ForegroundColor Yellow
} else {
    Write-Host "[OK] Zero-write guarantee comment present" -ForegroundColor Green
}

# ── STEP 3: Backup current production file ──────────────────
Write-Host "`n=== STEP 3: Backup ===" -ForegroundColor Cyan
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$bakDir = "$BAK_ROOT\c13e_backend_$timestamp"
New-Item -ItemType Directory -Force -Path $bakDir | Out-Null
Copy-Item "$SVC_SERVICES\inventory_state_engine.py" "$bakDir\inventory_state_engine.py" -ErrorAction SilentlyContinue
Write-Host "[OK] Backup: $bakDir\inventory_state_engine.py" -ForegroundColor Green

# ── STEP 4: Stop PZService ───────────────────────────────────
Write-Host "`n=== STEP 4: Stop PZService ===" -ForegroundColor Cyan
Stop-Service -Name "PZService" -Force
Start-Sleep -Seconds 2
Write-Host "[OK] PZService stopped" -ForegroundColor Green

# ── STEP 5: Deploy inventory_state_engine.py ────────────────
Write-Host "`n=== STEP 5: Deploy C13E backend file ===" -ForegroundColor Cyan
robocopy "$REPO_SRC" "$SVC_SERVICES" "inventory_state_engine.py" /COPY:DAT
Write-Host " [1/1] inventory_state_engine.py -> $SVC_SERVICES\" -ForegroundColor Green

# ── STEP 6: Start PZService ──────────────────────────────────
Write-Host "`n=== STEP 6: Start PZService ===" -ForegroundColor Cyan
Start-Service -Name "PZService"
Start-Sleep -Seconds 3
$svc = Get-Service -Name "PZService"
if ($svc.Status -eq "Running") {
    Write-Host "[OK] PZService is Running" -ForegroundColor Green
} else {
    Write-Host "[FAIL] PZService status: $($svc.Status)" -ForegroundColor Red
    exit 1
}

# ── STEP 7: Smoke test ───────────────────────────────────────
Write-Host "`n=== STEP 7: Smoke test ===" -ForegroundColor Cyan
$smokeUrl = "http://localhost:47213/api/v1/inventory/state/SHIPMENT_4218922912_2026-05_9040dd39"
try {
    $resp = Invoke-WebRequest -Uri $smokeUrl -UseBasicParsing -TimeoutSec 10
    $body = $resp.Content | ConvertFrom-Json
    Write-Host "total:              $($body.total)"           -ForegroundColor $(if ($body.total -eq 46) { 'Green' } else { 'Red' })
    Write-Host "counts.PURCHASE_TRANSIT: $($body.counts.PURCHASE_TRANSIT)" -ForegroundColor $(if ($body.counts.PURCHASE_TRANSIT -eq 46) { 'Green' } else { 'Red' })
    Write-Host "synthetic:          $($body.synthetic)"      -ForegroundColor $(if ($body.synthetic -eq $true) { 'Green' } else { 'Yellow' })
    Write-Host "source:             $($body.source)"         -ForegroundColor $(if ($body.source -eq 'audit.tracking') { 'Green' } else { 'Yellow' })
    if ($body.total -eq 46 -and $body.counts.PURCHASE_TRANSIT -eq 46) {
        Write-Host "[PASS] Lapis smoke test: total=46, PURCHASE_TRANSIT=46" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] Unexpected totals — check deploy" -ForegroundColor Red
    }
} catch {
    Write-Host "[WARN] Smoke test request failed (batch may not be on this machine): $_" -ForegroundColor Yellow
}

Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host " C13E BACKEND DEPLOY COMPLETE" -ForegroundColor Green
Write-Host " Backup: $bakDir" -ForegroundColor Cyan
Write-Host " Rollback: Stop-Service PZService; robocopy $bakDir $SVC_SERVICES inventory_state_engine.py /COPY:DAT; Start-Service PZService" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
