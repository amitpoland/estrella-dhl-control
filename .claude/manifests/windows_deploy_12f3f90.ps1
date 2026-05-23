# ============================================================
# Windows Production Deploy Script
# SHA: 12f3f90 (main HEAD -- Phase 8 Sprint 4 Search Graph Enrichment)
# Previous production SHA: 6995f48 (Phase 8 Sprint 3 MDI Graph Domain)
#
# PR #339 -- feat(phase8-sprint4): enrich=true on GET /api/v1/search
#
# DEPLOY ORDER REQUIREMENT:
#   Sprint 1 (c9c8418) MUST be deployed FIRST via windows_deploy_c9c8418.ps1
#   Sprint 2 (24bc62f) MUST be deployed SECOND via windows_deploy_24bc62f.ps1
#   Sprint 3 (6995f48) MUST be deployed THIRD via windows_deploy_6995f48.ps1
#   Sprint 4 (12f3f90) deploys AFTER Sprint 3 is confirmed running.
#   Standard robocopy covers all four in a single pass -- just pull to main HEAD.
#
# Files deployed (2 modified runtime files, all within service/app/**):
#
#   [1] MODIFIED  service/app/services/search_engine.py
#       -> C:\PZ\app\services\search_engine.py
#       Added: SearchHit.graph_enrichment optional field
#       Updated: SearchResult.to_dict() -- includes graph_enrichment when not None
#       Updated: execute_search() -- enrich: bool = False kwarg
#       Added: _enrich_hits() -- enriches top hits from documents.db
#       Added: _resolve_batch_ids_for_hit() -- domain-aware batch_id lookup
#       Invariants: PRAGMA query_only=ON, no writes, llm_used=False
#
#   [2] MODIFIED  service/app/api/routes_search.py
#       -> C:\PZ\app\api\routes_search.py
#       Added: enrich: bool = Query(default=False) parameter
#       Passes enrich=enrich to execute_search()
#       GET /api/v1/search?enrich=true now adds graph_enrichment to each hit
#
# PZService restart: REQUIRED (Python source files changed)
# Standard robocopy: YES -- all files within service/app/**
# Lesson J: COMPLIANT -- no engine-level root files
# Manifest encoding: ASCII-only -- no em-dashes, no smart quotes (HARD RULE)
# ============================================================

# --- Pre-flight ---
Write-Host "=== Phase 8 Sprint 4 Search Enrich Deploy -- SHA 12f3f90 ===" -ForegroundColor Cyan
Write-Host "Previous production SHA: 6995f48 (Phase 8 Sprint 3)"
Write-Host ""

# Verify local repo state
cd "C:\Users\Super Fashion\PZ APP"
$currentSHA = git rev-parse HEAD 2>&1
Write-Host "Local HEAD before pull: $currentSHA"

# Safety gate: Sprint 1 prerequisite
if (-not (Test-Path "C:\PZ\app\services\intelligence_graph.py")) {
    Write-Host "STOP: Sprint 1 not deployed -- intelligence_graph.py missing." -ForegroundColor Red
    Write-Host "      Deploy order: c9c8418 -> 24bc62f -> 6995f48 -> 12f3f90" -ForegroundColor Red
    exit 1
}
Write-Host "OK  Sprint 1 prerequisite: intelligence_graph.py present"

# Safety gate: Sprint 2 prerequisite
if (-not (Test-Path "C:\PZ\app\api\routes_intelligence_graph.py")) {
    Write-Host "STOP: Sprint 2 not deployed -- routes_intelligence_graph.py missing." -ForegroundColor Red
    exit 1
}
Write-Host "OK  Sprint 2 prerequisite: routes_intelligence_graph.py present"

# Safety gate: Sprint 3 prerequisite -- confirm _score_graph in MDI
$mdiDeployed = Get-Content "C:\PZ\app\services\master_data_intelligence.py" -Raw -ErrorAction SilentlyContinue
if (-not $mdiDeployed -or $mdiDeployed -notmatch "def _score_graph") {
    Write-Host "STOP: Sprint 3 not deployed -- _score_graph() missing from master_data_intelligence.py." -ForegroundColor Red
    Write-Host "      Run windows_deploy_6995f48.ps1 first, then re-run this script." -ForegroundColor Red
    exit 1
}
Write-Host "OK  Sprint 3 prerequisite: _score_graph() present in master_data_intelligence.py"

# Pull to 12f3f90 (or later)
git pull --ff-only origin main
$pulledSHA = git rev-parse HEAD 2>&1
Write-Host "After pull: $pulledSHA"

# --- Sync service/app -> C:\PZ\app ---
Write-Host ""
Write-Host "=== robocopy sync ===" -ForegroundColor Cyan
robocopy "C:\Users\Super Fashion\PZ APP\service\app" "C:\PZ\app" /E /XO `
  /XD __pycache__ .pytest_cache `
  /XF "*.pyc" "*.pyo" "*.zip"

$rc = $LASTEXITCODE
if ($rc -ge 4) {
    Write-Host "ERROR: robocopy exit code $rc -- STOP." -ForegroundColor Red
    exit 1
}
Write-Host "robocopy exit: $rc (0-3 = success)" -ForegroundColor Green

# --- Verify key files landed ---
Write-Host ""
Write-Host "=== File verification ===" -ForegroundColor Cyan
$files = @(
    "C:\PZ\app\services\search_engine.py",
    "C:\PZ\app\api\routes_search.py"
)
foreach ($f in $files) {
    if (Test-Path $f) {
        $sz = (Get-Item $f).Length
        Write-Host "OK  $f ($sz bytes)"
    } else {
        Write-Host "MISSING  $f" -ForegroundColor Red
    }
}

# Spot-check: confirm _enrich_hits in search_engine
$searchContent = Get-Content "C:\PZ\app\services\search_engine.py" -Raw
if ($searchContent -match "def _enrich_hits") {
    Write-Host "OK  _enrich_hits() confirmed in deployed search_engine"
} else {
    Write-Host "FAIL: _enrich_hits() NOT found -- Sprint 4 not deployed" -ForegroundColor Red
}

# Spot-check: confirm graph_enrichment in search_engine
if ($searchContent -match "graph_enrichment") {
    Write-Host "OK  graph_enrichment field confirmed in deployed search_engine"
} else {
    Write-Host "FAIL: graph_enrichment NOT found in search_engine" -ForegroundColor Red
}

# Spot-check: confirm enrich param in routes_search
$routeContent = Get-Content "C:\PZ\app\api\routes_search.py" -Raw
if ($routeContent -match "enrich") {
    Write-Host "OK  enrich param confirmed in deployed routes_search"
} else {
    Write-Host "FAIL: enrich param NOT found in deployed routes_search" -ForegroundColor Red
}

# Spot-check: PRAGMA query_only in search_engine
if ($searchContent -match "PRAGMA query_only") {
    Write-Host "OK  PRAGMA query_only confirmed in deployed search_engine"
} else {
    Write-Host "FAIL: PRAGMA query_only NOT found" -ForegroundColor Red
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

# --- Sprint 4 smoke tests ---
Write-Host ""
Write-Host "=== Sprint 4 smoke tests ===" -ForegroundColor Cyan

# Default (enrich=false) -- no graph_enrichment key
$noEnrichResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/search?q=test" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /search?q=test (no enrich): $($noEnrichResp.StatusCode) (expected 200)"
if ($noEnrichResp.StatusCode -eq 200) {
    $noEnrichJson = $noEnrichResp.Content | ConvertFrom-Json
    Write-Host "  llm_used: $($noEnrichJson.llm_used) (expected false)"
    Write-Host "  hits: $($noEnrichJson.hits.Count)"
    if ($noEnrichJson.hits.Count -gt 0 -and $noEnrichJson.hits[0].graph_enrichment) {
        Write-Host "  WARN: graph_enrichment present without enrich=true" -ForegroundColor Yellow
    } else {
        Write-Host "  OK  no graph_enrichment key (correct default)"
    }
}

# enrich=true -- graph_enrichment present in hits
$enrichResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/search?q=test&enrich=true" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /search?q=test&enrich=true: $($enrichResp.StatusCode) (expected 200)"
if ($enrichResp.StatusCode -eq 200) {
    $enrichJson = $enrichResp.Content | ConvertFrom-Json
    Write-Host "  llm_used: $($enrichJson.llm_used) (expected false)"
    Write-Host "  hits: $($enrichJson.hits.Count)"
    if ($enrichJson.hits.Count -gt 0) {
        $firstHit = $enrichJson.hits[0]
        if ($firstHit.graph_enrichment) {
            Write-Host "  OK  graph_enrichment present in first hit"
            Write-Host "  graph_available: $($firstHit.graph_enrichment.graph_available)"
            Write-Host "  related_count: $($firstHit.graph_enrichment.related_count)"
        } else {
            Write-Host "  WARN: graph_enrichment missing from hit with enrich=true" -ForegroundColor Yellow
        }
    }
}

# Phase 8 Sprint 3 regression: MDI graph domain still works
$mdiGraphResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence/graph" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /master-data/intelligence/graph: $($mdiGraphResp.StatusCode) (Sprint 3 regression)"

# Phase 8 Sprint 2 regression: intelligence graph route still works
$igResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/intelligence/graph?anchor=SMOKE-TEST" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /intelligence/graph?anchor=SMOKE-TEST: $($igResp.StatusCode) (Sprint 2 regression)"

# Phase 7.1 regression: search without enrich still working
$legacySearch = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/search?q=invoice" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "Search q=invoice (legacy, no enrich): $($legacySearch.StatusCode) (Phase 7.1 regression)"

# --- Stderr tail ---
Write-Host ""
Write-Host "=== Last 20 lines of stderr log ===" -ForegroundColor Cyan
Get-Content C:\PZ\logs\pz_stderr.log -Tail 20

Write-Host ""
Write-Host "=== Deploy complete ===" -ForegroundColor Green
Write-Host "SHA deployed: 12f3f90 (Phase 8 Sprint 4 -- search enrich=true)"
Write-Host "Phase 8 campaign complete. All 4 sprints deployed."
Write-Host "Rollback: git revert 12f3f90 --no-edit + robocopy + sc.exe restart"
