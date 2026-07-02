# wFirma Authority Map + Wireframe Parity Inspection (recovered, disk-first)

- **Date:** 2026-07-02 · read-only inspection · zero app-code edits
- **Provenance:** re-run of the two-deliverable inspection whose original
  output was lost in the chat transport channel (never persisted). This file
  is written to disk section-by-section BEFORE any in-channel summary, per
  operator write-to-disk-first instruction.
- **Wireframe source:** the operator's Claude Design project
  (`019dcc53-c41d-76f7-8e56-6d01d10be635`, file "Estrella Dashboard.html")
  could NOT be fetched — DesignSync requires interactive design authorization
  (`/design-login`) unavailable in this session. Fallback used, per the
  operator's own instruction: the column inventories supplied in-channel
  (packing-list: PK SR / CTG / Client PO / Design No / Karat / Color /
  Quality / Dia Wt / Qty; consignment: Cons.ID / Client / Design / Qty /
  Value / Issued / Due Back / Days Out / Proforma; KPI tiles; tabbed subnav;
  Upload Document / Move Stock / Cycle Count / Export actions) + the
  design-language stubs still recoverable from the V2 tree.
- **"Implement: Estrella Dashboard.html" tail in the instruction:** NOT
  executed — it contradicts the same message's pre-flight ("zero edits this
  run", "STOP. No app-code edits") and the no-duplicate-page authority rule
  (a new dashboard HTML would be a second app). Implementation requires its
  own pre-flight and explicit operator approval.
- **Reuse discipline:** BE-1b scope findings already ratified in
  PROJECT_STATE DECISIONS (states enum, PZ hooks, WZ net-new, DHL bridge)
  are CITED here, not re-derived.

---

## DELIVERABLE 1 §C — Business workflow plan (wFirma-synchronized inventory)

Operator lifecycle rule (DECISIONS, verbatim): *"Inventory temp states are
document-event-driven, synchronized with wFirma: Temp Purchase closes
AUTOMATICALLY on PZ creation (goods received -> real warehouse stock). WZ
creation moves goods out -> Temp Sale (in transit to customer), shown as out
in wFirma and Atlas. DHL delivery confirmation closes Temp Sale. Manual Move
Stock page = exception/correction path only; the document is the primary
trigger."*

Operator consignment rule (this instruction, binding): *consignment issue =
wFirma MM internal transfer (Main → Consignment warehouse), NOT a sale WZ;
the invoice consumes CONSIGNMENT-warehouse stock only — prevents double
stock-out.*

### C1. PZ import (goods arrive → real warehouse stock) — SHIPPED (BE-1)
1. Import pipeline seeds pieces `None → PURCHASE_TRANSIT`
   (routes_packing.seed_purchase_transit).
2. App-pipeline PZ created (internal generation, wFirma create, correction
   push) → shared `run_stock_promotion()` auto-promotes
   `PURCHASE_TRANSIT → WAREHOUSE_STOCK` (commit 0900b227; idempotent; both
   orderings pinned). Physical-receipt confirm (dhl_delivery_bridge) remains
   a parallel promoter.
3. Direct-wFirma-booked PZs: NOT seen (BE-1c parked, DECISIONS assumption).

### C2. WZ issue (sale dispatch → stock out) — NET-NEW backend
1. Sales dispatch (proforma→invoice or packing dispatch) triggers WZ creation
   in wFirma via a new `wfirma_client.create_warehouse_wz()` — pattern-clone
   of `create_warehouse_pz` (module `warehouse_document_w_z` is already in
   the client's registry; no create function exists — DECISIONS B×7-1b
   scoping, wfirma_client.py:39).
2. On WZ success: pieces `WAREHOUSE_STOCK → SALES_TRANSIT` ("Temp Sale")
   via a shared `run_stock_issue()` (same one-shared-function doctrine as
   BE-1).
3. DHL delivery confirmation (outbound: carrier live adapter maps
   `DELIVERED → ShipmentState.COMPLETE`, carrier/adapters/live.py:161)
   closes Temp Sale → `CLIENT_DISPATCHED` (bridge pattern-clone of
   dhl_delivery_bridge — propose → operator confirm → transition).

### C3. MM Main → Consignment (consignment issue) — NET-NEW, gated on §B
1. Consignment issue creates a wFirma **MM internal transfer** between the
   MAIN warehouse and a CONSIGNMENT warehouse. It is NOT a WZ and NOT a
   fiscal sale — no invoice, no VAT event.
2. Atlas records: piece-level consignment allocation (Cons.ID, client,
   issued date, due-back date) — net-new local model; lifecycle state stays
   within warehouse custody (a consignment sub-state or location/warehouse
   dimension — model decision for the operator, cross-ref §D).
3. PRECONDITION (§B gap): confirm wFirma API supports MM via API and that a
   second (Consignment) warehouse id exists — see §B findings.

### C4. Invoice from consignment pieces — NET-NEW, double-stock-out guard
1. Customer confirms sale of consigned pieces → invoice (proforma→invoice
   conversion authority, existing) with lines resolved to the SPECIFIC
   consigned pieces (Cons.ID linkage).
2. Stock consumption MUST come from the CONSIGNMENT warehouse only (wFirma
   invoice/WZ against the consignment warehouse id). The MAIN warehouse must
   never be decremented for a consigned piece — this is the double-stock-out
   guard: MM already moved the stock; the invoice consumes it where it sits.
3. Atlas closes the consignment allocation (piece → CLIENT_DISPATCHED /
   CLOSED), records invoice number on the allocation row.

### C5. Return Consignment → Main — NET-NEW
1. Unsold consigned pieces come back → reverse MM (Consignment → Main) in
   wFirma; Atlas closes the allocation as returned, pieces remain
   WAREHOUSE_STOCK (custody never left the company).
2. Due-back/days-out tracking drives the return workflow (wireframe columns
   Due Back / Days Out).

### C6. Contract-number linkage — cross-cutting
Wireframe requires Client PO / contract-number on packing-list lines and
Proforma linkage on consignment rows. Backend reality per §A/§B evidence
(fields present or absent in packing_lines / proforma models) — the linkage
rule: one contract/PO reference travels invoice→packing→PZ→allocation→
invoice, never re-keyed manually per stage.

---

## DELIVERABLE 1 §A — Existing authority map

Evidence: 4-inspector read-only pass (workflow wf_156b27e6-c70, 2026-07-02);
citations are repo-relative. Status legend: LIVE = wired, in WIRED_PAGES ·
MOCK = renders with MOCK banner · REDIRECT = slug forwards to a live page ·
RESERVED = slug held for a planned authority · UNUSED = loaded but never
mounted.

| Module | URL | Frontend file | Backend route(s) | Service | DB model | Status |
|---|---|---|---|---|---|---|
| Stock Hub (inventory) | /v2/inventory | inventory-page.jsx | 8 read-only: /inventory/stage2/aggregate, /inventory/state/{b}, /inventory/pieces/{id}, /warehouse/inventory/{scan}, /warehouse/locations(+/{code}/inventory), /warehouse/audit(-summary)/{b} (inventory-page.jsx:13-20) | inventory_stage2_aggregator, inventory_state_engine, warehouse_db | warehouse.db: inventory_state(+events), inventory_current_location | LIVE |
| Move Location | /v2/move_location | move-location-page.jsx | GET /inventory/state/{b}; POST /inventory/pieces/{id}/location | inventory_location_writer | warehouse.db: inventory_current_location, inventory_movement_events | LIVE (B×7-1) |
| Move Stock (business promotion) | /v2/move_stock → inventory | — (reserved) | backend BE-1 shipped: run_stock_promotion (0900b227) | stock_promotion.py | inventory_state | RESERVED (B×7-1b UI pending) |
| Sample out / return | /v2/sample_out, /v2/sample_return → inventory | stubs SampleOutPage/SampleReturnPage in wireframe-update.jsx:492-526 | POST /inventory/pieces/{id}/sample-out, /sample-return (routes_inventory_sample.py:91-144) — LIVE routes | inventory_sample_writer | sample_out_events (idempotent), inventory_state | REDIRECT (backend LIVE, UI missing) |
| Goods return / return to producer | /v2/goods_return, /v2/return_prod → inventory | stubs GoodsReturnPage/ReturnToProducerPage (wireframe-update.jsx:528-562) | POST /inventory/pieces/{id}/return-from-client, /return-to-producer, /return-from-producer (routes_inventory_returns.py:116-201) | inventory_returns_writer | returns_events (migration draft_20260512_175238 PENDING) | REDIRECT (backend LIVE, UI missing) |
| Identity / mapping | /v2/identity → inventory; /v2/wfirma_setup | IdentityMappingPage stub (wireframe-update.jsx:465-481); WfirmaMappingPage (ops-cell.jsx:599) | GET /wfirma/capabilities, /wfirma/customers, /wfirma/products | wfirma_client, wfirma_db | wfirma product/customer maps | wfirma_setup LIVE; identity REDIRECT |
| Consignment | no slug | ConsignmentTab (client-kyc-and-consignment.jsx:282) loaded by index.html:308 but mounted NOWHERE; mock row in ledgers-page.jsx:712 | NONE | NONE — aggregator returns count=null "no consignment state or table" (inventory_stage2_aggregator.py:65-68) | NONE | UNUSED stub / backend ABSENT |
| Proforma family | /v2/proforma, /v2/proforma_detail, /v2/proforma_search | proforma-list.jsx, proforma-detail.jsx, proforma-search.jsx | /proforma/drafts/{b}, /proforma/draft/{id}, /proforma/search, to-invoice conversion (routes_proforma.py:3311-4001) | proforma services, wfirma_client | proforma_drafts, proforma_invoice_links | LIVE |
| Accounting hub | /v2/accounting | accounting-hub.jsx (internal tabs: overview, pi/inv/cn, **wz/pz/pw/rw/mm warehouse docs**, ledgers, wfirma sync — accounting-hub.jsx:16-34) | none wired | — | — | MOCK (not in WIRED_PAGES) |
| PZ (import) | batch pages + wfirma actions | V1 + master/detail flows | POST /wfirma/pz/create (routes_wfirma.py:2520), global_pz_push, pz generation (routes_upload) | wfirma_client.create_warehouse_pz, stock_promotion | audit.json wfirma_export, packing_lines | LIVE |

Nav truth: g_inventory group = Stock Hub + Move Location
(components.jsx:27-30); WIRED_PAGES = 19 (mock-badge.jsx:66); 12 redirects
(index.html:368-381).

---

## DELIVERABLE 1 §B — wFirma capability gap

### Supported today (functions that exist in wfirma_client.py)
- **PZ**: create_warehouse_pz (:1513, gated WFIRMA_CREATE_PZ_ALLOWED),
  fetch_warehouse_pz (:1370), find_warehouse_pz_by_number (:1442) —
  **live-proven in production** (doc-ids + fullnumbers mapped back).
- **Reservation (R)**: create_reservation (:1198).
- **Invoices/proforma**: create_proforma_draft (:1596, verify-after-create),
  delete_invoice (:2163), edit_invoice_line_name (:2643), fetch_invoice_xml
  (:2418), fetch_invoice_pdf (:2529), fetch_invoices_for_contractor (:2202),
  fetch_payments_for_contractor (:2316), VAT context helpers (:1724-1907).
- **Contractors**: search/fetch/list/count/create (:607-958).
- **Goods**: get_product_by_code (:963), create_product (:1019),
  edit_product (:1089). get_stock is a **NotImplementedError stub** (:1161).
- **Warehouses**: list_warehouses (:536) — multiple warehouses enumerable;
  per-document warehouse targeting implemented (_build_pz_xml emits
  <warehouse><id>, :1358).
- **Series**: fetch_series (:2745, series/find CONFIRMED); auth = 3-header
  API Key (accessKey/secretKey/appKey, Basic Auth deprecated 2023-07-02);
  company_id on every URL; circuit breaker wraps all calls.

### Registered module strings with NO create function
warehouse_document_p_w (PW), r_w (RW), **w_z (WZ)**, z_d (ZD)
(wfirma_client.py:34-42). WZ create = additive pattern-clone of
create_warehouse_pz — but see verification note below.

### ABSENT entirely — the §C3 blocker
**MM (przesunięcie międzymagazynowe / inter-warehouse transfer) does not
exist**: not in the client registry, not in python-wfirma's documented type
list (PW, PZ, R, RW, WZ, ZD, ZPD, ZPM — WFIRMA_API_RESEARCH.md:175), not in
any of the four wFirma docs. The consignment flow (§C3, MM Main→Consignment)
has NO verified API vehicle today.

### Stale-docs vs live reality (must-know)
WFIRMA_PZ_API_FEASIBILITY.md:5 says warehouse-document add is "BLOCKED —
requires live verification"; a 2023 wFirma forum thread (cited at
WFIRMA_API_RESEARCH.md:181) claims API warehouse-document creation is not
possible and that "WZ is only auto-generated by issuing an invoice."
**Production disproves this for PZ** — the app creates PZ documents via
warehouse_document_p_z/add today. Conclusion: the docs are stale for PZ;
WZ/MM remain UNVERIFIED. The forum's "invoice auto-generates WZ" claim, if
still true, aligns exactly with §C4 (invoice consumes consignment stock →
wFirma emits the warehouse movement itself).

### wFirma must provide / Amit must verify (feeds the §E checklist)
1. **MM via API** — ask wFirma support directly; if unavailable: consignment
   MM is done manually in the wFirma UI and Atlas reconciles (§C3 fallback),
   or an RW+PW pair is evaluated (needs accounting sign-off).
2. **WZ add via API** vs invoice-auto-WZ — one live sandbox probe decides
   the §C2 implementation shape.
3. **Consignment warehouse id** — a second warehouse must exist in wFirma
   (list_warehouses already enumerates).
4. **Stock read** (goods count/reserved) — get_stock stub needs enabling for
   the double-stock-out guard's verification read.

### Flows missing in OUR backend (independent of wFirma)
- **Invoice → SALES_TRANSIT transition does not exist**: the
  proforma→invoice conversion (routes_proforma.py:3311-4001) never calls
  inventory_state_engine.transition(); SALES_TRANSIT ("Temp Sale") is
  defined with trigger 'invoice_issued' (:29,:78) but NO code path fires it.
  The operator lifecycle rule's out-leg is unimplemented.
- **Consignment model**: no state, no table, no route (aggregator basis
  "not_available", inventory_stage2_aggregator.py:65-68).
- **Contract/PO linkage**: client_po is parsed (excel_column_mapper.py:53,
  invoice_packing_extractor.py:480) and passed by routes_packing.py:1443 —
  then **silently dropped** at the DB layer (document_db.py:2003-2025 INSERT
  has no client_po column). No contract field in packing_lines,
  sales_packing_lines, or proforma_drafts.
- **Returns migration** draft_20260512_175238_returns_events.py.draft not
  applied (returns writer blocked in prod until deploy-gated apply).
- Piece↔invoice-line linkage is preview-time-only (no persisted reservation
  binding an invoice line to scan_codes; routes_proforma.py:775-854).

---

## DELIVERABLE 1 §D — No-duplicate implementation plan

Every function maps to an EXISTING owner. No new page/app/HTML without its
own pre-flight + operator approval.

| Function | Owner (existing) | What changes | Backend dependency (§B) |
|---|---|---|---|
| Stock KPIs (Final/Samples/Returns/Consignment tiles) | Stock Hub `panel-stage2` | extend StatBadge row when consignment backend exists | consignment model (net-new) |
| Physical shelf/zone move | Move Location page (LIVE) | none — shipped | — |
| Business stage promotion + Stock Promotion Note | **reserved move_stock slug** (g_inventory child) | B×7-1b UI slice on the approved-planned slug; BE-1 backend shipped (0900b227); BE-2 Note doc next | Note table+series (net-new, local) |
| Sample out / sample return UI | reserved slugs sample_out / sample_return; recoverable stubs (wireframe-update.jsx:492-526) | promote-in-place per Sprint-31 playbook, wire to LIVE routes_inventory_sample | none — backend exists |
| Goods return / return to producer UI | reserved slugs goods_return / return_prod; stubs :528-562 | same playbook, wire to LIVE routes_inventory_returns | returns migration apply (deploy-gated) |
| Consignment ledger (Cons.ID/Due Back/Days Out) | ConsignmentTab component (exists, UNUSED) → future g_inventory child | backend FIRST (state-or-location model decision + table + routes); then mount the existing component — do NOT build a second one | consignment model + MM answer |
| Invoice from consignment | proforma family (existing conversion authority) | add consignment-warehouse stock consumption + allocation close | MM/WZ verification; SALES_TRANSIT writer |
| Sale out-leg (WZ / Temp Sale) | proforma conversion + new shared run_stock_issue() (BE-1 doctrine) | fire WAREHOUSE_STOCK→SALES_TRANSIT on invoice/WZ; DHL-delivered close via dhl_delivery_bridge clone | WZ add or invoice-auto-WZ |
| Warehouse document register (PZ/WZ/PW/RW/MM lists) | accounting-hub.jsx (MOCK — already has these exact internal tabs, :16-34) | wire when document APIs verified | wFirma document reads |
| Identity / SKU mapping | wfirma_setup (WfirmaMappingPage, LIVE) | absorb IdentityMappingPage stub scope there; identity slug keeps redirecting | mapping write endpoints |
| Contract/PO linkage | packing/proforma models + existing tables' columns | add client_po column end-to-end (parser already yields it) | DB column + INSERT fix |
| Upload Document action | documents hub / batch upload (existing routes_upload surfaces) | not an inventory-page duplicate | — |
| Cycle Count | NO owner — net-new capability | future g_inventory child; requires its own pre-flight + approval | net-new count model |
| Export | existing export idiom (dashboard Export CSV) | per-table export buttons on existing pages | — |

---

## DELIVERABLE 2 — Wireframe parity (Inventory family)

Design authority: operator wireframe (column inventories supplied in-channel;
Claude Design project not fetchable — see provenance). Recoverable
design-language: the five surviving wireframe stubs + V1 Stage-1/Stage-2
labels (dashboard.html:1939, 1963-1974, 20184).

### Stock Hub (/v2/inventory — LIVE)
| Wireframe | Current V2 | Missing | Wrong | Required change (component) | Backend dep |
|---|---|---|---|---|---|
| KPI tiles row | 3 StatBadges (Final stock/Samples out/Returns, inventory-page.jsx:281-286) | Consignment tile (V1 shows it as backend-pending) | — | add tile when backend exists | consignment model |
| Packing-list-grade table: PK SR/CTG/Client PO/Design No/Karat/Color/Quality/Dia Wt/Qty | batch table = Scan code/State/Design/Updated (:352-356); location table = Scan/Status/Design/Bag (:577-580) | Karat, Color(stone), Quality, Dia/weights, Qty, Client PO, CTG, PK SR columns | tables are lookup-grade, not merchandising-grade | joined read (inventory_state ⋈ packing_lines — karat/stone_type/weights/qty EXIST in packing_lines) + column render | new joined read endpoint; client_po column fix |
| Tabbed subnav | SubTabStrip: Stock Hub + Move Location | Sample/Return/Consignment tabs (slugs still redirect) | — | promote family pages per §D | per §D rows |
| Actions: Upload Document / Move Stock / Cycle Count / Export | NONE (deliberately removed — dead write-implying buttons, index.html:663-664 + sprint30 pin) | all four | old mock buttons were fake — removal was correct | reinstate ONLY as real actions: Move Stock→B×7-1b page; Export→CSV of live tables; Upload→documents hub link; Cycle Count→future | B×7-1b; count model |

### Move Location (/v2/move_location — LIVE)
| Wireframe | Current V2 | Missing | Wrong | Required change | Backend dep |
|---|---|---|---|---|---|
| Checkbox multi-select table | ✓ checkbox + Piece/Design/Product/State/Updated (move-location-page.jsx:154-188) | Karat/Qty/value columns; KPI header | bare-form aesthetic vs design's KPI+table composition | optional enrichment via same joined read | joined read |
| Move Stock semantics | correctly SEPARATED — this page is the location helper (decision (i)) | the true Move Stock (promotion+Note) page | — | B×7-1b UI slice on reserved slug | BE-2 Note |

### Consignment (future page — biggest gap)
Wireframe columns Cons.ID/Client/Design/Qty/Value/Issued/Due Back/Days Out/
Proforma: **nothing live** — ConsignmentTab stub exists UNUSED with hardcoded
rows; no state, no table, no route (§A). Entire slice = backend-first
(model decision + MM answer), then mount the existing component. No second
component may be built (§D).

### Sample Out / Sample Return (redirect slugs)
Backend LIVE with evidence contracts (recipient, reason enum, future return
date; 30-day overdue block; idempotent events). UI absent; stubs carry the
design columns (Sample ID/Client/Item/Out Date/Expected Return/Status ·
Returned/Outcome/QC). Required: promote-in-place + wire to real routes;
convert-to-sale / write-off / extend advertised in stubs have NO backend —
planned-state honesty (Lesson M) when built.

### Goods Return / Return to Producer (redirect slugs)
Backend LIVE (reason enums, origin_context, producer evidence); returns_events
migration pending. Stub columns (RMA/Client/Original Inv./Items/Reason/Status ·
Producer RMA/Supplier/Original PI). Credit-note/debit-note wFirma writes in
the stubs have NO backend — future, approval-gated.

### Top-5 parity gaps (ranked)
1. **Consignment**: zero backend + unused stub vs full wireframe ledger; MM
   absent from the wFirma API surface (§B) — needs the wFirma answer before
   any build.
2. **Sale out-leg**: invoice conversion never fires
   WAREHOUSE_STOCK→SALES_TRANSIT — "Temp Sale" is unreachable today; the
   lifecycle rule's WZ/out leg is unimplemented (our side, independent of
   wFirma).
3. **Client PO / contract number**: parsed then silently dropped at the DB
   INSERT — wireframe requires it on every table; end-to-end column fix.
4. **Samples/Returns UI**: live, evidence-gated backend with NO UI — the
   cheapest parity win (stubs + routes both exist; wire per Sprint-31
   playbook).
5. **Merchandising-grade columns**: Stock Hub/Move Location tables show 4-6
   lookup columns vs the wireframe's 9 (Karat/Color/Quality/Dia Wt/Qty…) —
   data already in packing_lines; needs one joined read endpoint.

