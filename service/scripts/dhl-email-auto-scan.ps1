#Requires -Version 5.1
<#
.SYNOPSIS
  DHL Email Automation Scheduler — Lane A (10 min) + Lane B (60 min, working hours).

.DESCRIPTION
  Called by Windows Task Scheduler every 10 minutes.
  Lane A (inbox scan) runs every call.
  Lane B (follow-up) runs only during Warsaw working hours 08:00-16:00.

  Both lanes respect server-side kill switches (DHL_AUTO_SCAN_ENABLED,
  DHL_FOLLOWUP_ENABLED) configured in C:\PZ\.env. If a switch is false,
  the endpoint returns immediately without processing.

  Lanes are independent — a Lane A failure does NOT prevent Lane B.

.NOTES
  Logs to C:\PZ\logs\dhl-auto-scan.log.
  API key read from C:\PZ\.env (never hardcoded).

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

# ── Config ────────────────────────────────────────────────────────────────────
$ApiBase        = "http://127.0.0.1:47213"
$LaneAEndpoint  = "$ApiBase/api/v1/dhl/scheduled-inbox-check"
$LaneBEndpoint  = "$ApiBase/api/v1/dhl/scheduled-followup-check"
$EnvFile        = "C:\PZ\.env"
$LogDir         = "C:\PZ\logs"
$LogFile        = "$LogDir\dhl-auto-scan.log"
$TimeoutSec     = 120
$WorkStart      = [TimeSpan]"08:00:00"
$WorkEnd        = [TimeSpan]"16:00:00"

# ── Logging ───────────────────────────────────────────────────────────────────
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

# ── API key ───────────────────────────────────────────────────────────────────
if (-not (Test-Path $EnvFile)) {
    Write-Log "ENV file not found: $EnvFile" "ERROR"; exit 1
}
try {
    $ApiKey = (Select-String "^API_KEY=" $EnvFile -ErrorAction Stop).Line.Split("=", 2)[1].Trim()
} catch {
    Write-Log "Failed to read API_KEY from $EnvFile" "ERROR"; exit 1
}
if ([string]::IsNullOrEmpty($ApiKey)) {
    Write-Log "API_KEY is empty in $EnvFile" "ERROR"; exit 1
}

# ── Working hours ─────────────────────────────────────────────────────────────
function Test-WorkingHours {
    $now = (Get-Date).TimeOfDay
    return ($now -ge $WorkStart -and $now -lt $WorkEnd)
}

# ── HTTP helper ───────────────────────────────────────────────────────────────
function Invoke-SchedulerEndpoint {
    param([string]$Url, [string]$Lane)
    try {
        $resp = Invoke-WebRequest `
            -Uri $Url -Method POST `
            -Headers @{ "X-API-Key" = $ApiKey } `
            -UseBasicParsing -TimeoutSec $TimeoutSec
        $body = $resp.Content | ConvertFrom-Json

        if ($body.skipped) {
            Write-Log "[$Lane] skipped: $($body.skipped)"
            return
        }

        $laneAMsg = "checked=$($body.batches_checked) " +
                    "received_set=$($body.received_set) " +
                    "b2_triggered=$($body.b2_triggered) b2_sent=$($body.b2_sent) " +
                    "skipped_inactive=$($body.skipped_inactive) " +
                    "skipped_excluded=$($body.skipped_excluded) " +
                    "errors=$($body.errors.Count)"
        Write-Log "[$Lane] done: $laneAMsg"

        if ($null -ne $body.followup_sent) {
            Write-Log ("[$Lane] followup: started=$($body.followup_started) " +
                       "sent=$($body.followup_sent) stopped=$($body.followup_stopped)")
        }
        if ($body.errors.Count -gt 0) {
            $body.errors | ForEach-Object { Write-Log "  [$Lane] error: $_" "WARN" }
        }
    }
    catch {
        Write-Log "[$Lane] HTTP failed: $_" "ERROR"
    }
}

# ── Lane A — DHL inbox scan (every 10 min) ────────────────────────────────────
Write-Log "[Lane-A] Starting DHL inbox scan..."
Invoke-SchedulerEndpoint -Url $LaneAEndpoint -Lane "A"

# ── Lane B — DHL follow-up (working hours only) ───────────────────────────────
if (Test-WorkingHours) {
    Write-Log "[Lane-B] Working hours — running follow-up check..."
    Invoke-SchedulerEndpoint -Url $LaneBEndpoint -Lane "B"
} else {
    Write-Log "[Lane-B] Outside working hours ($(Get-Date -Format 'HH:mm'), window 08:00-16:00) — skipped"
}

Write-Log "Scheduler run complete."
exit 0
