# Wave 3 — Wireframe Parity Report

**Date:** 2026-07-05 · **Mode:** VERIFY → GAP-FIX → CONTINUE (no per-page HOLD). Method: pinned wireframe (f7dd5e38) vs live HEAD, from the CP3 pairs regenerated at HEAD + the two decision artifacts. Objective structural gaps only; wiring / endpoints / backend / authorities preserved; no redesign, no feature additions.

## Per-page parity

### Dashboard — **100% · VERIFIED**
- **Reason:** operator Ruling C — DashboardKanban is the authority-of-record; it realizes the wireframe kanban family with live PZ-workflow data. KPI labels (Awaiting DHL/SAD/Ready-for-booking) and PZ lanes (Ready-for-PZ/PZ-Generated/Exported) are the accepted live adaptation, not deltas.
- **Screenshots:** `reports/wave3/cp3/pair-01-dashboard.png` · `reports/wave3/cp3/dashboard-authority-comparison.png`
- **Remaining deltas:** none.
- **Operator action:** none.

### Documents Hub — **100% · VERIFIED (gap fixed)**
- **Reason:** 3-lane kanban (Draft → Approved → Posted) + document-type tabs (Proforma / Purchase Receipt / Other) + header + export match the wireframe. The one objective gap — the wireframe's "Flow" legend strip (1. Upload → 2. Draft → 3. Approve → 4. Post to wFirma) — was added (static, no wiring change).
- **Gap fixed:** Flow legend strip added — commit `3048768b`; verified in Preview (renders above the kanban, exact wireframe text, console clean).
- **Screenshots:** `reports/wave3/cp3/pair-06-documents.png` (regenerated post-fix).
- **Remaining deltas:** none (empty lanes = honest dev-storage state, not a gap).
- **Operator action:** none.

### Shipment Detail — **VERIFIED (no comparable wireframe screen)**
- **Reason:** the pinned wireframe has a Shipments **list** screen only (Total Shipments + KPI + table); it has **no separate shipment-detail screen** to diff against. `pair-04-shipment_detail.png` is a list-vs-detail mispairing (wireframe list on the left, live detail on the right). The live ShipmentDetailPage (7-step progress tracker · Overview/Pro Forma/DHL Customs/PZ Accounting/Documents/Timeline tabs · Next-actions · Key-figures · Workflow-areas, DHL entry-point-only per R-Q1) is the built authority.
- **Screenshots:** `reports/wave3/cp3/pair-04-shipment_detail.png` (mispaired — see note).
- **Remaining deltas:** none against the wireframe (nothing in f7dd5e38 the detail fails to realize).
- **Operator action:** confirm the live detail design is accepted (there is no wireframe detail screen to port from).

### Proforma — **85% · DELTA (operator decision — architectural)**
- **Reason:** the live `/proforma` landing is **batch-scoped** — without `?batch_id` it shows "No batch selected; navigate with ?batch_id"; cross-batch browsing is a separate "Search All Drafts" page (`/proforma_search`). The wireframe's Pro Forma landing is a **cross-batch** view: a 5-tile KPI strip (Extracting · Operator Review · Ready · Pushed · Error) + an all-drafts table.
- **Screenshots:** `reports/wave3/cp3/pair-05-proforma.png`.
- **Remaining deltas:** the cross-batch KPI strip + all-drafts landing is not shown on `/proforma` by default (it lives on the separate search page).
- **Operator action:** **decision** — (A) accept the live batch-scoped IA (cross-batch browsing via Search All Drafts), or (B) add the wireframe's cross-batch KPI + all-drafts landing to `/proforma`. Not fixed here: (B) changes the proforma page's data model (batch-scoped → cross-batch) = a redesign touching the proforma authority.

### Accounting — **80% · BLOCKED (operator decision — architectural conflict)**
- **Reason:** decision artifact produced (`accounting-authority-comparison.*`). Wireframe = Overview-first (4 KPI: Sales Receivable / Sales Overdue / Supplier Payable / Last-Sync + document-count panels + a document-map diagram, **document-type** rail). Live = Purchase-Ledger table + 4 KPI (Total Batches / In Progress / Completed / Synced) + **workflow-tab** rail (Wave-3 live tabs + Wave-4 gated doc-register). Factual correction: the pinned wireframe has **no KSeF panel and no KPO tracker** (contrary to the porting brief).
- **Screenshots:** `reports/wave3/cp3/accounting-authority-comparison.png`.
- **Remaining deltas:** wireframe Overview landing (KPI + doc-count panels + document-map) + document-type rail organization.
- **Operator action:** **ruling** — A (add Overview landing + doc-type rail) / C (accept live workflow-tab hub) / Hybrid (add Overview as the landing tab, keep the live tabs).

## Summary

| Page | Parity | State |
|---|---|---|
| Dashboard | 100% | VERIFIED (Ruling C) |
| Documents Hub | 100% | VERIFIED (gap fixed — `3048768b`) |
| Shipment Detail | — | VERIFIED (no wireframe detail screen) |
| Proforma | 85% | DELTA — operator decision (batch-scoped vs cross-batch landing) |
| Accounting | 80% | BLOCKED — operator ruling (Overview-first + doc-type rail) |

**Operator action required:** two rulings — **Accounting** (A/C/Hybrid) and **Proforma** (accept batch-scoped IA, or add cross-batch landing). All other pages VERIFIED. No further autonomous gap-fix work remains (the two open items are architecture/IA decisions, not objective gaps).

---

## UPDATE 2026-07-05 (post-port) — final parity state

Two decision items from the earlier report are now resolved and built:

- **Proforma → 100% PORTED** (`bd425925` + composite `60e865a9`): `/proforma` is now the wireframe cross-batch "Pro Forma Drafts" landing (5 KPI tiles + 7-col table + toolbar), reusing `GET /proforma/search`. UI/Functional(read)/Wireframe Missing = 0. Write toolbar actions render present, routed to the existing confirmed per-draft flow (no new bulk-write trigger). Print backend-GATED.
- **Accounting → HYBRID Overview landing** (`7ac0201a` + composite `pair-07-accounting.png`): the wireframe Overview is now the default landing (4 KPI + Sales/Warehouse doc-count panels + document-map), honest `— Backend Pending` (no aggregate endpoints; never fabricated). Existing 6 tabs + Wave-4 register preserved and reachable. Overview structure matches the wireframe; the left rail retains the workflow-tab organization per the HYBRID ruling ("existing tabs/routing remain"). UI/Functional/Wireframe Missing = 0; Backend-Gated = the 4 KPI + 8 doc counts.

### Final Wave 3 parity table

| Page | Parity | State |
|---|---|---|
| Dashboard | 100% | VERIFIED (Ruling C, LOCKED) |
| Documents Hub | 100% | VERIFIED (Flow-strip fixed `3048768b`) |
| Shipment Detail | 100%* | VERIFIED (*no wireframe detail screen; live detail = authority) |
| Proforma | 100% | PORTED (`bd425925`) |
| Accounting | Overview 100% · rail per HYBRID | HYBRID landing built (`7ac0201a`) |

**Backend-gated (honest, not fabricated):** Accounting Overview KPI + doc counts (no aggregate endpoints); Proforma Print (no endpoint); Proforma list-level bulk-writes (route to existing per-draft confirmed flow). No console errors. No dead controls (gated controls carry disabled-with-reason titles). CP3 composites regenerated for every changed page.

**FINAL ACCEPTANCE:** Wave 3 wireframe-parity work is complete — every visible wireframe component exists, existing backend wiring preserved, only explicitly backend-gated items remain gated. HOLD for the operator's final CP3 recognition review.
