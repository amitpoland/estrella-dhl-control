# ============================================================
# Windows Backend Deploy — C22-PERMANENT + C24-FINALIZE
# Target: main after C24-FINALIZE (commit 42afbba or newer)
# Campaigns:
#   C22-PERMANENT — routes_packing.py: header-block client extraction
#   C24-FINALIZE  — routes_customer_master.py: bill_to_nip alias
#                 — routes_proforma.py: EJ_DEV_WORKFLOW_BYPASS bypass gate
#                 — config.py: ej_dev_workflow_bypass flag
# Generated: 2026-05-20 | PZService RESTART REQUIRED
# ============================================================
# Files to deploy (4 backend files):
#   app/api/routes_packing.py          -> C:\PZ\app\api\
#   app/api/routes_customer_master.py  -> C:\PZ\app\api\
#   app/api/routes_proforma.py         -> C:\PZ\app\api\
#   app/core/config.py                 -> C:\PZ\app\core\
# ============================================================
# DEPLOY ORDER:
#   1. Run this script (stop PZService → copy 4 files → start PZService)
#   2. Then run windows_deploy_c22_c24_static.ps1 (no restart needed)
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
$SVC_API     = "C:\PZ\app\api"
$SVC_CORE    = "C:\PZ\app\core"
$REPO_API    = "C:\Users\Super Fashion\PZ APP\service\app\api"
$REPO_CORE   = "C:\Users\Super Fashion\PZ APP\service\app\core"
$BAK_ROOT    = "C:\PZ\app\bak"

# ── STEP 0: Pull latest main ───────────────────────────────────────────────────
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

# ── STEP 1: Verify C22-PERMANENT markers in routes_packing.py ─────────────────
Write-Host ""
Write-Host "=== STEP 1: Verify C22-PERMANENT markers ===" -ForegroundColor Cyan
$srcPacking = Get-Content "$REPO_API\routes_packing.py" -Raw
if (-not $srcPacking) {
    Write-Host "[FAIL] Could not read routes_packing.py" -ForegroundColor Red
    exit 1
}
$c22Markers = @(
    "_looks_like_company_name",
    "_is_table_header_or_data_row",
    "Client-Po denylist",
    "C22-PERMANENT"
)
$allOk = $true
foreach ($m in $c22Markers) {
    if ($srcPacking -match [regex]::Escape($m)) {
        Write-Host "[OK] C22 marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] C22 marker missing: $m" -ForegroundColor Red
        $allOk = $false
    }
}
if (-not $allOk) {
    Write-Host "[ABORT] C22 source verification failed." -ForegroundColor Red
    exit 1
}

# ── STEP 2: Verify C24-FINALIZE markers in routes_customer_master.py ──────────
Write-Host ""
Write-Host "=== STEP 2: Verify C24 bill_to_nip alias ===" -ForegroundColor Cyan
$srcCm = Get-Content "$REPO_API\routes_customer_master.py" -Raw
if (-not $srcCm) {
    Write-Host "[FAIL] Could not read routes_customer_master.py" -ForegroundColor Red
    exit 1
}
$c24CmMarkers = @(
    "bill_to_nip",
    "Alias: bill_to_nip",
    "`"bill_to_nip`""
)
foreach ($m in $c24CmMarkers) {
    if ($srcCm -match [regex]::Escape($m)) {
        Write-Host "[OK] C24 CM marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] C24 CM marker missing: $m" -ForegroundColor Red
        $allOk = $false
    }
}

# ── STEP 3: Verify C24-FINALIZE markers in routes_proforma.py ─────────────────
Write-Host ""
Write-Host "=== STEP 3: Verify C24 bypass flag in routes_proforma.py ===" -ForegroundColor Cyan
$srcProforma = Get-Content "$REPO_API\routes_proforma.py" -Raw
if (-not $srcProforma) {
    Write-Host "[FAIL] Could not read routes_proforma.py" -ForegroundColor Red
    exit 1
}
$c24ProformaMarkers = @(
    "ej_dev_workflow_bypass",
    "_dev_bypass",
    "DEV-BYPASS"
)
foreach ($m in $c24ProformaMarkers) {
    if ($srcProforma -match [regex]::Escape($m)) {
        Write-Host "[OK] C24 proforma marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] C24 proforma marker missing: $m" -ForegroundColor Red
        $allOk = $false
    }
}
# Verify wFirma create gate is NOT bypassed (safety check)
$createGatePresent = $srcProforma -match [regex]::Escape("wfirma_create_proforma_allowed")
if ($createGatePresent) {
    Write-Host "[OK] wFirma create gate still present in routes_proforma.py" -ForegroundColor Green
} else {
    Write-Host "[FAIL] wFirma create gate MISSING — aborting, source may be corrupt" -ForegroundColor Red
    exit 1
}

# ── STEP 4: Verify C24-FINALIZE marker in config.py ───────────────────────────
Write-Host ""
Write-Host "=== STEP 4: Verify C24 config flag ===" -ForegroundColor Cyan
$srcConfig = Get-Content "$REPO_CORE\config.py" -Raw
if (-not $srcConfig) {
    Write-Host "[FAIL] Could not read config.py" -ForegroundColor Red
    exit 1
}
if ($srcConfig -match [regex]::Escape("ej_dev_workflow_bypass")) {
    Write-Host "[OK] ej_dev_workflow_bypass flag present in config.py" -ForegroundColor Green
} else {
    Write-Host "[FAIL] ej_dev_workflow_bypass missing from config.py" -ForegroundColor Red
    $allOk = $false
}
if (-not $allOk) {
    Write-Host "[ABORT] Source verification failed. Aborting." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] All C22+C24 markers confirmed in source." -ForegroundColor Green

# ── STEP 5: Backup current production files ────────────────────────────────────
Write-Host ""
Write-Host "=== STEP 5: Backup ===" -ForegroundColor Cyan
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$bakDir = "$BAK_ROOT\c22_c24_backend_$timestamp"
New-Item -ItemType Directory -Force -Path $bakDir | Out-Null
Copy-Item "$SVC_API\routes_packing.py"         "$bakDir\routes_packing.py"         -ErrorAction SilentlyContinue
Copy-Item "$SVC_API\routes_customer_master.py" "$bakDir\routes_customer_master.py" -ErrorAction SilentlyContinue
Copy-Item "$SVC_API\routes_proforma.py"        "$bakDir\routes_proforma.py"        -ErrorAction SilentlyContinue
Copy-Item "$SVC_CORE\config.py"                "$bakDir\config.py"                 -ErrorAction SilentlyContinue
Write-Host "[OK] Backup: $bakDir\" -ForegroundColor Green

# ── STEP 6: Stop PZService ─────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== STEP 6: Stop PZService ===" -ForegroundColor Cyan
Stop-Service -Name "PZService" -Force
Start-Sleep -Seconds 2
Write-Host "[OK] PZService stopped" -ForegroundColor Green

# ── STEP 7: Deploy 4 backend files ────────────────────────────────────────────
Write-Host ""
Write-Host "=== STEP 7: Deploy C22+C24 backend files ===" -ForegroundColor Cyan

robocopy "$REPO_API" "$SVC_API" "routes_packing.py" /COPY:DAT
if ($LASTEXITCODE -ge 8) {
    Write-Host "[FAIL] robocopy error $LASTEXITCODE on routes_packing.py" -ForegroundColor Red
    Write-Host "Rollback: robocopy $bakDir $SVC_API routes_packing.py /COPY:DAT" -ForegroundColor Yellow
    Start-Service -Name "PZService"
    exit 1
}
Write-Host " [1/4] routes_packing.py -> $SVC_API\" -ForegroundColor Green

robocopy "$REPO_API" "$SVC_API" "routes_customer_master.py" /COPY:DAT
if ($LASTEXITCODE -ge 8) {
    Write-Host "[FAIL] robocopy error $LASTEXITCODE on routes_customer_master.py" -ForegroundColor Red
    Start-Service -Name "PZService"
    exit 1
}
Write-Host " [2/4] routes_customer_master.py -> $SVC_API\" -ForegroundColor Green

robocopy "$REPO_API" "$SVC_API" "routes_proforma.py" /COPY:DAT
if ($LASTEXITCODE -ge 8) {
    Write-Host "[FAIL] robocopy error $LASTEXITCODE on routes_proforma.py" -ForegroundColor Red
    Start-Service -Name "PZService"
    exit 1
}
Write-Host " [3/4] routes_proforma.py -> $SVC_API\" -ForegroundColor Green

robocopy "$REPO_CORE" "$SVC_CORE" "config.py" /COPY:DAT
if ($LASTEXITCODE -ge 8) {
    Write-Host "[FAIL] robocopy error $LASTEXITCODE on config.py" -ForegroundColor Red
    Start-Service -Name "PZService"
    exit 1
}
Write-Host " [4/4] config.py -> $SVC_CORE\" -ForegroundColor Green

# ── STEP 8: Start PZService ────────────────────────────────────────────────────
Write-Host ""
Write-Host "=== STEP 8: Start PZService ===" -ForegroundColor Cyan
Start-Service -Name "PZService"
Start-Sleep -Seconds 4
$svc = Get-Service -Name "PZService"
if ($svc.Status -eq "Running") {
    Write-Host "[OK] PZService is Running" -ForegroundColor Green
} else {
    Write-Host "[FAIL] PZService status: $($svc.Status)" -ForegroundColor Red
    Write-Host "Check Windows Event Log: Get-EventLog -LogName Application -Source PZService -Newest 10" -ForegroundColor Yellow
    exit 1
}

# ── STEP 9: Smoke test health endpoint ────────────────────────────────────────
Write-Host ""
Write-Host "=== STEP 9: Smoke test ===" -ForegroundColor Cyan
$smokeUrl = "http://localhost:47213/api/v1/health"
try {
    $resp = Invoke-WebRequest -Uri $smokeUrl -UseBasicParsing -TimeoutSec 10
    Write-Host "[OK] Health: HTTP $($resp.StatusCode)" -ForegroundColor Green
} catch {
    Write-Host "[WARN] Health check failed: $_" -ForegroundColor Yellow
}

# Verify ej_dev_workflow_bypass is accessible via settings
$configUrl = "http://localhost:47213/api/v1/admin/config-check"
try {
    $resp = Invoke-WebRequest -Uri $configUrl -UseBasicParsing -TimeoutSec 5
    Write-Host "[INFO] Config check: HTTP $($resp.StatusCode)" -ForegroundColor Cyan
} catch {
    Write-Host "[INFO] No /config-check endpoint (not required)" -ForegroundColor Cyan
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " C22+C24 BACKEND DEPLOY COMPLETE" -ForegroundColor Green
Write-Host " Files deployed: routes_packing.py, routes_customer_master.py," -ForegroundColor Green
Write-Host "                 routes_proforma.py, config.py" -ForegroundColor Green
Write-Host " Backup: $bakDir" -ForegroundColor Cyan
Write-Host " Rollback: Stop-Service PZService; robocopy $bakDir $SVC_API routes_packing.py routes_customer_master.py routes_proforma.py /COPY:DAT; robocopy $bakDir $SVC_CORE config.py /COPY:DAT; Start-Service PZService" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "NEXT: Run windows_deploy_c22_c24_static.ps1 (no restart needed)" -ForegroundColor Cyan
Write-Host "NEXT (optional): Add EJ_DEV_WORKFLOW_BYPASS=true to .env and restart for setup mode" -ForegroundColor Cyan
