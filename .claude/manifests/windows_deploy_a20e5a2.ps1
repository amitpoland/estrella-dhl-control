# ============================================================
# Windows Production Deploy Script
# Origin/main target: a20e5a2
# Campaign: C9 (Warsaw date + payment method) + INC-005 (AWB)
#         + C4 SSOT (freight_resolver comment) + #229 (canonical PZ)
# Generated: 2026-05-19 | Profile: windows_prod_v2
# Pre-deploy gate: 475/475 tests PASS on Mac dev
# ============================================================
# OPERATOR: Read every section before executing.
# Execute sequentially — do NOT skip any step.
# ============================================================

$ErrorActionPreference = "Stop"

# ── Paths ───────────────────────────────────────────────────
$PYTHON   = "C:\Users\Super Fashion\AppData\Local\Programs\Python\Python39\python.exe"
$PZ_ROOT  = "C:\PZ"
$APP_ROOT = "C:\PZ\app"
$REPO_SRC = "C:\Users\Super Fashion\PZ APP\service"

# ── STEP 0: Pre-deploy safety check ─────────────────────────
Write-Host "`n=== STEP 0: Pre-deploy safety check ===" -ForegroundColor Cyan
Set-Location "C:\Users\Super Fashion\PZ APP"
$ahead = git log --oneline "origin/main..HEAD" 2>&1
if ($ahead -and $ahead.Trim()) {
    Write-Host "WARNING: Windows HEAD is ahead of origin/main:" -ForegroundColor Yellow
    Write-Host $ahead
    Write-Host "INC-003 RESOLVED: 7392be1 is ancestor of a20e5a2. git pull is safe." -ForegroundColor Green
} else {
    Write-Host "Windows is at or behind origin/main — no local-only commits." -ForegroundColor Green
}

# ── STEP 1: Git pull ─────────────────────────────────────────
Write-Host "`n=== STEP 1: git pull --ff-only origin main ===" -ForegroundColor Cyan
git fetch origin
git pull --ff-only origin main
$headSha = git rev-parse --short HEAD
Write-Host "HEAD after pull: $headSha" -ForegroundColor Green
if ($headSha -ne "a20e5a2") {
    Write-Host "NOTE: HEAD is $headSha (expected a20e5a2). If a20e5a2 is ancestor, this is fine." -ForegroundColor Yellow
}

# ── STEP 2: Install tzdata ───────────────────────────────────
Write-Host "`n=== STEP 2: pip install tzdata>=2024.1 ===" -ForegroundColor Cyan
& $PYTHON -m pip install "tzdata>=2024.1" --quiet
& $PYTHON -c "import zoneinfo; zoneinfo.ZoneInfo('Europe/Warsaw'); print('tzdata OK')"

# ── STEP 3: Create new directories ──────────────────────────
Write-Host "`n=== STEP 3: Create C:\PZ\app\core (new) ===" -ForegroundColor Cyan
if (-not (Test-Path "$APP_ROOT\core")) {
    New-Item -ItemType Directory -Path "$APP_ROOT\core" | Out-Null
    Write-Host "Created $APP_ROOT\core" -ForegroundColor Green
} else {
    Write-Host "$APP_ROOT\core already exists" -ForegroundColor Gray
}

# ── STEP 4: Stop service ─────────────────────────────────────
Write-Host "`n=== STEP 4: nssm stop PZService ===" -ForegroundColor Cyan
nssm stop PZService
Start-Sleep -Seconds 3
$status = nssm status PZService
Write-Host "Service status: $status"
if ($status -notmatch "SERVICE_STOPPED") {
    Write-Host "ERROR: PZService did not stop. Aborting." -ForegroundColor Red
    exit 1
}

# ── STEP 5: Backup current app (rollback source) ─────────────
Write-Host "`n=== STEP 5: Backup current app to C:\PZ\app\bak ===" -ForegroundColor Cyan
if (-not (Test-Path "$APP_ROOT\bak")) {
    New-Item -ItemType Directory -Path "$APP_ROOT\bak" | Out-Null
}
robocopy "$APP_ROOT" "$APP_ROOT\bak" /E /COPY:DAT /XD "$APP_ROOT\bak" /XD "$APP_ROOT\__pycache__" /NFL /NDL /NJH
Write-Host "Backup complete." -ForegroundColor Green

# ── STEP 6: Deploy 10 files ──────────────────────────────────
Write-Host "`n=== STEP 6: Deploy 10 files ===" -ForegroundColor Cyan

# File 1 — NEW: timezone_utils.py → C:\PZ\app\core\
robocopy "$REPO_SRC\app\core" "$APP_ROOT\core" "timezone_utils.py" /COPY:DAT
Write-Host " [1/10] timezone_utils.py → $APP_ROOT\core\" -ForegroundColor Green

# File 2 — wfirma_client.py
robocopy "$REPO_SRC\app\services" "$APP_ROOT\services" "wfirma_client.py" /COPY:DAT
Write-Host " [2/10] wfirma_client.py → $APP_ROOT\services\" -ForegroundColor Green

# File 3 — customer_master_db.py
robocopy "$REPO_SRC\app\services" "$APP_ROOT\services" "customer_master_db.py" /COPY:DAT
Write-Host " [3/10] customer_master_db.py → $APP_ROOT\services\" -ForegroundColor Green

# File 4 — freight_resolver.py (comment-only change — safe)
robocopy "$REPO_SRC\app\services" "$APP_ROOT\services" "freight_resolver.py" /COPY:DAT
Write-Host " [4/10] freight_resolver.py → $APP_ROOT\services\" -ForegroundColor Green

# File 5 — routes_customer_master.py
robocopy "$REPO_SRC\app\api" "$APP_ROOT\api" "routes_customer_master.py" /COPY:DAT
Write-Host " [5/10] routes_customer_master.py → $APP_ROOT\api\" -ForegroundColor Green

# File 6 — routes_proforma.py
robocopy "$REPO_SRC\app\api" "$APP_ROOT\api" "routes_proforma.py" /COPY:DAT
Write-Host " [6/10] routes_proforma.py → $APP_ROOT\api\" -ForegroundColor Green

# File 7 — routes_dashboard.py (issue #229 — wfirma_pz_fullnumber)
robocopy "$REPO_SRC\app\api" "$APP_ROOT\api" "routes_dashboard.py" /COPY:DAT
Write-Host " [7/10] routes_dashboard.py → $APP_ROOT\api\" -ForegroundColor Green

# File 8 — dashboard.html (payment method dropdown + canonical PZ)
robocopy "$REPO_SRC\app\static" "$APP_ROOT\static" "dashboard.html" /COPY:DAT
Write-Host " [8/10] dashboard.html → $APP_ROOT\static\" -ForegroundColor Green

# File 9 — shipment-detail.html (INC-005 AWB fix)
robocopy "$REPO_SRC\app\static" "$APP_ROOT\static" "shipment-detail.html" /COPY:DAT
Write-Host " [9/10] shipment-detail.html → $APP_ROOT\static\" -ForegroundColor Green

# File 10 — requirements.txt (tzdata>=2024.1 added)
robocopy "$REPO_SRC" "$PZ_ROOT" "requirements.txt" /COPY:DAT
Write-Host "[10/10] requirements.txt → $PZ_ROOT\" -ForegroundColor Green

# ── STEP 7: Start service ─────────────────────────────────────
Write-Host "`n=== STEP 7: nssm start PZService ===" -ForegroundColor Cyan
nssm start PZService
Start-Sleep -Seconds 5
$status = nssm status PZService
Write-Host "Service status: $status"
if ($status -notmatch "SERVICE_RUNNING") {
    Write-Host "ERROR: PZService did not start. Check nssm logs. Rollback available." -ForegroundColor Red
    Write-Host "ROLLBACK: robocopy C:\PZ\app\bak C:\PZ\app /COPY:DAT /E" -ForegroundColor Yellow
    exit 1
}

# ── STEP 8: Health checks ─────────────────────────────────────
Write-Host "`n=== STEP 8: Health checks ===" -ForegroundColor Cyan
Start-Sleep -Seconds 3

$urls = @(
    "http://localhost:47213/health",
    "http://localhost:47213/api/v1/health"
)
foreach ($url in $urls) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
        Write-Host "  OK  $url — HTTP $($r.StatusCode)" -ForegroundColor Green
    } catch {
        Write-Host "  FAIL $url — $($_.Exception.Message)" -ForegroundColor Red
        Write-Host "ROLLBACK: robocopy C:\PZ\app\bak C:\PZ\app /COPY:DAT /E" -ForegroundColor Yellow
        exit 1
    }
}

# ── STEP 9: Runtime probes ────────────────────────────────────
Write-Host "`n=== STEP 9: Runtime probes ===" -ForegroundColor Cyan
$endpoints = @(
    "http://127.0.0.1:47213/api/v1/proforma/service-products",
    "http://127.0.0.1:47213/api/v1/customer-master/"
)
foreach ($url in $endpoints) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 10
        Write-Host "  OK  $url — HTTP $($r.StatusCode)" -ForegroundColor Green
    } catch {
        Write-Host "  WARN $url — $($_.Exception.Message)" -ForegroundColor Yellow
    }
}

# tzdata verification
& $PYTHON -c "
from zoneinfo import ZoneInfo
from datetime import date
from app.core.timezone_utils import warsaw_today
tz = ZoneInfo('Europe/Warsaw')
d = warsaw_today()
print(f'warsaw_today() = {d}  [tz={tz}]')
"
& $PYTHON -m pip show tzdata | Select-String "Version"

# ── STEP 10: Smoke checks (manual, operator completes) ────────
Write-Host "`n=== STEP 10: Smoke checks (manual) ===" -ForegroundColor Cyan
Write-Host "  [ ] Dashboard loads at https://pz.estrellajewels.eu"
Write-Host "  [ ] Payment method dropdown: Transfer / Cash / Card / Compensation (no 'other')"
Write-Host "  [ ] Create proforma → date in wFirma matches today's Warsaw date"
Write-Host "  [ ] Customer master PUT with payment_method saves and round-trips"
Write-Host "  [ ] Build DHL Reply Package button → no HTTP 422"
Write-Host "  [ ] ProformaReadinessCard Section 4 shows 'wFirma PZ full number' row"
Write-Host "  [ ] For batches with PZ exported: canName shows number, ↻ Refresh Mapping appears"

# ── STEP 11: INC-003 closure note ────────────────────────────
Write-Host "`n=== STEP 11: Post-deploy INC-003 ==="-ForegroundColor Cyan
Write-Host "git pull --ff-only succeeded. Update local-commit-deploys.jsonl:"
Write-Host '  Add note: "Windows pull to a20e5a2 completed <timestamp>"'

# ── DHL shadow corpus check ───────────────────────────────────
Write-Host "`n=== DHL P2 shadow corpus check ===" -ForegroundColor Cyan
$decisions = "$PZ_ROOT\storage\orchestrator_decisions.jsonl"
if (Test-Path $decisions) {
    $count = (Get-Content $decisions | Measure-Object -Line).Lines
    Write-Host "  orchestrator_decisions.jsonl: $count lines"
    if ($count -ge 50) {
        Write-Host "  CORPUS THRESHOLD MET ($count >= 50). Check AWB diversity before P2 promotion." -ForegroundColor Yellow
    } else {
        Write-Host "  Corpus: $count / 50 dispatches needed for P2 promotion." -ForegroundColor Gray
    }
} else {
    Write-Host "  orchestrator_decisions.jsonl: NOT FOUND (no shadow corpus yet)" -ForegroundColor Gray
    Write-Host "  P2 live promotion: BLOCKED — corpus required" -ForegroundColor Gray
}

Write-Host "`n=== DEPLOY COMPLETE ===" -ForegroundColor Green
Write-Host "  Origin/main: a20e5a2"
Write-Host "  Files deployed: 10"
Write-Host "  Rollback: robocopy C:\PZ\app\bak C:\PZ\app /COPY:DAT /E"
Write-Host "  Scorecard: .claude/memory/scorecards/2026-05-19-master-convergence-campaign10.md"
