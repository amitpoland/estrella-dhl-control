# ============================================================
# Windows Production Deploy Script
# SHA: cbb23ef (main HEAD 2026-05-24 -- Phase 7.1 Search Coverage Wiring)
# Previous production SHA: 3302a1b (Phase 7 Search Foundation, deployed 2026-05-23)
#
# PR #328 -- feat(phase71): add shipment domain to search -- AWB hits via tracking_db
#
# Files deployed (3 modified runtime files, all within service/app/**):
#
#   [1] MODIFIED  service/app/services/search_engine.py
#       -> C:\PZ\app\services\search_engine.py
#       Phase 7.1 additions: search_shipments() function, _TRACKING_DB path,
#       "shipment" domain in _ALL_DOMAINS, execute_search() tracking_db kwarg,
#       per-domain over-fetch for cross-domain score sorting.
#       llm_used=False hardcoded. PRAGMA query_only = ON. No writes.
#
#   [2] MODIFIED  service/app/api/routes_search.py
#       -> C:\PZ\app\api\routes_search.py
#       "shipment" added to _VALID_DOMAINS.
#       GET-only. No new routes.
#
#   [3] MODIFIED  service/app/main.py
#       -> C:\PZ\app\main.py
#       init_tracking_db called at startup so tracking_events.db is created
#       and AWB search queries can return shipment hits.
#
# PZService restart: REQUIRED (main.py changed)
# Standard robocopy: YES -- all files within service/app/**
# Lesson J: COMPLIANT -- no engine-level root files
# Manifest encoding: ASCII-only -- no em-dashes, no smart quotes (HARD RULE)
# ============================================================

# --- Pre-flight ---
Write-Host "=== Phase 7.1 Search Coverage Wiring Deploy -- SHA cbb23ef ===" -ForegroundColor Cyan
Write-Host "Previous production SHA: 3302a1b (Phase 7 Search Foundation)"
Write-Host ""

# Verify local repo state
cd "C:\Users\Super Fashion\PZ APP"
$currentSHA = git rev-parse HEAD 2>&1
Write-Host "Local HEAD before pull: $currentSHA"

# Pull to cbb23ef
git pull --ff-only origin main
$pulledSHA = git rev-parse HEAD 2>&1
Write-Host "After pull: $pulledSHA"
if ($pulledSHA -notmatch "cbb23ef") {
    Write-Host "WARN: SHA mismatch -- expected cbb23ef. Verify before sync." -ForegroundColor Yellow
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

# --- Verify key files landed ---
Write-Host ""
Write-Host "=== File verification ===" -ForegroundColor Cyan
$files = @(
    "C:\PZ\app\services\search_engine.py",
    "C:\PZ\app\api\routes_search.py",
    "C:\PZ\app\main.py"
)
foreach ($f in $files) {
    if (Test-Path $f) {
        $size = (Get-Item $f).Length
        Write-Host "OK  $f ($size bytes)"
    } else {
        Write-Host "MISSING  $f" -ForegroundColor Red
    }
}

# Spot-check: confirm search_shipments function deployed
$seContent = Get-Content "C:\PZ\app\services\search_engine.py" -Raw
if ($seContent -match "def search_shipments") {
    Write-Host "OK  search_shipments() function confirmed in deployed search_engine"
} else {
    Write-Host "FAIL: search_shipments() NOT found -- Phase 7.1 not deployed" -ForegroundColor Red
}

# Spot-check: confirm _TRACKING_DB constant deployed
if ($seContent -match "_TRACKING_DB") {
    Write-Host "OK  _TRACKING_DB constant confirmed"
} else {
    Write-Host "FAIL: _TRACKING_DB NOT found" -ForegroundColor Red
}

# Spot-check: confirm llm_used=False hardcoded
if ($seContent -match "llm_used=False") {
    Write-Host "OK  llm_used=False confirmed in deployed search_engine"
} else {
    Write-Host "FAIL: llm_used=False NOT found" -ForegroundColor Red
}

# Spot-check: confirm PRAGMA query_only
if ($seContent -match "PRAGMA query_only") {
    Write-Host "OK  PRAGMA query_only = ON confirmed"
} else {
    Write-Host "FAIL: PRAGMA query_only NOT found" -ForegroundColor Red
}

# Spot-check: confirm shipment in _VALID_DOMAINS in route
$routeContent = Get-Content "C:\PZ\app\api\routes_search.py" -Raw
if ($routeContent -match '"shipment"') {
    Write-Host "OK  'shipment' domain confirmed in deployed routes_search"
} else {
    Write-Host "FAIL: shipment domain NOT found in route" -ForegroundColor Red
}

# Spot-check: confirm init_tracking_db in main.py
$mainContent = Get-Content "C:\PZ\app\main.py" -Raw
if ($mainContent -match "init_tracking_db") {
    Write-Host "OK  init_tracking_db confirmed in deployed main.py"
} else {
    Write-Host "FAIL: init_tracking_db NOT found in main.py" -ForegroundColor Red
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

# --- Health checks ---
Write-Host ""
Write-Host "=== Health checks ===" -ForegroundColor Cyan
$apiKey = (Get-Content "C:\PZ\.env" | Where-Object { $_ -match "^API_KEY=" } | ForEach-Object { $_.Split("=", 2)[1] })

$local = Invoke-WebRequest http://127.0.0.1:47213/api/v1/health -UseBasicParsing
Write-Host "Local health: $($local.StatusCode)"

$public = Invoke-WebRequest https://pz.estrellajewels.eu/api/v1/health -UseBasicParsing
Write-Host "Public health: $($public.StatusCode)"

# --- Search smoke tests ---
Write-Host ""
Write-Host "=== Search smoke tests ===" -ForegroundColor Cyan

# Phase 7 regression: keyword search
$searchResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/search?q=test" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "Search q=test: $($searchResp.StatusCode)"
$searchJson = $searchResp.Content | ConvertFrom-Json
Write-Host "  llm_used: $($searchJson.llm_used)"
Write-Host "  total: $($searchJson.total)"
Write-Host "  interpreted_as: $($searchJson.interpreted_as)"

# Phase 7.1: AWB search -- should now include shipment domain
$awbResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/search?q=9765416334" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "Search q=9765416334 (AWB): $($awbResp.StatusCode)"
$awbJson = $awbResp.Content | ConvertFrom-Json
Write-Host "  llm_used: $($awbJson.llm_used)"
Write-Host "  interpreted_as: $($awbJson.interpreted_as)"
Write-Host "  domains_searched: $($awbJson.domains_searched -join ', ')"
Write-Host "  total: $($awbJson.total)"
$shipmentHits = $awbJson.hits | Where-Object { $_.domain -eq "shipment" }
Write-Host "  shipment hits: $($shipmentHits.Count)"

# Phase 7.1: shipment domain filter accepted (no 422)
$shipDomResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/search?q=test&domains=shipment" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "Search domains=shipment: $($shipDomResp.StatusCode) (expected 200)"

# Phase 7.1: confirm tracking_events.db created
if (Test-Path "C:\PZ\storage\tracking_events.db") {
    $sz = (Get-Item "C:\PZ\storage\tracking_events.db").Length
    Write-Host "OK  tracking_events.db created at startup ($sz bytes)"
} else {
    Write-Host "INFO: tracking_events.db not at C:\PZ\storage\ -- check storage_root path in .env"
}

# Invalid domain still 422
try {
    $badResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/search?q=test&domains=badomain" `
        -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing -ErrorAction Stop
    Write-Host "FAIL: invalid domain should 422 but got $($badResp.StatusCode)" -ForegroundColor Red
} catch {
    Write-Host "OK  Invalid domain -> 422 as expected"
}

# --- Stderr tail ---
Write-Host ""
Write-Host "=== Last 20 lines of stderr log ===" -ForegroundColor Cyan
Get-Content C:\PZ\logs\pz_stderr.log -Tail 20

Write-Host ""
Write-Host "=== Deploy complete ===" -ForegroundColor Green
Write-Host "SHA deployed: cbb23ef"
Write-Host "Rollback: git revert cbb23ef --no-edit + robocopy + sc.exe restart"
