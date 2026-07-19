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
      python -m pytest test_pz_regression.py   (C:\PZ-verify\test_pz_regression.py)
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
Write-Host "--- DEPLOY CLOSE CONDITIONS -----------------------------------"
Write-Host "  Running checks for expected SHA: $ExpectedSHA"
Write-Host "---------------------------------------------------------------"
Write-Host ""

# -------------------------------------------------------------
# Condition 1 - HEAD
# -------------------------------------------------------------
Write-Host "[1/8] Checking HEAD commit..."
$head = (git -C $RootDir rev-parse HEAD 2>&1).Trim()
$headOk = $head -match '^[0-9a-f]{40}$'
$pass1 = $headOk -and $head.StartsWith($ExpectedSHA)
$detail1 = if ($headOk) { "HEAD=$($head.Substring(0,10))  expected=$ExpectedSHA" } else { "git rev-parse failed: $head" }
Add-Result "HEAD" $pass1 $detail1

# -------------------------------------------------------------
# Condition 2 - PZ regression (root-level test_pz_regression.py)
# Distinct from service/tests/test_pz_*.py (221 tests, tracked in
# test-baseline.md). This checks the golden import-processor suite (~160).
# -------------------------------------------------------------
Write-Host "[2/8] Running PZ regression (root-level golden suite)..."
$env:PYTHONUTF8 = "1"
$pzOut = & python "$RootDir\test_pz_regression.py" 2>&1 | Out-String
$pzMatch = [regex]::Match($pzOut, '(\d+)/\d+ tests passed')
$pzCount = if ($pzMatch.Success) { [int]$pzMatch.Groups[1].Value } else { 0 }
$pass2 = $pzCount -ge $MinPzTests
$detail2 = "$pzCount passed (min $MinPzTests)"
Add-Result "PZ regression" $pass2 $detail2

# -------------------------------------------------------------
# Condition 3 - Carrier tests
# -------------------------------------------------------------
Write-Host "[3/8] Running carrier tests..."
$carrierTmp = [System.IO.Path]::GetTempFileName()
try {
    $carrierFiles = Get-ChildItem -Path "$ServiceDir\tests" -Filter "test_carrier_*.py" |
        Select-Object -ExpandProperty FullName
    Push-Location $ServiceDir
    & python -m pytest $carrierFiles -q > $carrierTmp 2>&1
    Pop-Location
    $carrierOut = Get-Content $carrierTmp -Raw -ErrorAction SilentlyContinue
} finally {
    Remove-Item $carrierTmp -ErrorAction SilentlyContinue
}
$carrierMatch = [regex]::Match($carrierOut, '(\d+) passed')
$carrierCount = if ($carrierMatch.Success) { [int]$carrierMatch.Groups[1].Value } else { 0 }
$pass3 = $carrierCount -ge $MinCarrierTests
$detail3 = "$carrierCount passed (min $MinCarrierTests)"
Add-Result "Carrier tests" $pass3 $detail3

# -------------------------------------------------------------
# Condition 4 - Robocopy  (skippable via -SkipRobocopy)
# -------------------------------------------------------------
if ($SkipRobocopy) {
    Write-Host "[4/8] Robocopy - SKIPPED (run separately)"
    Write-Host "      NOTE: C:\PZ\version.txt is written in the robocopy branch only," -ForegroundColor Yellow
    Write-Host "      so it was NOT updated by this run. Update it manually to the" -ForegroundColor Yellow
    Write-Host "      deployed SHA (BOM-less) or /api/v1/webhooks/wfirma/status will" -ForegroundColor Yellow
    Write-Host "      keep reporting the previous deploy." -ForegroundColor Yellow
    Add-Result "Robocopy" $true "skipped - operator confirmed ran separately (version.txt NOT updated)"
} else {
    Write-Host "[4/8] Running robocopy sync..."
    # OVERWRITE to match source exactly. No /XO — it skips stale/mismatched files
    # and caused the 2026-07-07 version-skew incident (production_deployment_rule.md
    # post-incident rule 3). Never /MIR.
    robocopy "$RootDir\service\app" "C:\PZ\app" /E `
        /XD __pycache__ .pytest_cache storage `
        /XF "*.pyc" "*.pyo" "*.zip"
    if ($LASTEXITCODE -ge 4) {
        Add-Result "Robocopy" $false "exit=$LASTEXITCODE  (STOP - 4+ is fatal)"
        Write-Host ""
        Write-Host "STOP: Robocopy exit $LASTEXITCODE >= 4. Aborting before service restart." -ForegroundColor Red
        foreach ($r in $results) {
            $icon = if ($r.Pass) { "[OK]" } else { "[!!]" }
            Write-Host "  $icon $($r.Name.PadRight(16)) $($r.Detail)"
        }
        exit 1
    }
    Add-Result "Robocopy" $true "exit=$LASTEXITCODE  (0-3=OK)"

    # -- Write version.txt for /api/v1/webhooks/wfirma/status version field --
    # MUST be BOM-less. `Out-File -Encoding utf8` emits a UTF-8 BOM on PowerShell 5.1,
    # and routes_webhooks_wfirma_status.py reads this with
    # read_text(encoding="utf-8").strip() — Python's strip() does NOT remove U+FEFF,
    # so a BOM leaks into the reported service version (41 chars instead of 40).
    [IO.File]::WriteAllText("C:\PZ\version.txt", $head, (New-Object Text.UTF8Encoding($false)))

    # -- Service restart (between conditions 4 and 5) --------------
    Write-Host "[*]   Restarting PZService..."
    sc.exe stop PZService | Out-Null
    $tries = 0
    while ((Get-Service PZService -ErrorAction SilentlyContinue).Status -ne 'Stopped' -and $tries -lt 15) {
        Start-Sleep -Seconds 1; $tries++
    }
    sc.exe start PZService | Out-Null
    $tries = 0
    while ((Get-Service PZService -ErrorAction SilentlyContinue).Status -ne 'Running' -and $tries -lt 30) {
        Start-Sleep -Seconds 1; $tries++
    }
}

# -------------------------------------------------------------
# Condition 5 - Service RUNNING
# -------------------------------------------------------------
Write-Host "[5/8] Checking PZService status..."
$svc = Get-Service PZService -ErrorAction SilentlyContinue
$svcStatus = if ($svc) { $svc.Status.ToString() } else { "NOT_FOUND" }
$pass5 = $svcStatus -eq 'Running'
Add-Result "Service" $pass5 "Status=$svcStatus"

# -------------------------------------------------------------
# Condition 6 - Local liveness HTTP 200
# Uses unauthenticated root path (/) — no API key required.
# -------------------------------------------------------------
Write-Host "[6/8] Checking local liveness (http://127.0.0.1:47213/)..."
try {
    $r6 = Invoke-WebRequest 'http://127.0.0.1:47213/' -UseBasicParsing -TimeoutSec 10
    $pass6 = $r6.StatusCode -eq 200
    Add-Result "Local liveness" $pass6 "HTTP $($r6.StatusCode)"
} catch {
    Add-Result "Local liveness" $false $_.Exception.Message
}

# -------------------------------------------------------------
# Condition 7 - Public liveness HTTP 200
# Uses unauthenticated root path (/) — no API key required.
# -------------------------------------------------------------
Write-Host "[7/8] Checking public liveness (https://pz.estrellajewels.eu/)..."
try {
    $r7 = Invoke-WebRequest 'https://pz.estrellajewels.eu/' -UseBasicParsing -TimeoutSec 15
    $pass7 = $r7.StatusCode -eq 200
    Add-Result "Public liveness" $pass7 "HTTP $($r7.StatusCode)"
} catch {
    Add-Result "Public liveness" $false $_.Exception.Message
}

# -------------------------------------------------------------
# Condition 8 - Log tail: no traceback or startup error
# -------------------------------------------------------------
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

# -------------------------------------------------------------
# Summary table
# -------------------------------------------------------------
$passed = ($results | Where-Object { $_.Pass }).Count
$total  = $results.Count

Write-Host ""
Write-Host "--- RESULTS ---------------------------------------------------"
foreach ($r in $results) {
    if ($r.Pass) {
        $icon = "[OK]"; $color = 'Green'
    } else {
        $icon = "[!!]"; $color = 'Red'
    }
    Write-Host ("  {0} {1}  {2}" -f $icon, $r.Name.PadRight(16), $r.Detail) -ForegroundColor $color
}
Write-Host "---------------------------------------------------------------"

if ($anyFail) {
    $failCount = $total - $passed
    Write-Host "RESULT: $failCount/$total CONDITION(S) FAILED - do not mark deploy closed." -ForegroundColor Red
    Write-Host ""
    exit 1
} else {
    Write-Host "RESULT: ALL $total CONDITIONS PASSED - deploy is closed." -ForegroundColor Green
    Write-Host ""
    exit 0
}
