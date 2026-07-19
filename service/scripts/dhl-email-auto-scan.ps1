#Requires -Version 5.1
<#
.SYNOPSIS
  DHL Email Automation Scheduler — Lane A (10 min) + Lane B (60 min, working hours).

.DESCRIPTION
  Called by Windows Task Scheduler every 10 minutes.

  Lane A: POST /api/v1/dhl/scheduled-inbox-check  — always.
  Lane B: POST /api/v1/dhl/scheduled-followup-check — working hours 08:00-16:00 Warsaw,
          only when 60+ minutes have passed since the last Lane B run.

  Kill switches (server-side — both default OFF for Lane B):
    DHL_AUTO_SCAN_ENABLED=false   disables Lane A
    DHL_FOLLOWUP_ENABLED=false    disables Lane B
    DHL_ORCH_AUTO_SEND_DHL_FOLLOWUP=false  disables actual email send (inner guard)

  API key read from C:\PZ\.env. Logs to C:\PZ\logs\dhl-auto-scan.log.
  Lane B last-run time tracked in C:\PZ\logs\dhl-lane-b-last-run.txt.

.NOTES
  Task Scheduler registration (already done — PZService-DHL-Email-AutoScan runs every 10 min).
  To enable Lane B: set DHL_FOLLOWUP_ENABLED=true in C:\PZ\.env + restart service.
  To disable:       set DHL_FOLLOWUP_ENABLED=false in C:\PZ\.env (kill switch).
#>

param()

$ErrorActionPreference = "Continue"

$ApiBase       = "http://127.0.0.1:47213"
$LaneAEndpoint = "$ApiBase/api/v1/dhl/scheduled-inbox-check"
$LaneBEndpoint = "$ApiBase/api/v1/dhl/scheduled-followup-check"
$EnvFile       = "C:\PZ\.env"
$LogDir        = "C:\PZ\logs"
$LogFile       = "$LogDir\dhl-auto-scan.log"
$LaneBStamp    = "$LogDir\dhl-lane-b-last-run.txt"
$TimeoutSec    = 300    # 5 min — ingestion cycle scans 25+ batches via Zoho API
$LaneBIntervalMin = 60  # Lane B fires at most once per hour
$WorkStart     = [TimeSpan]"08:00:00"
$WorkEnd       = [TimeSpan]"16:00:00"

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

function Test-WorkingHours {
    $now = (Get-Date).TimeOfDay
    return ($now -ge $WorkStart -and $now -lt $WorkEnd)
}

function Test-LaneBDue {
    if (-not (Test-Path $LaneBStamp)) { return $true }
    try {
        $last = [DateTime]::Parse((Get-Content $LaneBStamp -Raw).Trim())
        return ((Get-Date) - $last).TotalMinutes -ge $LaneBIntervalMin
    } catch { return $true }
}

# ── Read API key ───────────────────────────────────────────────────────────────
if (-not (Test-Path $EnvFile)) { Write-Log "ENV file not found: $EnvFile" "ERROR"; exit 1 }
try {
    $ApiKey = (Select-String "^API_KEY=" $EnvFile -ErrorAction Stop).Line.Split("=", 2)[1].Trim()
} catch { Write-Log "Failed to read API_KEY from $EnvFile" "ERROR"; exit 1 }
if ([string]::IsNullOrEmpty($ApiKey)) { Write-Log "API_KEY empty in $EnvFile" "ERROR"; exit 1 }

# ── Lane A — inbox scan (every 10 min, always) ─────────────────────────────────
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

# ── Lane B — DHL follow-up (working hours + 60-min interval) ──────────────────
if (Test-WorkingHours) {
    if (Test-LaneBDue) {
        Write-Log "[Lane-B] Running DHL follow-up check (working hours, interval due)..."
        try {
            $resp = Invoke-WebRequest `
                -Uri $LaneBEndpoint -Method POST `
                -Headers @{ "X-API-Key" = $ApiKey } `
                -UseBasicParsing -TimeoutSec 60
            $body = $resp.Content | ConvertFrom-Json
            if ($body.skipped) {
                Write-Log "[Lane-B] skipped: $($body.skipped)"
            } else {
                Write-Log ("[Lane-B] done: checked=$($body.batches_checked) " +
                           "started=$($body.followup_started) " +
                           "sent=$($body.followup_sent) " +
                           "stopped=$($body.followup_stopped) " +
                           "skipped_inactive=$($body.skipped_inactive) " +
                           "skipped_received=$($body.skipped_received) " +
                           "errors=$($body.errors.Count)")
                if ($body.errors.Count -gt 0) {
                    $body.errors | ForEach-Object { Write-Log "  error: $_" "WARN" }
                }
            }
            # Record Lane B last-run time (even on skip — prevents hammering)
            (Get-Date -Format "o") | Set-Content $LaneBStamp -Encoding UTF8
        } catch {
            Write-Log "[Lane-B] HTTP failed: $_" "ERROR"
        }
    } else {
        $minSince = [int]((Get-Date) - [DateTime]::Parse((Get-Content $LaneBStamp -Raw).Trim())).TotalMinutes
        Write-Log "[Lane-B] Interval not yet due ($minSince min since last run, need $LaneBIntervalMin min) — skipping"
    }
} else {
    Write-Log "[Lane-B] Outside working hours ($(Get-Date -Format 'HH:mm'), window 08:00-16:00) — skipping"
}

Write-Log "Scheduler run complete."
exit 0
