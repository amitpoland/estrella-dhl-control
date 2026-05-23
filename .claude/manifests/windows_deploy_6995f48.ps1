# ============================================================
# Windows Production Deploy Script
# SHA: 6995f48 (main HEAD -- Phase 8 Sprint 3 MDI Graph Domain)
# Previous production SHA: 24bc62f (Phase 8 Sprint 2 Intelligence Graph Route)
#
# PR #338 -- feat(phase8-sprint3): graph domain in MDI -- link-completeness
#
# DEPLOY ORDER REQUIREMENT:
#   Sprint 1 (c9c8418) MUST be deployed FIRST via windows_deploy_c9c8418.ps1
#   Sprint 2 (24bc62f) MUST be deployed SECOND via windows_deploy_24bc62f.ps1
#   Sprint 3 (6995f48) deploys AFTER Sprint 2 is confirmed running.
#
# Files deployed (2 modified runtime files, all within service/app/**):
#
#   [1] MODIFIED  service/app/services/master_data_intelligence.py
#       -> C:\PZ\app\services\master_data_intelligence.py
#       Added: graph DomainScore field on MasterDataIntelligenceReport
#       Added: _score_graph() function (link-completeness aggregate scorer)
#       Updated: generate_report() -- 7-domain platform score, rebalanced weights
#       Updated: to_dict() -- includes graph domain
#       Invariants: PRAGMA query_only=ON, no writes, llm_used=False
#
#   [2] MODIFIED  service/app/api/routes_mdi.py
#       -> C:\PZ\app\api\routes_mdi.py
#       Updated: _VALID_DOMAINS -- added "graph"
#       GET /api/v1/master-data/intelligence/graph now returns 200
#
# PZService restart: REQUIRED (Python source files changed)
# Standard robocopy: YES -- all files within service/app/**
# Lesson J: COMPLIANT -- no engine-level root files
# Manifest encoding: ASCII-only -- no em-dashes, no smart quotes (HARD RULE)
# ============================================================

# --- Pre-flight ---
Write-Host "=== Phase 8 Sprint 3 MDI Graph Domain Deploy -- SHA 6995f48 ===" -ForegroundColor Cyan
Write-Host "Previous production SHA: 24bc62f (Phase 8 Sprint 2)"
Write-Host ""

# Verify local repo state
cd "C:\Users\Super Fashion\PZ APP"
$currentSHA = git rev-parse HEAD 2>&1
Write-Host "Local HEAD before pull: $currentSHA"

# Safety gate: Sprint 1 prerequisite
if (-not (Test-Path "C:\PZ\app\services\intelligence_graph.py")) {
    Write-Host "STOP: Sprint 1 not deployed -- C:\PZ\app\services\intelligence_graph.py missing." -ForegroundColor Red
    Write-Host "      Run windows_deploy_c9c8418.ps1 first, then windows_deploy_24bc62f.ps1, then this." -ForegroundColor Red
    exit 1
}
Write-Host "OK  Sprint 1 prerequisite: intelligence_graph.py present"

# Safety gate: Sprint 2 prerequisite -- confirm route file exists
if (-not (Test-Path "C:\PZ\app\api\routes_intelligence_graph.py")) {
    Write-Host "STOP: Sprint 2 not deployed -- C:\PZ\app\api\routes_intelligence_graph.py missing." -ForegroundColor Red
    Write-Host "      Run windows_deploy_24bc62f.ps1 first, then re-run this script." -ForegroundColor Red
    exit 1
}
Write-Host "OK  Sprint 2 prerequisite: routes_intelligence_graph.py present"

# Pull to 6995f48 (or later)
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
    "C:\PZ\app\services\master_data_intelligence.py",
    "C:\PZ\app\api\routes_mdi.py"
)
foreach ($f in $files) {
    if (Test-Path $f) {
        $sz = (Get-Item $f).Length
        Write-Host "OK  $f ($sz bytes)"
    } else {
        Write-Host "MISSING  $f" -ForegroundColor Red
    }
}

# Spot-check: confirm _score_graph in master_data_intelligence
$mdiContent = Get-Content "C:\PZ\app\services\master_data_intelligence.py" -Raw
if ($mdiContent -match "def _score_graph") {
    Write-Host "OK  _score_graph() confirmed in deployed master_data_intelligence"
} else {
    Write-Host "FAIL: _score_graph() NOT found -- Sprint 3 not deployed" -ForegroundColor Red
}

# Spot-check: confirm graph in _VALID_DOMAINS in routes_mdi
$mdiRouteContent = Get-Content "C:\PZ\app\api\routes_mdi.py" -Raw
if ($mdiRouteContent -match '"graph"') {
    Write-Host "OK  graph domain confirmed in deployed routes_mdi"
} else {
    Write-Host "FAIL: graph domain NOT found in routes_mdi" -ForegroundColor Red
}

# Spot-check: confirm llm_used=False in master_data_intelligence
if ($mdiContent -match "llm_used=False") {
    Write-Host "OK  llm_used=False confirmed in deployed master_data_intelligence"
} else {
    Write-Host "WARN: llm_used=False not found" -ForegroundColor Yellow
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

# --- MDI graph smoke tests ---
Write-Host ""
Write-Host "=== MDI graph smoke tests ===" -ForegroundColor Cyan

# Platform report includes graph
$mdiResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /master-data/intelligence: $($mdiResp.StatusCode)"
if ($mdiResp.StatusCode -eq 200) {
    $mdiJson = $mdiResp.Content | ConvertFrom-Json
    Write-Host "  llm_used: $($mdiJson.llm_used) (expected false)"
    if ($mdiJson.graph) {
        Write-Host "  graph domain: present (entity_count=$($mdiJson.graph.entity_count))"
    } else {
        Write-Host "  WARN: graph domain missing from platform report" -ForegroundColor Yellow
    }
}

# Graph domain endpoint
$graphDomainResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence/graph" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /master-data/intelligence/graph: $($graphDomainResp.StatusCode) (expected 200)"
if ($graphDomainResp.StatusCode -eq 200) {
    $gd = $graphDomainResp.Content | ConvertFrom-Json
    Write-Host "  completeness_score: $($gd.completeness_score)"
    Write-Host "  llm_used: $($gd.llm_used)"
}

# Phase 8 Sprint 2 regression: intelligence graph route still works
$igResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/intelligence/graph?anchor=SMOKE-TEST" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /intelligence/graph?anchor=SMOKE-TEST: $($igResp.StatusCode) (Phase 8 Sprint 2 regression)"

# Phase 7.1 regression: search still working
$searchResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/search?q=test" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "Search q=test: $($searchResp.StatusCode) (Phase 7.1 regression)"

# --- Stderr tail ---
Write-Host ""
Write-Host "=== Last 20 lines of stderr log ===" -ForegroundColor Cyan
Get-Content C:\PZ\logs\pz_stderr.log -Tail 20

Write-Host ""
Write-Host "=== Deploy complete ===" -ForegroundColor Green
Write-Host "SHA deployed: 6995f48 (Phase 8 Sprint 3 -- MDI graph domain)"
Write-Host "Next: windows_deploy_12f3f90.ps1 (Phase 8 Sprint 4 -- search enrich)"
Write-Host "Rollback: git revert 6995f48 --no-edit + robocopy + sc.exe restart"
