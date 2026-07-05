# C-1w2 — Capabilities Write Path (+ Inseparable Reads)

**Date**: 2026-07-03  
**Branch**: deploy/latest  
**Slice**: C-1w2 — routes_wfirma_capabilities.py product-authority exit

---

## Objective

Route all product-authority access in `routes_wfirma_capabilities.py` through the
sync layer (`reservation_db.py`) so the file exits `KNOWN_PRODUCT_VIOLATION_FILES`
and the baseline drops from 3 → 2 (leaving only `routes_proforma.py` +
`routes_wfirma.py`).

---

## Files Modified

### A. `service/app/services/reservation_db.py` (additive only)

Added 6 new sync-layer helpers after `lookup_wfirma_product`:

- `create_wfirma_product(...)` — thin passthrough to `wfirma_client.create_product`
- `edit_wfirma_product(...)` — thin passthrough to `wfirma_client.edit_product`
- `get_cached_product(product_code)` — transitional cache read via `wfirma_db.get_product`
- `get_cached_products_batch(codes)` — transitional cache batch read
- `list_cached_products(sync_status)` — transitional cache list read
- `register_product_identity(db_path, *, wfirma_id, product_code, name, also_set_master_status, cache_kwargs)` — C-1w1 dual-write sequence: mirror FIRST (collision-safe), cache LAST (transitional); skips mirror if wfirma_id is empty

All transitional cache passthroughs carry the comment `# C-1w2: transitional cache read passthrough, removed after 1d.`

### B. `service/app/api/routes_wfirma_capabilities.py`

Replaced all 19 product-authority violation sites:

| Site | Old call | New call |
|------|----------|----------|
| `list_products` endpoint | `wfdb.list_products(...)` | `rdb.list_cached_products(...)` |
| `upsert_product` endpoint | `wfdb.upsert_product(...)` | `rdb.register_product_identity(...)` + 409 guard |
| `create_from_product_code` (search step) | `wfirma_client.get_product_by_code(pc)` | `rdb.lookup_wfirma_product(pc)` |
| `create_from_product_code` (existing) | `wfdb.upsert_product(...)` | `rdb.register_product_identity(...)` + 409 guard |
| `create_from_product_code` (create step) | `wfirma_client.create_product(...)` | `rdb.create_wfirma_product(...)` |
| `create_from_product_code` (post-create) | `wfdb.upsert_product(...)` | `rdb.register_product_identity(...)` + 409 guard |
| `adopt_existing_product` (search) | `wfirma_client.get_product_by_code(pc)` | `rdb.lookup_wfirma_product(pc)` |
| `adopt_existing_product` (mirror) | `wfdb.upsert_product(...)` | `rdb.register_product_identity(...)` + 409 guard |
| `update_and_adopt_product` (search) | `wfirma_client.get_product_by_code(pc)` | `rdb.lookup_wfirma_product(pc)` |
| `update_and_adopt_product` (edit) | `wfirma_client.edit_product(...)` | `rdb.edit_wfirma_product(...)` |
| `update_and_adopt_product` (mirror) | `wfdb.upsert_product(...)` | `rdb.register_product_identity(...)` + 409 guard |
| `create_and_adopt_product` (search) | `wfirma_client.get_product_by_code(pc)` | `rdb.lookup_wfirma_product(pc)` |
| `create_and_adopt_product` (create) | `wfirma_client.create_product(...)` | `rdb.create_wfirma_product(...)` |
| `create_and_adopt_product` (mirror) | `wfdb.upsert_product(...)` | `rdb.register_product_identity(...)` + 409 guard |
| `adopt_pending_found_for_batch` (batch cache) | `wfdb.get_products_batch(codes)` | `rdb.get_cached_products_batch(codes)` |
| `refresh_good_name_from_block` (local lookup) | `wfdb.get_product(pc)` | `rdb.get_cached_product(pc)` |
| `refresh_good_name_from_block` (edit) | `wfirma_client.edit_product(...)` | `rdb.edit_wfirma_product(...)` |
| `refresh_good_name_from_block` (mirror) | `wfdb.upsert_product(...)` | `rdb.register_product_identity(...)` + 409 guard |
| `shipment_setup_detail` (batch mapped) | `_wfdb.get_products_batch(all_codes)` | `rdb.get_cached_products_batch(all_codes)` |

Untouched (not pin violations): `wfdb.adopt_pending_product(pc)`, all customer functions.

### C. `service/tests/test_master_consumption_rule.py` (written to disk)

Updated `KNOWN_PRODUCT_VIOLATION_FILES`: removed `routes_wfirma_capabilities.py`,
added comment `# routes_wfirma_capabilities.py — MIGRATED in C-1w2`.  
Updated count assertion: `3 → 2`.

### D. `service/tests/test_wfirma_capabilities.py` (additive only)

Added 2 new tests at end of file:
- `test_c1w2_adopt_writes_product_mirror` — after `/goods/adopt` succeeds, mirror row exists with confirmed wfirma_id
- `test_c1w2_adopt_collision_returns_409` — second adopt with same wfirma_id returns 409 `wfirma_id_collision` with correct owner

---

## Test Results

```
tests/test_master_consumption_rule.py   8/8 PASSED  (pin baseline = 2)
tests/test_wfirma_capabilities.py      69/71 (2 pre-existing failures unchanged)
  FAILED: test_contractor_search_hit         (pre-existing — unrelated to C-1w2)
  FAILED: test_refresh_blocked_when_flag_off (pre-existing — settings default True)
New C-1w2 tests: 2/2 PASSED
Total: 77 passed, 2 failed (pre-existing)
```

---

## Pin Baseline Change

| File | Before C-1w2 | After C-1w2 |
|------|-------------|-------------|
| `routes_wfirma_capabilities.py` | VIOLATION | CLEAN |
| `routes_proforma.py` | VIOLATION | VIOLATION (residual) |
| `routes_wfirma.py` | VIOLATION | VIOLATION (residual) |
| Count | 3 | **2** |

---

## Invariants Preserved

- Mirror-first dual-write: `upsert_product_mirror` always before `wfdb.upsert_product`
- Empty wfirma_id rule: `register_product_identity` skips mirror when `wfirma_id` is blank
- No divergence on collision: `register_product_identity` returns without cache write on collision
- 409 shape consistent with C-1w1: `{"error": "wfirma_id_collision", "wfirma_id": ..., "owner_product_code": ...}`
- Transitional dual-write kept: cache writes preserved for slice 1d proforma-read migration
- `wfdb.adopt_pending_product` untouched (not a pin violation)
- All customer functions untouched

---

## DO NOT COMMIT / PUSH / DEPLOY

Per operator instruction: edit files and run tests only.
