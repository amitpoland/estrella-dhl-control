# C-2a — Customer Mirror Consolidation (Schema + Backfill)

**Slice**: C-2a  
**Campaign**: EJ Dashboard Phase-C, Customer Authority (Constitution §3/§7)  
**Date**: 2026-07-03  
**Branch**: deploy/latest  
**Status**: VERIFY-TREE ONLY — NO deploy, NO commit, NO fiscal/value logic

---

## What changed

### A. `service/app/services/reservation_db.py` (additive only)

**Schema (lines ~93–112 in the `_SCHEMA` constant):**  
Added `wfirma_customer_mirror` table immediately after `wfirma_product_mirror`:

```sql
CREATE TABLE IF NOT EXISTS wfirma_customer_mirror (
    contractor_id TEXT NOT NULL,
    client_name   TEXT NOT NULL DEFAULT '',
    sync_version  INTEGER NOT NULL DEFAULT 1,
    last_sync     TEXT NOT NULL DEFAULT '',
    hash          TEXT NOT NULL DEFAULT '',
    deleted_flag  INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (contractor_id)
);
CREATE INDEX IF NOT EXISTS idx_wcm_client_name ON wfirma_customer_mirror(client_name);
```

Exactly six mirror-discipline columns. `contractor_id` is PRIMARY KEY (stable wFirma id, never empty in mirror). `client_name` is a mutable label — NOT a unique key (names change legally). Non-unique index on `client_name` for lookup only.

**`upsert_customer_mirror(db_path, *, contractor_id, client_name="") -> Dict`:**
- Skips (returns `{"written": False, "reason": "empty_contractor_id"}`) when `contractor_id` is empty.
- On existing row: updates `client_name` + bumps `sync_version` + refreshes `last_sync`/`hash`. Name changes (legal renames) are NOT collisions — the label is updated.
- On new row: inserts with `sync_version=1`, `deleted_flag=0`.
- Returns `{"written": True, "reason": None}` on success.

**`backfill_customer_authority(db_path, wfirma_db_path=None) -> Dict`:**
- Idempotent. Sources: `wfirma_customer_mapping` (same reservation DB) + `wfirma_customers` (wfirma.db, read-only).
- For each source row with a non-empty `wfirma_customer_id`: calls `upsert_customer_mirror`.
- Name conflicts (same `contractor_id`, different `client_name` across sources) are collected as `name_conflicts: [(contractor_id, name_a, name_b)]`. Advisory only — not fatal. Mirror stores the last-seen label.
- Returns: `{from_mapping, from_cache, written, skipped_empty_id, name_conflicts}`.
- Missing sibling tables/files degrade silently (no exception raised).

### B. `service/tests/test_master_consumption_rule.py` (additive only)

Added `test_customer_mirror_schema_is_exactly_six_columns` — standing pin asserting `wfirma_customer_mirror` columns are exactly `{contractor_id, client_name, sync_version, last_sync, hash, deleted_flag}`. Any schema drift fails immediately.

### C. `service/tests/test_c1b_product_write_path.py` (additive only)

Added 10 C-2a customer mirror tests alongside the existing product mirror tests:

| Test | What it pins |
|---|---|
| `test_upsert_customer_mirror_insert` | Insert returns `written=True` |
| `test_upsert_customer_mirror_row_persisted` | Row survives, columns correct, sync_version=1 |
| `test_upsert_customer_mirror_update_bumps_sync_version` | Label update bumps sync_version to 2 |
| `test_upsert_customer_mirror_empty_id_skipped` | Empty contractor_id → `written=False, reason=empty_contractor_id` |
| `test_backfill_customer_authority_from_mapping` | Seeds from mapping → written=2 |
| `test_backfill_customer_authority_rows_correct` | Mirror row has correct client_name |
| `test_backfill_customer_authority_idempotent` | Second run creates no duplicate rows |
| `test_backfill_customer_authority_skips_empty_id` | Empty-id rows counted in skipped_empty_id |
| `test_backfill_customer_authority_name_conflict_reported` | Name mismatch across sources → name_conflicts list |

### D. Build record (this file)

`reports/implement/2026-07-03T130000Z/c2a-customer-mirror.md`

---

## Schema

```
wfirma_customer_mirror
├── contractor_id  TEXT PK   — wFirma stable contractor id (never empty here)
├── client_name    TEXT      — mutable display label (legal renames OK)
├── sync_version   INTEGER   — bumped on every upsert
├── last_sync      TEXT      — ISO-8601 timestamp of last write
├── hash           TEXT      — SHA-256[:32] of contractor_id|client_name
└── deleted_flag   INTEGER   — 0=active, 1=soft-deleted
```

---

## Backfill counts semantics

| Field | Meaning |
|---|---|
| `from_mapping` | Rows read from `wfirma_customer_mapping` (reservation DB) |
| `from_cache` | Rows read from `wfirma_customers` (wfirma.db) |
| `written` | Mirror rows actually inserted or updated |
| `skipped_empty_id` | Rows with empty `wfirma_customer_id` (skipped, not mirrored) |
| `name_conflicts` | List of `(contractor_id, name_a, name_b)` — same id seen with two different names; advisory only |

---

## Explicitly NOT done in C-2a

- **No read/write migration** — existing reads/writes of `wfirma_customer_mapping` and `wfirma_customers` are untouched. Migration is C-2b.
- **No legacy cache removal** — both `wfirma_customer_mapping` (reservation.db) and `wfirma_customers` (wfirma.db) are retained in place.
- **No customer_master changes** — `customer_master.sqlite` stays the business-enrichment authority above the mirror. C-2a adds only the sync layer below it.
- **No business route changes** — no route file was edited. The mirror is schema + backfill only.
- **No deploy, no commit, no PR** — verify-tree only per operator instruction.

---

## Analog

C-2a mirrors the structure of C-1a (`6c2fde43`): Product mirror schema → upsert helper → backfill from two legacy sources. The customer version uses `contractor_id` (PRIMARY KEY) instead of `product_code`, and treats name changes as label updates (not collisions) because customer names change legally.
