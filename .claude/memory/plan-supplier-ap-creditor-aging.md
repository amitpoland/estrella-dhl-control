# Campaign charter — Supplier AP / Creditor Aging

**Status:** QUEUED (not started)  
**Baseline:** production `0274cc34a051ac3a82763954fd59473cd18074e9` (Management Analysis Phase 1 closed)  
**Ratified:** 2026-08-09 (operator)

## Scope (narrow — one campaign)

Supplier AP / Creditor Aging only.

**Out of this campaign (separate later):**

- Sales Analysis
- Bank Reconciliation
- Consignment Exposure

## Architecture (mirror Phase 1 AR pattern)

```
wFirma expenses + linked payments
  → shared supplier remaining calculation
  → creditor aging
  → Supplier Ledger drill-down
```

UI: extend existing **Management Analysis** with a **Payables** section.  
Do **not** create a second accounting page.

## Fixed rules

1. Expenses + payments remain **wFirma authority** (read-only projection; no second AP DB).
2. Supplier joins use **IDs**, never names.
3. **No FX consolidation** — USD / EUR / PLN stay separate portfolios.
4. Credits / prepayments are **not** overdue payables (keep out of aging buckets).
5. Default aging basis = **due date**.
6. One shared remaining formula feeds Supplier Ledger + Payables analytics.

## First acceptance proof (before any Payables UI)

One real supplier with multiple expenses and payments:

```
Σ expense gross − Σ linked payments = supplier outstanding = Σ creditor-aging buckets
```

Δ must be **0.00** (or understood and documented). Only then build Payables UI.

## Implementation order

1. Inspect existing Supplier Ledger / expense / payment read paths.
2. Formalize shared supplier remaining helper.
3. Build read-only creditor portfolio projection + reconciliation tests.
4. Live reconcile one real supplier (JSON-only).
5. Add Payables section under Management Analysis + Supplier Ledger drill.
6. Tests → browser → security → seven-agent gate → App deploy.
