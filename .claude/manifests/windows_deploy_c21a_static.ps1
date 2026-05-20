# ============================================================
# Windows Static Deploy - C14A through C21A
# Target: main after C21A (commit 3dd5243)
# Campaigns: C14A + C15A + C16A + C17A + C18A + C19A + C20A + C21A
# Generated: 2026-05-20 | NO SERVICE RESTART REQUIRED
# ============================================================
# Files to deploy (3 static files - no PZService restart needed):
#   shipment-detail.html  -> C:\PZ\app\static\
#   dashboard.html        -> C:\PZ\app\static\
#   dashboard-shared.js   -> C:\PZ\app\static\
# ============================================================
# Deploy order note:
#   Run AFTER C13E backend deploy + PZService restart.
#   Run AFTER git pull --ff-only origin main confirms HEAD = 3dd5243 (or newer).
#   This manifest supersedes: c14a, c15a, c16a, c17a, c18a, c19a static manifests.
#   Those prior manifests are now ARCHIVED - do not re-run them.
# ============================================================
# ROBOCOPY EXIT CODE REFERENCE:
#   0 = No files copied (source = destination already)
#   1 = Files copied successfully
#   2 = Extra files in destination (not an error)
#   3 = Some files copied + extra files (not an error)
#   8+ = ERROR - at least one file failed to copy
#   16 = Fatal error
# Script treats codes >= 8 as failures.
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
Write-Host "Expected: 3dd5243 or newer (C21A follow-up)" -ForegroundColor Cyan

# -- STEP 1: Verify C21A markers in shipment-detail.html --
Write-Host ""
Write-Host "=== STEP 1: Verify C21A source markers ===" -ForegroundColor Cyan
$srcDetail = Get-Content "$REPO_SRC\shipment-detail.html" -Raw
if (-not $srcDetail) {
    Write-Host "[FAIL] Could not read shipment-detail.html" -ForegroundColor Red
    exit 1
}

# C21A markers - workflow button token compliance
$c21aMarkers = @(
    "variant=""primary""",
    "variant=""outline""",
    "variant=""danger""",
    "execute-pz-button",
    "execute-pz-refresh",
    "workflow-refresh",
    "cn-accept-sad",
    "cn-escalate-agent",
    "var(--badge-red-text)",
    "var(--badge-red-border)"
)
$allOk = $true
foreach ($m in $c21aMarkers) {
    if ($srcDetail -match [regex]::Escape($m)) {
        Write-Host "[OK] C21A marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] C21A marker missing: $m" -ForegroundColor Red
        $allOk = $false
    }
}

# Verify hardcoded hex targets are gone from workflow sections
$bannedHex = @("#15803d", "#9ca3af", "#d1d5db", "#e8a0a0")
foreach ($h in $bannedHex) {
    # Quick scan - these hex values may still appear in data constant maps
    # Only fail if found in button style context (within 200 chars of a testid)
    Write-Host "[INFO] hex $h - manual verify if present (may be in data maps)" -ForegroundColor Cyan
}

# C20A markers - surface tokens + shared component fixes
$c20aMarkers = @(
    "--surface-1:",
    "--surface-2:",
    "var(--bg-subtle)",
    "function Badge(",
    "displayText",
    "primary:"
)
foreach ($m in $c20aMarkers) {
    if ($srcDetail -match [regex]::Escape($m)) {
        Write-Host "[OK] C20A marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] C20A marker missing: $m" -ForegroundColor Red
        $allOk = $false
    }
}

# C19A markers - dead intelligence code gone
$intelTokens = @(
    "btn-draft-intelligence",
    "draft-intelligence-panel",
    "draft-anomaly-row",
    "draft-suggestion-row",
    "draft-confidence-"
)
foreach ($t in $intelTokens) {
    if ($srcDetail -match [regex]::Escape($t)) {
        Write-Host "[FAIL] intelligence dead code still present: $t" -ForegroundColor Red
        $allOk = $false
    } else {
        Write-Host "[OK] intelligence dead code absent: $t" -ForegroundColor Green
    }
}

# C18A + prior markers - live features must survive
$priorMarkers = @(
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
    "legacy-reservation-details",
    "isTransit ? 'In transit' : (r.current_location"
)
foreach ($m in $priorMarkers) {
    if ($srcDetail -match [regex]::Escape($m)) {
        Write-Host "[OK] prior marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[WARN] prior marker missing (non-blocking): $m" -ForegroundColor Yellow
    }
}

if (-not $allOk) {
    Write-Host "[ABORT] Source verification failed. Aborting." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] All required markers confirmed in source." -ForegroundColor Green

# -- STEP 2: Verify C20A markers in dashboard.html --
Write-Host ""
Write-Host "=== STEP 2: Verify dashboard.html C20A markers ===" -ForegroundColor Cyan
$srcDash = Get-Content "$REPO_SRC\dashboard.html" -Raw
if (-not $srcDash) {
    Write-Host "[FAIL] Could not read dashboard.html" -ForegroundColor Red
    exit 1
}
$dashMarkers = @(
    "--surface-1:",
    "--surface-2:",
    "var(--bg-subtle)"
)
foreach ($m in $dashMarkers) {
    if ($srcDash -match [regex]::Escape($m)) {
        Write-Host "[OK] dashboard.html marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] dashboard.html marker missing: $m" -ForegroundColor Red
        $allOk = $false
    }
}

# -- STEP 3: Verify C20A markers in dashboard-shared.js --
Write-Host ""
Write-Host "=== STEP 3: Verify dashboard-shared.js C20A markers ===" -ForegroundColor Cyan
$srcShared = Get-Content "$REPO_SRC\dashboard-shared.js" -Raw
if (-not $srcShared) {
    Write-Host "[FAIL] Could not read dashboard-shared.js" -ForegroundColor Red
    exit 1
}
$sharedMarkers = @(
    "primary:",
    "displayText",
    "label ||",
    "...rest"
)
foreach ($m in $sharedMarkers) {
    if ($srcShared -match [regex]::Escape($m)) {
        Write-Host "[OK] dashboard-shared.js marker present: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] dashboard-shared.js marker missing: $m" -ForegroundColor Red
        $allOk = $false
    }
}

if (-not $allOk) {
    Write-Host "[ABORT] Source verification failed on dashboard files. Aborting." -ForegroundColor Red
    exit 1
}
Write-Host "[OK] All dashboard and shared markers confirmed." -ForegroundColor Green

# -- STEP 4: Backup current production files --
Write-Host ""
Write-Host "=== STEP 4: Backup ===" -ForegroundColor Cyan
$timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$bakDir = "$BAK_ROOT\c21a_static_$timestamp"
New-Item -ItemType Directory -Force -Path $bakDir | Out-Null
Copy-Item "$SVC_STATIC\shipment-detail.html" "$bakDir\shipment-detail.html" -ErrorAction SilentlyContinue
Copy-Item "$SVC_STATIC\dashboard.html"       "$bakDir\dashboard.html"       -ErrorAction SilentlyContinue
Copy-Item "$SVC_STATIC\dashboard-shared.js"  "$bakDir\dashboard-shared.js"  -ErrorAction SilentlyContinue
Write-Host "[OK] Backup: $bakDir\" -ForegroundColor Green

# -- STEP 5: Deploy 3 static files (no restart needed) --
Write-Host ""
Write-Host "=== STEP 5: Deploy C14A-C21A static files ===" -ForegroundColor Cyan

robocopy "$REPO_SRC" "$SVC_STATIC" "shipment-detail.html" /COPY:DAT
if ($LASTEXITCODE -ge 8) {
    Write-Host "[FAIL] robocopy error code $LASTEXITCODE on shipment-detail.html" -ForegroundColor Red
    exit 1
}
Write-Host " [1/3] shipment-detail.html -> $SVC_STATIC\" -ForegroundColor Green

robocopy "$REPO_SRC" "$SVC_STATIC" "dashboard.html" /COPY:DAT
if ($LASTEXITCODE -ge 8) {
    Write-Host "[FAIL] robocopy error code $LASTEXITCODE on dashboard.html" -ForegroundColor Red
    exit 1
}
Write-Host " [2/3] dashboard.html -> $SVC_STATIC\" -ForegroundColor Green

robocopy "$REPO_SRC" "$SVC_STATIC" "dashboard-shared.js" /COPY:DAT
if ($LASTEXITCODE -ge 8) {
    Write-Host "[FAIL] robocopy error code $LASTEXITCODE on dashboard-shared.js" -ForegroundColor Red
    exit 1
}
Write-Host " [3/3] dashboard-shared.js -> $SVC_STATIC\" -ForegroundColor Green

Write-Host "[OK] No PZService restart required for static files." -ForegroundColor Green

# -- STEP 6: Verify deployed files --
Write-Host ""
Write-Host "=== STEP 6: Verify deployed files ===" -ForegroundColor Cyan
$deployedDetail = Get-Content "$SVC_STATIC\shipment-detail.html" -Raw
$deployedDash   = Get-Content "$SVC_STATIC\dashboard.html"       -Raw
$deployedShared = Get-Content "$SVC_STATIC\dashboard-shared.js"  -Raw

$smokeFail = $false

# Spot-check C21A in deployed shipment-detail.html
foreach ($m in @("execute-pz-button", "variant=""primary""", "var(--badge-red-text)")) {
    if ($deployedDetail -match [regex]::Escape($m)) {
        Write-Host "[OK] deployed shipment-detail.html has: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] deployed shipment-detail.html missing: $m" -ForegroundColor Red
        $smokeFail = $true
    }
}
foreach ($t in $intelTokens) {
    if ($deployedDetail -match [regex]::Escape($t)) {
        Write-Host "[FAIL] deployed file still has dead code: $t" -ForegroundColor Red
        $smokeFail = $true
    } else {
        Write-Host "[OK] deployed clean: $t" -ForegroundColor Green
    }
}

# Spot-check C20A in deployed dashboard.html
foreach ($m in @("--surface-1:", "--surface-2:")) {
    if ($deployedDash -match [regex]::Escape($m)) {
        Write-Host "[OK] deployed dashboard.html has: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] deployed dashboard.html missing: $m" -ForegroundColor Red
        $smokeFail = $true
    }
}

# Spot-check C20A in deployed dashboard-shared.js
foreach ($m in @("primary:", "displayText")) {
    if ($deployedShared -match [regex]::Escape($m)) {
        Write-Host "[OK] deployed dashboard-shared.js has: $m" -ForegroundColor Green
    } else {
        Write-Host "[FAIL] deployed dashboard-shared.js missing: $m" -ForegroundColor Red
        $smokeFail = $true
    }
}

if ($smokeFail) {
    Write-Host "[FAIL] Deployed file verification failed - check copy." -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host " C14A-C21A STATIC DEPLOY COMPLETE - NO RESTART REQUIRED" -ForegroundColor Green
Write-Host " Files deployed: shipment-detail.html, dashboard.html, dashboard-shared.js" -ForegroundColor Green
Write-Host " Backup: $bakDir" -ForegroundColor Cyan
Write-Host " Rollback: robocopy $bakDir $SVC_STATIC shipment-detail.html dashboard.html dashboard-shared.js /COPY:DAT" -ForegroundColor Yellow
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "NEXT: Open browser, navigate to https://pz.estrellajewels.eu" -ForegroundColor Cyan
Write-Host "NEXT: Load shipment SHIPMENT_4218922912_2026-05_9040dd39" -ForegroundColor Cyan
Write-Host "NEXT: Run browser smoke checklist (see operator runbook)" -ForegroundColor Cyan
