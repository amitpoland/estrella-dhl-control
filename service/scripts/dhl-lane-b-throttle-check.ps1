# Behavioral check for the Lane B throttle in dhl-email-auto-scan.ps1.
# Run: powershell -File scripts/dhl-lane-b-throttle-check.ps1  (exit 0 = pass).
# Dot-sources the shipped functions; never touches C:PZ (stamp -> TEMP).
# Original header: throttle + working-hours gate + independence.
# Dot-sources the real script's functions by extracting them, then exercises them.
$ErrorActionPreference = "Stop"
$src = Get-Content -Raw "$PSScriptRoot\dhl-email-auto-scan.ps1"

# Pull the three functions + the Lane B config vars out of the real file so we
# test the shipped code, not a copy. Stop before the main body runs.
$cut = $src.IndexOf('Write-Log "[Lane-A] Starting')
$prelude = $src.Substring(0, $cut)
Invoke-Expression $prelude

$fail = 0
function Check($label, $got, $want) {
    $ok = ($got -eq $want)
    "{0,-34} got={1,-6} want={2,-6} {3}" -f $label, $got, $want, ($(if($ok){"OK"}else{"FAIL"}))
    if (-not $ok) { $script:fail++ }
}

# Redirect the stamp to a temp file so we never touch C:\PZ.
$script:LaneBStamp = Join-Path $env:TEMP ("laneb_" + [guid]::NewGuid() + ".txt")

Check "no stamp -> due"        (Test-LaneBDue) $true
(Get-Date).AddMinutes(-30).ToString("yyyy-MM-ddTHH:mm:ss") | Set-Content $LaneBStamp
Check "30 min ago -> not due"  (Test-LaneBDue) $false
(Get-Date).AddMinutes(-90).ToString("yyyy-MM-ddTHH:mm:ss") | Set-Content $LaneBStamp
Check "90 min ago -> due"      (Test-LaneBDue) $true
"garbage!!" | Set-Content $LaneBStamp
Check "garbled stamp -> due"   (Test-LaneBDue) $true
Set-LaneBStamp
Check "stamp writes"           (Test-Path $LaneBStamp) $true
Check "fresh stamp -> not due" (Test-LaneBDue) $false

# Working-hours gate: force known times via a fixed reference is hard without
# mocking Get-Date; instead assert the function is boolean and matches its own
# rule for the current moment.
$now = Get-Date
$expected = -not ($now.DayOfWeek -in "Saturday","Sunday") -and $now.Hour -ge $WorkStart -and $now.Hour -lt $WorkEnd
Check "working-hours self-consistent" (Test-WorkingHours) $expected

Remove-Item $LaneBStamp -Force -ErrorAction SilentlyContinue
if ($fail -gt 0) { "RESULT: $fail FAILED"; exit 1 } else { "RESULT: all passed"; exit 0 }
