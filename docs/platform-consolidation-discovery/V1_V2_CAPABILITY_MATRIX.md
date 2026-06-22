# V1_V2_CAPABILITY_MATRIX.md — Estrella PZ Platform

**Campaign:** EJ PLATFORM CONSOLIDATION DISCOVERY
**Inspected:** `origin/main @ fb70e15` (read-only)
**Date:** 2026-06-18
**Companion docs:** [AUTHORITY_MAP.md](./AUTHORITY_MAP.md) · [DUPLICATE_AUTHORITY_REPORT.md](./DUPLICATE_AUTHORITY_REPORT.md) · [MIGRATION_ROADMAP.md](./MIGRATION_ROADMAP.md)

## Legend
**Surfaces:** V1 = `static/{dashboard,shipment-detail,batch,warehouse}.html` (FROZEN, Lesson F) · T1 = Track-1 standalone `static/*-v2.html` · T2 = Track-2 `static/v2/*.jsx` shell (WIRED 17/17) · ATL = `static/atlas/*.html` shell.
**Wiring status:** LIVE (real fetch + write) · READ (read-only live) · PENDING (disabled `PendingAction`, route named) · STUB (visual shell) · MOCK (hardcoded data) · — (absent).
**Authority source:** backend `derive_*` = backend-authoritative; client = computed in JS.

---

## 1. Shipments / Shipment detail

| Capability | V1 | T1 | T2 | ATL | Authority | Gap / Redundancy |
|---|---|---|---|---|---|---|
| Batch list | LIVE `dashboard.html` | LIVE `dashboard-v2.html` | LIVE `dashboard-page.jsx`/`dashboard-kanban.jsx` | READ `shipments-v2.html`,`dashboard-v2.html` | `routes_dashboard.py:492` | **6 consumers, one endpoint**; lane logic differs (V1 `OP_PREDICATES` vs T2 `deriveLane`) |
| New shipment intake | LIVE | partial `shipment-detail-v3.html` | — | PENDING (Sprint 03) | `routes_intake.py` | Only V1 complete |
| Shipment detail (full) | LIVE `shipment-detail.html` | partial v3 | LIVE `shipment-detail-page.jsx` (writes are PENDING) | — | `operational_authority.derive_status/sad/pz` | **2 live renderers, same batch** (CA-3) |
| DHL/customs tab | LIVE | — | PENDING (`shipment-detail-page.jsx:506-511`) | — | `routes_dhl_clearance.py` | V2 DHL tab = disabled stubs |
| PZ/accounting tab | LIVE (`shipment-detail.html:2486`) | — | PENDING (`:631-634`) | STUB `pz-v2.html` (Sprint 07) | `routes_wfirma.py:2485` | V1 only live write path |
| Timeline | LIVE | — | LIVE | — | `routes_tracking.py` | redundant |
| CN/HSN decision, operator-override | LIVE only | — | — | — | `routes_dashboard.py` | V1 only |

## 2. Dashboard / cross-batch

| Capability | V1 | T1 | T2 | ATL | Gap/Redundancy |
|---|---|---|---|---|---|
| Batch table + filters | LIVE | READ `dashboard-v2.html` | LIVE `dashboard-page.jsx` | READ `atlas/dashboard-v2.html` | **4 UIs, same endpoint** |
| Kanban lanes | LIVE (client `OP_PREDICATES`) | — | LIVE `dashboard-kanban.jsx` (`deriveLane`) | — | two client derivations diverge |
| Inbox / proposals | LIVE | STUB `inbox-v2.html` | LIVE `inbox-page.jsx` | — | redundant |
| DHL automation status | LIVE | LIVE `dhl-automation-v2.html` | READ `dhl-scan-status.jsx`,`dhl-daily-summary.jsx` | — | 3 surfaces, diff endpoints |
| Email queue, DSK audit log | LIVE only | — | — | — | V1 only |
| Finance/accounting | LIVE `/finance/postings` | LIVE `accounting-hub-v2.html` | **MOCK** `accounting-hub.jsx` | READ `atlas/ledgers-v2.html` | endpoint-shape mismatch `/finance/postings` vs `/ledger/clients` |

## 3. Inventory (read + writes)

| Capability | V1 | T1 | T2 | Authority | Gap |
|---|---|---|---|---|---|
| Stage-2 aggregate, batch state, piece lookup, warehouse audit | LIVE | LIVE `inventory-v2.html` | LIVE `inventory-page.jsx` | `routes_inventory.py`, `routes_warehouse_audit.py` | **3 surfaces redundant (read)** |
| Piece-location write (move) | LIVE (scan panel) | — | — | `routes_inventory_writes.py:43` | **No V2 write surface** |
| Returns (from-client/to-producer/from-producer) | — | — | — | `routes_inventory_returns.py:116,148,181` | **Backend exists; NO frontend anywhere** |
| Sample out/return | — | — | — | `routes_inventory_sample.py` | **Backend exists; NO frontend** |
| Consignment | — | — | — | none | **No backend, no UI** (`dashboard.html:1357` "no backing state or table") |

## 4. Authority / readiness cards

| Capability | V1 | T1 | T2 | Authority | Note |
|---|---|---|---|---|---|
| ReadinessBanner (per-domain) | LIVE `shipment-detail.html:873` | — | PENDING (no live readiness fetch in `shipment-detail-page.jsx`) | `routes_batch_readiness.py`, `routes_dhl_readiness.py` | V2 shipment detail lacks readiness load |
| Proforma readiness gate | LIVE inline | LIVE `proforma-v2.html` (`ProformaReadinessGate`) | LIVE `proforma-detail.jsx:801` | `routes_proforma.py:5376`, `customer_resolution_authority.py:209` | **T1+T2 both wired** |
| Overall readiness card | LIVE (real per-domain calls) | client `deriveLane` | client (batch-level only) | `operational_authority` | V2 dashboards derive from batch fields, not per-domain calls |

## 5. Proforma — the most mature V2 domain

| Capability | V1 | T1 | T2 | Authority | Note |
|---|---|---|---|---|---|
| Draft list (per-batch) | LIVE inline | LIVE `proforma-v2.html` | LIVE `proforma-list.jsx` | `routes_proforma.py:4006` | 3 surfaces |
| Draft detail | partial | **LIVE** `proforma-detail-v2.html` (1,073 ln) | **LIVE** `proforma-detail.jsx` (3,008 ln) | `routes_proforma.py:4027` | **dual full write surfaces (CA-1, HIGH)** |
| Approve/re-open, post-to-wFirma, convert-to-invoice | LIVE (old route shapes) | LIVE (disclosure modal) | LIVE (disclosure modal) | flag-gated `WFIRMA_CREATE_{PROFORMA,INVOICE}_ALLOWED` | T1 uses v1 `pz-api.js` lacking readiness pre-check |
| Clone, reset-from-packing, cancel | — | LIVE | LIVE | `routes_proforma.py` | **V2-only capabilities** |
| Cross-batch search | — | — | LIVE `proforma-search.jsx` | `routes_proforma.py:3929` | **T2-only** (M6) |
| Convert route shape | `/to-invoice/{batch}/{client}` (V1) | `/draft/{id}/to-invoice` (V2) | same | — | route divergence V1↔V2 |

## 6. DHL integrations

| Capability | V1 | T1 | T2 | Note |
|---|---|---|---|---|
| Scan inbox, mark-received, generate Polish desc, generate DSK, build/send reply | LIVE (`shipment-detail.html` + `batch.html`) | — | PENDING (`shipment-detail-page.jsx:506-511`) | **V1 only live; all V2 DHL writes are disabled stubs** |
| Followup automation (send-now/stop/recalc/mode) | LIVE | READ `dhl-automation-v2.html` | PENDING | V2 = monitoring only |
| Daily summary, auto-scan status | LIVE | LIVE | READ (`dhl-daily-summary.jsx`,`dhl-scan-status.jsx`) | redundant monitors |
| Self-clearance state, proactive dispatch | LIVE only (shadow mode) | — | — | V1 only |
| Live DHL label adapter | — | — | — | `carrier/adapters/live.py:44` `NotImplementedError` (Phase D, ADR-026) |

## 7. wFirma

| Capability | V1 | T1 | T2 | Note |
|---|---|---|---|---|
| Capabilities/products (customers, goods, adopt, auto-register) | LIVE (full) | LIVE `wfirma-inbox-v2.html`, `customer-master-v2.html` | READ `master-page.jsx` | V1 most complete writes |
| PZ clipboard/json/preview/create/adopt/confirm | LIVE (`shipment-detail.html`) | — | PENDING / STUB `pz-v2.html` | V1 only live |
| PZ correction lifecycle (7-step) | LIVE (`shipment-detail.html:12092`; `routes_pz.py:739-1347`) | — | STUB (collision w/ `pz-correction-v2-uxmod`) | V1 only live |
| Reservations | preview only | LIVE create | LIVE | T1+T2 wired |
| Reservation queue mgmt | — | — | — | `routes_reservations.py:144` backend-only, **no UI** |

## 8. PZ workflows

| Capability | V1 | T2/ATL | Authority | Note |
|---|---|---|---|---|
| PZ engine run (`/pz/process`) | LIVE (`batch.html`,`shipment-detail.html`) | — | `routes_pz.py:74` | V1 only |
| PZ lineage | LIVE inline | STUB `pz-v2.html` | `routes_pz.py:626` (per-batch) | **no cross-batch PZ list endpoint** |
| PZ correction full chain | LIVE | STUB (Sprint 07, collision OQ) | `routes_pz.py:739-1347` | V1 only live |
| Warehouse document (pz_document.pdf) | LIVE | — | `routes_wfirma.py:3162` | V1 only |

## 9. Documents

| Capability | V1 | T1 | T2 | Note |
|---|---|---|---|---|
| Proforma PDF | LIVE `/document` | LIVE `/document.pdf` | LIVE `/document.pdf` | route variant divergence (`/document` vs `/document.pdf`) |
| CMR PDF | — | — | `estrella-doc-cmr.jsx` (window.print only) | **no backend CMR generator** |
| Packing list PDF | — | — | `estrella-doc-packing.jsx` (print only) | **no backend generator** |
| DSK / email package | LIVE (`shipment-detail`,`batch.html`) | — | — | V1 only |
| Cross-batch documents hub | — | LIVE `documents-v2.html` (per-batch) | LIVE `documents-hub.jsx` (read) | **`GET /api/v1/documents` does not exist** (Sprint 04 gap) |
| Per-batch file list | LIVE `/upload/shipment/{id}/documents` | — | LIVE `/dashboard/batches/{id}/files` | two endpoints, same data |

## 10. Master data / customer master

| Capability | V1 | T1 | T2 | Note |
|---|---|---|---|---|
| Customer master CRUD | LIVE inline | **LIVE** `customer-master-v2.html` (926 ln, designated owner) | READ `master-page.jsx` + LIVE `client-detail.jsx` | redundant; T1 authoritative per arch plan |
| Shipping addresses / carrier accounts | LIVE | LIVE | LIVE `client-detail.jsx` | redundant |
| Products / designs / HS / units / FX / incoterms / VAT / box-types | LIVE | **LIVE** `master-data-v2.html` (1,665 ln) | READ | T1 designated V2 owner; **GAP: is `master-data-v2.html` (products) the same domain as `customer-master-v2.html`?** |
| Global search | — | — | LIVE `global-search.jsx` (header says "stubbed") / `atlas/search-v2.html` LIVE | `routes_search.py` exists; JSX may be prototype |
| Ledgers / statements | LIVE inline | LIVE `accounting-hub-v2.html` | READ `ledgers-page.jsx` / `atlas/ledgers-v2.html` | endpoint-shape mismatch |

---

## 11. Registers

### 11a. Critical gaps — backend exists, no frontend surface
| Capability | Backend | Surfaces |
|---|---|---|
| Inventory returns | `routes_inventory_returns.py:116,148,181` | none |
| Inventory sample | `routes_inventory_sample.py` | none |
| Reservation queue | `routes_reservations.py:144,174,200` | none |
| Cross-batch documents list | `GET /api/v1/documents` **absent** | none (Sprint 04) |
| Cross-batch PZ list | per-batch only | none (Sprint 07) |
| CMR / packing PDF generation | **absent** (frontend print only) | `estrella-doc-*.jsx` |
| Consignment | **absent** (no table) | none |
| DHL live label | `carrier/adapters/live.py:44` NotImplementedError | none (Phase D) |

### 11b. Remaining MOCK pages in T2 shell
`accounting-hub.jsx`, plus `reports` and `admin` shell routes (per `PROJECT_STATE.md`). `master-page.jsx` and `carriers-page.jsx` were flagged MOCK in `MOCK_PAGE_AUTHORITY_AUDIT.md` (2026-06-06) — **GAP: confirm current status vs WIRED_PAGES 17/17 claim** (the audit predates the campaign completion; reconcile).

### 11c. Orphaned/dead V2 files
`shipment-detail-page.v1.jsx` (MOCK, `simulateAction`), `shipment-detail-page.v2.jsx` (orphaned), `shipping-ops.jsx` (wireframe) — not loaded by `v2/index.html`. See [DUPLICATE_AUTHORITY_REPORT.md](./DUPLICATE_AUTHORITY_REPORT.md).

### 11d. Designated V2 owner per `docs/v2-architecture-plan.md` + atlas-v2 sprints
Proforma = `proforma-v2.html` (Sprint 01 MERGED, most complete) · Customer master = `customer-master-v2.html` · Master data = `master-data-v2.html` · PZ = `atlas/pz-v2.html`+Sprint 07 (STUB, collision) · Shipment detail V2 = Sprint 03 (PENDING; V1 live) · Documents = Sprint 04 (endpoint gap) · Dashboard aggregator = built last.

**Bottom line:** V2 is **read-complete** across most domains (T2 shell WIRED 17/17) but **write-incomplete** for shipment-detail actions (DHL, PZ, wFirma writes remain V1-only), and proforma has a **dual live write surface**. Inventory writes/returns/sample and reservation-queue have backends with **no UI in any generation**. See [MIGRATION_ROADMAP.md](./MIGRATION_ROADMAP.md) for decisions.
