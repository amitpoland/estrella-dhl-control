# Master Authority Cleanup Plan — Phase C-0 (plan half, read-only)

- **Date:** 2026-07-03 · read-only planning · zero code edits ·
  writes only this plan + DECISIONS/CLAUDE.md.
- **C-0 audit half is DONE** (b48b9f1c: Q0 census + V1-V7 in the Integration
  Architecture Audit) — cited here, not re-derived. This is the PLAN half.
- **Queue (operator):** C-0 → C-1 Product Master → C-2 Customer Master →
  C-3 Sample/Returns READ → C-4 Consignment → C-5 Invoice Selection →
  C-6 MM. Master-first rule in force (CLAUDE.md constitution).

**PROPOSED-NOT-DONE:** every schema, migration, and rerouting below is a
PROPOSAL. Nothing is implemented; no table/file/path containing "PZ" is
renamed (R1). **QUESTIONS-STOPPED-ON:** two operator-input items (below) gate
the mirror key choice. **DEVIATIONS-DISCLOSED:** none — this run is pure
planning, no code touched.

---

## 1. Violation → slice map (V1-V7 from b48b9f1c)

| # | Wrong path (file:line) | Slice | Corrected path |
|---|---|---|---|
| V1 | routes_wfirma.py:2003 create_product / :2320 edit_product → wFirma goods, no Product Master upstream | **C-1** | Product module → Product Master → Mirror → wFirma |
| V2 | wfirma_products (wfirma_db.py:79) + wfirma_product_mapping (reservation_db.py:60) — split product identity | **C-1** | one canonical Product Master + one wfirma_product_mirror |
| V3 | wfirma_customers (wfirma_db.py:62) + wfirma_customer_mapping (reservation_db.py:76) — client_name-keyed caches | **C-2** | Customer Master → one wfirma_customer_mirror(contractor_id) |
| V4 | routes_proforma.py:1500/1529/7767/7800 (search_customer) + :1877/3637/8067 (fetch_contractor_by_id) | **C-2** | Proforma → Customer Master → Mirror → wFirma |
| V5 | routes_ledgers.py:155,288 fetch_contractor_by_id direct | **C-2** | Ledgers → Customer Master → Mirror → wFirma |
| V6 | routes_reservations.py:161 get_product_by_code direct | **C-1** | Reservations → Product Master → Mirror → wFirma |
| V7 | routes_suppliers.py:396 direct; routes_customer_master.py:498,699 Master maps direct (no mirror layer) | **C-2** | <module> → Master → Mirror → wFirma |

C-1 owns V1, V2, V6 (product). C-2 owns V3, V4, V5, V7 (customer).

---

## 2. C-1 target design — Product Master

**Operator model — two layers, cleanly split:**

**Product Master (business authority)** — proposed canonical table
`product_master` (already in reservation_queue.db, promote it):
- `product_code` (PK — local authority key)
- `design_number` (design→product mapping; the one commercial-identity field)
- `is_active` (BOOL)
- `status` (enum incl. **"Mapping Required"**, "Mapped", "Adopted", "Not Found")
- (existing advisory columns design_no, category, item_type, hsn_code stay as
  business attributes — they belong to the Master, not the Mirror)

**Product Mirror (sync layer only)** — proposed canonical table
`wfirma_product_mirror`:
- `product_code` (FK → product_master)
- `wfirma_product_id` (NULL until synced)
- `last_sync` (ISO), `sync_version` (INT), `content_hash` (of the synced
  wFirma fields), `updated_at`
- NOTHING else — no name/unit/vat_rate/description (those move to the Master
  or a product_local overlay).

**Promote-vs-new verdict: PROMOTE.** `product_master` (reservation_db.py:32)
already exists as the business registry and is the resolver's advisory source.
Promote it to the authority (add is_active + status) rather than create a new
table. Create ONE new `wfirma_product_mirror` and RETIRE the two split mirrors
(wfirma_products, wfirma_product_mapping) by redirecting readers — **not
deleted in C-1** (deprecate-in-place; a later slice removes them once no reader
remains).

**Backfill source per column:**
- product_master.status/is_active ← derived from existing sync_status of
  wfirma_products (matched→Mapped, pending→Mapping Required, etc.).
- wfirma_product_mirror.wfirma_product_id ← COALESCE(wfirma_products.wfirma_product_id,
  wfirma_product_mapping.wfirma_product_id) (prefer the confirmed one).
- content_hash ← computed at backfill from the current wFirma-synced fields.

**Consumer rerouting list (every reader/writer → C-1 destination):**
- READERS of wfirma_products: routes_proforma.py:115,160,1016,1355,4127,5407,
  5497,5605,5652 (readiness/resolution checks); routes_packing.py:2105 (SQL
  SELECT),:2128; routes_dashboard.py:2415; routes_wfirma.py:1537 →
  **reroute to a Product Master read API** (get_product_mapping(product_code)
  returning {product_code, wfirma_product_id, status}).
- WRITERS: routes_proforma.py:4527 wfdb.upsert_product; wfirma_product_registration
  / wfirma_product_auto_register._mirror_to_reservation_mapping →
  **reroute to a single mirror upsert on wfirma_product_mirror**, status set on
  product_master.
- routes_reservations.py:170 sync_wfirma_products_by_codes (rworker) →
  **reads/writes the canonical mirror** (V6 fix).
- routes_master_data.py:408 upsert_product_local (a THIRD product surface —
  product_local overlay) → keep as the business-attribute overlay ABOVE the
  Master; it is not a mirror; note it, do not fold in C-1.
- **V1 product write path** (routes_wfirma.py:2003 create_product / :2320
  edit_product) → rerouted THROUGH the Master: the route resolves via Product
  Master, and on create/edit updates product_master.status + the mirror — the
  wFirma call stays behind the WFIRMA_CREATE_PRODUCT_ALLOWED gate.

---

## 3. C-2 target design — Customer Master

**Consolidation:** collapse the two client_name-keyed caches (wfirma_customers
in wfirma.db, wfirma_customer_mapping in reservation.db) into ONE canonical
mirror keyed by **stable contractor_id** (not mutable client_name). The
existing `customer_master.sqlite` STAYS as the business-enrichment authority;
the new `wfirma_customer_mirror` carries only contractor_id (PK) + bill_to_name
(label) + sync_status + last_synced_at.

**Keying migration:** client_name → contractor_id. Backfill: for each cache row
with a non-null wfirma_customer_id, key the mirror by that id; rows with no id
stay as unmatched (status). The name→id resolution the caches did is REPLACED
by the Customer Master resolver (already the primary path).

### RISK SECTION (mandatory) — the invoice-XML contractor-id path

**Current sourcing (b48b9f1c + this run's grep):** the proforma payload
builder sources `wfirma_customer_id` from **customer_master** when the resolver
matches there (routes_proforma.py:323/324/342/343/361/362 →
`str(cm.bill_to_contractor_id)`), but from the **wfirma_customers cache** on the
fallback path (routes_proforma.py:470/506/549/554 →
`per_doc/packing_master/cust["wfirma_customer_id"]`). So consolidating the cache
CAN change the contractor id in generated invoice XML on the fallback path.

**Before/after the C-2 change:**
- BEFORE: matched → id from customer_master; fallback → id from wfirma_customers cache.
- AFTER: matched → id from customer_master (unchanged); fallback → id from
  wfirma_customer_mirror keyed by the same contractor_id the cache held.
- Invariant: for every currently-resolvable client, the contractor_id in the
  emitted `<contractor>` block MUST be byte-identical before and after.

**Verification (output-equivalence, a hard gate on C-2):**
1. Snapshot: for a fixed set of known drafts (the golden batch + a sample of
   real drafts in the verify DB), generate the proforma XML BEFORE the change
   and capture the `<contractor>` id per draft.
2. Apply C-2 (verify-tree only).
3. Regenerate the XML and DIFF the `<contractor>` id per draft — **must be
   identical**. Any divergence FAILS the slice.
4. **Customs-value-freeze applies:** C-2 touches identity sourcing ONLY — no
   document VALUE (net/gross/duty/VAT) is recomputed; the equivalence check
   also asserts value fields are unchanged.

---

## 4. Migration mechanics (per slice)

- **DB backup FIRST** (verify-tree): copy the target DB to
  `<db>.pre-<slice>-<UTC>.bak` before any migration runs (the
  warehouse.db.pre-idempotency precedent).
- **Migration script naming:** `draft_<UTC>_<slug>.py.draft` under
  `service/app/db/migrations/` (the established draft convention — applied to
  the verify tree via SourceFileLoader; PROD application rides the deploy under
  deploy_persistence_storage_reviewer).
- **Rollback statement (each slice):** restore the `.bak`; the deprecated split
  tables are NOT dropped in C-1/C-2, so readers can be pointed back if needed.
- **Verify-tree-first:** ALL of C-1/C-2 lands in C:\PZ-verify + tests. **NO
  deploy.** Prod migration is a later, separately-gated step.

---

## 5. Slice specs (ready-to-run pre-flight blocks for operator approval)

### C-1 — Product Master Authority (pre-flight)
- **Module:** Product Master consolidation (extends the EJ Dashboard Product
  Master authority).
- **Declared file list (R1 scope-lock):** reservation_db.py (promote
  product_master + new wfirma_product_mirror + backfill),
  wfirma_product_auto_register.py / wfirma_product_registration.py (mirror
  writes → canonical), routes_wfirma.py (V1 create/edit reroute through
  Master), routes_reservations.py (V6), the readers in routes_proforma.py /
  routes_packing.py / routes_dashboard.py (read via Master API), a new
  migration draft, new/updated tests, PROJECT_STATE. **wfirma_db.py
  wfirma_products = deprecate-in-place (readers redirected, table kept).**
- **Gates:** golden 160/160; new pins (Master schema, mirror minimal-field,
  consumer-reroute grep pins, no-direct-wFirma-product-in-non-integration-
  module pin); render N/A (no UI). No deploy.
- **Tests:** product-master read/write round-trip; mirror sync-field-only pin;
  V1/V6 reroute pins; backfill-equivalence (every product_code resolvable
  before still resolvable after, same wfirma_product_id).

### C-2 — Customer Master Authority (pre-flight)
- **Module:** Customer Master consolidation (extends the EJ Dashboard Customer
  Master authority).
- **Declared file list (R1 scope-lock):** wfirma_db.py + reservation_db.py
  (deprecate the 2 caches, new wfirma_customer_mirror + backfill keyed by
  contractor_id), routes_proforma.py (V4 + fallback id from mirror),
  routes_ledgers.py (V5), routes_suppliers.py (V7), routes_customer_master.py
  (V7 mirror layer), a migration draft, new/updated tests, PROJECT_STATE.
- **Gates:** golden 160/160; **invoice-XML output-equivalence pin** (the risk
  section — `<contractor>` id + value fields byte-identical before/after on the
  known-draft set); customs-value-freeze pin; consumer-reroute grep pins;
  no-direct-wFirma-customer-in-non-integration-module pin. No deploy.
- **Tests:** contractor-id-keyed mirror round-trip; the output-equivalence
  suite (generate → diff contractor id + values); V4/V5/V7 reroute pins.

---

## OPERATOR-INPUT (gates the mirror key — from Q6, must answer before C-1/C-2 build)

1. **Stable contractor_id in ALL wFirma responses** (contractors, webhook
   payloads, invoice contractor blocks)? — required to key the Customer mirror
   by contractor_id instead of client_name (C-2 keying migration depends on it).
2. **/magazines (warehouse) endpoint** in the API plan, or is warehouse_id a
   config constant? — decides whether a Warehouse mirror is in scope (not C-1/
   C-2, but confirms the mirror-set shape).

These do NOT block writing C-1's Product Master (product_code is already the
local key); they DO gate C-2's contractor-id keying — if wFirma's contractor_id
is not universally present, C-2's key choice must be revisited before build.

**Next-await: operator ratification of C-1.** No mutation begins without it.
