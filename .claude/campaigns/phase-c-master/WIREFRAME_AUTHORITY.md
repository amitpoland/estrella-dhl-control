# Phase-C Inventory Master — Wireframe Authority (WIREFRAME_AUTHORITY.md)

**Platform v1.0 — FROZEN at `e2d69602` (operator ruling 2026-07-03)**

Constitution §12 (verbatim): "Inventory UI is exactly the supplied wireframe. Never
redesign. Never simplify. Never invent. Wireframe is the UI authority."

**Design authority files (operator-supplied, of record):**
- `docs/design/estrella-dashboard-wireframe.html` (sha256:f7dd5e3889…) — canonical wireframe
- `docs/design/inventory-page.design.jsx` — readable extract (InvStatTile design :28-43)
- `docs/design/README.md`

Source inspection: `reports/inspection/2026-07-02T-wfirma-wireframe-inspection.md`
(§A authority map, §D no-duplicate plan, DELIVERABLE 2 parity). Mandatory read before any
UI slice, together with `.claude/skills/frontend-design.md`. Lesson M applies to every
UI change (no capability suppression without a PROJECT_STATE DECISIONS cancellation).

---

## §A Authority map — wireframe surface → existing V2 owner

Status: LIVE = wired · MOCK = renders w/ banner · REDIRECT = slug forwards ·
RESERVED = slug held · UNUSED = loaded, never mounted.

| Module | URL | Frontend | Backend | Status |
|---|---|---|---|---|
| Stock Hub | /v2/inventory | inventory-page.jsx | 8 read-only inventory/warehouse routes | LIVE |
| Move Location | /v2/move_location → folded | into inventory-page Move Stock modal (`0cee8173`) | inventory_location_writer | LIVE (FOLDED) |
| Move Stock (promotion) | /v2/move_stock | reserved slug | BE-1 run_stock_promotion shipped (`0900b227`) | RESERVED (UI pending) |
| Sample out/return | /v2/sample_out, /v2/sample_return | stubs wireframe-update.jsx:492-526 | routes_inventory_sample.py:91-144 LIVE | REDIRECT (UI missing) → C-3b |
| Goods return / to producer | /v2/goods_return, /v2/return_prod | stubs :528-562 | routes_inventory_returns.py:116-201 LIVE (migration pending) | REDIRECT (UI missing) → C-3a/C-3c |
| Consignment | no slug | ConsignmentTab (client-kyc-and-consignment.jsx:282) UNUSED | NONE | ABSENT → C-4a..C-4c |
| Identity/mapping | /v2/identity → inventory; /v2/wfirma_setup | WfirmaMappingPage (ops-cell.jsx:599) | /wfirma/capabilities,/customers,/products | wfirma_setup LIVE |
| Proforma family | /v2/proforma(_detail,_search) | proforma-*.jsx | routes_proforma | LIVE |
| Accounting hub | /v2/accounting | accounting-hub.jsx (has wz/pz/pw/rw/mm tabs :16-34) | none wired | MOCK |
| PZ (import) | batch pages | V1 + master/detail | routes_wfirma pz_create + promotion | LIVE |

## §D No-duplicate plan — every function maps to an EXISTING owner

| Function | Owner (existing) | Change | Campaign slice |
|---|---|---|---|
| Stock KPI tiles (Final/Samples/Returns/Consignment) | Stock Hub panel-stage2 (B1 restyle done `a1708338`) | add Consignment tile when backend exists | C-4a+ |
| Physical shelf/zone move | Move Stock modal (folded) | shipped | — |
| Business promotion + Note | reserved move_stock slug | B×7-1b UI slice (BE-2 Note next) | outside campaign wave scope unless pulled |
| Sample out/return UI | reserved slugs + stubs :492-526 | promote-in-place (Sprint-31 playbook), wire to LIVE routes | C-3b |
| Goods return / producer UI | reserved slugs + stubs :528-562 | same playbook | C-3c |
| Consignment ledger | ConsignmentTab (exists, UNUSED) | backend FIRST (C-4a model + routes), then mount the existing component — **do NOT build a second one** | C-4a→C-4c |
| Invoice from consignment | proforma family (existing conversion authority) | consignment-warehouse consumption + allocation close | C-5a |
| Sale out-leg (Temp Sale) | proforma conversion + new shared run_stock_issue() | fire WAREHOUSE_STOCK→SALES_TRANSIT | C-3d |
| Warehouse doc register | accounting-hub.jsx (MOCK, tabs already exist) | wire when doc APIs verified | Wave 4 |
| Contract/PO linkage | packing/proforma tables | DONE (B3 `0602ddd3`) | closed |
| Upload Document | existing routes_upload surfaces | link, not duplicate | — |
| Cycle Count | NO owner — net-new | own pre-flight + operator approval required | not in Waves 1–4 |
| Export | existing export idiom | per-table buttons on existing pages | with C-3e |

## Wireframe column requirements (operator-supplied inventories)

- Packing-list-grade table: PK SR · CTG · Client PO · Design No · Karat · Color ·
  Quality · Dia Wt · Qty → C-3e joined read (data already in packing_lines).
- Consignment ledger: Cons.ID · Client · Design · Qty · Value · Issued · Due Back ·
  Days Out · Proforma → C-4a model fields.
- Sample stubs carry: Sample ID/Client/Item/Out Date/Expected Return/Status ·
  Returned/Outcome/QC. Stub actions convert-to-sale/write-off/extend have NO backend —
  planned-state honesty (Lesson M) when built.
- Returns stubs carry: RMA/Client/Original Inv./Items/Reason/Status · Producer
  RMA/Supplier/Original PI. Credit/debit-note wFirma writes = future, approval-gated.

## Top-5 parity gaps → slice assignment (wireframe inspection DELIVERABLE 2)

| # | Gap | Slice | Status at launch |
|---|---|---|---|
| 1 | Consignment (zero backend + unused stub; MM = OI-1) | C-4a/C-4b/C-4c | PENDING (Wave 3) |
| 2 | Sale out-leg — SALES_TRANSIT unreachable | C-3d | PENDING (Wave 2) |
| 3 | Client PO / contract number dropped at INSERT | B3 | **CLOSED** (`0602ddd3`, 2026-07-02) |
| 4 | Samples/Returns UI (live backend, no UI) | C-3b/C-3c | PENDING (Wave 2) |
| 5 | Merchandising-grade columns (4-6 vs wireframe's 9) | C-3e | PENDING (Wave 2) |

## UI rules riding with this authority (PROJECT_STATE 2026-07-03)

- UI DEVELOPMENT RULE + Inventory mapping gate (operator-ratified) — check before any
  inventory UI work.
- Old mock action buttons (Upload/Move/Cycle/Export) were deliberately removed as fake —
  reinstate ONLY as real actions wired to live backends.
- Wireframe hash check (W2-A5/W3-A2): re-hash `docs/design/estrella-dashboard-wireframe.html`
  at each wave boundary; a changed hash = wireframe-authority assumption AT-RISK →
  Confidence Gate.
