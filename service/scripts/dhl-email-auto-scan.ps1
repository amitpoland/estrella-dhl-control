#Requires -Version 5.1
<#
.SYNOPSIS
  DHL Email Auto-Scan — calls POST /api/v1/dhl/scheduled-inbox-check
  every time it runs (intended: every 10 minutes via Task Scheduler).

.DESCRIPTION
  Reads the API key from C:\PZ\.env and calls the scheduled-inbox-check
  endpoint. The endpoint runs one Zoho scan, applies cached email evidence
  to all active batches, and triggers B2 DSK replies where conditions are
  met.

  Register with Task Scheduler:
    schtasks /create /tn "PZService-DHL-Email-AutoScan" /tr "powershell.exe
      -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass
      -File C:\PZ\scripts\dhl-email-auto-scan.ps1"
      /sc MINUTE /mo 10 /ru SYSTEM

.NOTES
  - Idempotent: existing dhl_email.received and dhl_reply_package flags
    prevent duplicate writes and duplicate sends.
  - Only active (non-terminal, non-delivered) batches are touched.
  - Logs to C:\PZ\logs\dhl-auto-scan.log (created if absent).
  - Requires PZService running at http://127.0.0.1:47213.
#>

$ErrorActionPreference = "Stop"

# ── Config ────────────────────────────────────────────────────────────────────
$ApiBase    = "http://127.0.0.1:47213"
$Endpoint   = "$ApiBase/api/v1/dhl/scheduled-inbox-check"
$EnvFile    = "C:\PZ\.env"
$LogDir     = "C:\PZ\logs"
$LogFile    = "$LogDir\dhl-auto-scan.log"
$TimeoutSec = 120

# ── Logging helper ────────────────────────────────────────────────────────────
function Write-Log {
    param([string]$Msg, [string]$Level = "INFO")
    $ts  = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
    $line = "[$ts] [$Level] $Msg"
    Write-Host $line
    if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
    Add-Content -Path $LogFile -Value $line -Encoding UTF8
}

# ── Read API key ──────────────────────────────────────────────────────────────
if (-not (Test-Path $EnvFile)) {
    Write-Log "ENV file not found: $EnvFile" "ERROR"
    exit 1
}
$ApiKey = (Select-String "^API_KEY=" $EnvFile).Line.Split("=", 2)[1].Trim()
if ([string]::IsNullOrEmpty($ApiKey)) {
    Write-Log "API_KEY empty in $EnvFile" "ERROR"
    exit 1
}

# ── Call the endpoint ─────────────────────────────────────────────────────────
Write-Log "Starting DHL auto-scan..."
try {
    $resp = Invoke-WebRequest `
        -Uri $Endpoint `
        -Method POST `
        -Headers @{ "X-API-Key" = $ApiKey } `
        -UseBasicParsing `
        -TimeoutSec $TimeoutSec

    $body = $resp.Content | ConvertFrom-Json
    Write-Log ("Scan complete: checked=$($body.batches_checked) " +
               "received_set=$($body.received_set) " +
               "b2_triggered=$($body.b2_triggered) " +
               "b2_sent=$($body.b2_sent) " +
               "skipped=$($body.skipped_inactive) " +
               "errors=$($body.errors.Count)")

    if ($body.errors.Count -gt 0) {
        $body.errors | ForEach-Object { Write-Log "  error: $_" "WARN" }
    }
    exit 0
}
catch {
    Write-Log "Request failed: $_" "ERROR"
    exit 1
}
