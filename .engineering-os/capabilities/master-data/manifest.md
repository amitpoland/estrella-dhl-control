# Capability Manifest — master-data

**Status:** ACTIVE (Product Master foundation ACCEPTED; consumer packages in progress)
**Authority owner:** EJ Dashboard **Product Master** + **Customer Master** (consume-only)

> Load this manifest before any master-data package. If a change cannot name the authority,
> page, API, DB, and service below, **STOP** (Master-First rule).

---

## Authority chain

```
wFirma Product/Customer → Mirror (6-col, sync-only) → Product Master / Customer Master → all modules
```

- **Product Master** — physical home `reservation_queue.db` (`product_master`), owned by
  `reservation_db.py`. Holds: wFirma ID, product_code, design_no, status, sync_version,
  last_sync, active, `normalized_design_attributes` (variant signature).
- **Customer Master** — Customer Master authority (Client Master is the reference operability
  pattern: `↻ Sync from wFirma`, `⇅ Full Contractor Scan`, status panel).
- **Mirror** — `wfirma_product_mirror` = exactly 6 columns (`wfirma_id, product_code,
  sync_version, last_sync, hash, deleted_flag`); never business logic. Pinned by
  `test_master_consumption_rule.py`.

## Chain (route → service → model)

| Layer | Surface |
|---|---|
| **Page** | Master Data → Products tab / Clients (V2) |
| **API** | `routes_reservations.py` / `routes_admin.py` (`product-master/backfill`), product-master sync endpoints |
| **Service** | `cpa_product_service.py` (`upsert_product_master_from_packing`), `design_product_bridge.py`, `description_engine.py`, `wfirma_product_auto_register.py` |
| **DB** | `reservation_queue.db` (product_master), customer master DB, `wfirma_product_mirror` |

## Blockers vs advisories (Lesson N)

- **True blockers (PRODUCT authority):** missing product_code, duplicate conflict, invalid
  accounting fields, live-create approval (`WFIRMA_CREATE_PRODUCT_ALLOWED`).
- **Advisory only:** stock, scan, sales packing, PZ status, SAD, proforma — must NOT block
  product creation.

## Governance guardrails

- **Product Master is consume-only.** No module may MODIFY product_master or its authorities;
  modifying it is an architectural violation.
- **product_code mint stays in `store_invoice_lines`** — the sync never invents a code.
- **No new Master table / DB / authority.** Variant identity lives in the existing
  `normalized_design_attributes` column (no migration).
- **No wFirma product CREATE** outside the flag-gated write path.

## Related
Skills: `ej-dashboard-fullstack-governance` (authority), `wfirma-api-integration` (reference).
Agents: `backend-safety-reviewer`, `deploy-persistence-storage-reviewer`, `wfirma-integration`.
See also: `project-product-master-slice1`, `feedback-product-master-consume-only` (auto-memory).
