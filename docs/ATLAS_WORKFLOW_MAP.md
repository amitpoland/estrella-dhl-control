# ATLAS_WORKFLOW_MAP.md — Official Workflow Spine

**Status:** Active  
**Date:** 2026-06-01  
**Repo:** estrella-dhl-control  
**Related:** ADR-023 (master data = SSOT), ADR-024 (product master), ADR-025 (E2E workflow)

This document is the authoritative workflow spine for the Estrella Atlas operating system.
All workflow decisions, button→transition bindings, write-flag assignments, and the
official build sequence live here. When this document conflicts with any other source,
this document wins.

---

## 0. Model (spec)

Two intake tracks (purchase/import, sales/export) converge on `product_code` (= design id),
then customs → PZ → wFirma → proforma → invoice, with inventory staged by DHL status.
Master data is the single source of truth (ADR-023). All validation is
**detect → inbox → approve** (soft, advisory, overridable). Only wFirma writes are
hard-gated by flags.

---

## 1. Workflow transitions WF1–WF4 (spec)

### WF1 — Import / customs / PZ chain · Owner: Shipment Detail

| Step | Action |
|---|---|
| WF1.1 | Intake: AWB + carrier + supplier + client + documents |
| WF1.2 | Parse & mint `product_code` + PL/EN description |
| WF1.3 | Validate vs masters → inbox proposals |
| WF1.4 | DHL customs email received |
| WF1.5 | Generate Polish description / DSK / build reply package |
| WF1.6 | SAD / MRN recorded |
| WF1.7 | Generate PZ document |
| WF1.8 | Export PZ to wFirma (**flag-gated**: WFIRMA_CREATE_PZ_ALLOWED) |

### WF2 — Sales / proforma / invoice chain · Owner: Proforma

| Step | Action |
|---|---|
| WF2.1 | Sales packing list + client |
| WF2.2 | Match designs → `product_code` |
| WF2.3 | Create proforma draft |
| WF2.4 | Post proforma to wFirma (**flag-gated**: WFIRMA_CREATE_PROFORMA_ALLOWED) |
| WF2.5 | Convert proforma → WDT invoice (**flag-gated**: WFIRMA_CREATE_INVOICE_ALLOWED + payload-disclosure modal) |

### WF3 — Reservation / readiness approval gate · Owner: Reservation tab

| Step | Action |
|---|---|
| WF3.1 | Reserve stock against proforma / order |
| WF3.2 | Readiness approval (customer mapped, products resolved, advisory warnings reviewed) |

### WF4 — Inventory lifecycle · Owner: Inventory

| Step | Action |
|---|---|
| WF4.1 | IN_TRANSIT (auto, from DHL status) |
| WF4.2 | DELIVERED (auto, from DHL status) |
| WF4.3 | Confirm received (operator: person / date / location) |
| WF4.4 | WAREHOUSE_STOCK |
| WF4.5 | Dispatch / sample / return paths |
| WF4.6 | CLOSED |

**Inbox** — cross-cutting approval, hold, override, and proposal-execution layer for all WFs.

**Rule (spec):** every state-changing button references exactly one WF transition id.
Utility actions (download, copy, export-CSV, search) carry no WF id and are not
workflow transitions.

---

## 2. Button → transition binding (spec; endpoints to be confirmed in Phase 12)

| Screen | Button label | WF id | Gate |
|---|---|---|---|
| New Shipment | Save Draft | WF1.1 | — |
| New Shipment | Save & Run DHL Pre-check | WF1.1 | — |
| Shipment Detail | ✓ Mark Email Received | WF1.4 | — |
| Shipment Detail | Generate Polish Desc. | WF1.5 | advisory (DHL email) |
| Shipment Detail | Generate DSK | WF1.5 | advisory |
| Shipment Detail | Build Reply Package | WF1.5 | — |
| Shipment Detail | Generate PZ document | WF1.7 | advisory (SAD/MRN) |
| Shipment Detail | ✎ Confirm PZ Number | WF1.7 | — |
| Shipment Detail | Export PZ to wFirma | WF1.8 | WFIRMA_CREATE_PZ_ALLOWED |
| Shipment Detail | + Create Pro Forma Draft | WF2.3 | — |
| Proforma detail | Post to wFirma | WF2.4 | WFIRMA_CREATE_PROFORMA_ALLOWED |
| Proforma detail | Convert to Invoice | WF2.5 | WFIRMA_CREATE_INVOICE_ALLOWED + payload-disclosure modal |
| Reservation tab | Approve readiness | WF3.2 | — |
| Inventory | Receive (confirm received) | WF4.3 | — |
| Inventory | Move Stock | WF4.4/4.5 | — |
| Inbox | Approve / Hold / Override / Execute | cross-cutting | per-proposal |
| Utility (no WF) | Download PZ/Audit EN/PL/Memo/Calc XLSX/Correction | — | — |
| Utility (no WF) | Copy wFirma Format | — | — |
| Utility (no WF) | Export CSV | — | — |
| Utility (no WF) | Search | — | — |

---

## 3. wFirma write flags (spec) — hard gates, all default OFF, dev uses mock

| Flag | Guards |
|---|---|
| WFIRMA_CREATE_PRODUCT_ALLOWED | Product registration |
| WFIRMA_CREATE_PZ_ALLOWED | PZ export (WF1.8) |
| WFIRMA_CREATE_PROFORMA_ALLOWED | Proforma post (WF2.4) |
| WFIRMA_CREATE_INVOICE_ALLOWED | Convert to invoice (WF2.5) |

**Phase-0 finding for WFIRMA_CREATE_PZ_ALLOWED:** EXISTS in config.py

**Rule (spec):** no wFirma write may exist without its own explicit flag.

---

## 4. Product master authority (spec — ADR-024 / D1 resolved)

Composite identity = `supplier_id` + `supplier_product_code` + `normalized_design_attributes`.

- 417G and other non-globally-unique supplier codes are **NOT excluded**. Same code
  across different suppliers → separate `product_master` rows.
- Same supplier+code ambiguous → inbox disambiguation proposal.
- Every parsed line must resolve to exactly one `product_master` row.
  No free-text-only line authority.
- Supplier-specific parsing rules preserved.

---

## 5. Conflict rule (spec)

**Master wins.** A parsed document that disagrees with a master becomes an inbox
proposal, never a silent overwrite.

---

## 6. Dual valuation (spec)

- Purchase invoice value → customs / SAD / PZ cost basis.
- Sales packing / proforma value → warehouse / sales value.
- One backend resolver owns this rule; UI displays both values side-by-side.

---

## 7. Inbox proposal types (spec) — the detect → inbox → approve set

1. Supplier mismatch
2. Client mismatch
3. Product / design mismatch
4. Missing HS code
5. Price / value conflict
6. Sales-vs-purchase line mismatch
7. DHL-delivered-not-received
8. Product-not-synced-to-wFirma
9. PZ / proforma / invoice ready-for-approval
10. 417G disambiguation

---

## 8. Build sequence (spec) — official 12-phase order

> **This is the canonical build order.** It supersedes the earlier flat increment list
> in ADR-025. Phases must be executed in order; no phase begins until the previous
> is merged, deployed, and smoke-tested.

| Phase | Deliverable |
|---|---|
| **1** | Create process authority: this map + WF1–WF4 + button binding + amend ADR-025 *(IN PROGRESS)* |
| **2** | Soften the 3 hard-stops (DHL email, SAD/MRN, product-sync/PZ-before-proforma) to advisory/inbox; keep the 4 write flags hard |
| **3** | Build detect→inbox→approve: validate parsed data vs masters; create the proposal types in §7 |
| **4** | Enforce product master authority (composite key §4); remove free-text-only line authority |
| **5** | Dual-valuation resolver (§6) + UI shows both values |
| **6** | wFirma product registration at intake via inbox proposal → operator approves → push only if flag on |
| **7** | DHL→inventory lifecycle: IN_TRANSIT auto; DELIVERED → "confirm received" proposal → RECEIVED (person/date/location); scan → final/dispatch |
| **8** | Sales↔purchase line matching by `product_code`; mismatch → inbox proposal with exact reason (approve/correct/split) |
| **9** | Proforma/invoice closure: draft always creatable; post requires customer mapped + products resolved + advisory warnings reviewed + flag; convert requires payload-disclosure modal + explicit confirmation |
| **10** | Master backfill (company profile → supplier → client/importer → HS → product authority) + conflict rule §5 |
| **11** | UI wiring: Dashboard visual-only; Shipment Detail owns WF1; Proforma owns WF2; Reservation owns WF3; Inventory owns WF4; Inbox owns approval/hold/override |
| **12** | Verification: run one full safe shipment path with NO live writes; run one gated write path in test/staging ONLY; produce the §9 truth table; then enable production write flags one by one |

---

## 9. Phase-12 truth-table template (spec)

> Filled during Phase 12 verification. One row per state-changing transition.

| transition | button | endpoint | gate | inbox proposal | output document | status |
|---|---|---|---|---|---|---|
| WF1.1 | Save Draft | — | — | — | — | ☐ |
| WF1.4 | Mark Email Received | — | — | — | — | ☐ |
| WF1.7 | Generate PZ | — | advisory (SAD/MRN) | — | PZ PDF/XLSX | ☐ |
| WF1.8 | Export PZ to wFirma | — | WFIRMA_CREATE_PZ_ALLOWED | — | wFirma PZ record | ☐ |
| WF2.3 | Create Proforma Draft | — | — | — | draft | ☐ |
| WF2.4 | Post to wFirma | — | WFIRMA_CREATE_PROFORMA_ALLOWED | — | wFirma proforma | ☐ |
| WF2.5 | Convert to Invoice | — | WFIRMA_CREATE_INVOICE_ALLOWED | payload-disclosure | wFirma invoice | ☐ |
| WF3.2 | Approve readiness | — | — | — | — | ☐ |
| WF4.3 | Confirm received | — | — | — | — | ☐ |

---

*This map is append-only for §1–§7. §8 phase checkboxes are updated per merge. §9 truth table is populated during Phase 12.*