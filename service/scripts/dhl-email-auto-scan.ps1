#Requires -Version 5.1
<#
.SYNOPSIS
  DHL Email Auto-Scan (Lane A only) — inbox scan every 10 minutes.

.DESCRIPTION
  Calls POST /api/v1/dhl/scheduled-inbox-check.

  Lane B (follow-up automation) is deferred to PR #457 and will be
  deployed separately after Lane A has run cleanly for one production cycle.

  Kill switch: DHL_AUTO_SCAN_ENABLED=false in C:\PZ\.env disables the scan.
  API key read from C:\PZ\.env (never hardcoded).
  Logs to C:\PZ\logs\dhl-auto-scan.log.

.NOTES
  Task Scheduler registration (run once as administrator):

    schtasks /create /tn "PZService-DHL-Email-AutoScan" ^
      /tr "powershell.exe -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File C:\PZ\scripts\dhl-email-auto-scan.ps1" ^
      /sc MINUTE /mo 10 /ru SYSTEM /f

  Verify:  schtasks /query /tn "PZService-DHL-Email-AutoScan" /fo LIST
  Disable: schtasks /change /tn "PZService-DHL-Email-AutoScan" /disable
           OR set DHL_AUTO_SCAN_ENABLED=false in C:\PZ\.env
#>

param()

$ErrorActionPreference = "Continue"

$ApiBase       = "http://127.0.0.1:47213"
$LaneAEndpoint = "$ApiBase/api/v1/dhl/scheduled-inbox-check"
$EnvFile       = "C:\PZ\.env"
$LogDir        = "C:\PZ\logs"
$LogFile       = "$LogDir\dhl-auto-scan.log"
$TimeoutSec    = 300    # 5 min — ingestion cycle scans 25+ active batches via Zoho API

function Write-Log {
    param([string]$Msg, [string]$Level = "INFO")
    $ts   = (Get-Date -Format "yyyy-MM-ddTHH:mm:ss")
    $line = "[$ts] [$Level] $Msg"
    Write-Host $line
    try {
        if (-not (Test-Path $LogDir)) { New-Item -ItemType Directory -Path $LogDir -Force | Out-Null }
        Add-Content -Path $LogFile -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue
    } catch {}
}

if (-not (Test-Path $EnvFile)) { Write-Log "ENV file not found: $EnvFile" "ERROR"; exit 1 }
try {
    $ApiKey = (Select-String "^API_KEY=" $EnvFile -ErrorAction Stop).Line.Split("=", 2)[1].Trim()
} catch { Write-Log "Failed to read API_KEY from $EnvFile" "ERROR"; exit 1 }
if ([string]::IsNullOrEmpty($ApiKey)) { Write-Log "API_KEY empty in $EnvFile" "ERROR"; exit 1 }

Write-Log "[Lane-A] Starting DHL inbox scan..."
try {
    $resp = Invoke-WebRequest `
        -Uri $LaneAEndpoint -Method POST `
        -Headers @{ "X-API-Key" = $ApiKey } `
        -UseBasicParsing -TimeoutSec $TimeoutSec
    $body = $resp.Content | ConvertFrom-Json
    if ($body.skipped) {
        Write-Log "[Lane-A] skipped: $($body.skipped)"
    } else {
        Write-Log ("[Lane-A] done: checked=$($body.batches_checked) " +
                   "received_set=$($body.received_set) " +
                   "b2_triggered=$($body.b2_triggered) b2_sent=$($body.b2_sent) " +
                   "skipped_inactive=$($body.skipped_inactive) " +
                   "skipped_excluded=$($body.skipped_excluded) " +
                   "errors=$($body.errors.Count)")
        if ($body.errors.Count -gt 0) {
            $body.errors | ForEach-Object { Write-Log "  error: $_" "WARN" }
        }
    }
} catch {
    $errStr = "$_"
    if ($errStr -match "timed out|timeout") {
        Write-Log "[Lane-A] HTTP timed out — scan may still be running server-side." "ERROR"
        # Write timed_out status so the status card reflects reality.
        # The server may complete the scan; next run will overwrite with success/failed.
        try {
            $statusPath = "C:\PZ\storage\dhl_auto_scan_status.json"
            if (Test-Path $statusPath) {
                $existing = Get-Content $statusPath -Raw | ConvertFrom-Json
                if ($existing.status -eq "running") {
                    $existing.status = "timed_out"
                    $existing | ConvertTo-Json | Set-Content $statusPath -Encoding UTF8
                }
            }
        } catch {}
    } else {
        Write-Log "[Lane-A] HTTP failed: $errStr" "ERROR"
    }
}

Write-Log "Scheduler run complete."
exit 0
