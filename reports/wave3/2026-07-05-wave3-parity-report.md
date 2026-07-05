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
