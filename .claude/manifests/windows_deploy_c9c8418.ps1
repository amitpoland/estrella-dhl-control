# ============================================================
# Windows Production Deploy Script
# SHA: c9c8418 (main HEAD 2026-05-24 -- Phase 8 Sprint 1 Intelligence Graph)
# Previous production SHA: cbb23ef (Phase 7.1 Search Coverage Wiring, deployed 2026-05-24)
#
# PR #331 -- feat(phase8-sprint1): batch_id-centered intelligence graph resolver
#
# Files deployed (1 new runtime file, within service/app/**):
#
#   [1] NEW  service/app/services/intelligence_graph.py
#       -> C:\PZ\app\services\intelligence_graph.py
#       Phase 8 Sprint 1: four read-only graph builders.
#       build_awb_graph(), build_batch_graph(),
#       build_customer_graph(), build_invoice_graph().
#       All return GraphResult. llm_used=False hardcoded.
#       All DB connections via _ro_conn() + PRAGMA query_only = ON.
#       No HTTP calls. No DB writes. Conflict exposure only.
#
# Note: No new route registered in main.py yet (route added Sprint 2).
# PZService restart: REQUIRED (new module -- avoid stale runtime).
# Standard robocopy: YES -- file within service/app/**
# Lesson J: COMPLIANT -- no engine-level root files
# Manifest encoding: ASCII-only -- no em-dashes, no smart quotes (HARD RULE)
# ============================================================

# --- Pre-flight ---
Write-Host "=== Phase 8 Sprint 1 Intelligence Graph Deploy -- SHA c9c8418 ===" -ForegroundColor Cyan
Write-Host "Previous production SHA: cbb23ef (Phase 7.1 Search Coverage Wiring)"
Write-Host ""

# Verify local repo state
cd "C:\Users\Super Fashion\PZ APP"
$currentSHA = git rev-parse HEAD 2>&1
Write-Host "Local HEAD before pull: $currentSHA"

# Pull to c9c8418 (or later if further commits on main)
git pull --ff-only origin main
$pulledSHA = git rev-parse HEAD 2>&1
Write-Host "After pull: $pulledSHA"
if ($pulledSHA -notmatch "c9c8418") {
    Write-Host "INFO: HEAD is $pulledSHA (may be a later commit layered on c9c8418 -- verify sprint 1 file present)" -ForegroundColor Yellow
}

# --- Sync service/app -> C:\PZ\app ---
Write-Host ""
Write-Host "=== robocopy sync ===" -ForegroundColor Cyan
robocopy "C:\Users\Super Fashion\PZ APP\service\app" "C:\PZ\app" /E /XO `
  /XD __pycache__ .pytest_cache `
  /XF "*.pyc" "*.pyo" "*.zip"

$rc = $LASTEXITCODE
if ($rc -ge 4) {
    Write-Host "ERROR: robocopy exit code $rc -- STOP. Do not restart service." -ForegroundColor Red
    exit 1
}
Write-Host "robocopy exit: $rc (0-3 = success)" -ForegroundColor Green

# --- Verify key file landed ---
Write-Host ""
Write-Host "=== File verification ===" -ForegroundColor Cyan
$igPath = "C:\PZ\app\services\intelligence_graph.py"
if (Test-Path $igPath) {
    $sz = (Get-Item $igPath).Length
    Write-Host "OK  $igPath ($sz bytes)"
} else {
    Write-Host "MISSING  $igPath" -ForegroundColor Red
    exit 1
}

# Spot-check: confirm build_awb_graph deployed
$igContent = Get-Content $igPath -Raw
if ($igContent -match "def build_awb_graph") {
    Write-Host "OK  build_awb_graph() confirmed in deployed intelligence_graph"
} else {
    Write-Host "FAIL: build_awb_graph() NOT found -- Sprint 1 not deployed" -ForegroundColor Red
}

# Spot-check: confirm build_batch_graph deployed
if ($igContent -match "def build_batch_graph") {
    Write-Host "OK  build_batch_graph() confirmed"
} else {
    Write-Host "FAIL: build_batch_graph() NOT found" -ForegroundColor Red
}

# Spot-check: confirm build_customer_graph deployed
if ($igContent -match "def build_customer_graph") {
    Write-Host "OK  build_customer_graph() confirmed"
} else {
    Write-Host "FAIL: build_customer_graph() NOT found" -ForegroundColor Red
}

# Spot-check: confirm build_invoice_graph deployed
if ($igContent -match "def build_invoice_graph") {
    Write-Host "OK  build_invoice_graph() confirmed"
} else {
    Write-Host "FAIL: build_invoice_graph() NOT found" -ForegroundColor Red
}

# Spot-check: confirm llm_used=False hardcoded
if ($igContent -match "llm_used=False") {
    Write-Host "OK  llm_used=False confirmed in deployed intelligence_graph"
} else {
    Write-Host "FAIL: llm_used=False NOT found" -ForegroundColor Red
}

# Spot-check: confirm PRAGMA query_only
if ($igContent -match "PRAGMA query_only") {
    Write-Host "OK  PRAGMA query_only = ON confirmed"
} else {
    Write-Host "FAIL: PRAGMA query_only NOT found" -ForegroundColor Red
}

# Spot-check: confirm GraphResult dataclass
if ($igContent -match "class GraphResult") {
    Write-Host "OK  GraphResult dataclass confirmed"
} else {
    Write-Host "FAIL: GraphResult NOT found" -ForegroundColor Red
}

# --- Restart PZService ---
Write-Host ""
Write-Host "=== PZService restart ===" -ForegroundColor Cyan
sc.exe stop PZService
$tries = 0
while ((Get-Service PZService).Status -ne 'Stopped' -and $tries -lt 15) {
    Start-Sleep -Seconds 1; $tries++
}
Write-Host "Service stopped after $tries s"

sc.exe start PZService
Start-Sleep -Seconds 10
sc.exe query PZService

# --- Health check ---
Write-Host ""
Write-Host "=== Health checks ===" -ForegroundColor Cyan
$local = Invoke-WebRequest http://127.0.0.1:47213/api/v1/health -UseBasicParsing
Write-Host "Local health: $($local.StatusCode)"

$public = Invoke-WebRequest https://pz.estrellajewels.eu/api/v1/health -UseBasicParsing
Write-Host "Public health: $($public.StatusCode)"

# --- Python import smoke test ---
# Verifies the module is importable, all four builders are callable symbols,
# and the llm_used structural invariant is correct.
Write-Host ""
Write-Host "=== Python import smoke test ===" -ForegroundColor Cyan
$smokeScript = @"
import sys
sys.path.insert(0, r'C:\PZ\app')
try:
    from services.intelligence_graph import (
        build_awb_graph,
        build_batch_graph,
        build_customer_graph,
        build_invoice_graph,
        GraphResult,
        LinkCompleteness,
        AttributedValue,
    )
    import inspect
    for fn in [build_awb_graph, build_batch_graph, build_customer_graph, build_invoice_graph]:
        src = inspect.getsource(fn)
        assert 'llm_used=False' in src or 'llm_used = False' in src, f'{fn.__name__} missing llm_used=False'
        print(f'OK  {fn.__name__} callable + llm_used=False confirmed')
    print('OK  intelligence_graph import smoke PASS')
except Exception as e:
    print(f'FAIL: {e}')
    sys.exit(1)
"@

$smokeScript | python3 -
if ($LASTEXITCODE -ne 0) {
    Write-Host "FAIL: Python import smoke failed -- check PZService logs" -ForegroundColor Red
} else {
    Write-Host "OK  Python import smoke PASS" -ForegroundColor Green
}

# --- Search regression (Phase 7.1 confirm still live) ---
Write-Host ""
Write-Host "=== Phase 7.1 regression check ===" -ForegroundColor Cyan
$apiKey = (Get-Content "C:\PZ\.env" | Where-Object { $_ -match "^API_KEY=" } | ForEach-Object { $_.Split("=", 2)[1] })
$searchResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/search?q=test" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "Search q=test: $($searchResp.StatusCode)"
$searchJson = $searchResp.Content | ConvertFrom-Json
Write-Host "  llm_used: $($searchJson.llm_used)"
Write-Host "  domains_searched: $($searchJson.domains_searched -join ', ')"
Write-Host "  total: $($searchJson.total)"

# Confirm shipment domain still present (Phase 7.1 regression)
if ($searchJson.domains_searched -contains "shipment") {
    Write-Host "OK  shipment domain present in search (Phase 7.1 regression PASS)"
} else {
    Write-Host "WARN: shipment domain not in domains_searched -- Phase 7.1 regression check" -ForegroundColor Yellow
}

# --- Stderr tail ---
Write-Host ""
Write-Host "=== Last 20 lines of stderr log ===" -ForegroundColor Cyan
Get-Content C:\PZ\logs\pz_stderr.log -Tail 20

Write-Host ""
Write-Host "=== Deploy complete ===" -ForegroundColor Green
Write-Host "SHA deployed: c9c8418 (Phase 8 Sprint 1 -- intelligence_graph.py)"
Write-Host "Next: Phase 8 Sprint 2 (routes_intelligence_graph.py -- GET /api/v1/intelligence/graph)"
Write-Host "Rollback: git revert c9c8418 --no-edit + robocopy + sc.exe restart"
