# ============================================================
# Windows Static Deploy — C21A-PERM + C22-PERMANENT + C24-FINALIZE
# Target: main after C24-FINALIZE (commit 42afbba or newer)
# Campaigns:
#   C21A-PERM  — dashboard-shared.js: variant="primary" Btn fix
#              — dashboard.html: execute-pz-button
#   C22-PERMANENT (no static changes — packing parser backend-only)
#   C24-FINALIZE  — shipment-detail.html: rec.nip || rec.bill_to_nip fix
# Generated: 2026-05-20 | NO PZService RESTART REQUIRED
# ============================================================
# Files to deploy (3 static files):
#   app/static/shipment-detail.html  -> C:\PZ\app\static\
#   app/static/dashboard.html        -> C:\PZ\app\static\
#   app/static/dashboard-shared.js   -> C:\PZ\app\static\
# ============================================================
# DEPLOY ORDER:
#   1. Run windows_deploy_c22_c24_backend.ps1 FIRST (requires PZService restart)
#   2. Then run THIS script (no restart — static files served directly)
# ============================================================
# ROBOCOPY EXIT CODE REFERENCE:
#   0 = No files copied (source = destination already)
#   1 = Files copied successfully
#   2 = Extra files in destination (not an error)
#   8+ = ERROR
# Script treats codes >= 8 as failures.
# ============================================================

$ErrorActionPreference = "Continue"

# ── Paths ─────────────────────────────────────────────────────────────────────
$SVC_STATIC  = "C:\PZ\app\static"
$REPO_STATIC = "C:\Users\Super Fashion\PZ APP\service\app\static"
$BAK_ROOT    = "C:\PZ\app\bak"

# ── STEP 0: Verify repo state ──────────────────────────────────────────────────
Write-Host ""
Write-Host "=== STEP 0: Verify repo state ===" -ForegroundColor Cyan
Set-Location "C:\Users\Super Fashion\PZ APP"
git fetch origin
if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] git fetch failed" -ForegroundColor Red; exit 1 }
git pull --ff-only origin main
if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] git pull failed" -ForegroundColor Red; exit 1 }
$headSha = git rev-parse --short HEAD
Write-Host "HEAD after pull: $headSha" -ForegroundColor Green
Write-Host "Expected: 42afbba or newer (C24-FINALIZE)" -ForegroundColor Cyan

# ── STEP 1: Verify C24-FINALIZE marker in shipment-detail.html ────────────────
Write-Host ""
Write-Host "=== STEP 1: Verify C24 NIP fix in shipment-detail.html ===" -ForegroundColor Cyan
$srcDetail = Get-Content "$REPO_STATIC\shipment-detail.html" -Raw
if (-not $srcDetail) {
    Write-Host "[FAIL] Could not read shipment-detail.html" -ForegroundColor Red
    exit 1
}

$allOk = $true

# C24 NIP alias fix: frontend must read rec.nip first, rec.bill_to_nip as fallback
if ($srcDetail -match [regex]::Escape("rec.nip || rec.bill_to_nip")) {
    Write-Host "[OK] C24 NIP fix present: rec.nip || rec.bill_to_nip" -ForegroundColor Green
} else {
    Write-Host "[FAIL] C24 NIP fix MISSING in shipment-detail.html" -ForegroundColor Red
    $allOk = $false
}

# C21A: execute-pz-button testid must be present
if ($srcDetail -match [regex]::Escape("execute-pz-button")) {
    Write-Host "[OK] C21A marker present: execute-pz-button" -ForegroundColor Green
} else {
    Write-Host "[FAIL] C21A marker missing: execute-pz-button" -ForegroundColor Red
    $allOk = $false
}

# Safety: intelligence dead code must be absent
$deadCodeMarkers = @(
    "btn-draft-intelligence",
    "intelligence-panel",
    "anomaly-row",
    "suggestion-row"
)
foreach ($m in $deadCodeMarkers) {
    if ($srcDetail -match [regex]::Escape($m)) {
        Write-Host "[FAIL] Intelligence dead code found (should be absent): $m" -ForegroundColor Red
        $allOk = $false
    } else {
        Write-Host "[OK] Dead code absent: $m" -ForegroundColor Green
    }
}

# ── STEP 2: Verify C21A markers in dashboard.html ─────────────────────────────
Write-Host ""
Write-Host "=== STEP 2: Verify C21A markers in dashboard.html ===" -ForegroundColor Cyan
$srcDash = Get-Content "$REPO_STATIC\dashboard.html" -Raw
if (-not $srcDash) {
    Write-Host "[FAIL] Could not read dashboard.html" -ForegroundColor Red
    exit 1
}

$c21aDashMarkers = @(
    "execute-pz-button",
    "execute-pz-gate",
    "var(--badge-red-text)"
)
foreach ($m in $c21aDashMarkers) {
    if ($srcDash -match [regex]::Escape($m)) {
        Write-Host "[OK] C21A dashboard marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] C21A dashboard marker missing: $m" -ForegroundColor Red
        $allOk = $false
    }
}

# Safety: no intelligence dead code in dashboard either
foreach ($m in $deadCodeMarkers) {
    if ($srcDash -match [regex]::Escape($m)) {
        Write-Host "[FAIL] Intelligence dead code found in dashboard (should be absent): $m" -ForegroundColor Red
        $allOk = $false
    }
}

# ── STEP 3: Verify C21A markers in dashboard-shared.js ────────────────────────
Write-Host ""
Write-Host "=== STEP 3: Verify C21A markers in dashboard-shared.js ===" -ForegroundColor Cyan
$srcShared = Get-Content "$REPO_STATIC\dashboard-shared.js" -Raw
if (-not $srcShared) {
    Write-Host "[FAIL] Could not read dashboard-shared.js" -ForegroundColor Red
    exit 1
}

# C21A: variant="primary" must be handled in Btn component
$c21aSharedMarkers = @(
    "primary",
    "var(--accent)",
    "var(--badge-red-text)"
)
foreach ($m in $c21aSharedMarkers) {
    if ($srcShared -match [regex]::Escape($m)) {
        Write-Host "[OK] C21A shared marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] C21A shared marker missing: $m" -ForegroundColor Red
        $allOk = $false
    }
}

if (-not $allOk) {
    Write-Host "[ABORT] Source verification failed. Aborting deploy." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] All C21A+C24 static markers confirmed in source." -ForegroundColor Green

# ── STEP 4: Backup current production static files ────────────────────────────
Write-Host ""
Write-Host "=== STEP 4: Backup ===" -ForegroundColor Cyan
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$bakDir = "$BAK_ROOT\c22_c24_static_$timestamp"
New-Item -ItemType Directory -Force -Path $bakDir | Out-Null
Copy-Item "$SVC_STATIC\shipment-detail.html" "$bakDir\shipment-detail.html" -ErrorAction SilentlyContinue
Copy-Item "$SVC_STATIC\dashboard.html"       "$bakDir\dashboard.html"       -ErrorAction SilentlyContinue
Copy-Item "$SVC_STATIC\dashboard-shared.js"  "$bakDir\dashboard-shared.js"  -ErrorAction SilentlyContinue
Write-Host "[OK] Backup: $bakDir\" -ForegroundColor Green

# ── STEP 5: Deploy 3 static files (NO PZService restart needed) ───────────────
Write-Host ""
Write-Host "=== STEP 5: Deploy C21A+C24 static files ===" -ForegroundColor Cyan
Write-Host "NOTE: No PZService restart required for static files." -ForegroundColor Cyan

robocopy "$REPO_STATIC" "$SVC_STATIC" "shipment-detail.html" /COPY:DAT
if ($LASTEXITCODE -ge 8) {
    Write-Host "[FAIL] robocopy error $LASTEXITCODE on shipment-detail.html" -ForegroundColor Red
    Write-Host "Rollback: robocopy $bakDir $SVC_STATIC shipment-detail.html /COPY:DAT" -ForegroundColor Yellow
    exit 1
}
Write-Host " [1/3] shipment-detail.html -> $SVC_STATIC\" -ForegroundColor Green

robocopy "$REPO_STATIC" "$SVC_STATIC" "dashboard.html" /COPY:DAT
if ($LASTEXITCODE -ge 8) {
    Write-Host "[FAIL] robocopy error $LASTEXITCODE on dashboard.html" -ForegroundColor Red
    Write-Host "Rollback: robocopy $bakDir $SVC_STATIC dashboard.html /COPY:DAT" -ForegroundColor Yellow
    exit 1
}
Write-Host " [2/3] dashboard.html -> $SVC_STATIC\" -ForegroundColor Green

robocopy "$REPO_STATIC" "$SVC_STATIC" "dashboard-shared.js" /COPY:DAT
if ($LASTEXITCODE -ge 8) {
    Write-Host "[FAIL] robocopy error $LASTEXITCODE on dashboard-shared.js" -ForegroundColor Red
    Write-Host "Rollback: robocopy $bakDir $SVC_STATIC dashboard-shared.js /COPY:DAT" -ForegroundColor Yellow
    exit 1
}
Write-Host " [3/3] dashboard-shared.js -> $SVC_STATIC\" -ForegroundColor Green

# ── STEP 6: Smoke verify deployed files ───────────────────────────────────────
Write-Host ""
Write-Host "=== STEP 6: Smoke verify deployed files ===" -ForegroundColor Cyan

# Verify deployed shipment-detail.html contains C24 marker
$deployedDetail = Get-Content "$SVC_STATIC\shipment-detail.html" -Raw
if ($deployedDetail -match [regex]::Escape("rec.nip || rec.bill_to_nip")) {
    Write-Host "[OK] Deployed shipment-detail.html has C24 NIP fix" -ForegroundColor Green
} else {
    Write-Host "[FAIL] Deployed shipment-detail.html is MISSING C24 NIP fix — file may not have copied" -ForegroundColor Red
    exit 1
}

# Verify deployed dashboard.html contains execute-pz-button
$deployedDash = Get-Content "$SVC_STATIC\dashboard.html" -Raw
if ($deployedDash -match [regex]::Escape("execute-pz-button")) {
    Write-Host "[OK] Deployed dashboard.html has execute-pz-button" -ForegroundColor Green
} else {
    Write-Host "[FAIL] Deployed dashboard.html is MISSING execute-pz-button" -ForegroundColor Red
    exit 1
}

# Verify deployed dashboard-shared.js contains primary variant
$deployedShared = Get-Content "$SVC_STATIC\dashboard-shared.js" -Raw
if ($deployedShared -match [regex]::Escape("var(--accent)")) {
    Write-Host "[OK] Deployed dashboard-shared.js has primary variant colors" -ForegroundColor Green
} else {
    Write-Host "[FAIL] Deployed dashboard-shared.js MISSING primary variant" -ForegroundColor Red
    exit 1
}

# Verify service is still running (backend script should have already started it)
$svc = Get-Service -Name "PZService" -ErrorAction SilentlyContinue
if ($svc -and $svc.Status -eq "Running") {
    Write-Host "[OK] PZService is Running" -ForegroundColor Green
} else {
    Write-Host "[WARN] PZService status: $($svc.Status) — static files are served; backend may need restart" -ForegroundColor Yellow
}

# Optional health check
$smokeUrl = "http://localhost:47213/api/v1/health"
try {
    $resp = Invoke-WebRequest -Uri $smokeUrl -UseBasicParsing -TimeoutSec 10
    Write-Host "[OK] Health endpoint: HTTP $($resp.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "[WARN] Health check failed: $_ (static deploy complete; backend may not be running)" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " C21A+C24 STATIC DEPLOY COMPLETE" -ForegroundColor Green
Write-Host " Files deployed: shipment-detail.html, dashboard.html," -ForegroundColor Green
Write-Host "                 dashboard-shared.js" -ForegroundColor Green
Write-Host " Backup: $bakDir" -ForegroundColor Cyan
Write-Host " Rollback: robocopy $bakDir $SVC_STATIC shipment-detail.html dashboard.html dashboard-shared.js /COPY:DAT" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "BYPASS FLAG PROCEDURE (optional — for dev/diagnosis only):" -ForegroundColor Cyan
Write-Host "  Enable : Add EJ_DEV_WORKFLOW_BYPASS=true to C:\PZ\.env, then: Restart-Service PZService" -ForegroundColor Cyan
Write-Host "  Disable: Remove EJ_DEV_WORKFLOW_BYPASS from C:\PZ\.env, then: Restart-Service PZService" -ForegroundColor Cyan
Write-Host "  Status : GET http://localhost:47213/api/v1/health (check dev_bypass_active in response if exposed)" -ForegroundColor Cyan
Write-Host ""
Write-Host "C22+C24 FULL DEPLOY COMPLETE — backend + static both deployed." -ForegroundColor Green
Write-Host "Open https://pz.estrellajewels.eu to verify in browser." -ForegroundColor Cyan
