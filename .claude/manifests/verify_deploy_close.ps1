<#
.SYNOPSIS
    Reusable deploy close-condition gate for PZ production deploys.

.DESCRIPTION
    Checks all 8 required close conditions in sequence. Runs conditions
    1-3 (pre-deploy verification), executes robocopy (condition 4), restarts
    PZService, then checks conditions 5-8 (post-deploy verification).

    Exit 0 = all 8 conditions passed. Deploy is closed.
    Exit 1 = one or more conditions failed. Do not mark deploy closed.

.PARAMETER ExpectedSHA
    The git SHA the deployed HEAD must match (7+ characters). Required.

.PARAMETER MinPzTests
    Minimum passing count for the ROOT-LEVEL golden regression:
      python test_pz_regression.py   (C:\PZ-verify\test_pz_regression.py)
    Default: 160.

    NOTE: This is NOT the same as the service-level PZ suite tracked in
    test-baseline.md (tests/test_pz_*.py, currently 221 tests). That suite
    covers FastAPI routes. The root-level file covers the PZ import-processor
    golden constants. Both exist; this script gates on the root-level one.

.PARAMETER MinCarrierTests
    Minimum passing count for service/tests/test_carrier_*.py.
    Default: 469

.PARAMETER RootDir
    Repo root for git commands and PZ regression. Default: C:\PZ-verify

.PARAMETER ServiceDir
    FastAPI service directory for carrier tests. Default: C:\PZ-verify\service

.PARAMETER LogFile
    Production log file to tail for startup errors.
    Default: C:\PZ\logs\pz_stderr.log

.PARAMETER SkipRobocopy
    Skip the robocopy and service-restart steps (conditions 4-5). Use when
    the deploy sync was run separately and you only want to verify the result.

.EXAMPLE
    .\verify_deploy_close.ps1 -ExpectedSHA 88c5a57
    Full deploy + verify.

.EXAMPLE
    .\verify_deploy_close.ps1 -ExpectedSHA 88c5a57 -SkipRobocopy
    Verify only (robocopy already ran separately).
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$ExpectedSHA,

    [int]$MinPzTests = 160,
    [int]$MinCarrierTests = 469,
    [string]$RootDir = "C:\PZ-verify",
    [string]$ServiceDir = "C:\PZ-verify\service",
    [string]$LogFile = "C:\PZ\logs\pz_stderr.log",
    [switch]$SkipRobocopy
)

$ErrorActionPreference = 'Continue'
$results = [System.Collections.Generic.List[PSCustomObject]]::new()
$anyFail = $false

function Add-Result {
    param([string]$Name, [bool]$Pass, [string]$Detail)
    $script:results.Add([PSCustomObject]@{ Name=$Name; Pass=$Pass; Detail=$Detail })
    if (-not $Pass) { $script:anyFail = $true }
}

Write-Host ""
Write-Host "━━━ DEPLOY CLOSE CONDITIONS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
Write-Host "  Running checks for expected SHA: $ExpectedSHA"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
Write-Host ""

# ─────────────────────────────────────────────────────────────
# Condition 1 — HEAD
# ─────────────────────────────────────────────────────────────
Write-Host "[1/8] Checking HEAD commit..."
$head = (git -C $RootDir rev-parse HEAD 2>&1).Trim()
$headOk = $head -match '^[0-9a-f]{40}$'
$pass1 = $headOk -and $head.StartsWith($ExpectedSHA)
$detail1 = if ($headOk) { "HEAD=$($head.Substring(0,10))  expected=$ExpectedSHA" } else { "git rev-parse failed: $head" }
Add-Result "HEAD" $pass1 $detail1

# ─────────────────────────────────────────────────────────────
# Condition 2 — PZ regression (root-level test_pz_regression.py)
# Distinct from service/tests/test_pz_*.py (221 tests, tracked in
# test-baseline.md). This checks the golden import-processor suite (~160).
# ─────────────────────────────────────────────────────────────
Write-Host "[2/8] Running PZ regression (root-level golden suite)..."
$pzOut = & python "$RootDir\test_pz_regression.py" 2>&1 | Out-String
$pzMatch = [regex]::Match($pzOut, '(\d+) passed')
$pzCount = if ($pzMatch.Success) { [int]$pzMatch.Groups[1].Value } else { 0 }
$pass2 = $pzCount -ge $MinPzTests
$detail2 = "$pzCount passed (min $MinPzTests)"
Add-Result "PZ regression" $pass2 $detail2

# ─────────────────────────────────────────────────────────────
# Condition 3 — Carrier tests
# ─────────────────────────────────────────────────────────────
Write-Host "[3/8] Running carrier tests..."
Push-Location $ServiceDir
$carrierOut = & python -m pytest tests/test_carrier_*.py -q 2>&1 | Out-String
Pop-Location
$carrierMatch = [regex]::Match($carrierOut, '(\d+) passed')
$carrierCount = if ($carrierMatch.Success) { [int]$carrierMatch.Groups[1].Value } else { 0 }
$pass3 = $carrierCount -ge $MinCarrierTests
$detail3 = "$carrierCount passed (min $MinCarrierTests)"
Add-Result "Carrier tests" $pass3 $detail3

# ─────────────────────────────────────────────────────────────
# Condition 4 — Robocopy  (skippable via -SkipRobocopy)
# ─────────────────────────────────────────────────────────────
if ($SkipRobocopy) {
    Write-Host "[4/8] Robocopy — SKIPPED (run separately)"
    Add-Result "Robocopy" $true "skipped — operator confirmed ran separately"
} else {
    Write-Host "[4/8] Running robocopy sync..."
    robocopy "$RootDir\service\app" "C:\PZ\app" /E /XO `
        /XD __pycache__ .pytest_cache storage `
        /XF "*.pyc" "*.pyo" "*.zip"
    if ($LASTEXITCODE -ge 4) {
        Add-Result "Robocopy" $false "exit=$LASTEXITCODE  (STOP — 4+ is fatal)"
        Write-Host ""
        Write-Host "STOP: Robocopy exit $LASTEXITCODE >= 4. Aborting before service restart." -ForegroundColor Red
        foreach ($r in $results) {
            $icon = if ($r.Pass) { "[OK]" } else { "[!!]" }
            Write-Host "  $icon $($r.Name.PadRight(16)) $($r.Detail)"
        }
        exit 1
    }
    Add-Result "Robocopy" $true "exit=$LASTEXITCODE  (0-3=OK)"

    # ── Service restart (between conditions 4 and 5) ──────────────
    Write-Host "[*]   Restarting PZService..."
    sc.exe stop PZService | Out-Null
    $tries = 0
    while ((Get-Service PZService -ErrorAction SilentlyContinue).Status -ne 'Stopped' -and $tries -lt 15) {
        Start-Sleep -Seconds 1; $tries++
    }
    sc.exe start PZService | Out-Null
    Start-Sleep -Seconds 8
}

# ─────────────────────────────────────────────────────────────
# Condition 5 — Service RUNNING
# ─────────────────────────────────────────────────────────────
Write-Host "[5/8] Checking PZService status..."
$svc = Get-Service PZService -ErrorAction SilentlyContinue
$svcStatus = if ($svc) { $svc.Status.ToString() } else { "NOT_FOUND" }
$pass5 = $svcStatus -eq 'Running'
Add-Result "Service" $pass5 "Status=$svcStatus"

# ─────────────────────────────────────────────────────────────
# Condition 6 — Local health HTTP 200
# ─────────────────────────────────────────────────────────────
Write-Host "[6/8] Checking local health endpoint..."
try {
    $r6 = Invoke-WebRequest 'http://127.0.0.1:47213/api/v1/health' -UseBasicParsing -TimeoutSec 10
    $pass6 = $r6.StatusCode -eq 200
    Add-Result "Local health" $pass6 "HTTP $($r6.StatusCode)"
} catch {
    Add-Result "Local health" $false $_.Exception.Message
}

# ─────────────────────────────────────────────────────────────
# Condition 7 — Public health HTTP 200
# ─────────────────────────────────────────────────────────────
Write-Host "[7/8] Checking public health endpoint..."
try {
    $r7 = Invoke-WebRequest 'https://pz.estrellajewels.eu/api/v1/health' -UseBasicParsing -TimeoutSec 15
    $pass7 = $r7.StatusCode -eq 200
    Add-Result "Public health" $pass7 "HTTP $($r7.StatusCode)"
} catch {
    Add-Result "Public health" $false $_.Exception.Message
}

# ─────────────────────────────────────────────────────────────
# Condition 8 — Log tail: no traceback or startup error
# ─────────────────────────────────────────────────────────────
Write-Host "[8/8] Tailing production log for errors..."
$tail = Get-Content $LogFile -Tail 30 -ErrorAction SilentlyContinue
if ($null -eq $tail) {
    Add-Result "Logs" $false "cannot read $LogFile"
} else {
    $errorPattern = 'Traceback \(most recent call last\)|ImportError|ModuleNotFoundError|No module named|startup failed|Application startup failed|ERROR:|CRITICAL:'
    $hits = $tail | Select-String -Pattern $errorPattern
    $pass8 = ($null -eq $hits -or $hits.Count -eq 0)
    $detail8 = if ($pass8) { "clean (last 30 lines)" } else { "FOUND: $($hits[0].Line.Trim())" }
    Add-Result "Logs" $pass8 $detail8
}

# ─────────────────────────────────────────────────────────────
# Summary table
# ─────────────────────────────────────────────────────────────
$passed = ($results | Where-Object { $_.Pass }).Count
$total  = $results.Count

Write-Host ""
Write-Host "━━━ RESULTS ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
foreach ($r in $results) {
    if ($r.Pass) {
        $icon = "[OK]"; $color = 'Green'
    } else {
        $icon = "[!!]"; $color = 'Red'
    }
    Write-Host ("  {0} {1}  {2}" -f $icon, $r.Name.PadRight(16), $r.Detail) -ForegroundColor $color
}
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if ($anyFail) {
    $failCount = $total - $passed
    Write-Host "RESULT: $failCount/$total CONDITION(S) FAILED — do not mark deploy closed." -ForegroundColor Red
    Write-Host ""
    exit 1
} else {
    Write-Host "RESULT: ALL $total CONDITIONS PASSED — deploy is closed." -ForegroundColor Green
    Write-Host ""
    exit 0
}
