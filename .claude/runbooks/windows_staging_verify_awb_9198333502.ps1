# windows_staging_verify_awb_9198333502.ps1
#
# Staging verification runbook for AWB 9198333502 — compliance_intelligence_resolver
# feature (COMPLIANCE_INTELLIGENCE_RESOLVER_ENABLED).
#
# PURPOSE
#   Verify that the new compliance resolver feature works correctly on the
#   Windows staging environment for AWB 9198333502, which has:
#     importer_match: null, exporter_match: null, qty_match_by_type: null,
#     vat_match: true
#
# SAFETY GATES
#   - DO NOT run on production (C:\PZ).  Staging only.
#   - DO NOT enable the flag on production.
#   - audit.verification must remain unmodified after every step.
#   - All checks are READ-ONLY against a staging service instance.
#
# PREREQUISITES
#   1. Staging service running on localhost:47214 (NOT 47213 = production)
#   2. AWB 9198333502 batch already processed and audit.json present
#   3. PowerShell 5.1+ with Invoke-RestMethod available
#   4. $env:STAGING_API_KEY set to the staging API key
#   5. $env:STAGING_BATCH_ID set to the batch_id for AWB 9198333502
#      (check storage/outputs/ folder on the staging machine)
#
# USAGE
#   $env:STAGING_API_KEY = "your-staging-key"
#   $env:STAGING_BATCH_ID = "9198333502_<date>"
#   .\windows_staging_verify_awb_9198333502.ps1
#
# EXIT CODES
#   0 = all checks passed
#   1 = one or more checks failed

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$StagingBase   = "http://localhost:47214"
$BatchId       = $env:STAGING_BATCH_ID
$ApiKey        = $env:STAGING_API_KEY
$StagingRoot   = "C:\PZ-STAGING"    # staging storage root — NOT C:\PZ
$AuditPath     = "$StagingRoot\outputs\$BatchId\audit.json"

$PASS = "[PASS]"
$FAIL = "[FAIL]"
$INFO = "[INFO]"

$failed = 0

function Check($label, $ok, $detail = "") {
    if ($ok) {
        Write-Host "$PASS $label" -ForegroundColor Green
    } else {
        Write-Host "$FAIL $label — $detail" -ForegroundColor Red
        $script:failed++
    }
}

Write-Host ""
Write-Host "=== Compliance Intelligence Resolver — Staging Verification ===" -ForegroundColor Cyan
Write-Host "$INFO AWB: 9198333502 | Batch: $BatchId | Base: $StagingBase"
Write-Host ""

# ── STEP 0: Sanity — not pointing at production ───────────────────────────────
Write-Host "--- Step 0: Production safety check ---"
Check "StagingBase is NOT production port (47213)" ($StagingBase -notmatch ":47213")
Check "StagingRoot is NOT C:\PZ" ($StagingRoot -ne "C:\PZ")
Write-Host ""

# ── STEP 1: Confirm batch exists and has audit.json ──────────────────────────
Write-Host "--- Step 1: Audit file presence ---"
Check "audit.json exists on disk" (Test-Path $AuditPath)

$audit = $null
if (Test-Path $AuditPath) {
    $audit = Get-Content $AuditPath -Raw | ConvertFrom-Json
    Check "audit.json parseable" ($null -ne $audit)
}
Write-Host ""

# ── STEP 2: Pre-flag baseline — flag OFF ─────────────────────────────────────
Write-Host "--- Step 2: Baseline (flag OFF) ---"
$headers = @{ "X-API-Key" = $ApiKey }
$batchUrl = "$StagingBase/api/v1/dashboard/batches/$BatchId"

try {
    $resp = Invoke-RestMethod -Uri $batchUrl -Headers $headers -Method Get
    Check "batch_detail responds 200" $true
} catch {
    Check "batch_detail responds 200" $false "HTTP error: $_"
    Write-Host "$FAIL Cannot continue without batch_detail response." -ForegroundColor Red
    exit 1
}

Check "compliance_resolution ABSENT when flag OFF" ($null -eq $resp.compliance_resolution)
Check "verification.vat_match is true" ($resp.verification.vat_match -eq $true)
Check "verification.importer_match is null" ($null -eq $resp.verification.importer_match)
Check "verification.exporter_match is null" ($null -eq $resp.verification.exporter_match)
Check "verification.qty_match_by_type is null" ($null -eq $resp.verification.qty_match_by_type)
Write-Host ""

# ── STEP 3: Snapshot audit.verification before enabling flag ─────────────────
Write-Host "--- Step 3: Capture verification snapshot ---"
$snapImporter    = $resp.verification.importer_match
$snapExporter    = $resp.verification.exporter_match
$snapQty         = $resp.verification.qty_match_by_type
$snapVat         = $resp.verification.vat_match
Write-Host "$INFO Snapshot: importer=$snapImporter exporter=$snapExporter qty=$snapQty vat=$snapVat"
Write-Host ""

# ── STEP 4: Enable flag via staging env override and restart ──────────────────
Write-Host "--- Step 4: Enable flag in staging .env ---"
Write-Host "$INFO To enable: add COMPLIANCE_INTELLIGENCE_RESOLVER_ENABLED=1 to staging .env"
Write-Host "$INFO Then restart the staging service: nssm restart PZService-staging"
Write-Host "$INFO Press Enter after restarting the staging service..."
$null = Read-Host

# Re-query with flag enabled
try {
    $respFlagged = Invoke-RestMethod -Uri $batchUrl -Headers $headers -Method Get
    Check "batch_detail responds 200 with flag enabled" $true
} catch {
    Check "batch_detail responds 200 with flag enabled" $false "HTTP error: $_"
    exit 1
}

Write-Host ""

# ── STEP 5: compliance_resolution present and structured ─────────────────────
Write-Host "--- Step 5: compliance_resolution structure ---"
$cr = $respFlagged.compliance_resolution
Check "compliance_resolution present in response" ($null -ne $cr)

if ($null -ne $cr) {
    foreach ($field in @("importer_match", "exporter_match", "qty_match_by_type", "vat_match")) {
        $entry = $cr.$field
        Check "compliance_resolution.$field present" ($null -ne $entry)
        if ($null -ne $entry) {
            $validStates = @("engine_verified", "intelligence_resolved", "gap", "failed")
            Check "compliance_resolution.$field.state is valid enum" ($validStates -contains $entry.state)
        }
    }
}
Write-Host ""

# ── STEP 6: vat_match stays engine_verified ───────────────────────────────────
Write-Host "--- Step 6: vat_match = engine_verified ---"
if ($null -ne $cr -and $null -ne $cr.vat_match) {
    Check "vat_match.state = engine_verified" ($cr.vat_match.state -eq "engine_verified")
    Check "vat_match.confidence = deterministic" ($cr.vat_match.confidence -eq "deterministic")
}
Write-Host ""

# ── STEP 7: qty_match_by_type always stays gap ────────────────────────────────
Write-Host "--- Step 7: qty_match_by_type stays gap ---"
if ($null -ne $cr -and $null -ne $cr.qty_match_by_type) {
    Check "qty_match_by_type.state = gap (never intelligence_resolved)" ($cr.qty_match_by_type.state -eq "gap")
}
Write-Host ""

# ── STEP 8: importer_match and exporter_match resolved or gap ────────────────
Write-Host "--- Step 8: importer/exporter resolution ---"
if ($null -ne $cr) {
    $impState = if ($null -ne $cr.importer_match) { $cr.importer_match.state } else { "missing" }
    $expState = if ($null -ne $cr.exporter_match) { $cr.exporter_match.state } else { "missing" }
    Write-Host "$INFO importer_match.state = $impState"
    Write-Host "$INFO exporter_match.state = $expState"
    $allowedStates = @("intelligence_resolved", "gap")
    Check "importer_match.state is intelligence_resolved or gap" ($allowedStates -contains $impState)
    Check "exporter_match.state is intelligence_resolved or gap" ($allowedStates -contains $expState)
    if ($impState -eq "intelligence_resolved") {
        Write-Host "$INFO importer evidence: $($cr.importer_match.evidence)"
    }
    if ($expState -eq "intelligence_resolved") {
        Write-Host "$INFO exporter evidence: $($cr.exporter_match.evidence)"
    }
}
Write-Host ""

# ── STEP 9: audit.verification NOT mutated ────────────────────────────────────
Write-Host "--- Step 9: audit.verification immutability ---"
Check "verification.importer_match still null after flag enable" ($null -eq $respFlagged.verification.importer_match)
Check "verification.exporter_match still null after flag enable" ($null -eq $respFlagged.verification.exporter_match)
Check "verification.qty_match_by_type still null after flag enable" ($null -eq $respFlagged.verification.qty_match_by_type)
Check "verification.vat_match still true after flag enable" ($respFlagged.verification.vat_match -eq $true)

# Verify audit.json on disk also unmodified
if (Test-Path $AuditPath) {
    $auditAfter = Get-Content $AuditPath -Raw | ConvertFrom-Json
    Check "audit.json disk: importer_match still null" ($null -eq $auditAfter.verification.importer_match)
    Check "audit.json disk: exporter_match still null" ($null -eq $auditAfter.verification.exporter_match)
    Check "audit.json disk: qty_match_by_type still null" ($null -eq $auditAfter.verification.qty_match_by_type)
    Check "audit.json disk: vat_match still true" ($auditAfter.verification.vat_match -eq $true)
    Check "audit.json disk: compliance_resolution NOT written to disk" ($null -eq $auditAfter.compliance_resolution)
}
Write-Host ""

# ── STEP 10: Disable flag and confirm baseline restored ───────────────────────
Write-Host "--- Step 10: Disable flag and confirm baseline restored ---"
Write-Host "$INFO Remove COMPLIANCE_INTELLIGENCE_RESOLVER_ENABLED from staging .env"
Write-Host "$INFO Restart staging service: nssm restart PZService-staging"
Write-Host "$INFO Press Enter after restarting..."
$null = Read-Host

try {
    $respRestored = Invoke-RestMethod -Uri $batchUrl -Headers $headers -Method Get
    Check "batch_detail responds 200 after flag disable" $true
    Check "compliance_resolution absent after flag disable" ($null -eq $respRestored.compliance_resolution)
} catch {
    Check "batch_detail responds 200 after flag disable" $false "HTTP error: $_"
}
Write-Host ""

# ── SUMMARY ───────────────────────────────────────────────────────────────────
Write-Host "=== SUMMARY ===" -ForegroundColor Cyan
if ($failed -eq 0) {
    Write-Host "$PASS All checks passed. Feature verified for AWB 9198333502." -ForegroundColor Green
    Write-Host "$INFO DO NOT enable flag on production without operator sign-off."
} else {
    Write-Host "$FAIL $failed check(s) failed. DO NOT enable flag on production." -ForegroundColor Red
}
Write-Host ""

exit $failed
