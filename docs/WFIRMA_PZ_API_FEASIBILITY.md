# wFirma PZ Warehouse Document — API Feasibility Assessment

**Date:** 2026-04-27  
**Scope:** Can PZ (Przyjęcie Zewnętrzne) documents be created via wFirma API?  
**Conclusion: BLOCKED — requires live endpoint verification before proceeding**

---

## Current Implementation Status

| Mode | Status | File |
|------|--------|------|
| Phase 1 — Clipboard Export | ✅ LIVE | `service/app/api/routes_wfirma.py` |
| Phase 1B — PZ_READY.json | ✅ LIVE | `service/app/api/routes_wfirma.py` |
| Phase 2 — Chrome AutoFill | ✅ READY | `chrome_wfirma_autofill/autofill_pz.js` |
| Phase 3 — Direct API | 🔴 BLOCKED | `wfirma_api_payload.json` (placeholder) |

---

## Evidence Assessment for PZ API Write

### Evidence FOR (warehousedocuments/add exists)

| Source | Finding | Weight |
|--------|---------|--------|
| `python-wfirma` (PyPI v0.1.0) | Explicitly lists PW, PZ, R, RW, WZ, ZD, ZPD, ZPM with add/find/get/edit/delete | MEDIUM (alpha library, may reflect planned features) |
| Postman collection (speeding-moon-225969) | Shows `warehouse_document_z_p_d/get` and `warehouse_document_z_p_d/delete` | MEDIUM (GET/DELETE confirmed, not ADD) |
| wFirma pomoc page | Confirms API exists with general module support | LOW (no warehouse specifics) |

### Evidence AGAINST (PZ write via API may not work)

| Source | Finding | Weight |
|--------|---------|--------|
| wFirma forum thread (forum.wfirma.pl/temat/2511) | "No ability to create warehouse documents through API; WZ only possible via invoice auto-creation" | HIGH (direct user + wFirma staff) |
| dbojdo/wFirma PHP SDK (most maintained SDK) | No warehouse module in the supported module list | HIGH (maintained by wFirma-connected dev) |
| webit/w-firma-api Packagist | No warehouse module in full module list | HIGH |
| Zero documented PZ add examples | No public example of a successful `warehousedocuments/add` call found in any source | HIGH |
| All known commercial integrations | All use invoices/contractors — none use warehouse write | MEDIUM |

### Contradictory Signal Explained

The forum post saying "no warehouse document creation" may pre-date a later API update.
The python-wfirma library lists warehouse documents but is alpha (v0.1.0) and may reflect aspirational features.
The most likely interpretation:

- `warehousedocuments/find` and `warehousedocuments/get` — **probably work**
- `warehousedocuments/add` for PZ — **status unknown, requires plan-specific access or may be unavailable**

---

## Risk Analysis

### Risk if we proceed without verification

| Risk | Impact | Probability |
|------|--------|-------------|
| 404 — endpoint doesn't exist | Silent failure, no PZ created | MEDIUM |
| 403 — not authorized on plan | Need to upgrade wFirma plan | MEDIUM |
| 201 but wrong data mapping | Stock corrupted with wrong values | HIGH |
| PZ created with wrong goods ID | Inventory mismatch, hard to fix | HIGH |
| Duplicate PZ on retry | Double stock entry, accounting error | HIGH |
| KSeF auth cascade failure | API key blocked, all API stops | LOW |

**Overall pre-verification risk: HIGH**

---

## Verification Checklist (COMPLETE BEFORE ENABLING)

### Step 1: Confirm plan supports warehouse API
```
□ Log into wFirma
□ Check: Ustawienia → Aplikacje → Klucze API
□ Note: what modules are shown/accessible
□ Contact wFirma support (pomoc@wfirma.pl) and ask:
  "Czy API umożliwia tworzenie dokumentów magazynowych (PZ) przez endpoint
   warehousedocuments/add? Jakiego planu wymaga ta funkcja?"
```

### Step 2: Create test company
```
□ Create separate "firma testowa" in wFirma with NO real accounting
□ Generate API keys for the test company
□ Add at least one test warehouse (Magazyn testowy)
□ Add at least one test good/product
□ Add at least one test contractor
```

### Step 3: Test read operations first
```
□ Call: POST /warehouses/find → should return warehouse list
□ Call: POST /goods/find → should return goods list
□ Call: POST /warehousedocuments/find → should return empty list
□ If any returns 404: STOP — the module is not available on this plan
```

### Step 4: Test minimal PZ add
```
□ Construct the minimal payload (type, date, contractor, warehouse, one item)
□ Call: POST /warehousedocuments/add
□ Expected: 201 with document ID
□ Log the response: record the ID for verification
```

### Step 5: Cross-verify created PZ
```
□ Log into wFirma UI
□ Navigate to Magazyn → Dokumenty
□ Find the created PZ document
□ Verify: contractor name, date, goods, quantities, prices ALL match
□ Compare net value against PZ_READY.json totals
```

### Step 6: Test idempotency (duplicate protection)
```
□ Send the same payload twice with same description/AWB
□ Verify: either second call is rejected, or system detects duplicate
□ If no duplicate detection: plan duplicate prevention in our service
```

### Step 7: Enable in Estrella system
```
□ Only after steps 1-6 ALL pass
□ Add `WFIRMA_API_ENABLED=true` to .env
□ Add duplicate-detection logic (check by AWB+date before creating)
□ Add audit trail entry for every created PZ
□ Add rollback: store PZ document ID so it can be reviewed/deleted if wrong
```

---

## Pre-verified Safe Operations (Available Now)

These endpoints are confirmed safe and can be used immediately for read/reporting:

```python
# Get all contractors (for matching supplier names)
POST /contractors/find

# Get all goods (for matching product catalog)
POST /goods/find

# Get invoices for a date range (for reporting dashboard)
POST /invoices/find  with date conditions

# Get payments (for outstanding balance)
POST /payments/find  with invoice conditions

# Get expenses (for duty/cost reporting)
POST /expenses/find  with date conditions
```

---

## Planned Phase 3 Payload (once verified)

When `warehousedocuments/add` is confirmed, the service will:

1. Look up `contractor.id` from `/contractors/find?nip=...`
2. Look up or create `good.id` from `/goods/find?name=...`
3. Look up `warehouse.id` from `/warehouses/find`
4. Build the payload from `PZ_READY.json`
5. POST to `/warehousedocuments/add`
6. Store the returned document ID in `audit.json["wfirma_export"]["api_doc_id"]`
7. Post confirmation to Cliq

### Planned payload shape
```json
{
  "api": {
    "warehousedocuments": {
      "warehousedocument": {
        "type": "PZ",
        "date": "2026-04-27",
        "contractor": { "id": "<resolved-contractor-id>" },
        "warehouse": { "id": "<resolved-warehouse-id>" },
        "description": "Import AWB 3283625844 / MRN 26PL123456789A / PZ 1/2026",
        "warehousedocumentcontents": {
          "warehousedocumentcontent": [
            {
              "good": { "id": "<resolved-good-id>" },
              "count": "5",
              "price": 1234.56,
              "description": "Invoice EJL/25-26/1248; AWB 3283625844; MRN 26PL...; A00 allocated in cost; NBP 3,7058"
            }
          ]
        }
      }
    }
  }
}
```

---

## Decision Matrix

| Scenario | Action |
|----------|--------|
| wFirma confirms `warehousedocuments/add` works | Proceed to build Phase 3 |
| wFirma says endpoint exists but requires premium plan | Evaluate plan upgrade cost vs. time saved |
| wFirma says endpoint doesn't support PZ creation | Remain on Phase 1 (clipboard) + Phase 2 (autofill) |
| wFirma says will be supported in future release | Add to roadmap, keep clipboard as primary |

**Current default: Phase 1 (clipboard) is the production path until Phase 3 is verified.**

---

## Timeline Recommendation

| Week | Task |
|------|------|
| Now | Email wFirma support asking about `warehousedocuments/add` on current plan |
| +1 week | Create test company, test read operations |
| +2 weeks | If step 3 passes, test minimal PZ add |
| +3 weeks | Full cross-verification against manual PZ |
| +4 weeks | Enable Phase 3 if all checks pass |
