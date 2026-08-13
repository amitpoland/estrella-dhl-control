# Measure-B008-B009-AppDebt.ps1
# READ-ONLY classifier for owed B-008/B-009 App deployment debt.
# Run on the Windows production host (Estrella). Does NOT sync, restart, or write.
#
# Usage (elevated not required for measure):
#   powershell -NoProfile -ExecutionPolicy Bypass -File C:\PZ-main\.claude\deploy\Measure-B008-B009-AppDebt.ps1
#
# Expected tip (docs tip at authorship): 965344452c81a7f2e26ac90b39a3b60ff738277a
# Exact App files (#1218 + #1220):
#   app\api\routes_contractor_projection.py
#   app\services\proforma_invoice_link_db.py
#   app\static\shipment-detail.html
# Engine delta vs 80b7ae09: NONE → App-only if deploy needed.

$ErrorActionPreference = "Stop"
$TipExpected = "965344452c81a7f2e26ac90b39a3b60ff738277a"
$AppRel = @(
  "api\routes_contractor_projection.py",
  "services\proforma_invoice_link_db.py",
  "static\shipment-detail.html"
)
$TipSha256 = @{
  "api\routes_contractor_projection.py" = "5b0de4cf5ab5779cbda668998df3ca438cc1825fa2ff0a3371b7682f2183671b"
  "services\proforma_invoice_link_db.py" = "dd4af5a77a1877bf31fdea5dabccbc486ddfc17cf48bcb9ad614c13e41ae2bb4"
  "static\shipment-detail.html"         = "ab658d17d97879b039722519e4ac0fbb073c01e7bb8ac6b4f2897c65e624e718"
}

function Get-FileSha256([string]$Path) {
  if (-not (Test-Path -LiteralPath $Path)) { return $null }
  return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash.ToLowerInvariant()
}

Write-Host "=== B-008/B-009 App debt measure (READ-ONLY) ==="
$verPath = "C:\PZ\version.txt"
$prodSha = if (Test-Path $verPath) { (Get-Content -LiteralPath $verPath -Raw).Trim() } else { "<MISSING>" }
Write-Host "C:\PZ\version.txt      : $prodSha"

Push-Location C:\PZ-main
try {
  git fetch origin main | Out-Null
  $mainSha = (git rev-parse origin/main).Trim()
} finally { Pop-Location }
Write-Host "origin/main            : $mainSha"
if ($mainSha -ne $TipExpected) {
  Write-Host "NOTE: tip moved past authored expected $TipExpected — re-hash App files from C:\PZ-main before sync."
}

# NSSM / service
$svc = Get-Service -Name PZService -ErrorAction SilentlyContinue
Write-Host "PZService Status       : $(if ($svc) { $svc.Status } else { '<MISSING>' })"
try {
  $nssmApp = (& nssm get PZService Application 2>$null)
  $nssmDir = (& nssm get PZService AppDirectory 2>$null)
  $nssmArgs = (& nssm get PZService AppParameters 2>$null)
  Write-Host "NSSM Application       : $nssmApp"
  Write-Host "NSSM AppDirectory      : $nssmDir"
  Write-Host "NSSM AppParameters     : $nssmArgs"
} catch {
  Write-Host "NSSM                    : unavailable ($($_.Exception.Message))"
}

Write-Host ""
Write-Host "=== Hash compare (tip expected vs C:\PZ\app) ==="
$mismatch = 0
$missing = 0
foreach ($rel in $AppRel) {
  $prodPath = Join-Path "C:\PZ\app" $rel
  $srcPath  = Join-Path "C:\PZ-main\service\app" $rel
  $hProd = Get-FileSha256 $prodPath
  $hSrc  = Get-FileSha256 $srcPath
  $hTip  = $TipSha256[$rel]
  $ok = ($hProd -and $hSrc -and ($hProd -eq $hSrc))
  if (-not $hProd) { $missing++; $ok = $false }
  elseif ($hProd -ne $hSrc) { $mismatch++ }
  Write-Host ("{0}`n  prod={1}`n  main={2}`n  tip_pin={3}`n  match_prod_main={4}" -f $rel, $hProd, $hSrc, $hTip, $ok)
}

# Ride-along: App files between prod marker and tip (when prod SHA is a git object)
Write-Host ""
Write-Host "=== Ride-along App delta (prod marker → origin/main) ==="
$rideAlongCount = -1
if ($prodSha -match '^[0-9a-f]{7,40}$') {
  Push-Location C:\PZ-main
  try {
    $files = git diff --name-only "$prodSha..origin/main" -- service/app/ 2>$null
    if ($LASTEXITCODE -eq 0) {
      $list = @($files | Where-Object { $_ })
      $rideAlongCount = $list.Count
      Write-Host "App files changed: $rideAlongCount"
      $list | ForEach-Object { Write-Host "  $_" }
      $engine = git diff --name-only "$prodSha..origin/main" -- audit_agent.py audit_pdf.py correction_engine.py customs_description_engine.py description_grammar.py dhl_clearance_handler.py dhl_email_monitor.py dsk_generator.py escalation.py invoice_learning_agent.py learning_agent.py parser_fix_proposals.py polish_description_generator.py pz_dual_export.py pz_import_processor.py pz_pdf_export.py 2>$null
      $engList = @($engine | Where-Object { $_ })
      Write-Host "Engine files changed: $($engList.Count)"
      $engList | ForEach-Object { Write-Host "  ENGINE $_" }
    } else {
      Write-Host "Cannot diff $prodSha..origin/main (SHA not in this clone?)"
    }
  } finally { Pop-Location }
} else {
  Write-Host "Skip ride-along (production marker not a git SHA)."
}

# Classification
Write-Host ""
Write-Host "=== CLASSIFICATION ==="
$decision = "UNKNOWN"
if ($mismatch -eq 0 -and $missing -eq 0) {
  # Disk matches main App bytes for the three files — check if process needs reload
  # Heuristic: if version marker == main tip AND hashes match → ALREADY_LIVE candidate;
  # if hashes match but marker behind → still ALREADY_LIVE for these bytes (marker lag) or DEPLOY to stamp.
  if ($prodSha -eq $mainSha) {
    $decision = "ALREADY_LIVE_OR_RELOAD_ONLY"
    Write-Host "Disk hashes for B-008/B-009 App files match C:\PZ-main. Marker == tip."
    Write-Host "Next: confirm running process imported these modules (hit include_advisory routes)."
    Write-Host "If routes absent after healthy process → NSSM_PATH_HOLD."
    Write-Host "If routes present → ALREADY_LIVE (close debt without redeploy)."
    Write-Host "If routes stale while disk correct → RELOAD_ONLY (restart PZService; do NOT redeploy)."
  } else {
    $decision = "DISK_MATCH_MARKER_LAG"
    Write-Host "Disk hashes match main for the three App files, but version.txt ($prodSha) != tip ($mainSha)."
    Write-Host "Do NOT redeploy solely to repair a stale process. Prefer RELOAD_ONLY + stamp/reconcile per Deploy-PZ rules."
  }
} else {
  $decision = "DEPLOY_REQUIRED"
  Write-Host "DISK BEHIND required App bytes → DEPLOY_REQUIRED (App-only)."
  if ($rideAlongCount -gt 3) {
    Write-Host "HOLD RISK: ride-along App file count=$rideAlongCount (>3). Gate FULL production→tip payload before Release."
  } elseif ($rideAlongCount -eq 3 -or $rideAlongCount -eq -1) {
    Write-Host "Ride-along looks like B-008/B-009-only (or unmeasured). Gate App payload then:"
    Write-Host "  cd C:\PZ-main; git pull --ff-only origin main"
    Write-Host "  # seven-agent GO on frozen tip, then:"
    Write-Host "  powershell -NoProfile -ExecutionPolicy Bypass -File .\.claude\deploy\Deploy-PZ.ps1 -Release -Scope App"
  }
}

Write-Host ""
Write-Host "DECISION=$decision"
Write-Host "External writes required for measure: 0"
Write-Host "Do not start B-011 until deployment debt is CLOSED on this host."
