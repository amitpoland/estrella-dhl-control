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

# The health endpoints are authenticated (require_api_key / X-API-Key) BY DESIGN.
# An anonymous probe returns 401 -- correct app behaviour, NOT a deploy failure.
# The validator must therefore authenticate as a legitimate caller: it reads the
# SAME credential the service loads (health_auth_env_var out of health_auth_env_file,
# the runtime .env) and presents it as the X-API-Key request header. The value is
# used ONLY as a header; it is NEVER written to a check detail, to Write-Host, or to
# any artifact. If the credential cannot be obtained the health check FAILS EXPLICITLY
# rather than silently passing an endpoint it could not verify. Weakening the endpoint
# to make this check pass is forbidden -- fix the credential source, never the route.
function Get-HealthApiKey {
    param($Cfg)
    # Precedence: an explicit operator-shell override, then the runtime .env.
    if ($env:PZ_HEALTH_API_KEY) { return $env:PZ_HEALTH_API_KEY }
    $envFile = $Cfg.health_auth_env_file
    $varName = $Cfg.health_auth_env_var
    if (-not $envFile -or -not $varName) { return $null }
    if (-not (Test-Path $envFile)) { return $null }
    # A present-but-UNREADABLE .env (e.g. a service-account-only ACL that denies the
    # deploying user) must FAIL the health check with a structured per-URL result, NOT
    # crash the whole validator: $ErrorActionPreference is 'Stop', so an unguarded
    # Get-Content would terminate the script before the check table or rollback check
    # ever printed. Read defensively and return $null; the caller records an explicit FAIL.
    try { $lines = Get-Content $envFile -Encoding UTF8 -ErrorAction Stop }
    catch { return $null }
    foreach ($line in $lines) {
        $t = $line.Trim()
        if ($t.StartsWith('#')) { continue }
        $eq = $t.IndexOf('=')
        if ($eq -lt 1) { continue }
        # Exact name match so e.g. ANTHROPIC_API_KEY never satisfies API_KEY.
        if ($t.Substring(0, $eq).Trim() -ne $varName) { continue }
        # Parse the value the SAME way python-dotenv (which the service loads with) does,
        # or the validator could send a credential the service rejects on a healthy .env:
        # a quoted value keeps everything inside the quotes; an unquoted value has an
        # inline comment ( whitespace + '#' ) stripped. A '#' with no leading space is
        # part of the value (keys may contain '#'), matching python-dotenv exactly.
        $val = $t.Substring($eq + 1).Trim()
        if ($val.StartsWith('"') -or $val.StartsWith("'")) {
            $val = $val.Trim().Trim('"').Trim("'")
        }
        else {
            $c = $val.IndexOf(' #')
            if ($c -ge 0) { $val = $val.Substring(0, $c) }
            $val = $val.Trim()
        }
        if ($val) { return $val }
    }
    return $null
}

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

# 7 - health endpoints respond (authenticated -- see Get-HealthApiKey)
$healthKey = Get-HealthApiKey -Cfg $cfg
foreach ($u in $cfg.health_urls) {
    if (-not $healthKey) {
        Add-Result "health $u" $false "health credential unavailable - cannot authenticate to an X-API-Key-protected endpoint (set PZ_HEALTH_API_KEY, or provision $($cfg.health_auth_env_var) in $($cfg.health_auth_env_file))"
        continue
    }
    try {
        # Cache-Control:no-cache so an edge/CDN (the https URL front) cannot answer a
        # health probe from a stale 200 primed before this deploy -- the probe must
        # reflect the CURRENTLY deployed backend, not a cached response.
        $r = Invoke-WebRequest $u -Headers @{ "X-API-Key" = $healthKey; "Cache-Control" = "no-cache" } -UseBasicParsing -TimeoutSec 15
        Add-Result "health $u" ($r.StatusCode -eq 200) "HTTP $($r.StatusCode)"
    }
    catch {
        # Emit the HTTP status code when the server answered; never the request
        # (which carries the key). A transport failure has no code -> its message
        # is safe (it references no header) and is more useful than a bare code.
        $code = if ($_.Exception.Response) { [int]$_.Exception.Response.StatusCode } else { 0 }
        $detail = if ($code) { "HTTP $code" } else { $_.Exception.Message }
        Add-Result "health $u" $false $detail
    }
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
