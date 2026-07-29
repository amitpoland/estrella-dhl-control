<#
.SYNOPSIS
    SOLE validation authority for PZ production deployment. READ-ONLY.

.DESCRIPTION
    Verifies deploy close-conditions. Performs NO copy, NO service control, NO write
    of any kind -- validation that can mutate is not validation. Every path comes from
    windows_prod_v2.json; required test counts come from the test-baseline contract.

    Replaces the validation half of the retired .claude/manifests/verify_deploy_close.ps1,
    whose execution half (file convergence, service control, version-file write) moved
    to the sole execution authority.

.PARAMETER ExpectedSHA
    The SHA production must be running.

.NOTES
    Exit 0 = all conditions passed. Exit 1 = one or more failed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)][string]$ExpectedSHA,
    [string]$Unit
)

$ErrorActionPreference = "Stop"
$cfgPath = Join-Path $PSScriptRoot "windows_prod_v2.json"
if (-not (Test-Path $cfgPath)) { Write-Error "config not found: $cfgPath"; exit 1 }
$cfg = Get-Content $cfgPath -Raw -Encoding UTF8 | ConvertFrom-Json

$results = @()
function Add-Result { param([string]$Name, [bool]$Ok, [string]$Detail) $script:results += [pscustomobject]@{ Check = $Name; Ok = $Ok; Detail = $Detail } }

# 1 - deployed SHA matches expectation (via the version file)
if (Test-Path $cfg.version_file) {
    # RAW BYTES, deliberately. Get-Content silently strips a UTF-8 BOM that Python's
    # utf-8 reader does NOT, so a text-mode check passes while the runtime endpoint
    # serves a corrupted SHA. Validation must see what the consumer sees.
    $bytes = [System.IO.File]::ReadAllBytes($cfg.version_file)
    $hasBom = ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF)
    $actual = ([System.Text.Encoding]::UTF8.GetString($bytes)).Trim([char]0xFEFF, ' ', "`r", "`n", "`t")
    Add-Result "version_file is BOM-free" (-not $hasBom) $(if ($hasBom) { "BOM PRESENT - the status endpoint would serve a corrupted SHA" } else { "clean" })
    Add-Result "version_file matches ExpectedSHA" ($actual -eq $ExpectedSHA) "file=$actual expected=$ExpectedSHA"
}
else { Add-Result "version_file present" $false "MISSING: $($cfg.version_file) - the wfirma status endpoint will report no version" }

# 2 - certified source is at the expected SHA
$head = (& git -C $cfg.source_root rev-parse HEAD 2>$null)
Add-Result "source_root HEAD == ExpectedSHA" ($LASTEXITCODE -eq 0 -and $head.Trim() -eq $ExpectedSHA) "head=$head"

# 3 - artifact for this SHA exists and production matches its manifest
$art = Join-Path $cfg.artifact_root "app-$ExpectedSHA"
$man = "$art.manifest.csv"
if (Test-Path $man) {
    $bad = @()
    foreach ($row in Import-Csv $man) {
        $dst = Join-Path $cfg.runtime_app $row.Rel
        if (-not (Test-Path $dst)) { $bad += "MISSING $($row.Rel)" }
        elseif ((Get-FileHash $dst -Algorithm SHA256).Hash -ne $row.Hash) { $bad += "MISMATCH $($row.Rel)" }
    }
    Add-Result "production matches artifact manifest" ($bad.Count -eq 0) "$($bad.Count) discrepancies"
}
else { Add-Result "artifact manifest present" $false "MISSING: $man" }

# 4 - engine files match the certified source by content hash (Lesson J)
$engineBad = @()
foreach ($ef in $cfg.engine_files) {
    $s = Join-Path $cfg.source_root $ef
    $d = Join-Path $cfg.runtime_engine $ef
    if (-not (Test-Path $d)) { $engineBad += "MISSING $ef" }
    elseif (-not (Test-Path $s)) { $engineBad += "SOURCE MISSING $ef" }
    elseif ((Get-FileHash $s -Algorithm SHA256).Hash -ne (Get-FileHash $d -Algorithm SHA256).Hash) { $engineBad += "MISMATCH $ef" }
}
Add-Result "engine files match source" ($engineBad.Count -eq 0) ($engineBad -join "; ")

# 5 - protected runtime state still present and untouched by deployment
$missing = @($cfg.protected_runtime_paths | Where-Object { -not (Test-Path $_) })
Add-Result "protected runtime paths intact" ($missing.Count -eq 0) ("missing: " + ($missing -join ", "))

# 6 - service is running
$svc = Get-Service $cfg.service -ErrorAction SilentlyContinue
Add-Result "$($cfg.service) Running" ($null -ne $svc -and $svc.Status -eq 'Running') "status=$($svc.Status)"

# 7 - health endpoints respond
foreach ($u in $cfg.health_urls) {
    try {
        $r = Invoke-WebRequest $u -UseBasicParsing -TimeoutSec 15
        Add-Result "health $u" ($r.StatusCode -eq 200) "HTTP $($r.StatusCode)"
    }
    catch { Add-Result "health $u" $false $_.Exception.Message }
}

# 8 - a restorable rollback unit exists for this SHA
$units = @()
if (Test-Path $cfg.backup_root) {
    $units = @(Get-ChildItem $cfg.backup_root -Directory -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -like "$ExpectedSHA*" -or ($Unit -and $_.Name -eq $Unit) })
}
Add-Result "rollback unit available" ($units.Count -ge 1) ("units: " + (($units | ForEach-Object Name) -join ", "))

$results | ForEach-Object { "{0}  {1}  {2}" -f $(if ($_.Ok) { "PASS" } else { "FAIL" }), $_.Check, $_.Detail }
$failed = @($results | Where-Object { -not $_.Ok }).Count
if ($failed -gt 0) { Write-Host "`n$failed condition(s) FAILED - do not mark the deploy closed."; exit 1 }
Write-Host "`nAll $($results.Count) conditions passed - deploy is closed."
exit 0
