#Requires -Version 5.1
<#
.SYNOPSIS
  DHL Email Auto-Scan — Lane A (inbox scan) + Lane B (follow-up) every 10 minutes.

.DESCRIPTION
  Lane A: POST /api/v1/dhl/scheduled-inbox-check           — every run (~10 min).
  Lane B: POST /api/v1/dhl/scheduled-followup-check         — throttled to 60 min.

  The lanes are independent: Lane B runs even if Lane A fails, in its own
  try/catch, and neither exits the script early.

  Lane B is throttled SCRIPT-SIDE to one call per LaneBIntervalMin (60) using a
  last-run stamp, and pre-filtered to working hours, purely to avoid needless
  wakeups. The SERVER is the authority on whether any follow-up is actually
  sent: /scheduled-followup-check honours its own DHL_FOLLOWUP_ENABLED kill
  switch, re-checks Warsaw working hours, enforces per-batch send preconditions
  (validate_followup_send_preconditions), and is idempotent via
  last_followup_sent_at + followup_count. So a too-eager script cannot
  double-send; a too-shy script only delays a follow-up to the next 10-min tick.

  Kill switches:
    - DHL_AUTO_SCAN_ENABLED=false in C:\PZ\.env → skips Lane A.
    - DHL_FOLLOWUP_ENABLED=false in C:\PZ\.env  → server returns immediately for Lane B.
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
$LaneBEndpoint = "$ApiBase/api/v1/dhl/scheduled-followup-check"
$EnvFile       = "C:\PZ\.env"
$LogDir        = "C:\PZ\logs"
$LogFile       = "$LogDir\dhl-auto-scan.log"
$TimeoutSec    = 300    # 5 min — ingestion cycle scans 25+ active batches via Zoho API

# ── Lane B throttle ───────────────────────────────────────────────────────────
# Task cadence is ~10 min; Lane B should fire at most hourly. A last-run stamp
# on disk enforces the interval across separate task invocations. Working hours
# are Warsaw wall-clock (matches WORK_START/WORK_END in dhl_followup_sla.py);
# the box is Europe/Warsaw, so local time is correct.
$LaneBIntervalMin = 60
$LaneBStamp       = "C:\PZ\storage\dhl_lane_b_last_run.txt"   # last-run timestamp
$WorkStart        = 8    # 08:00 Warsaw
$WorkEnd          = 16   # 16:00 Warsaw (exclusive)

function Test-WorkingHours {
    # Cheap pre-filter only — the server re-checks the precise Warsaw window and
    # owns the real decision. Weekdays 08:00–16:00 local.
    $now = Get-Date
    if ($now.DayOfWeek -eq "Saturday" -or $now.DayOfWeek -eq "Sunday") { return $false }
    return ($now.Hour -ge $WorkStart -and $now.Hour -lt $WorkEnd)
}

function Test-LaneBDue {
    # True when no stamp exists or the interval has elapsed. Never throws — an
    # unreadable/garbled stamp is treated as "due" so a follow-up is not stuck.
    if (-not (Test-Path $LaneBStamp)) { return $true }
    try {
        $last = [datetime]::Parse((Get-Content $LaneBStamp -Raw).Trim())
        return ((Get-Date) - $last).TotalMinutes -ge $LaneBIntervalMin
    } catch {
        return $true
    }
}

function Set-LaneBStamp {
    try {
        $dir = Split-Path $LaneBStamp -Parent
        if (-not (Test-Path $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
        (Get-Date -Format "yyyy-MM-ddTHH:mm:ss") | Set-Content $LaneBStamp -Encoding UTF8
    } catch {
        Write-Log "[Lane-B] failed to write last-run stamp: $_" "WARN"
    }
}

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

# ── Lane B: DHL follow-up SLA ─────────────────────────────────────────────────
# Independent of Lane A above: reached even if the Lane A call threw, and never
# exits the script on its own error. Throttled to LaneBIntervalMin and gated to
# working hours here; the server is the final authority on each send.
if (-not (Test-WorkingHours)) {
    Write-Log "[Lane-B] outside working hours — skipped."
} elseif (-not (Test-LaneBDue)) {
    Write-Log "[Lane-B] not due (last run < $LaneBIntervalMin min ago) — skipped."
} else {
    Write-Log "[Lane-B] Starting DHL follow-up check..."
    try {
        $respB = Invoke-WebRequest `
            -Uri $LaneBEndpoint -Method POST `
            -Headers @{ "X-API-Key" = $ApiKey } `
            -UseBasicParsing -TimeoutSec $TimeoutSec
        $bodyB = $respB.Content | ConvertFrom-Json
        if ($bodyB.skipped) {
            Write-Log "[Lane-B] skipped: $($bodyB.skipped)"
        } else {
            Write-Log ("[Lane-B] done: checked=$($bodyB.batches_checked) " +
                       "followup_started=$($bodyB.followup_started) " +
                       "followup_sent=$($bodyB.followup_sent) " +
                       "followup_stopped=$($bodyB.followup_stopped) " +
                       "suppressed=$($bodyB.followup_suppressed) " +
                       "skipped_inactive=$($bodyB.skipped_inactive) " +
                       "skipped_excluded=$($bodyB.skipped_excluded) " +
                       "errors=$($bodyB.errors.Count)")
            if ($bodyB.errors.Count -gt 0) {
                $bodyB.errors | ForEach-Object { Write-Log "  error: $_" "WARN" }
            }
        }
        # Stamp only on a completed call (success or server-side skip), so a
        # transport failure retries on the next 10-min tick rather than waiting
        # a full hour.
        Set-LaneBStamp
    } catch {
        Write-Log "[Lane-B] HTTP failed: $_" "ERROR"
    }
}

Write-Log "Scheduler run complete."
exit 0
