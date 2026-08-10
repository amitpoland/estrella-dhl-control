# Authority TRACE — Proforma vs fiscal AR universe

**Date:** 2026-08-10  
**Tree:** `C:\PZ-wt\ledger-fiscal`  
**HEAD:** `9873d170f1bc45582860ff7cac2d27418f90e747` (`feat/ledger-exclude-proforma-fiscal` = production/main baseline)  
**Phase:** 0 — inspect only; no behavior edits yet.

## Authority rule (operator)

Fiscal receivable universe for **Client Ledger / Client Balance / Management Analysis** =

- posted invoices (`normal`) + fiscal corrections (`correction`)
- payments **linked to those fiscal documents**

**Proforma is NOT a fiscal invoice** → contributes **0** to invoice count, invoiced, outstanding, receivable, aging, customer balance, MA KPIs.

---

## 1. Exact Proforma entry path(s)

### Root cause (shared bulk path)

Default type tuple includes `"proforma"` at three stacked layers:

| Layer | File | Default / call site |
|---|---|---|
| wFirma bulk fetch | `wfirma_client.fetch_invoices_for_period` ~L2975 | `types=("normal","correction","proforma")` → `type in` XML |
| Fact-universe | `ledger_fact_universe.load_ar_fact_universe` ~L165 | same default; cache key includes `types` |
| MA builder | `accounting_analytics.build_management_analysis` ~L363 | same default; passes through to `load_ar_fact_universe` |

**Client Balance roster** (`routes_ledgers` `client-balances.json` ~L673):

```text
load_ar_fact_universe(df, dt)   # inherits default WITH proforma
  → build_statement_index_by_contractor(invoice_facts, payment_facts)
```

**Management Analysis** (`routes_ledgers` `management-analysis.json` → `build_management_analysis`):

```text
load_ar_fact_universe(df, dt, types=…)  # default WITH proforma
  → build_customer_receivables / match_payments_to_invoices
```

Proforma nodes are parsed by `_parse_invoice_fact` and treated as **positive debits** in `ledger_aggregator`:

- `aggregate_statement_from_facts` ~L805–809: warns `proforma_treated_as_debit` but **keeps** the row
- `_invoice_signed_debit_credit` ~L719: “Regular invoices and proformas are positive debits”
- totals loop ~L960: `e["type"] in ("invoice","correction","proforma")` adds to `invoiced`
- MA `build_customer_receivables` ~L157–167: increments `invoice_count` / `gross_invoiced` for non-correction rows with no type filter — so proforma counts as an invoice

### Parallel per-contractor path (Client Ledger drill)

UI Client Ledger (`ledgers-page.jsx`) loads:

1. Roster → `/client-balances.json` (bulk fact-universe — above)
2. Selected client → `/clients/{id}/statement.json` (**separate** fetch, not fact-universe)

`statement.json` / `invoice-ledger.json` (~L200, ~L334) call:

```text
wfirma_client.fetch_invoices_for_contractor(
    cid, df, dt, types=("normal", "correction", "proforma")
)
```

So even if fact-universe defaults change, **drill statement still re-injects proforma** unless these call sites change too.

### Payment contamination paths

Payments are fetched **without** a document-type filter (`fetch_payments_for_period` / `fetch_payments_for_contractor`). Linkage is `payment.invoice/id` → invoice fact id.

| Surface | Payment linked only to Proforma (after Proforma excluded from invoice facts) |
|---|---|
| **MA** (`match_payments_to_invoices`) | `inv is None` → unmatched; **does not** enter `paid_against_invoice` / `payments_applied` / aging. **Safe if invoices exclude proforma.** |
| **Client statement** (`aggregate_statement_from_facts`) | Same match miss → `payment_links_invoice_outside_window`, but payment **still becomes a statement entry** (~L930–936) and **still adds to `received` / reduces `outstanding`** (~L963–968). **Contaminates fiscal outstanding unless payments are filtered or totals use matched-only.** |

Today (proforma **in** invoice set): a payment linked to Proforma **matches** the proforma row and reduces that “debit,” polluting invoiced + outstanding together.

---

## 2. Callers: fiscal vs commercial type sets

### Must use **fiscal** types `("normal", "correction")` only

| Caller | Today | Role |
|---|---|---|
| `load_ar_fact_universe` default | includes proforma | **Shared AR boundary** for Balance + MA |
| `build_management_analysis` default | includes proforma | MA KPIs |
| `client-balances.json` | inherits universe default | Client Balance roster |
| `statement.json` / `statement.pdf` | explicit 3-tuple | Client Ledger drill (must agree with Balance/MA) |
| `invoice-ledger.json` | explicit 3-tuple | Per-client invoice register under ledgers |

### Intentionally keep / already exclude proforma (do NOT globally strip)

| Caller | Types | Why leave alone |
|---|---|---|
| `wfirma_client.create_proforma_draft` / proforma routes | writes `type=proforma` | Commercial sales workflow — not fiscal AR |
| `find_invoices_for_proforma`, `fetch_proforma_enrichment`, PDF by id | single-doc | Proforma ops / convert identity |
| `list_invoices_by_type` | **already** `"normal"` \| `"correction"` only | Accounting document list (Wave 4) — fiscal register |
| `tools/sync_customer_invoice_snapshot.py` | `INVOICE_TYPES_SYNCED = ("normal","correction")` | Snapshot already fiscal |
| Aggregator still *able* to parse type=proforma | — | Harmless if fiscal fetch never supplies them; UI TYPE_LABEL may remain |
| Tests asserting default `normal,correction,proforma` in fetch XML | e.g. `test_ledger_invoice_ledger_phase10a.py` ~L522 | Must be updated when fiscal default changes; optional commercial override may remain on fetch helpers |

### Fetch helpers — do not blind-edit defaults without callers

`fetch_invoices_for_period` / `fetch_invoices_for_contractor` default to 3-types. Options:

1. Change defaults to fiscal 2-types, and pass `("…","proforma")` only where a commercial register needs it (none identified under Client Ledger / MA today), **or**
2. Leave transport defaults, force fiscal tuple at **fact-universe + statement routes**.

Prefer (1) at fact-universe + ledger routes; change transport defaults only if every ledger caller is audited — safer for “do not break commercial registers.”

---

## 3. Ledger fiscal-universe boundary (anti-divergence)

**Preferred single boundary:**

```text
FISCAL_AR_INVOICE_TYPES = ("normal", "correction")

load_ar_fact_universe(..., types=FISCAL_AR_INVOICE_TYPES)   # default
        │
        ├─ client-balances.json  → build_statement_index_by_contractor
        └─ management-analysis.json → build_management_analysis
                 └─ same invoice_facts + payment match math

Per-contractor statement.json / invoice-ledger.json
        └─ MUST pass the SAME FISCAL_AR_INVOICE_TYPES
           (today hard-codes proforma — divergence risk)
```

**Do not** invent a second MA-only filter or post-hoc “drop proforma in analytics only” — Client Ledger and MA would diverge.

**Payment rule at fiscal boundary:**

- Apply payment amounts to AR **only** when `linked_invoice` ∈ fiscal invoice facts in window (already true for MA).
- For statement totals / outstanding / aging: **matched-to-fiscal only**; proforma-only-linked payments must not reduce fiscal outstanding (statement entry visibility is optional; fiscal math is not).

**AP path:** `load_ap_fact_universe` uses expenses — no invoice proforma. Out of scope for this exclusion (still measure AR/AP Δ0.00 after change).

---

## 4. Regression fixture (Phase 1 must prove)

```
Invoice      1,000 USD
Proforma       500 USD
Payment        400 USD linked to Invoice
→ Invoice count=1, Invoiced=1000, Payments=400, Outstanding=600, Proforma contrib=0
```

Second case: payment linked **only** to Proforma → fiscal outstanding unchanged (no −payment on fiscal AR).

---

## 5. Cold perf notes (Phase 2 — after fiscal fix)

Existing instrumentation on fact-universe / routes: `wfirma_wait_ms`, `ej_ms` / `ej_normalize_ms`, `ej_aggregate_ms`, `cache_hit`, `coalesced`, `per_customer_wfirma_calls`, page waits.

Excluding proforma from `type in` **may** reduce invoice page count (measure; do not claim without timings). Keep architecture: bulk → fact-universe → shared math → Balance/Ledger/MA. No N+1 reopen.

---

## 6. Phase 1 edit plan (post-trace; not executed yet)

1. Introduce shared constant `FISCAL_AR_INVOICE_TYPES = ("normal", "correction")` (fact-universe or thin shared module).
2. Default `load_ar_fact_universe` + `build_management_analysis` to that constant.
3. Align `statement.json` / `invoice-ledger.json` fetch `types=` to same constant.
4. Fix statement fiscal totals so proforma-only-linked (unmatched-to-fiscal) payments do not contaminate `received`/`outstanding` (and aging remains invoice-matched only — already).
5. Fixture tests for the two cases above; update tests that expect `proforma_treated_as_debit` / default 3-type wire body for fiscal callers.
6. Do **not** remove proforma create/read/convert paths; do **not** touch Sales Analysis / Bank / Consignment / DHL.

---

## 7. HOLD triggers (from brief)

- Proforma still affects fiscal totals
- Unexpected invoice/credit/payment accounting change
- Client Ledger ≠ MA
- AR/AP Δ ≠ 0.00
- N+1 returns
- Perf “win” from silently dropping valid fiscal invoices/payments
- Any wFirma write

---

## Phase 1+2 implementation record (post-edit)

**Implemented (HEAD pending commit):**
- FISCAL_AR_INVOICE_TYPES / COMMERCIAL_AR_INVOICE_TYPES in ledger_fact_universe.py
- Default AR universe + MA builder use fiscal types only
- statement.json / invoice-ledger.json pass FISCAL_AR_INVOICE_TYPES
- Aggregator drops type=proforma (proforma_excluded_from_fiscal); fiscal entries = matched payments only
- build_portfolio_from_facts drops proforma before payment match
- Transport wfirma_client.fetch_* defaults left as commercial 3-tuple (non-ledger callers)
- Regression: test_ledger_fiscal_proforma_exclusion.py + updated phase10b/pdf/perf tests
- Cold path: no architecture change; instrumentation retained (wfirma_wait_ms, ej_ms, cache_hit, coalesced, per_customer_wfirma_calls=0); excluding proforma reduces invoice type-in set (live cold delta on deploy smoke)
