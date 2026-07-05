# Integration Architecture Audit — Phase C gate-0 (read-only)

- **Date:** 2026-07-03 · read-only · zero edits · disk-first
- **Method:** 6-inspector parallel audit (workflow wf_1c9a85db-7b9), each citing
  repo evidence + wFirma docs, flagging OPERATOR-INPUT-REQUIRED where only
  Amit's wFirma-account config can answer.
- **Wireframe of record present:** docs/design/estrella-dashboard-wireframe.html
  (sha256:f7dd5e3889…).

---

## Q1 — wFirma Product Master → Mirror → Design chain

- **wFirma `goods` module** (add/edit/find/get). `WFirmaProduct` = 6 fields:
  `wfirma_id` (immutable PK, used in goods/edit URL), `name`, **`code` = our
  product_code (the SOLE lookup key)**, `unit`, `count` (read-only stock),
  `reserved`. Live fns: get_product_by_code (:963), create_product (:1019),
  edit_product (name/description only, :1089); `get_stock` is a
  NotImplementedError stub (:1161). **No goods webhook** anywhere.
- **Design linkage EXISTS**: packing_lines.design_no →
  `product_authority_resolver.resolve_batch_product_authority()` (:96, single
  canonical resolver → `design_to_product_codes`) → design_product_mapping +
  product_master (reservation.db). product_master is ADVISORY-only
  (product_authority_resolver:9).
- **Two product mirrors already exist** (see Q6): `wfirma_products` (wfirma.db)
  + `wfirma_product_mapping` (reservation.db).
- **Chain verdict:** the Product→Design half EXISTS and is clean (one
  resolver). The wFirma-goods-identity half exists but is SPLIT across two
  mirror tables carrying business fields → consolidation needed.

## Q2 — Customer Master

- **customer_master.sqlite = the operator BUSINESS-ENRICHMENT authority**, not
  a minimal mirror. Synced fill-when-empty (COALESCE) from wFirma via two
  paths: Phase 3 (webhook-triggered per terminal invoice event →
  fetch_contractor_by_id → upsert_identity_only, sync_source='webhook') and
  Phase 3B (full contractor poll every 6h → sync_source='wfirma_poll'). Two
  write modes: upsert_customer (full-set operator Save) vs upsert_identity_only
  (COALESCE — wFirma can never blank operator freight/insurance/KYC/credit).
- **NOT the single customer table:** a second name-keyed cache `wfirma_customers`
  (wfirma.db) + a duplicate `wfirma_customer_mapping` (reservation.db) both map
  client_name → wfirma_customer_id. The proforma resolver is a 4-step chain
  (packing-master → customer_master → wfirma_customers exact → prefix). Comment
  routes_proforma.py:525 declares "Customer Master is authority," but the
  wfirma_customer_id in the invoice XML is sourced from wfirma_customers.
- **Verdict:** customer_master is the authority for identity/VAT/commercial
  defaults; the two name-keyed caches are duplicates to fold into ONE canonical
  contractor-id-keyed mirror (Q6).

## Q3 — Warehouse documents + lifecycle

`_WAREHOUSE_MODULES` registers 7 strings (auth routing only; registration ≠
create fn). Live: **PZ** (create/fetch/find — live-proven in prod,
routes_wfirma:2519, gated WFIRMA_CREATE_PZ_ALLOWED), **R** (create_reservation),
**warehouses/find** (list_warehouses). **WZ/PW/RW/ZD registered but NO create
fn** (NET-NEW). **MM absent from every layer** (client, docs, python-wfirma
type list) — WFIRMA-GATED on the operator support answer.

Lifecycle annotation (Purchase → PZ → MAIN → MM → Sample/Consignment → MM →
MAIN → Invoice → WZ → Sold):

| Edge | Status |
|---|---|
| Purchase → PZ | **EXISTS** (pz_create + run_stock_promotion, BE-1) |
| PZ → MAIN (stock) | **EXISTS** (app state; PZ itself moves wFirma stock; no separate doc) |
| MAIN → MM → Consignment | **NET-NEW + WFIRMA-GATED** (MM API unconfirmed) |
| Consignment → MM → MAIN | **NET-NEW + WFIRMA-GATED** (same MM gate) |
| Invoice → WZ → Sold | **PARTIAL/GATED** — invoice API exists; SALES_TRANSIT transition NEVER fired (routes_proforma:3311-4001 never calls transition()); WZ = standalone-add vs invoice-auto-WZ unconfirmed |

## Q4 + Q5 — Sample / Returns / Consignment

- **Sample/returns are WRITE-ONLY** (confirms scope-stop a2126333): sample_out
  / sample_return (inventory_sample_writer), mark_returned_from_client /
  _to_producer / return_from_producer_to_stock (inventory_returns_writer) — all
  through inventory_state_engine.transition(). **Zero read/list endpoints**;
  only stage2/aggregate counts. returns_events migration draft NOT applied in
  prod (returns writer blocked until deploy).
- **BE-2b boundary confirmed & pinned:** sample-return and producer-restock are
  direct transitions with NO Stock Promotion Note (returns to stock ≠ Temp→Final
  promotions). Only run_stock_promotion writes Notes.
- **Consignment: zero state/table/route** (inventory_state_engine.STATES has no
  CONSIGNMENT; aggregator hardcodes count=null "not_available"; ConsignmentTab
  is a loaded-but-unmounted stub). Designed flow (operator-ratified): issue = MM
  MAIN→CONSIGNMENT (internal transfer, not WZ, no VAT); invoice consumes
  CONSIGNMENT-warehouse stock only; unsold → reverse MM. **Double-stock-out
  avoided architecturally** (MM decrements MAIN once; invoice consumes where the
  stock sits, in CONSIGNMENT — Lesson N authority separation: MM owns movement,
  INVOICE owns consumption). Every MM edge WFIRMA-GATED; the fallback
  (operator-created MM in wFirma UI + Atlas reconcile) preserves all authority
  boundaries. **SALES_TRANSIT write path missing** — needed for both normal
  sales out-leg and the consignment sale leg. Consignment allocation model =
  net-new table.

## Q6 — Mirror tables census + canonical set

**Existing mirror-shaped tables:** `wfirma_customers` (wfirma.db, client_name
key) · `wfirma_customer_mapping` (reservation.db, DUPLICATE) · `wfirma_products`
(wfirma.db) · `wfirma_product_mapping` (reservation.db, DUPLICATE) ·
customer_master (business layer) · snapshots (customer/payment — immutable audit,
not mirrors) · poll/sync-state control tables.

**Against the operator minimal-field rule** (wFirma ID + Product Code + sync
fields + design-number [Product only]): **4 tables VIOLATE it** — the two
customer caches (keyed by mutable client_name, carry ship-to/currency routing)
and the two product mirrors (carry name/unit/vat_rate/description). Two
structural duplicates (customer×2, product×2 across wfirma.db vs reservation.db)
can diverge silently.

**Proposed canonical mirror set (3 tables):**
- **wfirma_customer_mirror** — `contractor_id` PK (stable wFirma id, NOT
  client_name) + bill_to_name (label only) + sync_status + last_synced_at.
- **wfirma_product_mirror** — `product_code` PK + wfirma_product_id +
  `design_number` (the one extra field the rule allows) + sync_status +
  last_synced_at.
- **wfirma_warehouse_mirror** — NET-NEW: warehouse_code PK + wfirma_warehouse_id
  + sync_status (only if warehouse IDs must resolve from wFirma vs config const).

customer_master stays as the operator business-enrichment layer above the
mirror (NOT collapsed). Snapshots/state tables stay.

## Q7 — Synchronization matrix

| Object | wFirma API | Webhook (handler) | Scheduled sync today |
|---|---|---|---|
| **Product** | YES (goods add/find/edit) | **NO** (no goods handler) | **NO** |
| **Customer** | YES (contractors find/get/add) | INDIRECT (via invoice events, Phase 3) | **YES** (Phase 3B poll, 6h) |
| **Invoice** | YES (add/get/find/edit) | **YES** (Faktury.* → snapshot) | via webhook only |
| **PZ** | YES (add/get/find) | **NO** | **NO** (on-demand) |
| **WZ** | PARTIAL (registered, no create fn) | **NO** | **NO** |
| **MM** | **NOT MODELED** at all | NO | NO |
| **Payment** | YES (read-only find) | NO | **YES** (Phase 4A, 1h) |

Scheduler: single APScheduler 30s tick, 6 steps (register → snapshot invoices →
enrich → customer sync → payment sync → contractor poll). Webhook auth = HMAC of
`webhook_key` body field vs WFIRMA_WEBHOOK_KEY (503 if unset). The webhook
pipeline is **invoice-specific** — a goods/PZ/WZ event would fail at
`invoices/get` and dead-letter.

---

## VERDICT — the frozen architecture

### Authority map (which authority owns each future feature)

| Authority | Owns | Canonical store |
|---|---|---|
| **Product Mirror** | product ↔ wFirma goods identity + design-number linkage | wfirma_product_mirror (consolidate 2 existing) + product_authority_resolver |
| **Customer Master** | customer identity, VAT, commercial/freight/insurance/KYC defaults | customer_master.sqlite (business layer) + wfirma_customer_mirror (consolidate 2 caches) |
| **Inventory V2** | piece lifecycle, locations, stock promotion notes, sample/returns state | inventory_state_engine + warehouse.db (single-writer) |
| **wFirma** | accounting documents (PZ/WZ/MM/invoice), stock in wFirma warehouses | wfirma_client + the document endpoints |

Rule (now permanent, DECISIONS): no inventory feature starts until it names
which of these four it extends; if none, STOP and ask.

### Mirror set: 3 canonical (consolidate the 4 duplicates → 2 + 1 net-new).

### Sync strategy per object
- **Product:** on-demand API today; ADD a goods poll or webhook only if catalog
  drift becomes a problem (operator-input: do goods webhooks exist?). Consolidate
  to one mirror first.
- **Customer:** keep Phase 3 (invoice-indirect) + Phase 3B (6h poll). Consider a
  direct contractor webhook if the account emits Kontrahenci.* (operator-input).
- **Invoice:** webhook-driven (working). Confirm event registration + WEBHOOK_KEY
  set (operator-input).
- **PZ:** on-demand (working). No poll needed.
- **WZ/MM:** blocked on the wFirma answers; until then, operator-created in
  wFirma UI + Atlas reconcile.

### Ordered Phase-C implementation queue (adjusted by findings)

1. **Sample/Returns READ endpoints** — the exact gap that blocked the 4 tabs;
   app-side only, no wFirma dependency, no operator-input. Unblocks real UI
   parity. **Do first** (needs a freeze-exception since backend is frozen).
2. **SALES_TRANSIT write path** (fire invoice_issued transition on
   proforma→invoice) — app-side; needed for BOTH the normal sale out-leg and the
   consignment sale leg. No wFirma dependency.
3. **Mirror consolidation** (Product + Customer → canonical) — foundational
   de-risk; refactor, no user surface; removes the divergence risk.
4. **Consignment** (allocation model + MAIN→MM→CONSIGNMENT) — **BLOCKED on the
   MM API answer**; cannot start until Amit answers OQ-WFIRMA-MM-ANSWER.
5. **Invoice-from-consignment selection** — after (2) + (4).
6. **MM sync / WZ standalone** — WFIRMA-GATED entirely.

Buildable now without any operator-input: **(1) and (2)**. Everything past (3)
waits on the wFirma answers. This is why the Sample/Returns READ endpoints are
the single highest-value next backend slice.

---

## Consolidated OPERATOR-INPUT list (§E-merged — for Amit / wFirma support)

**Blocks the consignment build (highest priority):**
1. **MM via API** — does wFirma expose przesunięcie międzymagazynowe
   (inter-warehouse transfer) via API, and under what module/endpoint?
   (OQ-WFIRMA-MM-ANSWER; gates Phase-C queue items 4-6.)
2. **CONSIGNMENT warehouse** — run `list_warehouses()` / check wFirma UI: does a
   second warehouse exist, or must it be created? Is stock one warehouse today?
3. **WZ add via API vs invoice-auto-WZ** — one sandbox probe: does an invoice
   against a warehouse auto-emit the WZ, or is a standalone warehouse_document_w_z/add needed?
4. **get_stock enablement** — the stub (wfirma_client:1161) needs the goods/get
   grant for the double-stock-out verification read.
5. **Sandbox / test company** — is there one for MM/WZ write trials before prod?
6. **PZ delete/reversal** — does warehouse_document_p_z/delete/{id} exist? (repo
   has no delete path + a CI test that fails if one is added.)

**Account config the sync depends on:**
7. **WFIRMA_WEBHOOK_KEY** set in the NSSM prod env? (empty → all invoice webhooks
   silently 503-rejected.)
8. **WFIRMA_CREATE_PZ_ALLOWED** current prod value? (false → all PZ creates
   error before hitting wFirma.)
9. **Invoice webhooks** — which Faktury.* events are registered, and does the URL
   point at POST /api/v1/webhooks/wfirma on prod?
10. **Goods webhooks** (Towary.*) — registered? (no handler exists; would
    dead-letter.)
11. **Contractor webhooks** (Kontrahenci.*) — registered? (only indirect sync
    today.)
12. **Warehouse (Magazyn) module** active? (determines whether goods count/reserved
    populate and whether PZ add stays available.)

**Mirror-consolidation design inputs:**
13. **Stable contractor_id** in ALL wFirma responses (contractors, webhook
    payloads, invoice contractor blocks)? — required to key the canonical
    customer mirror by contractor_id instead of client_name.
14. **/magazines endpoint** in the API plan, or is warehouse_id a config constant?
    — decides whether a Warehouse mirror table is needed.
15. **Contractor API fields** — does /contractors return default_currency and
    per-contractor series IDs, or are series account-level? — decides which
    customer_master columns can auto-fill vs stay operator-only.

These merge into and extend the §E checklist
(reports/inspection/2026-07-03T-wfirma-section-e-operator-checklist.md).

---

# AMENDMENT (2026-07-03) — Single-application model + authority violations

Added atop the original audit (b9f5664c) per operator direction. Governs the
APPLICATION AUTHORITY RULE (CLAUDE.md constitution + PROJECT_STATE DECISIONS):
**one application = EJ Dashboard**; every module reaches wFirma only via
`<module> → EJ Dashboard <Master> → Mirror → wFirma`; direct wFirma
product/customer maps and module-grown masters are violations.

**PROPOSED-NOT-DONE / QUESTIONS-STOPPED-ON / DEVIATIONS-DISCLOSED:** this
amendment is READ-ONLY analysis. The canonical mirrors, the Product Master
consolidation, and every violation fix below are PROPOSALS — none is
implemented. No file/path/table containing "PZ" is renamed (R1 scope note).
Nothing here touches code. Any fix is a separate operator-approved slice.

## Q0 — EJ Dashboard authority census

One application authority (EJ Dashboard). Verdicts reuse b9f5664c evidence.

| Authority | Canonical files | Canonical API | Canonical DB | Dependents / integrations | Verdict |
|---|---|---|---|---|---|
| **Product Master** | product_authority_resolver.py, reservation_db.py (product_master, design_product_mapping) | resolve_batch_product_authority() | reservation_queue.db (product_master advisory) | proforma_draft_sync, sales_packing_matcher, design_product_bridge, routes_wfirma product-resolve | **FRAGMENTED** — no single Product Master: design linkage is clean (one resolver) but wFirma-goods identity is SPLIT across wfirma_products (wfirma.db) + wfirma_product_mapping (reservation.db), and product_master is advisory-only. A single canonical Product Master does not exist yet. |
| **Customer Master** | customer_master_db.py | upsert_customer / upsert_identity_only | customer_master.sqlite | proforma resolver, ledgers, suppliers, dashboard, contractor-projection | **REAL but FRAGMENTED** — customer_master.sqlite is the identity/VAT/commercial authority, but two name-keyed caches (wfirma_customers in wfirma.db, wfirma_customer_mapping in reservation.db) fragment it and the invoice XML sources wfirma_customer_id from a cache. |
| **Inventory** | inventory_state_engine.py + warehouse_db.py | transition() (single-writer) | warehouse.db | PZ promotion, sample/returns writers, Move Stock modal, location reads | **REAL** — single-writer discipline; the strongest authority. |
| **Packing** | packing_db.py | get_packing_lines_for_batch, resolver feed | packing.db (packing_lines) | product resolver, PZ rows, sales matcher | **REAL**. |
| **PZ** | routes_wfirma.py (pz_create) + stock_promotion.py | POST /wfirma/pz/create, run_stock_promotion() | audit.json (wfirma_export) + inventory_state | import pipeline, DHL bridge | **REAL** (live-proven, gated). |
| **WZ** | — (registered string only) | none (no create fn) | none | operator lifecycle rule references it | **ABSENT** — registered in _WAREHOUSE_MODULES, no create fn, SALES_TRANSIT never fired. |
| **Invoice** | routes_proforma.py + wfirma_client (invoices/*) | create_proforma_draft, to-invoice conversion | proforma_links.db + wfirma_invoice_snapshots | webhook pipeline, customer sync | **REAL**. |
| **Sample** | inventory_sample_writer.py + routes_inventory_sample.py | POST sample-out / sample-return | warehouse.db (sample_out_events) | inventory_state_engine | **REAL but WRITE-ONLY** (no read/list endpoint — the Phase-C gap). |
| **Consignment** | client-kyc-and-consignment.jsx (unmounted stub) | none | none (aggregator hardcodes not_available) | nothing (stub loaded, mounted nowhere) | **ABSENT** — no state, table, or route. |
| **Returns** | inventory_returns_writer.py + routes_inventory_returns.py | POST return-from-client / to-producer / from-producer | warehouse.db (returns_events; migration not applied in prod) | inventory_state_engine | **REAL but WRITE-ONLY** (no read/list; returns migration pending). |

## Q3-amend — Violation inspection (direct wFirma product/customer maps)

Exact call sites that bypass an EJ Dashboard master and map DIRECTLY to wFirma
(read-only grep; cited). The Customer Master's OWN sync (routes_customer_master
pulling wFirma to fill itself) is the authority doing its job — but it still
maps direct-to-wFirma without a mirror layer (design-debt, listed as V7).

- **Fragment tables (module-grown masters):** wfirma_customers (wfirma_db.py:62)
  + wfirma_customer_mapping (reservation_db.py:76) — two client_name-keyed
  customer caches; wfirma_products (wfirma_db.py:79) + wfirma_product_mapping
  (reservation_db.py:60) — two split product mirrors.
- **routes_ledgers.py:155,288** — `wfirma_client.fetch_contractor_by_id` direct.
- **routes_proforma.py:1500,1529,7767,7800** (`search_customer` live) + **:1877,
  3637,8067** (`fetch_contractor_by_id`) — direct customer fallback bypassing
  Customer Master.
- **routes_suppliers.py:396** — `fetch_contractor_by_id` direct.
- **routes_reservations.py:161** — `get_product_by_code` shim direct.
- **routes_wfirma.py:1926,2003,2320** — product resolve/create/edit direct (no
  Product Master upstream).
- **routes_wfirma_capabilities.py:279,310,373,440,515** — customer/product probes
  (read-only diagnostic; wFirma-facing by purpose — lower risk).

## AUTHORITY VIOLATIONS (cleanup list, ordered by risk)

```
V1  Product write path (routes_wfirma.py:2003 create_product / :2320 edit_product)
    -> wFirma goods, with NO single Product Master upstream
    Status: AUTHORITY VIOLATION (write, highest risk)
    Correct path: Product module -> EJ Dashboard Product Master -> Mirror -> wFirma

V2  Two product mirrors: wfirma_products (wfirma_db) + wfirma_product_mapping (reservation_db)
    -> split product↔wFirma identity across two DBs, both carry business fields
    Status: AUTHORITY VIOLATION (fragmented master)
    Correct path: one canonical Product Master + one wfirma_product_mirror(product_code+design)

V3  Two customer caches: wfirma_customers (wfirma_db) + wfirma_customer_mapping (reservation_db)
    -> client_name-keyed masters that duplicate Customer Master; invoice XML sources id from a cache
    Status: AUTHORITY VIOLATION (fragmented master, mutable key)
    Correct path: Customer Master -> one wfirma_customer_mirror(contractor_id) -> wFirma

V4  routes_proforma customer fallback (:1500/1529/7767/7800/1877/3637/8067)
    -> wfirma_client.search_customer / fetch_contractor_by_id direct
    Status: AUTHORITY VIOLATION (module bypasses Customer Master)
    Correct path: Proforma -> Customer Master -> Mirror -> wFirma

V5  routes_ledgers.py:155,288 -> fetch_contractor_by_id direct
    Status: AUTHORITY VIOLATION (module bypasses Customer Master)
    Correct path: Ledgers -> Customer Master -> Mirror -> wFirma

V6  routes_reservations.py:161 -> get_product_by_code direct
    Status: AUTHORITY VIOLATION (module bypasses Product Master)
    Correct path: Reservations -> Product Master -> Mirror -> wFirma

V7  routes_suppliers.py:396 + routes_customer_master.py:498,699 -> direct wFirma contractor calls
    Status: AUTHORITY VIOLATION (supplier module direct; Customer Master maps
    direct without a mirror layer — design-debt, lowest risk)
    Correct path: <module> -> Master -> Mirror -> wFirma
```

Diagnostic wFirma-capabilities probes (routes_wfirma_capabilities.py) are
wFirma-facing by design (read-only) — NOT counted as violations.

## Phase-C queue, reframed under the single-application model

The original queue holds; reframed so every item names its EJ Dashboard
authority (no new applications, no new masters):

1. **Sample/Returns READ endpoints** — extends the **Inventory authority**
   (reads inventory_state + sample_out_events/returns_events; clients via
   Customer Master). Zero wFirma. Buildable now (freeze-exception). **← Part 2.**
2. **SALES_TRANSIT write path** — extends the **Inventory authority** (fires the
   invoice_issued transition from the Invoice authority). App-side.
3. **Mirror consolidation** — collapses V2+V3 into the canonical **Product
   Master** + **Customer Master** mirror layer; fixes V1/V4/V5/V6 routing.
4. **Consignment** — new capability under the **Inventory authority**
   (allocation model) + **wFirma** (MM). BLOCKED on the MM answer.
5. **Invoice-from-consignment** — **Invoice authority** consuming
   consignment-warehouse stock.
6. **MM sync / WZ** — **wFirma authority**; WFIRMA-GATED.

No item creates a new application or master; each extends an existing EJ
Dashboard authority. Buildable without operator-input: (1), (2).
