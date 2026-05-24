# ============================================================
# Windows Production Deploy Script
# SHA: 1c6046b (main HEAD -- Phase 9 Workflow Intelligence Foundation)
# Previous production SHA: 12f3f90 (Phase 8 Sprint 4 Search Graph Enrichment)
#
# PR #342 -- feat(phase9): workflow intelligence -- GET /api/v1/workflow/intelligence
#
# Files deployed (3 modified/new runtime files, all within service/app/**):
#
#   [1] NEW  service/app/services/workflow_intelligence.py
#       -> C:\PZ\app\services\workflow_intelligence.py
#       WorkflowBlocker, WorkflowWarning, WorkflowIntelligenceResult dataclasses
#       get_workflow_intelligence(batch_id, domain=None) -> WorkflowIntelligenceResult
#       resolve_batch_id_from_awb(awb) -> Optional[str]
#       Status: BLOCKED | INCOMPLETE | READY | UNKNOWN
#       Severity: HIGH (wfirma/sales/conflict) | MEDIUM (warehouse) | LOW (dhl)
#       Invariants: PRAGMA query_only=ON, no writes, llm_used=False
#
#   [2] NEW  service/app/api/routes_workflow_intelligence.py
#       -> C:\PZ\app\api\routes_workflow_intelligence.py
#       GET /api/v1/workflow/intelligence
#       Params: batch_id (str), awb (str), domain (str), limit (int)
#       422 if neither batch_id nor awb given
#       404 if AWB resolves to no batch
#       domain filter: warehouse|sales|wfirma|dhl|graph|readiness
#
#   [3] MODIFIED  service/app/main.py
#       -> C:\PZ\app\main.py
#       +1 import: from .api.routes_workflow_intelligence import router as workflow_intelligence_router
#       +1 include_router: app.include_router(workflow_intelligence_router)
#
# PZService restart: REQUIRED (main.py changed -- new import + router mount)
# Standard robocopy: YES -- all files within service/app/**
# Lesson J: COMPLIANT -- no engine-level root files
# Manifest encoding: ASCII-only -- no em-dashes, no smart quotes (HARD RULE)
# ============================================================

# --- Pre-flight ---
Write-Host "=== Phase 9 Workflow Intelligence Deploy -- SHA 1c6046b ===" -ForegroundColor Cyan
Write-Host "Previous production SHA: 12f3f90 (Phase 8 Sprint 4)"
Write-Host ""

# Verify local repo state
cd "C:\Users\Super Fashion\PZ APP"
$currentSHA = git rev-parse HEAD 2>&1
Write-Host "Local HEAD before pull: $currentSHA"

# Safety gate: Phase 8 Sprint 4 prerequisite -- confirm _enrich_hits in search_engine
$searchContent = Get-Content "C:\PZ\app\services\search_engine.py" -Raw -ErrorAction SilentlyContinue
if (-not $searchContent -or $searchContent -notmatch "def _enrich_hits") {
    Write-Host "STOP: Phase 8 Sprint 4 not deployed -- _enrich_hits() missing from search_engine.py." -ForegroundColor Red
    Write-Host "      Deploy Phase 8 all 4 sprints first, then re-run this script." -ForegroundColor Red
    exit 1
}
Write-Host "OK  Phase 8 prerequisite: _enrich_hits() present in search_engine.py"

# Pull to 1c6046b (or later)
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
    "C:\PZ\app\services\workflow_intelligence.py",
    "C:\PZ\app\api\routes_workflow_intelligence.py",
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

# Spot-check: confirm get_workflow_intelligence in service
$wfContent = Get-Content "C:\PZ\app\services\workflow_intelligence.py" -Raw
if ($wfContent -match "def get_workflow_intelligence") {
    Write-Host "OK  get_workflow_intelligence() confirmed in deployed workflow_intelligence"
} else {
    Write-Host "FAIL: get_workflow_intelligence() NOT found -- Phase 9 not deployed" -ForegroundColor Red
}

# Spot-check: confirm llm_used=False in service
if ($wfContent -match "llm_used = False") {
    Write-Host "OK  llm_used=False confirmed in deployed workflow_intelligence"
} else {
    Write-Host "FAIL: llm_used=False NOT found in workflow_intelligence" -ForegroundColor Red
}

# Spot-check: confirm PRAGMA query_only in service
if ($wfContent -match "PRAGMA query_only") {
    Write-Host "OK  PRAGMA query_only confirmed in deployed workflow_intelligence"
} else {
    Write-Host "FAIL: PRAGMA query_only NOT found" -ForegroundColor Red
}

# Spot-check: confirm workflow router in main.py
$mainContent = Get-Content "C:\PZ\app\main.py" -Raw
if ($mainContent -match "workflow_intelligence_router") {
    Write-Host "OK  workflow_intelligence_router confirmed in deployed main.py"
} else {
    Write-Host "FAIL: workflow_intelligence_router NOT found in main.py" -ForegroundColor Red
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

# --- Phase 9 smoke tests ---
Write-Host ""
Write-Host "=== Phase 9 smoke tests ===" -ForegroundColor Cyan

# No params -> 422
$noParams = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/workflow/intelligence" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing -ErrorAction SilentlyContinue
Write-Host "GET /workflow/intelligence (no params): $($noParams.StatusCode) (expected 422)"

# With batch_id -> 200
$withBatch = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/workflow/intelligence?batch_id=SMOKE-TEST" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /workflow/intelligence?batch_id=SMOKE-TEST: $($withBatch.StatusCode) (expected 200)"
if ($withBatch.StatusCode -eq 200) {
    $wfJson = $withBatch.Content | ConvertFrom-Json
    Write-Host "  workflow_status: $($wfJson.workflow_status)"
    Write-Host "  llm_used: $($wfJson.llm_used) (expected false)"
    Write-Host "  blockers: $($wfJson.blockers.Count)"
    Write-Host "  missing_links: $($wfJson.missing_links.Count)"
}

# Domain filter -> 200
$withDomain = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/workflow/intelligence?batch_id=SMOKE-TEST&domain=wfirma" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /workflow/intelligence?batch_id=SMOKE-TEST&domain=wfirma: $($withDomain.StatusCode) (expected 200)"

# Invalid domain -> 422
$badDomain = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/workflow/intelligence?batch_id=X&domain=invalid" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing -ErrorAction SilentlyContinue
Write-Host "GET /workflow/intelligence?batch_id=X&domain=invalid: $($badDomain.StatusCode) (expected 422)"

# Unknown AWB -> 404
$unknownAWB = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/workflow/intelligence?awb=0000000000" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing -ErrorAction SilentlyContinue
Write-Host "GET /workflow/intelligence?awb=0000000000: $($unknownAWB.StatusCode) (expected 404)"

# Phase 8 Sprint 4 regression: search enrich still works
$searchEnrich = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/search?q=test&enrich=true" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /search?q=test&enrich=true: $($searchEnrich.StatusCode) (Phase 8 regression)"

# Phase 8 Sprint 2 regression: intelligence graph route still works
$igResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/intelligence/graph?anchor=SMOKE-TEST" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /intelligence/graph?anchor=SMOKE-TEST: $($igResp.StatusCode) (Phase 8 regression)"

# Phase 7 regression: search still working
$searchResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/search?q=test" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /search?q=test: $($searchResp.StatusCode) (Phase 7 regression)"

# --- Stderr tail ---
Write-Host ""
Write-Host "=== Last 20 lines of stderr log ===" -ForegroundColor Cyan
Get-Content C:\PZ\logs\pz_stderr.log -Tail 20

Write-Host ""
Write-Host "=== Deploy complete ===" -ForegroundColor Green
Write-Host "SHA deployed: 1c6046b (Phase 9 -- Workflow Intelligence Foundation)"
Write-Host "Next: Phase 10 (Operations Intelligence) after smoke tests confirm PASS."
Write-Host "Rollback: git revert 1c6046b --no-edit + robocopy + sc.exe restart"
