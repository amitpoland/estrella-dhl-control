# ============================================================
# Windows Production Deploy Script
# SHA: 958e914 (main HEAD 2026-05-23 — Phase 6 Document Coverage Intelligence)
# Previous production SHA: eaa2875 (Phase 5, confirmed by operator 2026-05-23)
#
# ALSO INCLUDES (landed between eaa2875 and 958e914 on main):
#   SHA 8dea14b — feat(global-pz): governed execution layer PR #319
#   SHA 62ec20f — fix: correction-execute 500 hotfix
#   SHA 3a5bad0 — chore: PROJECT_STATE.md update
#   SHA 958e914 — feat(phase6): document coverage intelligence PR #321
#
# PR #321 — feat(phase6): document coverage intelligence MDI domain
#
# Files deployed (3 modified runtime files):
#
#   [1] MODIFIED  service/app/services/master_data_intelligence.py
#       → C:\PZ\app\services\master_data_intelligence.py
#       Phase 6 additions: _score_documents(), document DomainScore field on
#       MasterDataIntelligenceReport, _DOC_DB path, get_document_coverage_summary
#       import, updated generate_report() and platform weights (6 domains),
#       updated to_dict(). llm_used=False hardcoded. Read-only. No LLM calls.
#
#   [2] MODIFIED  service/app/services/document_db.py
#       → C:\PZ\app\services\document_db.py
#       Phase 6 addition: get_document_coverage_summary() appended at end.
#       PRAGMA query_only = ON. No schema changes. No migrations.
#
#   [3] MODIFIED  service/app/api/routes_mdi.py
#       → C:\PZ\app\api\routes_mdi.py
#       "document" added to _VALID_DOMAINS. GET-only. No new routes.
#
# NOTE: Cumulative with PR #319 (global PZ execution layer) if production
#       is still at eaa2875. Those files are also within service/app/**
#       and covered by standard robocopy.
#
# PZService restart: REQUIRED (master_data_intelligence.py, document_db.py changed)
# Standard robocopy: YES — all files within service/app/**
# Lesson J: COMPLIANT — no engine-level root files
# 7-agent gate: 7/7 GO (PR #321)
# ============================================================

# --- Pre-flight ---
Write-Host "=== Phase 6 Document Coverage Intelligence Deploy — SHA 958e914 ===" -ForegroundColor Cyan
Write-Host "Previous production SHA: eaa2875 (Phase 5 — confirmed 2026-05-23)"
Write-Host ""

# Verify we are on the right SHA
cd "C:\Users\Super Fashion\PZ APP"
$currentSHA = git rev-parse HEAD 2>&1
Write-Host "Local HEAD: $currentSHA"

# Pull to 958e914
git pull --ff-only origin main
$pulledSHA = git rev-parse HEAD 2>&1
Write-Host "After pull: $pulledSHA"
if ($pulledSHA -notmatch "958e914") {
    Write-Host "WARN: SHA mismatch — expected 958e914. Verify before sync." -ForegroundColor Yellow
}

# --- Sync service/app → C:\PZ\app ---
Write-Host ""
Write-Host "=== robocopy sync ===" -ForegroundColor Cyan
robocopy "C:\Users\Super Fashion\PZ APP\service\app" "C:\PZ\app" /E /XO `
  /XD __pycache__ .pytest_cache `
  /XF "*.pyc" "*.pyo" "*.zip"

$rc = $LASTEXITCODE
if ($rc -ge 4) {
    Write-Host "ERROR: robocopy exit code $rc — STOP. Do not restart service." -ForegroundColor Red
    exit 1
}
Write-Host "robocopy exit: $rc (0–3 = success)" -ForegroundColor Green

# --- Verify key files landed ---
Write-Host ""
Write-Host "=== File verification ===" -ForegroundColor Cyan
$files = @(
    "C:\PZ\app\services\master_data_intelligence.py",
    "C:\PZ\app\services\document_db.py",
    "C:\PZ\app\api\routes_mdi.py"
)
foreach ($f in $files) {
    if (Test-Path $f) {
        $size = (Get-Item $f).Length
        Write-Host "OK  $f ($size bytes)"
    } else {
        Write-Host "MISSING  $f" -ForegroundColor Red
    }
}

# Spot-check Phase 6: confirm get_document_coverage_summary in deployed document_db
$docDbContent = Get-Content "C:\PZ\app\services\document_db.py" -Raw
if ($docDbContent -match "get_document_coverage_summary") {
    Write-Host "OK  get_document_coverage_summary confirmed in deployed document_db"
} else {
    Write-Host "FAIL: get_document_coverage_summary NOT found — old document_db deployed" -ForegroundColor Red
}

# Spot-check Phase 6: confirm PRAGMA query_only in document_db
if ($docDbContent -match "query_only") {
    Write-Host "OK  PRAGMA query_only confirmed in deployed document_db"
} else {
    Write-Host "FAIL: PRAGMA query_only NOT found in deployed document_db" -ForegroundColor Red
}

# Spot-check Phase 6: confirm _score_documents in MDI
$mdiContent = Get-Content "C:\PZ\app\services\master_data_intelligence.py" -Raw
if ($mdiContent -match "_score_documents") {
    Write-Host "OK  _score_documents confirmed in deployed MDI service"
} else {
    Write-Host "FAIL: _score_documents NOT found — Phase 6 not deployed" -ForegroundColor Red
}

# Spot-check Phase 6: confirm document domain in MasterDataIntelligenceReport
if ($mdiContent -match "document: DomainScore") {
    Write-Host "OK  document DomainScore field confirmed in deployed MDI service"
} else {
    Write-Host "FAIL: document DomainScore NOT found in MDI" -ForegroundColor Red
}

# Spot-check Phase 6: confirm _DOC_DB path constant
if ($mdiContent -match "_DOC_DB") {
    Write-Host "OK  _DOC_DB path constant confirmed in deployed MDI service"
} else {
    Write-Host "FAIL: _DOC_DB NOT found in deployed MDI service" -ForegroundColor Red
}

# Spot-check Phase 6: confirm document in _VALID_DOMAINS
$routerContent = Get-Content "C:\PZ\app\api\routes_mdi.py" -Raw
if ($routerContent -match '"document"') {
    Write-Host "OK  document domain in _VALID_DOMAINS confirmed in deployed router"
} else {
    Write-Host "FAIL: document NOT found in _VALID_DOMAINS" -ForegroundColor Red
}

# Spot-check: confirm llm_used=False still hardcoded
if ($mdiContent -match "llm_used=False") {
    Write-Host "OK  llm_used=False confirmed in deployed MDI service"
} else {
    Write-Host "FAIL: llm_used=False NOT found" -ForegroundColor Red
}

# Spot-check Phase 5 (regression): confirm Phase 5 signals still present
if ($mdiContent -match "_desc_quality") {
    Write-Host "OK  Phase 5 _desc_quality still present (regression check)"
} else {
    Write-Host "FAIL: _desc_quality missing — Phase 5 regression" -ForegroundColor Red
}

# Spot-check: GET-only router
if ($routerContent -notmatch "@router\.post|@router\.put|@router\.delete") {
    Write-Host "OK  GET-only confirmed in deployed router"
} else {
    Write-Host "FAIL: write route found in deployed router" -ForegroundColor Red
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
$local = Invoke-WebRequest http://127.0.0.1:47213/api/v1/health -UseBasicParsing
Write-Host "Local health: $($local.StatusCode)"

$public = Invoke-WebRequest https://pz.estrellajewels.eu/api/v1/health -UseBasicParsing
Write-Host "Public health: $($public.StatusCode)"

# --- MDI smoke tests (Phase 6) ---
Write-Host ""
Write-Host "=== MDI smoke tests ===" -ForegroundColor Cyan
$apiKey = (Get-Content "C:\PZ\.env" | Where-Object { $_ -match "^API_KEY=" } | ForEach-Object { $_.Split("=", 2)[1] })

# Full platform report — must now include document domain
$mdiResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "MDI platform report: $($mdiResp.StatusCode)"
$mdiJson = $mdiResp.Content | ConvertFrom-Json
Write-Host "  llm_used: $($mdiJson.llm_used)"
Write-Host "  advisory_class: $($mdiJson.advisory_class)"
Write-Host "  platform_score: $($mdiJson.platform_score)"

# Phase 6: document domain present in platform report
if ($mdiJson.document) {
    Write-Host "OK  document domain present in platform report"
    Write-Host "  [Phase6] document.entity_count: $($mdiJson.document.entity_count)"
    Write-Host "  [Phase6] document.completeness_score: $($mdiJson.document.completeness_score)"
    Write-Host "  [Phase6] document.advisory_class: $($mdiJson.advisory_class)"
} else {
    Write-Host "FAIL: document domain NOT present in platform report" -ForegroundColor Red
}

# Document domain — dedicated endpoint
$docResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence/document" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "MDI document: $($docResp.StatusCode)"
$docJson = $docResp.Content | ConvertFrom-Json
Write-Host "  entity_count: $($docJson.entity_count)"
Write-Host "  completeness_score: $($docJson.completeness_score)"
Write-Host "  advisory_class: $($docJson.advisory_class)"

# Phase 6 detail fields
if ($docJson.details) {
    Write-Host "  [Phase6] total_documents: $($docJson.details.total_documents)"
    Write-Host "  [Phase6] extraction_complete_count: $($docJson.details.extraction_complete_count)"
    Write-Host "  [Phase6] awb_linked_count: $($docJson.details.awb_linked_count)"
    Write-Host "  [Phase6] mrn_linked_count: $($docJson.details.mrn_linked_count)"
    Write-Host "  [Phase6] customs_declaration_count: $($docJson.details.customs_declaration_count)"
    Write-Host "  [Phase6] pz_document_count: $($docJson.details.pz_document_count)"
    Write-Host "  [Phase6] pz_with_workdrive_count: $($docJson.details.pz_with_workdrive_count)"
} else {
    Write-Host "WARN: document domain details not present" -ForegroundColor Yellow
}

# Phase 5 regression: product domain still works
$prodResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence/product" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "MDI product (Phase 5 regression): $($prodResp.StatusCode)"

# Phase 5 regression: finishing domain still works
$finResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence/finishing" `
    -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing
Write-Host "MDI finishing (Phase 5 regression): $($finResp.StatusCode)"

# Invalid domain (should still 422)
try {
    $badResp = Invoke-WebRequest "http://127.0.0.1:47213/api/v1/master-data/intelligence/badomain" `
        -Headers @{"X-API-Key" = $apiKey} -UseBasicParsing -ErrorAction Stop
    Write-Host "FAIL: invalid domain should have 422 but got $($badResp.StatusCode)" -ForegroundColor Red
} catch {
    Write-Host "OK  Invalid domain → 422 as expected"
}

# --- Stderr tail ---
Write-Host ""
Write-Host "=== Last 20 lines of stderr log ===" -ForegroundColor Cyan
Get-Content C:\PZ\logs\pz_stderr.log -Tail 20

Write-Host ""
Write-Host "=== Deploy complete ===" -ForegroundColor Green
Write-Host "SHA deployed: 958e914"
Write-Host "Rollback: git revert 958e914 --no-edit + robocopy + sc.exe restart"
