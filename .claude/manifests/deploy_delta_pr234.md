# Deploy Delta Manifest — PR #234
# Campaign 13A: read-only PURCHASE_TRANSIT projection for in-transit batches
# Merge commit: aaa898b (2026-05-20T01:02:01Z)
# Base: origin/main HEAD after PR #234 merge
# Windows current: a20e5a2 (10-file deploy from Campaign 9/10)
#   + routes_proforma.py from PR #233 (deploy_delta_pr233.md)
# Profile: windows_prod_v2

## What changed

PR #234 modifies exactly 2 runtime files (no schema changes):

| # | Source dir | File | Destination dir | Note |
|---|------------|------|-----------------|------|
| 1 | `service\app\services` | `inventory_state_engine.py` | `C:\PZ\app\services` | New projector function + constants |
| 2 | `service\app\services` | `inventory_batch_state.py` | `C:\PZ\app\services` | Wire projector into batch-state reader |

Test file added (no deploy needed):
- `service/tests/test_inventory_state_transit_projection.py` — 15 tests, all pass

## What changed in inventory_state_engine.py

New constants (additive):
- `_LIFECYCLE_TRANSIT_STATUSES: frozenset` — active-flight clearance statuses
- `_LIFECYCLE_TERMINAL_STATUSES: frozenset` — closed/archived statuses that suppress projection

New function (additive):
- `derive_purchase_transit_projection(batch_id, audit, packing_lines) -> List[Dict]`
  - READ-ONLY pure function — opens no DB connection
  - Returns [] on: malformed audit, empty packing lines, terminal status, unknown status
  - Returns synthetic PURCHASE_TRANSIT rows when clearance_status in transit set

No change to: `transition()`, `get_state()`, `list_by_state()`, `count_by_state()`, `get_history()`.
No DB schema change. No INSERT/UPDATE/DELETE added.

## What changed in inventory_batch_state.py

`get_batch_state()` extended:
- Response now includes `synthetic: bool` and `source: str` fields
- When `real_total == 0`: calls `_try_purchase_transit_projection()` (safe, returns [] on any error)
- When projection returns rows: `counts[PURCHASE_TRANSIT] = len(projection)`, `synthetic=True`, `source="audit.tracking"`
- Real rows always win — projection called ONLY when real_total == 0

New helpers (additive):
- `_try_purchase_transit_projection(batch_id)` — wraps engine projector; returns [] on any error
- `_read_audit_safe(batch_id)` — reads audit.json; returns None on any error

## Pre-deploy steps (Windows)

```powershell
# Prerequisites: PR #233 must already be deployed (routes_proforma.py)
# 1. Pull merged main on Windows:
git fetch origin
git pull --ff-only origin main
$headSha = git rev-parse --short HEAD
Write-Host "HEAD after pull: $headSha"   # expect aaa898b or later

# 2. Stop service
nssm stop PZService
Start-Sleep -Seconds 3
```

## Deploy (2 files)

```powershell
$APP_ROOT = "C:\PZ\app"
$REPO_SRC = "C:\Users\Super Fashion\PZ APP\service"

robocopy "$REPO_SRC\app\services" "$APP_ROOT\services" "inventory_state_engine.py" /COPY:DAT
Write-Host " [1/2] inventory_state_engine.py → $APP_ROOT\services\" -ForegroundColor Green

robocopy "$REPO_SRC\app\services" "$APP_ROOT\services" "inventory_batch_state.py" /COPY:DAT
Write-Host " [2/2] inventory_batch_state.py → $APP_ROOT\services\" -ForegroundColor Green
```

## Post-deploy

```powershell
nssm start PZService
Start-Sleep -Seconds 5
$status = nssm status PZService
Write-Host "Service status: $status"
if ($status -notmatch "SERVICE_RUNNING") {
    Write-Host "ROLLBACK: robocopy C:\PZ\app\bak\services C:\PZ\app\services inventory_state_engine.py inventory_batch_state.py /COPY:DAT" -ForegroundColor Red
    exit 1
}
Invoke-WebRequest -Uri "http://localhost:47213/health" -UseBasicParsing -TimeoutSec 10
Invoke-WebRequest -Uri "http://localhost:47213/api/v1/health" -UseBasicParsing -TimeoutSec 10
```

## Smoke check — Lapis batch (AWB 4218922912)

```
GET /api/v1/inventory/state/SHIPMENT_4218922912_2026-05_9040dd39
```

Expected response structure:
```json
{
  "batch_id": "SHIPMENT_4218922912_2026-05_9040dd39",
  "synthetic": true,
  "source": "audit.tracking",
  "total": 30,
  "counts": {
    "PURCHASE_TRANSIT": 30,
    "WAREHOUSE_STOCK": 0,
    ...
  },
  "pieces": [
    {
      "scan_code": "...",
      "state": "PURCHASE_TRANSIT",
      "synthetic": true,
      "source": "audit.tracking"
    },
    ...
  ]
}
```

If batch has been warehouse-scanned since C13A was implemented (real rows exist), response will show:
```json
{ "synthetic": false, "source": "inventory_state", "total": <actual_count> }
```
Real rows always override the projection — this is correct behavior.

## Safety invariants confirmed (unchanged)

- `_guard_wfirma_export` in routes_wfirma.py: UNCHANGED
- `WFIRMA_CREATE_PZ_ALLOWED=False`: UNCHANGED
- `transition()` in inventory_state_engine.py: UNCHANGED
- DHL orchestrator flags: UNCHANGED
- Queue/email paths: UNCHANGED
- DB schema: UNCHANGED (no migrations)
- Projector opens ZERO write connections to inventory_state

## Rollback

```powershell
robocopy "C:\PZ\app\bak\services" "C:\PZ\app\services" "inventory_state_engine.py" "inventory_batch_state.py" /COPY:DAT
nssm restart PZService
```
