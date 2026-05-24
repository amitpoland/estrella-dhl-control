# ============================================================
# Windows Production Deploy Script
# SHA: 95fc0fe (main HEAD -- Phase 10 Operations Intelligence)
# Previous production SHA: 1c6046b (Phase 9 Workflow Intelligence)
#
# PR #345 -- feat(phase10): operations intelligence -- GET /api/v1/operations/intelligence
#
# Files deployed (3 modified/new runtime files, all within service/app/**):
#
#   [1] NEW  service/app/services/operations_intelligence.py
#       -> C:\PZ\app\services\operations_intelligence.py
#       OperationsIntelligenceResult dataclass
#       get_operations_intelligence(period, domain, *, doc_db, batch_limit)
#       Period: today | 7d | 30d
#       Metrics: total_batches, blocked_batches, incomplete_batches, ready_batches
#                document_coverage_score, master_data_score, graph_completeness_score
#                workflow_risk_summary, top_missing_evidence, top_master_data_gaps
#       Invariants: PRAGMA query_only=ON, no writes, llm_used=False
#
#   [2] NEW  service/app/api/routes_operations_intelligence.py
#       -> C:\PZ\app\api\routes_operations_intelligence.py
#       GET /api/v1/operations/intelligence
#       Params: period (str), domain (str)
#       422 if period not in today|7d|30d
#       422 if domain not valid
#
#   [3] MODIFIED  service/app/main.py
#       -> C:\PZ\app\main.py
#       +1 import: from .api.routes_operations_intelligence import router as operations_intelligence_router
#       +1 include_router: app.include_router(operations_intelligence_router)
#
# PZService restart: REQUIRED (main.py changed -- new import + router mount)
# Standard robocopy: YES -- all files within service/app/**
# Lesson J: COMPLIANT -- no engine-level root files
# Manifest encoding: ASCII-only -- no em-dashes, no smart quotes (HARD RULE)
# ============================================================

# --- Pre-flight ---
Write-Host "=== Phase 10 Operations Intelligence Deploy -- SHA 95fc0fe ===" -ForegroundColor Cyan
Write-Host "Previous production SHA: 1c6046b (Phase 9 Workflow Intelligence)"
Write-Host ""

# Verify local repo state
cd "C:\Users\Super Fashion\PZ APP"
$currentSHA = git rev-parse HEAD 2>&1
Write-Host "Local HEAD before pull: $currentSHA"

# Safety gate: Phase 9 prerequisite -- confirm get_workflow_intelligence in service
$wfContent = Get-Content "C:\PZ\app\services\workflow_intelligence.py" -Raw -ErrorAction SilentlyContinue
if (-not $wfContent -or $wfContent -notmatch "def get_workflow_intelligence") {
    Write-Host "STOP: Phase 9 not deployed -- get_workflow_intelligence() missing from workflow_intelligence.py." -ForegroundColor Red
    Write-Host "      Deploy Phase 9 (SHA 1c6046b) first, then re-run this script." -ForegroundColor Red
    exit 1
}
Write-Host "OK  Phase 9 prerequisite: get_workflow_intelligence() present in workflow_intelligence.py"

# Pull to 95fc0fe (or later)
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
    "C:\PZ\app\services\operations_intelligence.py",
    "C:\PZ\app\api\routes_operations_intelligence.py",
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

# Spot-check: confirm get_operations_intelligence in service
$opsContent = Get-Content "C:\PZ\app\services\operations_intelligence.py" -Raw
if ($opsContent -match "def get_operations_intelligence") {
    Write-Host "OK  get_operations_intelligence() confirmed in deployed operations_intelligence"
} else {
    Write-Host "FAIL: get_operations_intelligence() NOT found -- Phase 10 not deployed" -ForegroundColor Red
}

# Spot-check: confirm llm_used=False in service
if ($opsContent -match "llm_used = False") {
    Write-Host "OK  llm_used=False confirmed in deployed operations_intelligence"
} else {
    Write-Host "FAIL: llm_used=False NOT found in operations_intelligence" -ForegroundColor Red
}

# Spot-check: confirm PRAGMA query_only in service
if ($opsContent -match "PRAGMA query_only") {
    Write-Host "OK  PRAGMA query_only confirmed in deployed operations_intelligence"
} else {
    Write-Host "FAIL: PRAGMA query_only NOT found" -ForegroundColor Red
}

# Spot-check: confirm operations router in main.py
$mainContent = Get-Content "C:\PZ\app\main.py" -Raw
if ($mainContent -match "operations_intelligence_router") {
    Write-Host "OK  operations_intelligence_router confirmed in deployed main.py"
} else {
    Write-Host "FAIL: operations_intelligence_router NOT found in main.py" -ForegroundColor Red
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

# --- Phase 10 smoke tests ---
Write-Host ""
Write-Host "=== Phase 10 smoke tests ===" -ForegroundColor Cyan

# Default period (7d) -> 200
$default7d = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/operations/intelligence" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /operations/intelligence (default 7d): $($default7d.StatusCode) (expected 200)"
if ($default7d.StatusCode -eq 200) {
    $opsJson = $default7d.Content | ConvertFrom-Json
    Write-Host "  period: $($opsJson.period)"
    Write-Host "  total_batches: $($opsJson.total_batches)"
    Write-Host "  blocked_batches: $($opsJson.blocked_batches)"
    Write-Host "  ready_batches: $($opsJson.ready_batches)"
    Write-Host "  llm_used: $($opsJson.llm_used) (expected false)"
    Write-Host "  master_data_score: $($opsJson.master_data_score)"
}

# period=today -> 200
$today = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/operations/intelligence?period=today" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /operations/intelligence?period=today: $($today.StatusCode) (expected 200)"

# period=30d -> 200
$d30 = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/operations/intelligence?period=30d" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /operations/intelligence?period=30d: $($d30.StatusCode) (expected 200)"

# domain=wfirma -> 200
$domWf = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/operations/intelligence?domain=wfirma" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /operations/intelligence?domain=wfirma: $($domWf.StatusCode) (expected 200)"

# Invalid period -> 422 (use -ErrorAction SilentlyContinue to avoid exception on 4xx)
$badPeriod = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/operations/intelligence?period=invalid" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing -ErrorAction SilentlyContinue
Write-Host "GET /operations/intelligence?period=invalid: $($badPeriod.StatusCode) (expected 422)"

# Invalid domain -> 422
$badDomain = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/operations/intelligence?domain=bogus" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing -ErrorAction SilentlyContinue
Write-Host "GET /operations/intelligence?domain=bogus: $($badDomain.StatusCode) (expected 422)"

# Phase 9 regression: workflow intelligence still works
$wfResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/workflow/intelligence?batch_id=SMOKE-TEST" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "GET /workflow/intelligence?batch_id=SMOKE-TEST: $($wfResp.StatusCode) (Phase 9 regression)"

# Phase 8 regression: intelligence graph still works
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
Write-Host "SHA deployed: 95fc0fe (Phase 10 -- Operations Intelligence)"
Write-Host "Next: Phase 2 (Advisory LLM Explanations) after smoke tests confirm PASS -- requires explicit operator approval."
Write-Host "Rollback: git revert 95fc0fe --no-edit + robocopy + sc.exe restart"
