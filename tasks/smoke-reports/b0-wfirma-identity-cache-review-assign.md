# Smoke report — B0 wFirma identity cache + review-and-assign

**Date:** 2026-05-16
**PRs merged:** #141 (feature) + #142 (hotfix)
**Merge SHAs:** 08529b3 → ad82ab6 (post-hotfix)
**Production SHA after deploy:** ad82ab6
**Service:** PZService RUNNING

## Files deployed (robocopy /XO)
- `service/app/core/config.py`
- `service/app/services/suppliers_db.py`
- `service/app/api/routes_suppliers.py`
- `service/app/api/routes_wfirma_capabilities.py`
- `service/app/static/dashboard.html`
- (5 files copied first pass, dashboard re-copied after hotfix)

## Gates
| Gate | Result |
|---|---|
| `test_master_data_suppliers_wfirma_sync.py` | **26/26** ✓ |
| `test_dashboard_master_design.py` + `test_master_data_hard_rules.py` | **116/116** ✓ (1 pre-existing baseline failure `test_b9_carriers_config_does_not_touch_runtime` deselected — confirmed unrelated, fails on main without these changes) |
| `python test_pz_regression.py` (pre-deploy) | **160/160** ✓ |
| `python test_pz_regression.py` (post-deploy) | **160/160** ✓ |
| `campaign_status doctor` | clean ✓ |

## Smoke results (production, flags default-OFF)

### 1. Preview endpoint (suppliers) — read-only
```
GET  /api/v1/suppliers/sync-from-wfirma/preview
→ 200, ok=true, mode=preview, fetched=221, proposals_count=221
   statuses: new_candidate=211, skipped_invalid=10
```

### 2. Apply suppliers with flag OFF — blocked-state
```
POST /api/v1/suppliers/sync-from-wfirma/apply
body: {"wfirma_ids":["999999-nonexistent"]}
→ 200, ok=false, mode=blocked, applied_count=0
   blocking_reasons: "wfirma_sync_suppliers_allowed is false — operator must enable WFIRMA_SYNC_SUPPLIERS_ALLOWED to apply"
```

### 3. No supplier rows inserted by smoke
```
GET /api/v1/suppliers/ → suppliers total=0
```

### 4. Preview endpoint (customers) — read-only
```
GET  /api/v1/wfirma/customers/sync-from-wfirma/preview
→ 200, ok=true, mode=preview, fetched=221, proposals_count=218
   statuses: needs_operator_review=4, new_candidate=214
```

### 5. Apply customers with flag OFF — blocked-state
```
POST /api/v1/wfirma/customers/sync-from-wfirma/apply
body: {"wfirma_ids":["999999-nonexistent"]}
→ 200, ok=false, mode=blocked, applied_count=0
   blocking_reasons: "wfirma_sync_customers_allowed is false — operator must enable WFIRMA_SYNC_CUSTOMERS_ALLOWED to apply"
```

### 6. Stderr clean
```
INFO:     Started server process [1124]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:47213
```
No tracebacks. No wfirma-write log lines. No finance_dual_write log lines.

### 7. Health
- local `/api/v1/health` → 200 ✓
- public `https://pz.estrellajewels.eu/api/v1/health` → 200 ✓

### 8. Browser steps (manual — operator follow-up)
- Master Data → **Suppliers** → click "Fetch suppliers from wFirma" → review table with 221 rows expected
- Master Data → **Customer Master** → click "Fetch customers from wFirma" → review table with 218 rows expected (hotfix #142 corrected the URL)
- Skip action dims row and excludes from Assign-all
- Save / Assign with flag OFF surfaces the blocked alert

## Defect found and corrected
PR #141 dashboard buttons + test allow-lists used `/api/v1/wfirma/capabilities/customers/...` but the router prefix is `/api/v1/wfirma` only. Customer Master button was 404 in production until hotfix PR #142. Suppliers buttons were unaffected.

Root cause: developer confusion between file name (`routes_wfirma_capabilities.py`) and router prefix (`/api/v1/wfirma`). Fixed in PR #142 and re-verified live.

## What is live
- Suppliers Fetch button → opens review panel (preview only, no write)
- Customer Master Fetch button → opens review panel (preview only, no write)
- Per-row View / Edit / Save-Assign / Skip in both panels
- Backend endpoints (preview + apply) registered and serving
- Status enum: matched_existing / new_candidate / needs_operator_review / skipped_invalid / blocked_by_flag

## What is blocked by flag (default-OFF)
- `WFIRMA_SYNC_SUPPLIERS_ALLOWED` — write to `suppliers.sqlite`
- `WFIRMA_SYNC_CUSTOMERS_ALLOWED` — write to `wfirma_customers` (master_data.sqlite)

Apply endpoints respond `{mode: "blocked", applied_count: 0, blocking_reasons: [...]}` until operator flips the flag.

## What was NOT touched
- KYC fields (eori, address, contact_email, contact_phone, notes) — preserved on apply by design (test-asserted)
- Shipping addresses (`customer_master.shipping_addresses`)
- Carrier accounts (`customer_master.carrier_accounts`)
- Proforma routes / wFirma invoice posting
- PZ engine / landed-cost calculation
- DHL / customs / shipment routes
- Finance ledger / dual-write
- product_identity_engine
- `.env`
- Production DB files (no copy committed)

## Risks
- Apply endpoints are gated and idempotent; manual flag flip required before any real write.
- Robocopy `/XO` only copies newer; no destructive sync.
- No wFirma write call introduced in supplier cache files (source-grep guard test in suite).

## Lesson surfaced for tasks/lessons.md
Router file name (e.g. `routes_wfirma_capabilities.py`) is NOT the same as its mount prefix (`/api/v1/wfirma`). Always verify URLs against `router = APIRouter(prefix=...)` declaration before wiring frontend buttons or test allow-lists. PR #141 → #142 was caused by this confusion. Cheap mitigation: add a contract test that spins up the FastAPI app and asserts every URL the dashboard references resolves to a registered route.

## Next batch (gated — do NOT start without operator green-light)
- Operator drives one real review session via the live UI to validate classification correctness on real data.
- After confirmation, operator flips `WFIRMA_SYNC_SUPPLIERS_ALLOWED=true` and applies a small selected subset.
- Mirror flow for `WFIRMA_SYNC_CUSTOMERS_ALLOWED=true`.
- Only after both flag-on validations: packing-list contractor resolver design (separate batch).

## Current status
- PR #141: MERGED
- PR #142 (hotfix): MERGED
- Production: live, flags OFF
- Smoke: PASS (10/10 phase-5 checks)
- Operator action required: browser validation of review panels (manual steps 4–5)
