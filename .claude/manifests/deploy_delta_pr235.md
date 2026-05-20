# Deploy Delta Manifest — PR #235
# Campaign 13B: parser body-cell fallback for client name extraction
# Branch: feat/c13b-parser-body-fallback
# Merge commit: TBD (merge when operator approves)
# Base: origin/main HEAD after PR #234 merge (aaa898b)
# Profile: windows_prod_v2

## What changed

PR #235 modifies exactly 2 runtime files + 1 test file (no schema changes):

| # | Source dir | File | Destination dir | Note |
|---|------------|------|-----------------|------|
| 1 | `service\app\api` | `routes_packing.py` | `C:\PZ\app\api` | Upload path: C13B resolution block; reprocess: Pass 5; response: 2 new fields |
| 2 | `service\app\services` | `invoice_packing_extractor.py` | `C:\PZ\app\services` | _new_diagnostic() adds client_name_resolution placeholder |

Test file (no deploy needed):
- `service/tests/test_packing_client_name_parser.py` — 50 tests total (20 new C13B), all pass

## What changed in routes_packing.py

### Upload path (`upload_packing_list`)

After `process_packing_upload()` returns, new C13B block runs:
1. `_guess_client_from_filename(safe_name)` → tries filename suffix pattern
2. If empty → `_guess_client_from_preamble(str(dest_path))` → scans top-12 Excel rows for `Client:` / `Consignee:` / `Buyer:` / `Ship To:`
3. Injects `client_name_resolution` dict into `result["parser_diagnostic"]` and `result["document"]["parser_diagnostic"]`

Two new fields in upload response:
- `suggested_client_name`: resolved client name (or "")
- `client_name_resolution`: "filename" | "preamble" | "none"

No existing function signatures changed. No DB writes added. No inventory lifecycle touched.

### Reprocess path (sales_packing_list branch)

Pass 5 added after existing Pass 4 (filename hint at line ~1151):
- Calls `_guess_client_from_preamble(str(file_path))` when `preserved_client_name` still empty
- Guards: file_path must exist on disk; all errors swallowed (returns [] on any failure)
- Logged as "Pass 5 — body-cell fallback"

## What changed in invoice_packing_extractor.py

`_new_diagnostic()` extended with one new key:
```python
"client_name_resolution": None,  # C13B — injected by routes_packing after extraction
```

No other changes. `extract_packing()` unchanged. `process_packing_upload()` unchanged.

## Pre-deploy steps (Windows)

```powershell
# Prerequisites: PR #233 + PR #234 must already be deployed
# 1. Pull merged main on Windows:
git fetch origin
git pull --ff-only origin main
$headSha = git rev-parse --short HEAD
Write-Host "HEAD after pull: $headSha"   # expect merge commit of PR #235 or later

# 2. Stop service
nssm stop PZService
Start-Sleep -Seconds 3
```

## Deploy (2 files)

```powershell
$APP_ROOT = "C:\PZ\app"
$REPO_SRC = "C:\Users\Super Fashion\PZ APP\service"

robocopy "$REPO_SRC\app\api" "$APP_ROOT\api" "routes_packing.py" /COPY:DAT
Write-Host " [1/2] routes_packing.py → $APP_ROOT\api\" -ForegroundColor Green

robocopy "$REPO_SRC\app\services" "$APP_ROOT\services" "invoice_packing_extractor.py" /COPY:DAT
Write-Host " [2/2] invoice_packing_extractor.py → $APP_ROOT\services\" -ForegroundColor Green
```

## Post-deploy

```powershell
nssm start PZService
Start-Sleep -Seconds 5
$status = nssm status PZService
Write-Host "Service status: $status"
if ($status -notmatch "SERVICE_RUNNING") {
    Write-Host "ROLLBACK: robocopy C:\PZ\app\bak\api C:\PZ\app\api routes_packing.py /COPY:DAT" -ForegroundColor Red
    Write-Host "ROLLBACK: robocopy C:\PZ\app\bak\services C:\PZ\app\services invoice_packing_extractor.py /COPY:DAT" -ForegroundColor Red
    exit 1
}
Invoke-WebRequest -Uri "http://localhost:47213/health" -UseBasicParsing -TimeoutSec 10
Invoke-WebRequest -Uri "http://localhost:47213/api/v1/health" -UseBasicParsing -TimeoutSec 10
```

## Smoke check — invoice 178 orphan file

Upload `EJL-26-27-178-Packing list of shipment-1pc-16-05-26-Client.xlsx` containing
a row/cell with `Client: Diamond Point` in the top 12 rows:

Expected upload response:
```json
{
  "ok": true,
  "suggested_client_name": "Diamond Point",
  "client_name_resolution": "preamble",
  "total_rows": 1,
  ...
}
```

If the Excel file has no `Client:` / `Consignee:` / `Buyer:` / `Ship To:` preamble:
```json
{
  "ok": true,
  "suggested_client_name": "",
  "client_name_resolution": "none"
}
```
→ Operator must assign client manually (existing flow, unchanged).

Upload file with normal pattern `148 Client SUOKKO.xlsx`:
```json
{
  "suggested_client_name": "SUOKKO",
  "client_name_resolution": "filename"
}
```
→ Confirms filename path still works (no regression).

## Safety invariants confirmed (unchanged)

- `_guard_wfirma_export` in routes_wfirma.py: UNCHANGED
- `WFIRMA_CREATE_PZ_ALLOWED=False`: UNCHANGED
- `transition()` in inventory_state_engine.py: UNCHANGED
- DHL orchestrator flags: UNCHANGED
- Queue/email paths: UNCHANGED
- DB schema: UNCHANGED (no migrations)
- Orphan Assign Client UI: UNCHANGED
- PZ creation flow: UNCHANGED
- No production data mutations

## Rollback

```powershell
robocopy "C:\PZ\app\bak\api" "C:\PZ\app\api" "routes_packing.py" /COPY:DAT
robocopy "C:\PZ\app\bak\services" "C:\PZ\app\services" "invoice_packing_extractor.py" /COPY:DAT
nssm restart PZService
```
