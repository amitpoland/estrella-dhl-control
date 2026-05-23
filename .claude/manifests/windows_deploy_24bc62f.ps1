# ============================================================
# Windows Production Deploy Script
# SHA: 24bc62f (main HEAD 2026-05-24 -- Phase 8 Sprint 2 Intelligence Graph Route)
# Previous production SHA: cbb23ef (Phase 7.1 Search Coverage Wiring, deployed 2026-05-24)
# Sprint 1 SHA (pending deploy): c9c8418 (intelligence_graph.py -- manifest at windows_deploy_c9c8418.ps1)
#
# PR #335 -- feat(phase8-sprint2): GET /api/v1/intelligence/graph route with anchor-based dispatch
#
# DEPLOY ORDER REQUIREMENT:
#   Sprint 1 (c9c8418) MUST be deployed FIRST via windows_deploy_c9c8418.ps1
#   Sprint 2 (24bc62f) deploys AFTER Sprint 1 is confirmed running.
#   Standard robocopy covers both in a single pass -- just pull to main HEAD.
#
# Files deployed (3 modified runtime files, all within service/app/**):
#
#   [1] MODIFIED  service/app/services/intelligence_graph.py
#       -> C:\PZ\app\services\intelligence_graph.py
#       Phase 8 Sprint 2 addition: to_dict() method on GraphResult.
#       Serialises attributed values, link_completeness, conflict_keys.
#       No logic changes to builders.
#
#   [2] NEW  service/app/api/routes_intelligence_graph.py
#       -> C:\PZ\app\api\routes_intelligence_graph.py
#       GET /api/v1/intelligence/graph. Auth: X-API-Key.
#       anchor / anchor_type / builder params.
#       Read-only resolvers with PRAGMA query_only = ON.
#       422 on invalid params. 404 on unresolved non-batch anchor.
#       llm_used=False structural invariant.
#
#   [3] MODIFIED  service/app\main.py
#       -> C:\PZ\app\main.py
#       Import + include_router for intelligence_graph_router.
#
# PZService restart: REQUIRED (main.py changed)
# Standard robocopy: YES -- all files within service/app/**
# Lesson J: COMPLIANT -- no engine-level root files
# Manifest encoding: ASCII-only -- no em-dashes, no smart quotes (HARD RULE)
# ============================================================

# --- Pre-flight ---
Write-Host "=== Phase 8 Sprint 2 Intelligence Graph Route Deploy -- SHA 24bc62f ===" -ForegroundColor Cyan
Write-Host "Previous production SHA: cbb23ef (Phase 7.1)"
Write-Host "Sprint 1 required first: windows_deploy_c9c8418.ps1 (intelligence_graph.py)"
Write-Host ""

# Verify local repo state
cd "C:\Users\Super Fashion\PZ APP"
$currentSHA = git rev-parse HEAD 2>&1
Write-Host "Local HEAD before pull: $currentSHA"

# Pull to 24bc62f (or later)
git pull --ff-only origin main
$pulledSHA = git rev-parse HEAD 2>&1
Write-Host "After pull: $pulledSHA"
if ($pulledSHA -notmatch "24bc62f") {
    Write-Host "INFO: HEAD is $pulledSHA (may be a later commit layered on 24bc62f -- verify sprint 2 files present)" -ForegroundColor Yellow
}

# Safety gate: confirm Sprint 1 was already deployed (check intelligence_graph.py exists)
if (-not (Test-Path "C:\PZ\app\services\intelligence_graph.py")) {
    Write-Host "STOP: Sprint 1 not deployed -- C:\PZ\app\services\intelligence_graph.py missing." -ForegroundColor Red
    Write-Host "      Run windows_deploy_c9c8418.ps1 first, then re-run this script." -ForegroundColor Red
    exit 1
}
Write-Host "OK  Sprint 1 prerequisite: intelligence_graph.py present in production"

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
    "C:\PZ\app\services\intelligence_graph.py",
    "C:\PZ\app\api\routes_intelligence_graph.py",
    "C:\PZ\app\main.py"
)
foreach ($f in $files) {
    if (Test-Path $f) {
        $sz = (Get-Item $f).Length
        Write-Host "OK  $f ($sz bytes)"
    } else {
        Write-Host "MISSING  $f" -ForegroundColor Red
    }
}

# Spot-check: confirm to_dict in intelligence_graph
$igContent = Get-Content "C:\PZ\app\services\intelligence_graph.py" -Raw
if ($igContent -match "def to_dict") {
    Write-Host "OK  to_dict() confirmed in deployed intelligence_graph"
} else {
    Write-Host "FAIL: to_dict() NOT found -- Sprint 2 not deployed" -ForegroundColor Red
}

# Spot-check: confirm route file
$routeContent = Get-Content "C:\PZ\app\api\routes_intelligence_graph.py" -Raw
if ($routeContent -match '"/graph"') {
    Write-Host "OK  /graph route confirmed in deployed routes_intelligence_graph"
} else {
    Write-Host "FAIL: /graph route NOT found in deployed routes" -ForegroundColor Red
}

# Spot-check: confirm anchor_type param in route
if ($routeContent -match "anchor_type") {
    Write-Host "OK  anchor_type param confirmed in deployed route"
} else {
    Write-Host "FAIL: anchor_type NOT found" -ForegroundColor Red
}

# Spot-check: confirm llm_used=False in route
if ($routeContent -match "llm_used=False") {
    Write-Host "OK  llm_used=False confirmed in deployed route"
} else {
    Write-Host "WARN: llm_used=False not in route file (check service layer)" -ForegroundColor Yellow
}

# Spot-check: confirm PRAGMA query_only in route
if ($routeContent -match "PRAGMA query_only") {
    Write-Host "OK  PRAGMA query_only = ON confirmed in deployed route"
} else {
    Write-Host "FAIL: PRAGMA query_only NOT found in route" -ForegroundColor Red
}

# Spot-check: confirm intelligence_graph_router in main.py
$mainContent = Get-Content "C:\PZ\app\main.py" -Raw
if ($mainContent -match "intelligence_graph_router") {
    Write-Host "OK  intelligence_graph_router confirmed in deployed main.py"
} else {
    Write-Host "FAIL: intelligence_graph_router NOT found in main.py" -ForegroundColor Red
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

# --- Intelligence graph smoke tests ---
Write-Host ""
Write-Host "=== Intelligence graph smoke tests ===" -ForegroundColor Cyan

# Phase 8 Sprint 2: batch anchor + batch builder (default)
$graphResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/intelligence/graph?anchor=SMOKE-TEST-BATCH" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /intelligence/graph?anchor=SMOKE-TEST-BATCH: $($graphResp.StatusCode) (expected 200)"
if ($graphResp.StatusCode -eq 200) {
    $graphJson = $graphResp.Content | ConvertFrom-Json
    Write-Host "  llm_used: $($graphJson.llm_used) (expected false)"
    Write-Host "  batch_id: $($graphJson.batch_id)"
    Write-Host "  builder: $($graphJson.builder)"
    Write-Host "  conflict_keys: $($graphJson.conflict_keys)"
}

# Phase 8 Sprint 2: batch anchor + awb builder
$awbBuilderResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/intelligence/graph?anchor=SMOKE-TEST&builder=awb" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /intelligence/graph?anchor=SMOKE-TEST&builder=awb: $($awbBuilderResp.StatusCode) (expected 200)"

# Phase 8 Sprint 2: invalid anchor_type -> 422
try {
    $badResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/intelligence/graph?anchor=X&anchor_type=invalid" `
        -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing -ErrorAction Stop
    Write-Host "FAIL: invalid anchor_type should 422 but got $($badResp.StatusCode)" -ForegroundColor Red
} catch {
    Write-Host "OK  Invalid anchor_type -> 422 as expected"
}

# Phase 8 Sprint 2: awb anchor not found -> 404
try {
    $notFoundResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/intelligence/graph?anchor=0000000000&anchor_type=awb" `
        -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing -ErrorAction Stop
    Write-Host "FAIL: unknown AWB anchor should 404 but got $($notFoundResp.StatusCode)" -ForegroundColor Red
} catch {
    Write-Host "OK  Unknown AWB anchor -> 404 as expected"
}

# Phase 7.1 regression: search still working
$searchResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/search?q=test" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "Search q=test: $($searchResp.StatusCode) (Phase 7.1 regression)"
$searchJson = $searchResp.Content | ConvertFrom-Json
Write-Host "  llm_used: $($searchJson.llm_used)"
Write-Host "  domains_searched: $($searchJson.domains_searched -join ', ')"

# --- Stderr tail ---
Write-Host ""
Write-Host "=== Last 20 lines of stderr log ===" -ForegroundColor Cyan
Get-Content C:\PZ\logs\pz_stderr.log -Tail 20

Write-Host ""
Write-Host "=== Deploy complete ===" -ForegroundColor Green
Write-Host "SHA deployed: 24bc62f (Phase 8 Sprint 2 -- GET /api/v1/intelligence/graph)"
Write-Host "Next: Phase 8 Sprint 3 (graph domain in MDI)"
Write-Host "Rollback: git revert 24bc62f --no-edit + robocopy + sc.exe restart"
