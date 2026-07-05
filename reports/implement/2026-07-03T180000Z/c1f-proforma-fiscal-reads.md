# C-1f: Proforma Fiscal Reads Migration (1d) — Build Record

**Date:** 2026-07-03  
**Branch:** deploy/latest  
**Slice:** C-1f — OUTPUT-EQUIVALENCE-GATED  
**Files Changed:** service/app/api/routes_proforma.py, service/app/services/reservation_db.py, service/tests/test_master_consumption_rule.py  
**New Test File:** service/tests/test_c1f_mirror_first_reads.py  

---

## 1. Precondition Verification

All required preconditions confirmed before implementation:
- C-1w1 (`2c30b972`): service-product mirror write operational
- C-1w2 (`3833627c`): wfirma_capabilities writes migrated  
- C-1e (`7c4f6f0b`): routes_wfirma.py reads migrated
- Mirror Completeness Proof (`37aaaf27`): every confirmed-id write path feeds `wfirma_product_mirror`

---

## 2. Read Sites Enumerated (Before → After)

| Original Line | New Line | Call | Payload Field Fed | Migration |
|---|---|---|---|---|
| 153 | 237 | `wfdb.get_products_batch(all_codes)` | `wfirma_product_id` presence check (warehouse readiness) | Mirror batch `get_mirror_products_batch` with per-code cache fallback |
| 959 | 1067 | `wfdb.get_product(product_code)` | `product_match` boolean (`missing_product` counter) | `_c1f_mirror_good_id_with_fallback()` |
| 1387 | 1491 | `wfdb.get_product(ct)` | `good_id` → `ReservationLine.wfirma_good_id` (service charge, preview) | `_c1f_mirror_good_id_with_fallback()` |
| 1560 | 1664 | `wfdb.get_product(pc)` | `good_id` → `ReservationLine.wfirma_good_id` (product lines, preview) | `_c1f_mirror_good_id_with_fallback()` |
| 1713 | 1817 | `wfdb.get_product(ct)` | Truthiness only → `_unmapped` → non-blocking warning string | `_c1f_mirror_good_id_or_cache_truthiness()` |
| 2346 | 2450 | `wfdb.list_products()` | Reverse map `{wfirma_product_id → product_code}` | `rdb.list_mirror_products()` with cache fallback for missing mirror rows |
| 4466 | 4589 | `wfdb.get_product(ct)` | `wfirma_product_id` + `product_name_pl`, `vat_rate`, `unit` (list endpoint) | Mirror-first for id; cache kept for non-identity fields |
| 4565 | 4692 | `wfdb.get_product(ct)` | `product_name_pl`, `vat_rate`, `unit` for POST confirmation (id is `pid` from body) | Annotated: `pid` already known; cache kept for non-identity fields only |
| 5673-5674 | 5806 | `wfdb.get_product(_pc)` | `wfirma_product_id` presence → `_missing_codes` block | `_c1f_mirror_good_id_with_fallback()` |
| 6720 | 6853 | `wfdb.get_product` (callable) | `wfirma_product_id` truthiness via `product_mapping_lookup` | `_c1f_product_mapping_lookup` wrapper function |
| 7722 | 7871 | `wfdb.get_product(ct)` | Truthiness only → `_sc_unmapped` → non-blocking warning (posting path) | `_c1f_mirror_good_id_or_cache_truthiness()` |
| 7875 | 8024 | `wfdb.get_product(pc)` | `good_id` → `ReservationLine.wfirma_good_id` (actual posting path) | `_c1f_mirror_good_id_with_fallback()` |

**Residual wfdb calls (intentional, not violations):**
- Line 119: Inside `_c1f_mirror_good_id_with_fallback` — the cache fallback path  
- Line 272: Inside warehouse-readiness code — per-code cache fallback when mirror absent  
- Line 2479: Inside `_build_wfirma_id_to_code_map` — cache fallback for mirror gaps  
- Line 4609: In list-service-products — cache for non-identity fields (name/vat_rate/unit)  
- Line 4699: `wfdb.upsert_product` — the SINGLE transitional dual-write site (cleanup post-1d)  
- Line 4713: Cache re-read after upsert — non-identity fields only (name/vat_rate/unit)

---

## 3. New Accessors Added to reservation_db.py

```python
def get_mirror_product(db_path: Path, product_code: str) -> Optional[Dict[str, Any]]
    # Returns mirror row dict or None. 6 columns: wfirma_id, product_code, sync_version, last_sync, hash, deleted_flag.

def get_mirror_products_batch(db_path: Path, product_codes: List[str]) -> Dict[str, Dict[str, Any]]
    # Batch version. Returns {product_code: row_dict}. Single query.

def list_mirror_products(db_path: Path) -> List[Dict[str, Any]]
    # All mirror rows ordered by product_code. For reverse-map builder.
```

---

## 4. Mirror-First / Fallback Design Rationale

### Equivalence Guarantee
When mirror and cache agree (the normal post-backfill state established by C-1a + Mirror Completeness Proof), both return the same `wfirma_id`/`wfirma_product_id`. The payload is byte-identical before and after migration. The mirror-first path IS the cache-path in this state — just reading a different physical table.

### Loud Divergence (not silent)
When mirror and cache DISAGREE (data integrity issue surfacing):
- Mirror id used (mirror is the post-1d authority)
- WARNING logged: `C-1f: id divergence for %r — mirror=%r cache=%r — using mirror`

### Fallback Path
When mirror row is absent or has empty `wfirma_id` (backfill gap):
- Cache id used (preserving existing behavior)
- WARNING logged: `C-1f: mirror absent/empty for %r — falling back to cache id=%r`

### Non-Identity Fields
The mirror stores ONLY sync-identity columns (6 columns per LAYER RESPONSIBILITIES).
Sites needing `product_name_pl`, `vat_rate`, `unit` continue reading the cache for THOSE fields only. The `wfirma_product_id` (the fiscal-payload identity field) comes from the mirror. This is the hybrid approach for sites 4466 and 4565.

### Sync_status Equivalence
The cache uses `sync_status == "matched"` to indicate a confirmed product.
The mirror uses `wfirma_id != ""` as the equivalent signal (mirror write only happens on confirmed registration per C-1w1/C-1w2/C-1e design).

---

## 5. OUTPUT-EQUIVALENCE GATE — Test Evidence

### Gate 1: test_master_consumption_rule.py
```
Before: 11 passed in 7.64s
After:  11 passed in 7.98s  ✅ IDENTICAL
```

### Gate 2: Smoke suite
```
Before: 63 passed, 1 skipped in 44.03s
After:  63 passed, 1 skipped in 46.77s  ✅ IDENTICAL
```

### Gate 3: New C-1f tests (test_c1f_mirror_first_reads.py)
```
9 passed in 6.94s  ✅ ALL NEW TESTS PASS
```
Tests cover: mirror-confirmed, mirror-absent fallback (with WARNING), divergence (with WARNING), missing DB, batch accessor, list accessor.

### Gate 4: Proforma authority + payload-pinning tests
```
test_customer_invoice_snapshot.py + test_draft_proforma_authority_phase_a.py + 
test_adr027_vat_from_master.py + test_authority_separation.py + 
test_awb9158478722_import_pz_sales_authority.py:
  93 passed, 1 warning  ✅ ALL PASS
```

### Gate 5: Root golden regression
```
160/160 tests passed | 0 failed  ✅ IDENTICAL
```

### Pre-existing failures (NOT caused by C-1f)
- `test_audit_proforma_converted.py` (3 failures): Pre-existing, caused by operator's untracked main.py changes (supplier_invoice_ocr router addition). Failure asserts `status=="failed"` but gets `"blocked"` — unrelated to product id resolution. Confirmed by: (a) test does not reference any C-1f-touched code paths, (b) failure message is about convert endpoint response shape, not product lookups.

---

## 6. test_master_consumption_rule.py Pin Status

**Count stays at 1** (routes_proforma.py remains in KNOWN_PRODUCT_VIOLATION_FILES).
**Reason**: The `acc:upsert_product` pattern at line ~4699 still matches (transitional dual-write, cleanup post-1d). Additionally, transitional cache reads for non-identity fields (name/vat_rate/unit) at lines 4609 and 4713 match `acc:get_product`.

**Comment updated** to document:
- C-1f migrated the 12 fiscal reads to mirror-first
- Residual = single dual-write site + non-identity cache reads (post-1d cleanup)

---

## 7. Dirty-Tree Verification

**C-1f modified (expected):**
- `service/app/api/routes_proforma.py` (M)
- `service/app/services/reservation_db.py` (M)
- `service/tests/test_master_consumption_rule.py` (M)
- `service/tests/test_c1f_mirror_first_reads.py` (?? NEW)

**Operator pre-existing files — UNTOUCHED:**
- 6 modified: config.py, main.py, components.jsx, index.html, mock-badge.jsx, pz-api.js
- 35+ untracked: dhl_*, query*, scripts/*, service/app/api/routes_supplier_invoice_ocr.py, etc.

---

## 8. No Commits / No Push

Per operator rule: no commit, no push, no PR, no deploy. Working tree only.
