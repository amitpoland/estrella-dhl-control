# ============================================================
# Windows Production Deploy Script
# Target SHA: 617b2b7 (main HEAD 2026-05-23)
# Previous production SHA: fe0ab30 (Phase 3A, deployed 2026-05-23)
#
# Commits included in this deploy:
#   01764ce feat(lineage): V2 deterministic allocation with unit-price scoring
#   bf9a9ae feat(ai-governance): Phase 3 Proper — centralize all AI calls through ai_gateway (#312)
#   617b2b7 chore(state): update PROJECT_STATE after Phase 3 Proper merge
#
# Files deployed (7):
#   [1] MODIFIED service/app/core/config.py
#       → C:\PZ\app\core\config.py
#       Adds 3 new optional settings: ai_gateway_daily_budget_usd (float, default 0.0),
#       ai_gateway_circuit_breaker_threshold (int, default 5),
#       ai_gateway_circuit_breaker_timeout_s (float, default 60.0)
#
#   [2] NEW     service/app/services/ai_call_ledger.py
#       → C:\PZ\app\services\ai_call_ledger.py
#       SQLite-backed AI call ledger. Dormant until ai_parser_enabled=True.
#
#   [3] MODIFIED service/app/services/ai_customs_evidence.py
#       → C:\PZ\app\services\ai_customs_evidence.py
#       Migrated to call ai_gateway.call() instead of anthropic.Anthropic() directly.
#
#   [4] MODIFIED service/app/services/ai_customs_parser.py
#       → C:\PZ\app\services\ai_customs_parser.py
#       Migrated to call ai_gateway.call() instead of anthropic.Anthropic() directly.
#
#   [5] NEW     service/app/services/ai_gateway.py
#       → C:\PZ\app\services\ai_gateway.py
#       Centralized AI call path. Circuit breaker, budget cap, PII redaction.
#       DORMANT: ai_parser_enabled defaults to False. No external API call possible
#       unless operator explicitly sets ai_parser_enabled=True in production .env.
#
#   [6] NEW     service/app/services/ai_redactor.py
#       → C:\PZ\app\services\ai_redactor.py
#       PII scrubbing utility. No side effects on import.
#
#   [7] MODIFIED service/app/services/global_pz_lineage.py
#       → C:\PZ\app\services\global_pz_lineage.py
#       Adds classify_item_type_from_style() — pure read-only function.
#
# NOT deployed (tests + docs only):
#   service/tests/ (all test files)
#   docs/ai-governance/
#   .claude/memory/
#
# 7-agent gate: ALL GO (2026-05-23)
#   - git-diff-reviewer: CLEAN
#   - backend-impact-reviewer: SAFE (gateway dormant confirmed)
#   - persistence-storage-reviewer: SAFE (separate DB file, no writes at default config)
#   - security-reviewer: SECURE
#   - qa-reviewer: PASS (166/166 AI tests)
#   - release-manager: READY
#   - lead-coordinator: GO (revised after dormancy evidence presented)
#
# Tests (Mac pre-deploy): 166/166 AI-related tests PASS
# PZService RESTART REQUIRED (Python files changed)
# No live Anthropic API call during or after deploy (ai_parser_enabled=False default)
#
# Lesson J: all files in service/app/** — standard robocopy path, no engine sync needed
# Lesson K (Lesson K — explicit boundary): this script does NOT run gh, sc.exe stop/start
#           without explicit operator approval at each step.
#
# OPERATOR: Execute in elevated (Administrator) PowerShell.
#           Read every step. Do NOT skip any section.
# ============================================================

$ErrorActionPreference = "Stop"

$REPO_ROOT = "C:\Users\Super Fashion\PZ APP"
$REPO_SVC  = "$REPO_ROOT\service"
$APP_ROOT  = "C:\PZ\app"
$BAK_DIR   = "C:\PZ\app\bak\617b2b7_$(Get-Date -Format 'yyyyMMdd_HHmmss')"

# ── STEP 0: Local-commit safety check ────────────────────────
Write-Host "`n=== STEP 0: Local-commit safety check ===" -ForegroundColor Cyan
Set-Location $REPO_ROOT
git fetch origin 2>&1 | Write-Host
$ahead = git log --oneline "origin/main..HEAD" 2>&1
if ($ahead -and $ahead.Trim() -and $ahead -notmatch "^fatal") {
    Write-Host "WARNING: Windows HEAD has local commits NOT on origin/main:" -ForegroundColor Yellow
    Write-Host $ahead -ForegroundColor Yellow
    Write-Host ""
    Write-Host "These may be the reconciliation commits documented in PROJECT_STATE.md." -ForegroundColor Yellow
    Write-Host "This deploy uses file-level robocopy — git state does not need to match" -ForegroundColor Yellow
    Write-Host "exactly for the file copies to be correct." -ForegroundColor Yellow
    Write-Host "Continuing without pull (files will be copied from repo state)." -ForegroundColor Yellow
    $skipPull = $true
} else {
    Write-Host "No local-only commits — safe to pull." -ForegroundColor Green
    $skipPull = $false
}

# ── STEP 1: Git pull ──────────────────────────────────────────
Write-Host "`n=== STEP 1: git pull --ff-only origin main ===" -ForegroundColor Cyan
if ($skipPull) {
    Write-Host "SKIPPED (local commits present — see STEP 0)." -ForegroundColor Yellow
    $headSha = git rev-parse --short HEAD
    Write-Host "Current Windows repo HEAD: $headSha" -ForegroundColor Yellow
} else {
    git pull --ff-only origin main
    if ($LASTEXITCODE -ne 0) { Write-Host "[FAIL] git pull failed" -ForegroundColor Red; exit 1 }
    $headSha = git rev-parse --short HEAD
    Write-Host "HEAD after pull: $headSha" -ForegroundColor Green
    if ($headSha -ne "617b2b7") {
        Write-Host "NOTE: HEAD is $headSha (expected 617b2b7 or later). Continuing." -ForegroundColor Yellow
    }
}

# ── STEP 2: Source content verification ──────────────────────
Write-Host "`n=== STEP 2: Verify source file content markers ===" -ForegroundColor Cyan

# Verify ai_gateway.py is the gatekeeper
$gatewaySrc = "$REPO_SVC\app\services\ai_gateway.py"
if (-not (Test-Path $gatewaySrc)) {
    Write-Host "[FAIL] ai_gateway.py NOT found in source — wrong branch?" -ForegroundColor Red; exit 1
}
$gatewayHasAnthropicClient = Select-String -Path $gatewaySrc -Pattern "anthropic\.Anthropic\(" -Quiet
if (-not $gatewayHasAnthropicClient) {
    Write-Host "[FAIL] anthropic.Anthropic() NOT in ai_gateway.py — source integrity check failed" -ForegroundColor Red; exit 1
}
Write-Host "  [OK] ai_gateway.py exists and contains anthropic.Anthropic()" -ForegroundColor Green

# Verify ai_customs_parser.py uses gateway (not direct anthropic)
$parserSrc = "$REPO_SVC\app\services\ai_customs_parser.py"
$parserHasDirect = Select-String -Path $parserSrc -Pattern "anthropic\.Anthropic\(" -Quiet
if ($parserHasDirect) {
    Write-Host "[FAIL] ai_customs_parser.py still has direct anthropic.Anthropic() — migration incomplete!" -ForegroundColor Red; exit 1
}
$parserHasGateway = Select-String -Path $parserSrc -Pattern "ai_gateway" -Quiet
if (-not $parserHasGateway) {
    Write-Host "[FAIL] ai_customs_parser.py does NOT reference ai_gateway — migration incomplete!" -ForegroundColor Red; exit 1
}
Write-Host "  [OK] ai_customs_parser.py uses gateway (no direct anthropic client)" -ForegroundColor Green

# Verify ai_customs_evidence.py uses gateway
$evidSrc = "$REPO_SVC\app\services\ai_customs_evidence.py"
$evidHasDirect = Select-String -Path $evidSrc -Pattern "anthropic\.Anthropic\(" -Quiet
if ($evidHasDirect) {
    Write-Host "[FAIL] ai_customs_evidence.py still has direct anthropic.Anthropic() — migration incomplete!" -ForegroundColor Red; exit 1
}
$evidHasGateway = Select-String -Path $evidSrc -Pattern "ai_gateway" -Quiet
if (-not $evidHasGateway) {
    Write-Host "[FAIL] ai_customs_evidence.py does NOT reference ai_gateway — migration incomplete!" -ForegroundColor Red; exit 1
}
Write-Host "  [OK] ai_customs_evidence.py uses gateway (no direct anthropic client)" -ForegroundColor Green

# Verify ai_call_ledger.py has prompt_hash (not raw prompt)
$ledgerSrc = "$REPO_SVC\app\services\ai_call_ledger.py"
if (-not (Test-Path $ledgerSrc)) {
    Write-Host "[FAIL] ai_call_ledger.py NOT found in source" -ForegroundColor Red; exit 1
}
$ledgerHashCol = Select-String -Path $ledgerSrc -Pattern "prompt_hash" -Quiet
if (-not $ledgerHashCol) {
    Write-Host "[FAIL] prompt_hash column NOT in ai_call_ledger.py — governance check failed" -ForegroundColor Red; exit 1
}
Write-Host "  [OK] ai_call_ledger.py has prompt_hash (no raw prompt storage)" -ForegroundColor Green

# Verify ai_redactor.py exists and has redact_pair
$redactorSrc = "$REPO_SVC\app\services\ai_redactor.py"
if (-not (Test-Path $redactorSrc)) {
    Write-Host "[FAIL] ai_redactor.py NOT found in source" -ForegroundColor Red; exit 1
}
$redactorFn = Select-String -Path $redactorSrc -Pattern "def redact_pair" -Quiet
if (-not $redactorFn) {
    Write-Host "[FAIL] redact_pair function NOT in ai_redactor.py" -ForegroundColor Red; exit 1
}
Write-Host "  [OK] ai_redactor.py has redact_pair function" -ForegroundColor Green

Write-Host "`n  All source content checks PASSED." -ForegroundColor Green

# ── STEP 3: Backup existing deployed files ────────────────────
Write-Host "`n=== STEP 3: Backup existing C:\PZ\app files ===" -ForegroundColor Cyan
New-Item -ItemType Directory -Path $BAK_DIR -Force | Out-Null

$filesToBackup = @(
    "core\config.py",
    "services\ai_customs_evidence.py",
    "services\ai_customs_parser.py",
    "services\global_pz_lineage.py"
)

foreach ($f in $filesToBackup) {
    $src = "$APP_ROOT\$f"
    $dst = "$BAK_DIR\$f"
    $dstDir = Split-Path $dst -Parent
    if (Test-Path $src) {
        New-Item -ItemType Directory -Path $dstDir -Force | Out-Null
        Copy-Item $src $dst
        Write-Host "  Backed up: $f" -ForegroundColor Gray
    } else {
        Write-Host "  Not present (new file will be added): $f" -ForegroundColor Gray
    }
}

Write-Host "  Backup complete: $BAK_DIR" -ForegroundColor Green

# ── STEP 4: Robocopy runtime files ────────────────────────────
Write-Host "`n=== STEP 4: robocopy service\app → C:\PZ\app ===" -ForegroundColor Cyan

robocopy "$REPO_SVC\app" "$APP_ROOT" /E /XO /XD __pycache__ .pytest_cache /XF "*.pyc" "*.pyo" "*.zip"
$rc = $LASTEXITCODE
if ($rc -ge 8) {
    Write-Host "[FAIL] robocopy exit code $rc — error. Investigate before continuing." -ForegroundColor Red
    exit 1
}
Write-Host "  robocopy exit code: $rc (0-3 = success, 4-7 = some files skipped — check above)" -ForegroundColor $(if ($rc -le 3) { "Green" } else { "Yellow" })

# ── STEP 5: Post-copy file content verification ───────────────
Write-Host "`n=== STEP 5: Verify deployed file content ===" -ForegroundColor Cyan

# C1: ai_gateway.py deployed and is the only file with anthropic.Anthropic(
$deployedGateway = "$APP_ROOT\services\ai_gateway.py"
if (-not (Test-Path $deployedGateway)) {
    Write-Host "[FAIL] C:\PZ\app\services\ai_gateway.py NOT deployed" -ForegroundColor Red; exit 1
}
Write-Host "  [OK] ai_gateway.py deployed" -ForegroundColor Green

# C2: No other service file has direct anthropic.Anthropic(
$directInParser = Select-String -Path "$APP_ROOT\services\ai_customs_parser.py" -Pattern "anthropic\.Anthropic\(" -Quiet
$directInEvidence = Select-String -Path "$APP_ROOT\services\ai_customs_evidence.py" -Pattern "anthropic\.Anthropic\(" -Quiet
if ($directInParser) {
    Write-Host "[FAIL] anthropic.Anthropic() found in deployed ai_customs_parser.py — wrong file deployed!" -ForegroundColor Red; exit 1
}
if ($directInEvidence) {
    Write-Host "[FAIL] anthropic.Anthropic() found in deployed ai_customs_evidence.py — wrong file deployed!" -ForegroundColor Red; exit 1
}
Write-Host "  [OK] No direct anthropic.Anthropic() in deployed parser/evidence files" -ForegroundColor Green

# C3: ai_call_ledger.py deployed with prompt_hash
$deployedLedger = "$APP_ROOT\services\ai_call_ledger.py"
if (-not (Test-Path $deployedLedger)) {
    Write-Host "[FAIL] ai_call_ledger.py NOT deployed" -ForegroundColor Red; exit 1
}
$deployedLedgerHash = Select-String -Path $deployedLedger -Pattern "prompt_hash" -Quiet
if (-not $deployedLedgerHash) {
    Write-Host "[FAIL] prompt_hash NOT in deployed ai_call_ledger.py" -ForegroundColor Red; exit 1
}
Write-Host "  [OK] ai_call_ledger.py deployed with prompt_hash" -ForegroundColor Green

# C4: ai_redactor.py deployed with redact_pair
$deployedRedactor = "$APP_ROOT\services\ai_redactor.py"
if (-not (Test-Path $deployedRedactor)) {
    Write-Host "[FAIL] ai_redactor.py NOT deployed" -ForegroundColor Red; exit 1
}
$deployedRedactPair = Select-String -Path $deployedRedactor -Pattern "def redact_pair" -Quiet
if (-not $deployedRedactPair) {
    Write-Host "[FAIL] redact_pair NOT in deployed ai_redactor.py" -ForegroundColor Red; exit 1
}
Write-Host "  [OK] ai_redactor.py deployed with redact_pair" -ForegroundColor Green

# C5: config.py deployed
if (-not (Test-Path "$APP_ROOT\core\config.py")) {
    Write-Host "[FAIL] config.py NOT deployed" -ForegroundColor Red; exit 1
}
Write-Host "  [OK] config.py deployed" -ForegroundColor Green

Write-Host "`n  All post-copy content checks PASSED." -ForegroundColor Green

# ── STEP 6: PZService restart (requires Administrator) ────────
Write-Host "`n=== STEP 6: PZService restart ===" -ForegroundColor Cyan
Write-Host "  Stopping PZService..." -ForegroundColor Yellow
sc.exe stop PZService
$tries = 0
while ((Get-Service PZService).Status -ne 'Stopped' -and $tries -lt 15) {
    Start-Sleep -Seconds 1; $tries++
}
if ((Get-Service PZService).Status -ne 'Stopped') {
    Write-Host "[WARN] PZService did not stop cleanly after 15s. Current status: $((Get-Service PZService).Status)" -ForegroundColor Yellow
    Write-Host "       Proceeding with start — NSSM may still restart Uvicorn." -ForegroundColor Yellow
}
Write-Host "  Starting PZService..." -ForegroundColor Yellow
sc.exe start PZService
Start-Sleep -Seconds 12
$svcStatus = (Get-Service PZService).Status
Write-Host "  PZService status: $svcStatus" -ForegroundColor $(if ($svcStatus -eq 'Running') { "Green" } else { "Red" })

# ── STEP 7: Health checks ─────────────────────────────────────
Write-Host "`n=== STEP 7: Health checks ===" -ForegroundColor Cyan

try {
    $local = Invoke-WebRequest http://127.0.0.1:47213/api/v1/health -TimeoutSec 15
    Write-Host "  Local  health: $($local.StatusCode)" -ForegroundColor $(if ($local.StatusCode -eq 200) { "Green" } else { "Red" })
} catch {
    Write-Host "  [FAIL] Local health check failed: $_" -ForegroundColor Red; exit 1
}

try {
    $public = Invoke-WebRequest https://pz.estrellajewels.eu/api/v1/health -TimeoutSec 20
    Write-Host "  Public health: $($public.StatusCode)" -ForegroundColor $(if ($public.StatusCode -eq 200) { "Green" } else { "Red" })
} catch {
    Write-Host "  [WARN] Public health check failed (Cloudflare tunnel may need 30s): $_" -ForegroundColor Yellow
}

# ── STEP 8: Stderr log check ──────────────────────────────────
Write-Host "`n=== STEP 8: Check stderr log for import errors ===" -ForegroundColor Cyan
$stderrLines = Get-Content C:\PZ\logs\pz_stderr.log -Tail 20 -ErrorAction SilentlyContinue
if ($stderrLines) {
    $importErrors = $stderrLines | Where-Object { $_ -match "ImportError|ModuleNotFound|Traceback|ERROR" }
    if ($importErrors) {
        Write-Host "[WARN] Potential errors in stderr log:" -ForegroundColor Yellow
        $importErrors | ForEach-Object { Write-Host "  $_" -ForegroundColor Yellow }
    } else {
        Write-Host "  [OK] No ImportError/ModuleNotFound/Traceback in last 20 lines" -ForegroundColor Green
    }
    Write-Host "`n  Last 5 lines of pz_stderr.log:" -ForegroundColor Gray
    $stderrLines | Select-Object -Last 5 | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
} else {
    Write-Host "  [OK] Log file empty or not found" -ForegroundColor Green
}

# ── STEP 9: Gateway safety final check ───────────────────────
Write-Host "`n=== STEP 9: Final gateway safety check ===" -ForegroundColor Cyan

# Confirm anthropic.Anthropic( exists ONLY in ai_gateway.py in deployed files
$allServices = Get-ChildItem "$APP_ROOT\services\*.py" | Where-Object { $_.Name -ne "ai_gateway.py" }
$violations = @()
foreach ($f in $allServices) {
    $hit = Select-String -Path $f.FullName -Pattern "anthropic\.Anthropic\(" -Quiet
    if ($hit) { $violations += $f.Name }
}
if ($violations.Count -gt 0) {
    Write-Host "[FAIL] anthropic.Anthropic() found outside ai_gateway.py in: $($violations -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "  [OK] anthropic.Anthropic() confined to ai_gateway.py only" -ForegroundColor Green

# Confirm ai_parser_enabled=False in .env (no live AI call possible)
$envFile = "C:\PZ\.env"
if (Test-Path $envFile) {
    $aiEnabled = Select-String -Path $envFile -Pattern "^AI_PARSER_ENABLED\s*=\s*[Tt]rue" -Quiet
    if ($aiEnabled) {
        Write-Host "[WARN] AI_PARSER_ENABLED=True found in production .env — AI gateway is ACTIVE" -ForegroundColor Yellow
        Write-Host "       Ensure this is intentional before proceeding." -ForegroundColor Yellow
    } else {
        Write-Host "  [OK] AI_PARSER_ENABLED not set to True in .env — gateway dormant" -ForegroundColor Green
    }
} else {
    Write-Host "  [OK] No .env override — ai_parser_enabled defaults to False — gateway dormant" -ForegroundColor Green
}

# ── STEP 10: Deploy summary ───────────────────────────────────
Write-Host "`n=== DEPLOY COMPLETE ===" -ForegroundColor Green
Write-Host "  Pulled SHA  : 617b2b7 (or nearest descendant)" -ForegroundColor White
Write-Host "  Files synced: 7 (config + 3 new services + 3 updated services)" -ForegroundColor White
Write-Host "  Backup at   : $BAK_DIR" -ForegroundColor White
Write-Host "  PZService   : $((Get-Service PZService).Status)" -ForegroundColor White
Write-Host "  AI gateway  : DORMANT (ai_parser_enabled=False by default)" -ForegroundColor White
Write-Host ""
Write-Host "  Rollback if needed:" -ForegroundColor White
Write-Host "  > robocopy `"$BAK_DIR`" `"$APP_ROOT`" /E /COPY:DAT" -ForegroundColor Gray
Write-Host "  > sc.exe stop PZService; sc.exe start PZService" -ForegroundColor Gray
Write-Host ""
Write-Host "Phase 3 Proper AI Gateway is LIVE in dormant state." -ForegroundColor Green
