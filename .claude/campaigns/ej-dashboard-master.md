# EJ Dashboard — Master Campaign

**Adopted:** 2026-06-29  
**Status:** ACTIVE  
**Owner:** amitpoland  

---

## Mission

Build a single event-driven ERP platform where:

- **wFirma** is the accounting authority.
- **EJ Dashboard** is the authority for logistics, customs, warehouse, shipping, inventory, and operator workflows.
- Every integration is event-driven.
- Every business authority has exactly one owner.
- Every change is auditable and replayable.

---

## Architecture Rules (Locked — permanent)

These rules apply to every PR, every sprint, every session. A change that violates a rule is
incomplete until the violation is resolved.

| # | Rule |
|---|---|
| 1 | One authority per business domain |
| 2 | Immutable event log |
| 3 | Immutable snapshots |
| 4 | Separate enrichment layer |
| 5 | No direct webhook → business table writes |
| 6 | Operator-entered data is never overwritten automatically |
| 7 | Every integration must be replayable |
| 8 | Every state transition must be observable |
| 9 | Background processing only — after webhook acknowledgment |
| 10 | Every feature must fit this architecture before implementation begins |

Cross-reference: `service/docs/production_deployment_rule.md`, `CLAUDE.md §Engineering Lessons`

---

## Execution Strategy (per session)

1. Read this document.
2. Identify the next incomplete phase on the active track.
3. Complete that phase end-to-end (code → tests → PR → deploy → verify).
4. Update the roadmap below.
5. Move to the next phase.

No jumping between unrelated tracks unless the task is a production hotfix.
Every phase ends with a verified production deploy — not a merged PR.

---

## Track A — React / Proforma

**Authority:** EJ Dashboard owns proforma lifecycle, operator workflow, and UI.

| Phase | Status | PR / SHA |
|---|---|---|
| D1 — Atlas shell | ✅ COMPLETE | PR #791 / `1619009b` |
| D2 — Renderer parity | ✅ COMPLETE | PR #789 / `1e1ff9f3` |
| D3 — Editable fields (incoterm, insurance_eur) | ✅ COMPLETE | PR #792 / `d1df260b` |
| D4 — (next) | ⏳ PENDING | — |
| D5 | ⏳ PENDING | — |
| D6 | ⏳ PENDING | — |
| UI cleanup | ⏳ PENDING | — |
| Audit polish | ⏳ PENDING | — |
| Workflow completion | ⏳ PENDING | — |

---

## Track B — wFirma Integration

**Authority:** wFirma owns all accounting documents. EJ Dashboard reads via event pipeline only.

| Phase | Status | PR / SHA |
|---|---|---|
| Phase 1 — Webhook Capture | ✅ COMPLETE | PR #794 / deployed |
| Phase 2A.1 — Processing + Snapshots | ✅ COMPLETE | PR #795 / `c3f1229a` |
| Phase 2A.2 — Diagnostics endpoint | ✅ COMPLETE | PR #796 / pending merge+deploy |
| Phase 2B — Safe Enrichment (3 fields) | ⏳ PENDING | — |
| Phase 3 — Customer Sync | ⏳ PENDING | — |
| Phase 4 — Payment Sync | ⏳ PENDING | — |
| Phase 5 — KSeF Sync | ⏳ PENDING | — |
| Phase 6 — Credit Notes | ⏳ PENDING | — |
| Phase 7 — Inventory Sync | ⏳ PENDING | — |
| Phase 8 — Full Event Bus | ⏳ PENDING | — |

**Phase 2B scope (locked):** enrich exactly three fields via existing `write_postposting_enrichment()`
at `proforma_invoice_link_db.py:1427` — `wfirma_issue_date`, `wfirma_payment_due`,
`wfirma_payment_method`. No new write paths. Only fires after SNAPSHOTTED events confirmed in production.

---

## Track C — Customer Master

**Authority:** EJ Dashboard owns customer identity; wFirma Sync via Track B event pipeline.

| Item | Status |
|---|---|
| Payment Terms Authority | ⏳ PENDING |
| Payment Method Authority | ⏳ PENDING |
| Customer Defaults | ⏳ PENDING |
| Customer Webhook Sync | ⏳ PENDING |
| Customer Statements | ⏳ PENDING |
| Outstanding Balance | ⏳ PENDING |
| Credit Control | ⏳ PENDING |

---

## Track D — Warehouse & Inventory

**Authority:** EJ Dashboard owns all warehouse operations and inventory state.

| Item | Status |
|---|---|
| Inventory Authority | ⏳ PENDING |
| Warehouse Events | ⏳ PENDING |
| Shipment Lifecycle | ⏳ PENDING |
| Scan Workflow | ⏳ PENDING |
| Stock vs Customer Goods separation | ⏳ PENDING |
| Inventory Synchronization | ⏳ PENDING |

---

## Track E — Customs & Shipping

**Authority:** EJ Dashboard owns all customs evidence chains and shipment status.

| Item | Status |
|---|---|
| DHL | ⏳ PENDING |
| CMR | ⏳ PENDING |
| Packing | ⏳ PENDING |
| Customs | ⏳ PENDING |
| Shipment Status | ⏳ PENDING |
| Export Lifecycle | ⏳ PENDING |

---

## Track F — Finance & Reporting

**Authority:** wFirma owns financials; EJ Dashboard owns operational metrics and management reporting.

| Item | Status |
|---|---|
| Dashboards | ⏳ PENDING |
| KPIs | ⏳ PENDING |
| Audit Reports | ⏳ PENDING |
| Operational Metrics | ⏳ PENDING |
| Financial Metrics | ⏳ PENDING |
| Management Reports | ⏳ PENDING |

---

## Track G — AI & Automation

**Dependency:** Tracks A–F must have stable authority boundaries before AI layer is added.

| Item | Status |
|---|---|
| AI document processing | 🔮 FUTURE |
| Email automation | 🔮 FUTURE |
| Workflow assistants | 🔮 FUTURE |
| Intelligent search | 🔮 FUTURE |
| Predictive alerts | 🔮 FUTURE |
| Operational copilots | 🔮 FUTURE |

---

## Immediate next priorities (as of 2026-06-29)

1. Merge and deploy PR #796 (Phase 2A.2 diagnostics)
2. Start Phase 2B — Snapshot → Business Enrichment
3. Return to Track A and complete D4
4. Continue Customer Master synchronization (Track C)
5. Payment synchronization (Track B Phase 4 / Track C)

---

## Dependencies Matrix

Use this to answer "what must be done first?" and "what does this phase unlock?"

| Phase | Depends On | Blocks |
|---|---|---|
| **Track A** | | |
| D4 | D3 ✅ | D5 |
| D5 | D4 | D6 |
| D6 | D5 | Workflow Completion |
| Workflow Completion | D6 | Track F Dashboards |
| **Track B** | | |
| Phase 2B — Enrichment | Phase 2A.2 ✅ | Phase 3 (Customer Sync), Phase 4 (Payment Sync) |
| Phase 3 — Customer Sync | Phase 2B | Track C Customer Defaults, Payment Sync |
| Phase 4 — Payment Sync | Phase 2B, Phase 3 | Track C Statements, Phase 5 (KSeF) |
| Phase 5 — KSeF Sync | Phase 2B | Phase 6 (Credit Notes) |
| Phase 6 — Credit Notes | Phase 5 | Track F Financial Metrics |
| Phase 7 — Inventory Sync | Track D Warehouse Authority | Phase 8 (Event Bus) |
| Phase 8 — Full Event Bus | Phases 3–7 | Track G AI & Automation |
| **Track C** | | |
| Customer Defaults | Phase 3 (Customer Sync) | Payment Terms Authority |
| Payment Terms Authority | Customer Defaults | Outstanding Balance |
| Outstanding Balance | Payment Terms | Customer Statements |
| Customer Statements | Outstanding Balance | Credit Control |
| Credit Control | Customer Statements | Track F Management Reports |
| **Track D** | | |
| Warehouse Authority | — (no hard deps) | Phase 7 (Inventory Sync), Shipment Lifecycle |
| Shipment Lifecycle | Warehouse Authority | Track E Shipment Status |
| Inventory Synchronization | Warehouse Authority, Phase 7 | Track F Operational Metrics |
| **Track E** | | |
| DHL | Shipment Lifecycle | Shipment Status, Export Lifecycle |
| Shipment Status | DHL, Customs | Track F Operational Metrics |
| Export Lifecycle | CMR, Packing, Customs | Track F Audit Reports |
| **Track F** | | |
| Operational Metrics | Track D + Track E stable | Dashboards, KPIs |
| Financial Metrics | Track C stable, Phase 4 (Payment Sync) | Management Reports |
| Dashboards | Operational + Financial Metrics | Track G Predictive Alerts |
| Management Reports | Dashboards, Financial Metrics | — |
| **Track G** | | |
| All AI & Automation | Tracks A–F mature | — |

**Reading rules:**
- A phase with all Depends-On marked ✅ is eligible to start now.
- A phase blocked on a pending item cannot start until that item deploys to production.
- "No hard deps" means the phase can be scoped and started independently, but must not create authority conflicts with in-progress tracks.

---

## Changelog

| Date | Change |
|---|---|
| 2026-06-29 | Campaign adopted; Track A D1–D3 and Track B Phases 1–2A.2 marked complete |
| 2026-06-29 | Dependencies Matrix added |
