# Deploy Delta Manifest — PR #233
# Campaign 12: Proforma preview gate separation
# Feature commit: 3f61fd0 (on feat/c12-preview-gate-separation)
# Base: origin/main HEAD after PR #233 merge (merge commit SHA — run `git rev-parse --short HEAD` post-merge)
# Windows current: a20e5a2 (10-file deploy from Campaign 9/10)
# Profile: windows_prod_v2

## What changed

PR #233 modifies exactly 1 runtime file:

| # | Source dir | File | Destination dir | Note |
|---|------------|------|-----------------|------|
| 1 | `service\app\api` | `routes_proforma.py` | `C:\PZ\app\api` | Preview gate separation |

Test files changed (no deploy needed — tests only):
- `service/tests/test_proforma_preview_gate_separation.py` — new tests
- `service/tests/test_proforma_warehouse_gate.py` — updated existing test

## What changed in routes_proforma.py

Three new functions / constants added (no existing function signatures changed):

1. `_check_proforma_export_prerequisites(batch_id)` — new; carries wFirma PZ
   requirement that was incorrectly inside preview path; called ONLY for create
2. `_derive_batch_lifecycle(batch_id)` — new; returns DHL_TRANSIT when
   inventory_state rows=0 AND clearance_status in transit set
3. `_LIFECYCLE_TRANSIT_STATUSES` — new frozenset constant

`_check_warehouse_readiness()` — removed check #1 (wfirma_pz_doc_id); now
only checks product resolution + price conflicts

`_build_preview()` response extended with new fields:
- `can_preview` (bool) — True when sales rows exist; independent of PZ state
- `export_blockers` (list) — gates for wFirma create only
- `warehouse_blockers` (list) — subset of blocking_reasons
- `batch_lifecycle` (str) — POST_IMPORT / DHL_TRANSIT / PRE_IMPORT / UNKNOWN

`ready` logic: `ready = not blocking_reasons and not export_blockers`

## Pre-deploy steps (Windows)

```powershell
# 1. Merge PR #233 on GitHub (operator action)
# 2. On Windows machine:
git fetch origin
git pull --ff-only origin main
$headSha = git rev-parse --short HEAD
Write-Host "HEAD after pull: $headSha"

# 3. Verify make verify passes on Windows (optional — runs Python pytest)
# python -m pytest service/tests/ -q

# 4. Stop service
nssm stop PZService
Start-Sleep -Seconds 3
```

## Deploy (1 file)

```powershell
$PYTHON   = "C:\Users\Super Fashion\AppData\Local\Programs\Python\Python39\python.exe"
$APP_ROOT = "C:\PZ\app"
$REPO_SRC = "C:\Users\Super Fashion\PZ APP\service"

robocopy "$REPO_SRC\app\api" "$APP_ROOT\api" "routes_proforma.py" /COPY:DAT
Write-Host " [1/1] routes_proforma.py → $APP_ROOT\api\" -ForegroundColor Green
```

## Post-deploy

```powershell
nssm start PZService
Start-Sleep -Seconds 5
$status = nssm status PZService
Write-Host "Service status: $status"
if ($status -notmatch "SERVICE_RUNNING") {
    Write-Host "ROLLBACK: robocopy C:\PZ\app\bak C:\PZ\app /COPY:DAT /E" -ForegroundColor Red
    exit 1
}

# Health checks
Invoke-WebRequest -Uri "http://localhost:47213/health" -UseBasicParsing -TimeoutSec 10
Invoke-WebRequest -Uri "http://localhost:47213/api/v1/health" -UseBasicParsing -TimeoutSec 10
```

## Smoke checks

- [ ] Preview proforma for batch SHIPMENT_4218922912_2026-05_9040dd39 (AWB 4218922912)
      → `can_preview: true` in response
      → `batch_lifecycle: "DHL_TRANSIT"` (clearance_status=dsk_generated, no inventory rows)
      → Diamond Point lines: `stock_status: "dhl_transit"`, `stock_ok: true`
      → `export_blockers`: mentions "proforma export requires wFirma PZ"
      → `blocking_reasons`: empty (no warehouse blocking)
- [ ] Preview proforma for any existing batch with PZ doc
      → `ready: true`, `can_preview: true`, `export_blockers: []`
- [ ] Create proforma with no PZ doc → still blocked (export_blockers gate active)
- [ ] No regression on existing proforma flows (Diamond Point, Verhoeven, etc.)

## Safety invariants (unchanged)

- `_guard_wfirma_export` in routes_wfirma.py: UNCHANGED — still raises 422 when ZC429 missing
- `WFIRMA_CREATE_PZ_ALLOWED=False`: UNCHANGED
- No real wFirma writes introduced
- No customer auto-assignment

## Gate results

| Agent | Verdict |
|-------|---------|
| Test suite (244/244) | PASS |
| Proforma suite (338/338) | PASS |
| C12 specific (8/8) | PASS |
| Safety invariants | CLEAR — no write gates modified |
| PR #233 mergeable | YES (GitHub confirms MERGEABLE) |

## Rollback

```powershell
# Restore previous routes_proforma.py from backup
robocopy "C:\PZ\app\bak\api" "C:\PZ\app\api" "routes_proforma.py" /COPY:DAT
nssm restart PZService
```
