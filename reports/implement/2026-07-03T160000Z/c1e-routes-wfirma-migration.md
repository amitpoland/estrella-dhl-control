# C-1e Build Record — routes_wfirma reads(5)+writes(3) migration

**Date:** 2026-07-03T16:00:00Z  
**Branch:** deploy/latest  
**Operator ruling:** 2026-07-03 Option (a): C-1w1/C-1w2 pattern

---

## 0. Dirty-tree pre-flight

At session start the working tree contained:
- **6 modified** (operator local work): `service/app/core/config.py`, `service/app/main.py`,
  `service/app/static/v2/components.jsx`, `service/app/static/v2/index.html`,
  `service/app/static/v2/mock-badge.jsx`, `service/app/static/v2/pz-api.js`
- **35 untracked** entries (scripts, tmp files, dhl certs, etc.)

**At session end:** same 6 operator files untouched, same 35 untracked unchanged.
C-1e adds 4 modified files: `routes_wfirma.py`, `test_master_consumption_rule.py`,
`test_wfirma_products_resolve.py`, `test_wfirma_products_sync_names.py`.  
No stash, no clean, no reset --hard executed (Dirty-Tree Protection rule honored).

---

## 1. Import change

| File | Line | Change |
|------|------|--------|
| `service/app/api/routes_wfirma.py` | :70–71 | Removed `from ..services import wfirma_db` (fully unused after migration); `reservation_db as rdb` already present at :71 (now :70). Added `# C-1e: wfirma_db fully migrated; import removed` comment. |

---

## 2. Read migrations (×5) — transitional cache passthroughs

| Site | Original line | Call before | Call after | Comment |
|------|--------------|-------------|------------|---------|
| READ 1 | :1670 | `wfirma_db.list_products()` | `rdb.list_cached_products()` | `# C-1e: transitional cache read via sync layer` |
| READ 2 | :1918 | `wfirma_db.get_products_batch(list(seen.keys()))` | `rdb.get_cached_products_batch(list(seen.keys()))` | `# C-1e: transitional cache read via sync layer` |
| READ 3 | :2100 | `wfirma_db.list_products()` | `rdb.list_cached_products()` | `# C-1e: transitional cache read via sync layer` |
| READ 4 | :2333 | `wfirma_db.get_product(pc)` | `rdb.get_cached_product(pc)` | `# C-1e: transitional cache read via sync layer` |
| READ 5 | :2685 | `wfirma_db.list_products()` | `rdb.list_cached_products()` | `# C-1e: transitional cache read via sync layer` |

All args verbatim. `rdb.*` are thin passthroughs (kept until 1d re-points to mirror/Master).

---

## 3. Write migrations (×3) — mirror-first dual-write

### Write site 1 — found path (original :1945)

**Context:** `for pc, meta in seen.items()` loop, inside `if found is not None:` block.
The `rdb.lookup_wfirma_product(pc)` is already wrapped in try/except above; the upsert
was OUTSIDE that try — no existing exception handler at the call site.

**Collision handling decision:** Per-item error collect + `continue`. Rationale: we are
inside a batch loop; a collision means another product_code already owns this wfirma_id
in the mirror. Aborting the batch would be wrong — other items in the batch are valid.
The item is added to `failed_details` with `"error": "wfirma_id_collision"` and
`"existing_owner": _reg.get("owner")`. The `found_and_mapped` counter is NOT incremented.

**db_path idiom:** `settings.storage_root / "reservation_queue.db"` + `rdb.init_reservation_db(_db_path)` — exact idiom from routes_wfirma_capabilities.py post-C-1w2.

**wfirma_id source:** `found.wfirma_id` (confirmed by `rdb.lookup_wfirma_product` return value).

### Write site 2 — created path (original :2069, shifted after site-1 expansion)

**Context:** inside same `for pc, meta in seen.items()` loop, after `rdb.create_wfirma_product_via_master` succeeds. No existing exception handler at the upsert call site (the surrounding try/except covers `create_wfirma_product_via_master`, not the upsert).

**Collision handling decision:** Per-item error collect + `continue`. Rationale: same as
write site 1 (batch loop). The wFirma good was already created (or existed), but the mirror
says another product_code owns this wfirma_id. Operator must resolve; item reported to
`failed_details` with `"error": "wfirma_id_collision"`. The `created` counter is NOT
incremented on collision (prevented via `continue` before `created += 1`).

**wfirma_id source:** `result_product.wfirma_id` (confirmed non-empty — guard above).

**Local variable name:** `_db_path_w2`, `_reg_w2` (avoids shadowing `_rdb` from `_reservation_db()` call earlier in the function).

### Write site 3 — sync-names path (original :2393, shifted)

**Context:** inside `for pc, meta in seen.items()` loop in `wfirma_products_sync_names`,
already wrapped in `try/except Exception as exc`. The outer try/except had per-item error
collection + continue.

**Collision handling decision:** Per-item collision handled INSIDE the try block (before
the except). Collision → `failed_details.append(...)` + `continue`. This preserves the
surrounding error-handling idiom (try/except still catches any Exception from
`register_product_identity` itself). The existing except block now only catches
`register_product_identity` exceptions (DB write failures), not collisions (which are
clean returns from the function). Comment added: "wFirma already updated but mirror reports
another code owns this id — operator must resolve."

**wfirma_id source:** `wfirma_id` local variable (confirmed non-empty — guard 10 lines above).

**Local variable names:** `_db_path_w3`, `_reg_w3`.

---

## 4. Dual-write disclosure

All 3 write sites use `rdb.register_product_identity(db_path, wfirma_id=..., product_code=..., cache_kwargs=dict(...))` which performs:
1. **Mirror FIRST** — `upsert_product_mirror` (collision-safe)
2. **Cache LAST** — `wfirma_db.upsert_product(**cache_kwargs)` (transitional, kept until 1d)

The `wfirma_db` import is removed from `routes_wfirma.py` — the transitional cache write now goes through `register_product_identity` which imports `wfirma_db` internally (whitelisted sync layer).

---

## 5. Pin update: test_master_consumption_rule.py

| Change | Before | After |
|--------|--------|-------|
| `KNOWN_PRODUCT_VIOLATION_FILES` | `{"routes_proforma.py", "routes_wfirma.py"}` | `{"routes_proforma.py"}` |
| Count assertion in `test_known_violation_baseline_is_documented_and_shrinking` | `== 2` | `== 1` |
| Comment for `routes_wfirma.py` entry | (in set) | Moved to comment: "MIGRATED in C-1e (5 reads + 3 writes → rdb sync layer)" |

`routes_proforma.py` remains the last residual (C-1d/C-1f).

---

## 6. Test updates

### Existing test file updates (patch target corrections):

| File | Tests updated | Patch change |
|------|--------------|--------------|
| `test_wfirma_products_resolve.py` | 7 tests | `wfirma_db.get_products_batch` → `rdb.get_cached_products_batch`; `wfirma_db.list_products` → `rdb.list_cached_products`; `wfirma_db.upsert_product` → `rdb.register_product_identity` (fake_register captures kwargs); dead `wfirma_db.get_product` patches removed |
| `test_wfirma_products_sync_names.py` | 1 test | Source-grep updated: `wfirma_db.upsert_product` → `rdb.register_product_identity` |

### New C-1e tests added to `test_wfirma_products_resolve.py`:

| Test | Write site | What it pins |
|------|-----------|--------------|
| `test_c1e_goods_find_path_writes_mirror` | Write site 1 | After found path, `wfirma_product_mirror` row exists with correct `wfirma_id` |
| `test_c1e_found_path_collision_returns_per_item_error` | Write site 1 | Collision → `found_and_mapped=0`, `failed=1`, `error=wfirma_id_collision` in failed_details |

Both follow C-1w2 style from `test_wfirma_capabilities.py:1474`.

---

## 7. Verification: zero remaining product accessor calls

```
grep -nE "wfirma_db\.(get_product|get_products_batch|list_products|upsert_product)\s*\(" \
  service/app/api/routes_wfirma.py
# → (no output) ZERO rows
```

Full detector sweep (comment-stripped, all 10 patterns):
```
Remaining hits in routes_wfirma.py: NONE — clean
```

---

## 8. Test evidence

| Suite | Before C-1e | After C-1e |
|-------|-------------|------------|
| `test_master_consumption_rule.py` | 11 passed | **11 passed** |
| `test_wfirma_products_resolve.py` | 7 failed (wfirma_db patches broken after import removal), 2 pre-existing in capabilities | **10 passed** (all resolve tests + 2 new C-1e tests) |
| `test_wfirma_products_sync_names.py` | 1 failed (source-grep) | **passed** |
| `test_wfirma_capabilities.py` | 2 pre-existing failures | **same 2 pre-existing** (unchanged) |
| Smoke suite (`-m smoke`) | 63 passed, 1 skipped | **63 passed, 1 skipped** (identical) |

Pre-existing failures (pre-C-1e, file-untouched proof): `test_contractor_search_hit` and `test_refresh_blocked_when_flag_off` in `test_wfirma_capabilities.py` — both fail on `routes_wfirma_capabilities.py` behavior, not `routes_wfirma.py`; they appear in baseline before any C-1e edit.

---

## 9. Files changed

| File | Type | Change summary |
|------|------|---------------|
| `service/app/api/routes_wfirma.py` | Implementation | 5 read migrations + 3 write migrations + `wfirma_db` import removal |
| `service/tests/test_master_consumption_rule.py` | Test | Pin count 2→1; routes_wfirma.py removed from KNOWN_PRODUCT_VIOLATION_FILES |
| `service/tests/test_wfirma_products_resolve.py` | Test | 7 test patches updated + 2 new C-1e tests added |
| `service/tests/test_wfirma_products_sync_names.py` | Test | Source-grep updated for new write path |

No commit, no push, no PR, no deploy, no gh, no robocopy, no sc.exe.
