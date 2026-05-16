# Phase 6F — Payment-Charge Posting Architecture (Inspection Only)

> **STATUS: INSPECTION ONLY. NO IMPLEMENTATION IN THIS CAMPAIGN.**
>
> This report inspects the existing finance / payment / ledger / charge surface
> and proposes an explicit-charge architecture. Implementation is gated on
> operator approval of the proposed schema and posting model. Until that
> approval lands, the current behaviour stays in place.
>
> Campaign: OIA-2026-05 · Phase: P5 · Author: claude-session 2026-05-16

---

## 1 — What was inspected

| Surface | File(s) | Behaviour today |
|---|---|---|
| Pure ledger aggregator | `service/app/services/ledger_aggregator.py` (607 lines) | Reads wFirma `<invoice>` XML nodes; emits 7 per-invoice fields per currency: `wfirma_doc_id`, `doc_number`, `type`, `date`, `currency`, `total_net`, `total_gross`. **No payments. No aging. No balances.** 8 fields are explicitly FORBIDDEN as outputs until a payments-side probe (Phase 10A.5) lands. |
| Ledger HTTP read surface | `service/app/api/routes_ledgers.py` (477 lines, 3 GET endpoints) | Read-only. No writes. |
| Operator-entered service charges | `service/app/services/proforma_service_charges_db.py` (174 lines) | Per `(batch_id, client_name, charge_type)`; allow-list = `{freight, insurance}`. UPSERT semantics. Charges stored separately from sales lines. |
| Proforma posting & drafts | `service/app/api/routes_proforma.py` (29 POST routes) | Has `service-charges`, `approve`, `post`, `suggest-freight`, `suggest-insurance`, `bulk-price-recovery` endpoints. Charges feed proforma totals via `proforma_pz_*` engines. |
| Payment posting engine | (none discovered) | **Does not currently exist as a first-class module.** Payment state is sourced from wFirma invoice XML at read-time (and explicitly NOT emitted until probe). |
| Settlement close logic | (none discovered as separate module) | Inferred to live inside individual proforma adoption / closure paths. |
| Exchange-difference logic | (none in `*exchange*` or `*fx_diff*` filenames) | Not modelled explicitly. Any FX delta between proforma issuance and payment settlement is currently invisible to the ledger aggregator. |
| Frontend payment-charge fields | `dashboard.html` proforma drafting panels — `freight`, `insurance` flow via `proforma_service_charges`. | UI exposes charge fields per draft; backend writes them through. |

---

## 2 — Behaviour map (current state)

```
                ┌────────────────────────────────────────────────────┐
                │  wFirma (system of record for invoices + payments) │
                └─────────────┬──────────────────────┬───────────────┘
                              │ XML                  │ XML
                              ▼                      ▼
                ┌─────────────────────────┐  ┌──────────────────────┐
                │  ledger_aggregator      │  │  payments/find       │
                │  (Phase 10A)            │  │  ← NOT WIRED YET     │
                │  Emits 7 invoice fields │  │  Phase 10A.5 probe   │
                │  per currency           │  │  not yet built       │
                └─────────────┬───────────┘  └──────────────────────┘
                              │
                              ▼
                ┌─────────────────────────┐
                │  /api/v1/ledgers/...    │  (read-only GET)
                └─────────────────────────┘

         ┌────────────────────────────────────────────────┐
         │  Operator-entered charges (freight, insurance) │
         │  proforma_service_charges (local SQLite)       │
         └─────────────────┬──────────────────────────────┘
                           │
                           ▼
         ┌────────────────────────────────────────────────┐
         │  /api/v1/proforma/draft/{id}/service-charges   │
         │  /api/v1/proforma/draft/{id}/approve  → post   │
         └─────────────────┬──────────────────────────────┘
                           │  POST to wFirma proforma
                           ▼
                  ┌──────────────────┐
                  │  wFirma proforma │  (system of record again)
                  └──────────────────┘

         (no module today reads payments back from wFirma into a
          settlement-aware ledger, computes remaining balance,
          attributes payments to charges, or models exchange
          difference at settlement time.)
```

---

## 3 — Identified mismatches between UI charge fields and backend posting

| # | Mismatch | Evidence | Risk |
|---|---|---|---|
| **M1** | UI lets operator enter freight + insurance as discrete line-level charges, but the ledger aggregator emits ONLY `total_net` and `total_gross` at invoice level. There is no projection back to "this much was charged for freight on this invoice". | `LEDGER_ENTRY_FIELDS` enumerates 7 fields; none is charge-typed. | Cannot reconcile what part of a payment settled which charge. |
| **M2** | Charges are stored in a separate local SQLite (`proforma_service_charges`) keyed by `(batch_id, client_name, charge_type)`. After the proforma is posted to wFirma, the link from a wFirma invoice id back to the originating local charge row is implicit (via `batch_id`), not explicit. | `proforma_service_charges_db.py` schema has no `wfirma_invoice_id` column. | Hard to answer "what charges sit on wFirma invoice 12345?" without re-querying both stores. |
| **M3** | Payment state is FORBIDDEN as a ledger output until Phase 10A.5 probe lands. `payment_state`, `remaining`, `alreadypaid`, `due_date`, `paid_date`, `aging` all blocked. | `FORBIDDEN_ENTRY_FIELDS` (lines 62-71 of ledger_aggregator.py). | Statement-of-account / settlement views currently unbuildable. |
| **M4** | There is no first-class settlement closure or exchange-difference computation. If a proforma is invoiced in EUR but the payment lands in PLN at a different rate, the system today has no place to record the FX delta. | No `*exchange*`/`*settlement_close*` modules found. | Audit-trail gap for cross-currency settlements. |
| **M5** | The current B0 fix proved `kuke_approved=true` requires `kuke_limit` (validated at customer-master level). But credit usage against that limit on payment settlement is unmodelled. | `customer_master` has `credit_limit` + `kuke_limit` columns but no consumption tracking table. | Cannot answer "how much of this client's KUKE limit is currently exposed?" |
| **M6** | The 23 `proforma/draft/*` POST endpoints write charges to the local `proforma_service_charges` table, but the proforma `/post` endpoint (line 3674) issues to wFirma. After that issuance, the local table is the only place where the charge breakdown survives — wFirma's invoice XML does not preserve charge-type labelling. | Cross-read of routes_proforma + ledger_aggregator. | One-way information loss at wFirma posting. |

---

## 4 — Risk if unchanged

| Risk | Severity | Time horizon |
|---|---|---|
| Cannot produce a per-client statement of account with remaining balances | HIGH | Now |
| Cannot attribute partial payments to charges vs net | HIGH | Now |
| Cannot detect FX-delta at settlement on cross-currency clients | MEDIUM | Per cross-currency invoice |
| Cannot enforce credit limit at proforma issuance time | MEDIUM-HIGH | Per issuance |
| Audit gap: post-issuance, charge-type labelling lives only in local SQLite, not in wFirma | MEDIUM | Cumulative — grows monthly |
| If `proforma_service_charges.sqlite` is lost, history is irrecoverable from wFirma | HIGH | Permanent data loss on disk failure if not backed up |

---

## 5 — Recommended explicit-charge model

### 5.1 Conceptual

Make every monetary movement explicit and typed. Stop conflating "the proforma total" with "the components of that total".

```
Charge       — operator-entered or system-derived component of an amount due
                 (types: net_goods, freight, insurance, customs_duty, vat_eu,
                  vat_pl, rounding_adjustment, fx_delta_at_settlement)
Posting      — a write to an external system of record (wFirma) that creates
                 or modifies an invoice, with a snapshot of the charges
                 attached
Payment      — an inbound cash event, attributed to a posting and decomposed
                 across charges (proportional or operator-directed)
Settlement   — a posting that is fully paid (sum-of-payments ≥ sum-of-charges
                 within rounding tolerance) with FX delta locked in
```

### 5.2 Schema proposal (additive only)

All new tables live in a NEW file — `<storage_root>/finance_postings.sqlite` — so the proposal does NOT alter existing schemas (`customer_master.sqlite`, `master_data.sqlite`, `proforma_links.db`).

```sql
-- 6F.1 — Charges (the typed components of an amount due)
CREATE TABLE charges (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id            TEXT NOT NULL,
    client_name         TEXT NOT NULL,
    charge_type         TEXT NOT NULL,         -- enum (see CHARGE_TYPES below)
    amount_minor        INTEGER NOT NULL,      -- stored in minor units (cents)
    currency            TEXT NOT NULL,         -- ISO 4217
    source              TEXT NOT NULL,         -- operator | derived | wfirma
    posting_id          INTEGER,               -- FK → postings.id, null until posted
    notes               TEXT,
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX idx_charges_batch_client ON charges (batch_id, client_name);
CREATE INDEX idx_charges_posting     ON charges (posting_id);

-- 6F.2 — Postings (a snapshot of charges issued to wFirma at moment T)
CREATE TABLE postings (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    batch_id            TEXT NOT NULL,
    client_name         TEXT NOT NULL,
    wfirma_invoice_id   TEXT,                   -- null while drafted
    wfirma_doc_number   TEXT,
    posting_kind        TEXT NOT NULL,          -- proforma | invoice | correction
    posted_at           TEXT,                   -- null = draft
    issued_total_minor  INTEGER NOT NULL,       -- sum of charges at issue
    currency            TEXT NOT NULL,
    fx_rate_at_issue    TEXT,                   -- Decimal-as-string; NBP at issue
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX idx_postings_batch_client ON postings (batch_id, client_name);
CREATE INDEX idx_postings_wfirma_id    ON postings (wfirma_invoice_id);

-- 6F.3 — Payments (inbound cash events)
CREATE TABLE payments (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id          INTEGER NOT NULL,       -- FK → postings.id
    paid_at             TEXT NOT NULL,
    amount_minor        INTEGER NOT NULL,
    currency            TEXT NOT NULL,
    fx_rate_at_payment  TEXT,                   -- NBP table B at payment date
    wfirma_payment_id   TEXT,                   -- mapping back to wFirma payment
    source              TEXT NOT NULL,          -- wfirma | bank_recon | operator
    created_at          TEXT NOT NULL,
    updated_at          TEXT NOT NULL
);
CREATE INDEX idx_payments_posting ON payments (posting_id);

-- 6F.4 — Payment-to-charge allocations (one row per payment-applied-to-charge)
CREATE TABLE payment_allocations (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    payment_id          INTEGER NOT NULL,       -- FK → payments.id
    charge_id           INTEGER NOT NULL,       -- FK → charges.id
    applied_minor       INTEGER NOT NULL,       -- amount of this payment that landed on this charge
    fx_delta_minor      INTEGER NOT NULL DEFAULT 0,  -- the FX-difference component
    allocation_method   TEXT NOT NULL,          -- proportional | operator_directed
    created_at          TEXT NOT NULL
);
CREATE INDEX idx_alloc_payment ON payment_allocations (payment_id);
CREATE INDEX idx_alloc_charge  ON payment_allocations (charge_id);

-- 6F.5 — Settlement events (a posting reaches fully-paid status)
CREATE TABLE settlements (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    posting_id          INTEGER NOT NULL UNIQUE,
    settled_at          TEXT NOT NULL,
    fx_delta_total_minor INTEGER NOT NULL DEFAULT 0,
    rounding_diff_minor INTEGER NOT NULL DEFAULT 0,
    created_at          TEXT NOT NULL
);

-- CHARGE_TYPES (Python-side allow-list, frozenset):
--   net_goods, freight, insurance, customs_duty, vat_eu, vat_pl,
--   rounding_adjustment, fx_delta_at_settlement
```

**Key properties:**
- Minor units (cents) avoid all float arithmetic.
- Decimal-as-string for FX rates avoids float drift.
- A payment is allocated across N charges via `payment_allocations`; sum(applied_minor) == payment.amount_minor.
- FX delta surfaces as its own charge type at settlement time so it is visible in the ledger, not hidden.
- Existing `proforma_service_charges_db.py` table stays in place; data is **migrated forward** to the new `charges` table with `source="operator"` and `charge_type` mapped from `freight`/`insurance` directly.

### 5.3 Posting proposal (write path)

A proforma post goes through the existing `routes_proforma /post` endpoint plus one new local-only step:

```
Operator → Approve draft → /post endpoint
  1. Build proforma XML using current logic (unchanged).
  2. POST to wFirma — get wfirma_invoice_id.
  3. *** NEW: persist a posting row with snapshot of charges ***
       a. INSERT INTO postings (...).
       b. For each existing service_charges row + the net-goods total:
            INSERT INTO charges (posting_id, charge_type, amount_minor, ...).
       c. INSERT INTO charges (charge_type='vat_pl', amount_minor=brutto-netto, ...).
  4. Existing audit log / cliq post unchanged.
```

The posting record is the **explicit bridge** between the local charge model and the wFirma invoice id. After this, the ledger aggregator can join wFirma invoices to local postings and re-attach charge-type labels.

### 5.4 Preview proposal (read path)

A new local-only endpoint (no wFirma write):

```
GET  /api/v1/finance/postings/{posting_id}/breakdown
     → {posting, charges[], payments[], allocations[], settlement?}
```

This is the "statement of account at posting level" view. UI binds the proforma-pipeline page to this for "Charge breakdown" on hover. Pure read; no writes, no recalculations of PZ.

### 5.5 Settlement-close logic

When a `payment` row is inserted (manually or via wFirma payments-find probe), trigger:

```
def maybe_close_settlement(posting_id):
    sum_charges  = SUM(charges.amount_minor WHERE posting_id=?)
    sum_payments = SUM(payments.amount_minor WHERE posting_id=?)
    if abs(sum_charges - sum_payments) <= ROUNDING_TOLERANCE:
        INSERT INTO settlements (...).
        compute fx_delta_total = ... (sum of allocations.fx_delta_minor)
        OPTIONAL: emit fx_delta_at_settlement charge row.
```

No mutation of historical charges or postings. Settlement is an **append-only event**.

---

## 6 — Migration plan

| Step | Description | Type | Reversible? |
|---|---|---|---|
| M1 | Create `finance_postings.sqlite` (5 new tables) | Additive | Yes — delete file |
| M2 | Backfill: read `proforma_service_charges` rows; for each, create matching `postings` + `charges` rows. wFirma invoice id resolved via existing local mapping where present, null otherwise. | Read-only of old data | Yes — `DELETE FROM charges WHERE source='legacy_backfill'` |
| M3 | New endpoint `POST /api/v1/finance/postings/from-proforma/{draft_id}` (local-only, idempotent) — operator runs this once per draft to materialise the explicit charge snapshot | Additive route | Yes — never called → never writes |
| M4 | Modify `routes_proforma /post` to call M3 after wFirma POST succeeds | Behavioural change | Yes — feature-flag-gated by `settings.explicit_charges_enabled` default `False` |
| M5 | Wire `payments/find` probe (Phase 10A.5 still open) → `payments` table inserts | Additive | Yes |
| M6 | Wire settlement-close trigger on payment insert | Additive (event-only) | Yes |
| M7 | Surface `breakdown` view in dashboard (read-only panel) | Frontend additive | Yes |

Default rollout: M1+M2 deploy first (read-only data shape), M3+M7 second (explicit creation + view), M4 third (gated behaviour change), M5+M6 last (closes the loop).

---

## 7 — Tests proposed (none implemented yet)

- DB layer: 30 tests across `test_finance_charges.py` (validate, CRUD, allocation arithmetic, settlement-close trigger).
- API layer: 12 tests across `test_routes_finance_postings.py` (auth, preview, breakdown, idempotency).
- Source-grep contract suite extension (`test_master_data_hard_rules.py`):
  - The new `charges` table must NOT have an `api_key` / credential column (already guarded generically).
  - The new posting path must NOT mutate the existing `ledger_aggregator` 7-field contract.
  - FX delta is captured as a charge row, NOT silently rolled into net.
- Regression suite: `test_pz_regression.py` must stay 160/160 because **NOTHING in the PZ landed-cost calculation path changes**.

---

## 8 — Implementation batches (proposed; gated on approval)

| Batch | Title | Classification | Dependencies |
|---|---|---|---|
| 6F.1 | New SQLite schema + DB module (`finance_postings_db.py`) | NEEDS_SCHEMA_APPROVAL | — |
| 6F.2 | Backfill script from `proforma_service_charges` | AUTO_SAFE | 6F.1 merged |
| 6F.3 | Read-only `/breakdown` endpoint | AUTO_SAFE | 6F.1 + 6F.2 merged |
| 6F.4 | UI panel: charge breakdown on proforma pipeline | AUTO_SAFE | 6F.3 merged |
| 6F.5 | `/post` integration — feature-flagged | NEEDS_SECURITY_REVIEW | 6F.4 merged + Phase 10A.5 probe |
| 6F.6 | Settlement-close event + FX-delta capture | NEEDS_SECURITY_REVIEW | 6F.5 merged |
| 6F.7 | Frontend statement-of-account view | AUTO_SAFE | 6F.6 merged |

Each batch follows the campaign-runner contract: state tracked in `tasks/campaign-state.json`; smoke report under `tasks/smoke-reports/`; PR review per the hard-rules audit suite.

---

## 9 — Hard-rule audit on the proposal itself

| Hard rule | Compliance |
|---|---|
| No wFirma live posting | ✅ The proposed write path uses the EXISTING `/post` endpoint; the new explicit-charges layer is purely local |
| No proforma posting/approval mutation | ✅ Proforma posting logic unchanged; explicit-charge snapshot is captured AFTER `/post` succeeds |
| No PZ/customs/DHL calculation change | ✅ PZ engine path is not touched; explicit-charge layer is downstream of proforma issuance, completely separate from landed-cost calculation |
| No FX override into landed-cost | ✅ FX-delta at settlement is captured but NEVER fed back into landed-cost; it surfaces only in the settlement-time view |
| No `.env` changes | ✅ A new settings flag is proposed in `core/config.py` (not `.env`) |
| No direct production DB/storage edit | ✅ All migrations via PR + robocopy + restart |
| No irreversible external action | ✅ Every step is reversible by deletion of `finance_postings.sqlite` |
| No hidden accounting mutation | ✅ Explicit charge model is the OPPOSITE of hidden mutation — it surfaces previously implicit data |
| No fake backend data | ✅ Backfill (M2) sources from real `proforma_service_charges`; no synthetic charges generated |

**Conclusion:** the proposal is hard-rule compliant. Operator approval is needed for: (a) the new schema, (b) the feature-flagged behaviour change in `/post`, (c) the settlement-close event semantics.

---

## 10 — Recommendation

1. **Operator review** of sections 5.2 (schema), 5.3 (posting), 5.4 (preview), 5.5 (settlement-close).
2. **Operator decision** on charge-type allow-list — current proposal is 8 types; operator may add/remove.
3. **Operator decision** on rollout sequence — current proposal is M1→M7 staged; operator may prefer different ordering.
4. **Stop point.** This campaign goes no further into implementation. The next campaign (Phase 6F implementation) starts when operator signs off on §10.1–§10.3.

---

## 11 — Stop signal

**Phase 5 closes here.** This document is the Phase 5 deliverable. Any further work on Phase 6F charge posting is gated on operator approval of the architecture above. The Operational Integrity + Automation campaign continues without implementing accounting changes.
