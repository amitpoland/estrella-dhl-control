# wFirma Ledger / Statement / Balance Report Research

**Status:** Inspection-only. Evidence collected from doc.wfirma.pl,
the repo's existing validated maps, and HTTP header probes. No
implementation, no write actions, no schema changes.

**Question:** Does wFirma already expose a customer ledger / statement
of account / balance / receivables / payables report that the Estrella
dashboard can embed or proxy, instead of building Phase 10B's custom
Statement subsystem?

**Short answer:** **No.** No such endpoint exists in the wFirma public
API, and the wFirma web UI cannot be embedded in a cross-origin iframe.
A custom JSON aggregation (the current Phase 10A path) remains the only
workable architecture.

---

## 1. Endpoint surface

### 1.1 What the wFirma API DOES expose (relevant subset)

| Endpoint | Status | Evidence | Use for ledger? |
|---|---|---|---|
| `invoices/find` | **CONFIRMED** | Validated map; live use in `app/tools/sync_customer_invoice_snapshot.py`; live probe (Phase 10A.5) | Per-contractor invoice list |
| `invoices/get/{id}` | **CONFIRMED** | Validated map; `wfirma_client.fetch_invoice_xml`; Phase 5 verify-after-create | Per-invoice drill-down |
| `invoices/download/{id}` | **CONFIRMED** | Validated map; `wfirma_client.fetch_invoice_pdf` (Phase 8) | Per-invoice PDF (already wired) |
| `payments/find` | **CONFIRMED** | Validated map; live probe accepted no-filter / `contractor_id` / `invoice_id` / `date` filters with status `OK` | Per-contractor payment ledger |
| `payments/get/{id}` | **CONFIRMED** | Validated map; live probe | Per-payment drill-down |
| `contractors/get/{id}` | **CONFIRMED** | `wfirma_client.fetch_contractor_by_id`; receiver preflight | Header / contractor metadata |
| `expenses/find` | **CONFIRMED** | Validated map | Supplier-side ledger (Phase 10E) |
| `ledger_accountant_years/find,get` | **CONFIRMED in doc.wfirma.pl Postman collection** | Static HTML collection extract | Fiscal-year metadata only — **NOT** a customer ledger |
| `ledger_operation_schemas/find,get` | **CONFIRMED in doc.wfirma.pl** | Same | Accounting rule schemas — **NOT** a customer ledger |

The two "ledger" modules wFirma does have describe **chart-of-accounts
metadata and journal-entry schemas**, not contractor balances. The
"invoice_ledger" string seen in the Postman collection is a folder
name grouping `invoices/*` calls — not an endpoint.

### 1.2 What the wFirma API does NOT expose

| Capability searched | Status | Evidence |
|---|---|---|
| `reports/*` | **NOT FOUND** | `WFIRMA_API_VALIDATED_MAP.md:126` "Analytics / reports — ❌ NOT FOUND"; `WFIRMA_ENDPOINT_MAP.md:439` "Reports / analytics endpoint — no evidence in any SDK"; static doc.wfirma.pl extract returns zero `reports/*` patterns |
| `balances/*` | **NOT FOUND** | Zero hits in doc.wfirma.pl |
| `settlements/*` | **NOT FOUND** | Zero hits in doc.wfirma.pl |
| `statements/*` / `statement_of_account` | **NOT FOUND** | Zero hits |
| `receivables/*` / `payables/*` | **NOT FOUND** | Zero hits |
| `customer_ledger/*` / `contractor_ledger/*` | **NOT FOUND** | Zero hits |
| `customer_balance/*` | **NOT FOUND** | Zero hits |
| `aging/*` / `outstanding/*` | **NOT FOUND** | Zero hits |
| `print/*` (cross-module HTML print) | **NOT FOUND** | Zero hits — only `invoices/download` exists for printable artifacts |
| `export/*` (CSV/XLSX export) | **NOT FOUND** | Zero hits |
| `contractors/print` / `contractors/export` / `contractors/statement` | **NOT FOUND** | doc.wfirma.pl shows only `contractors/{add,edit,delete,find,get}` |
| `expenses/download` / `payments/download` | **NOT FOUND** | Static extract shows only `invoices/download` as a download verb |
| Bank statement import | **NOT FOUND** | `WFIRMA_API_VALIDATED_MAP.md:127` "Bank statement import — ❌ NOT FOUND" |

### 1.3 The only printable / downloadable artifact endpoint

```
invoices/download/{id}     ← per-invoice PDF
```

That is the entire downloadable surface of the wFirma public API. There
is **no statement PDF**, **no aging report PDF**, **no contractor
balance PDF**, **no XLSX export of any kind**.

---

## 2. Authentication model

| Surface | Auth | Browser-cookie compatible? |
|---|---|---|
| wFirma API (`api2.wfirma.pl`) | 3-header API key (appKey + accessKey + secretKey, post-2023-07-02 deprecation per `wfirma_client._api_key_headers`) | **No** — API does not accept session cookies |
| wFirma web UI (`wfirma.pl`) | Browser session cookie (operator login) | Yes for that user's browser only |

**Implication:** the dashboard cannot reuse a wFirma user's browser
session via our backend; the backend uses an API key that is independent
of any user's web login. There is no SSO or session-sharing mechanism.

---

## 3. Embedding feasibility

### 3.1 Cross-origin iframe — BLOCKED

Live HEAD probe of `https://wfirma.pl`:

```
x-frame-options: SAMEORIGIN
```

A cross-origin `<iframe src="https://wfirma.pl/...">` from
`pz.estrellajewels.eu` is **browser-blocked**. Even if a wFirma URL
existed that rendered a contractor statement, the SAMEORIGIN policy
makes it un-embeddable in our dashboard.

`api2.wfirma.pl` does not return `X-Frame-Options` (because it serves
`application/xml`, not HTML), but there is no HTML page there to embed
either.

### 3.2 Backend proxy of an HTML page — BLOCKED

A backend proxy could theoretically fetch the wFirma HTML page and
re-stream it under our origin. **Not feasible** because:

- The wFirma web UI requires a browser session cookie, not an API key.
  Our backend has no way to authenticate as a wFirma user without
  credential storage and login automation, both out of scope.
- Even if authenticated, the page is dynamic JavaScript rendering
  against wFirma's internal APIs that are not part of the public
  contract — fragile across wFirma releases.
- Proxying wFirma's chrome/UI through our origin is a TOS concern
  (no explicit clause checked, but customary SaaS terms forbid it).

### 3.3 Backend proxy of a PDF — PARTIALLY POSSIBLE (per-invoice only)

`invoices/download/{id}` is already proxied in Phase 8 (the
`/api/v1/proforma/{batch}/{client}/document.pdf` route streams the
wFirma PDF through our backend). **There is no equivalent PDF endpoint
for a contractor statement.** Phase 8's pattern is reusable only at
the per-invoice grain.

### 3.4 Direct download by the operator — IRRELEVANT

The operator could log in to wFirma's web UI and download a contractor
statement themselves (if the UI offers one). That bypasses our system
entirely and offers no integration value — the dashboard would still
need its own surface for per-shipment / per-batch context.

---

## 4. Architecture comparison

| Architecture | Status | Reason |
|---|---|---|
| **A — Native wFirma report embedded in viewport** | **BLOCKED** | (a) No statement endpoint exists in the API or web UI per evidence above. (b) Even if it did, `X-Frame-Options: SAMEORIGIN` blocks cross-origin embedding. (c) Auth model mismatch (API key vs session cookie). |
| **B — Proxy a wFirma-rendered PDF through backend** | **BLOCKED** | No statement / ledger / balance PDF endpoint exists. Only `invoices/download/{id}` is downloadable, and that is per-invoice (already wired in Phase 8). |
| **C — Custom JSON aggregation (current Phase 10A path)** | **UNBLOCKED** | `invoices/find` + `payments/find` are confirmed via validated maps and the Phase 10A.5 live probe. Aggregation logic lives in `app/services/ledger_aggregator.py`. Phase 10A ships an invoice ledger today; Phase 10B can extend to a Statement once the invoice-side payment-state probe (Phase 10A.5 follow-up) lands. |
| **D — Hybrid: custom aggregation + per-invoice PDF drill-down** | **UNBLOCKED, RECOMMENDED** | C plus Phase 8's `invoices/download/{id}` proxy gives operator-facing drill-down without requiring a new statement-PDF endpoint that wFirma does not provide. |

---

## 5. Security concerns (if A or B were ever revisited)

- **`X-Frame-Options: SAMEORIGIN`** on `wfirma.pl` is a per-deploy
  setting. If wFirma loosened it, embedding would still require auth
  the dashboard cannot reasonably provide.
- **Storing wFirma user passwords** to drive a headless-browser proxy
  is a credential-hoarding antipattern that should not land.
- **OAuth / SSO with wFirma** is not in the validated map; webhooks
  exist (`webhooks/*`) but webhooks are push from wFirma, not auth
  delegation.
- **TOS risk** of proxying wFirma's UI under our origin is non-zero
  and not worth investigating without a real product reason to embed.

---

## 6. Recommended architecture

**D — Hybrid.**

- Continue Phase 10A (invoice ledger JSON, live).
- Land Phase 10A.5 follow-up probe with a real invoice id to settle
  the invoice-side payment-state field question.
- Phase 10B: aggregator computes balance / aging from `invoices/find`
  + `payments/find` (Architecture B from prior Phase 10 inspection —
  payments-driven). Pattern is already proven by the Phase 10A.5 live
  evidence (`payments/find` returns `<value>`, `<value_pln>`,
  `<invoice/id>`, `<currency_label>`, `<date>` for every payment).
- Per-invoice PDF drill-down reuses the Phase 8 `invoices/download/{id}`
  proxy. No new wFirma calls required for that link.

## 7. What should NOT be built custom

- **No iframe widget** pointing at wFirma. SAMEORIGIN and auth both
  block it.
- **No statement PDF renderer** in this phase. The Phase 10 inspection
  (10B option) ships a JSON ledger first; PDF rendering is a separate
  later phase if the JSON proves insufficient for operator workflow.
  Custom PDF work duplicates what `reportlab` already does for PZ
  exports — small code, but should not land before the JSON model is
  proven by use.
- **No "wFirma SSO" / cookie sharing.** Not feasible with the API key
  auth model; not justified by product need.
- **No wFirma UI scraper.** TOS risk, fragility, and zero added value
  over the JSON aggregator path.

## 8. Open questions deferred to follow-up

- Does `invoices/get/{id}` carry `<paymentstate>` / `<alreadypaid>` /
  `<remaining>` / `<paymentdate>` / `<paid_date>`? **Pending the
  Phase 10A.5 real-id re-run.** If yes → Architecture A (invoice-
  driven) becomes available alongside the recommended payments-driven
  path. If no → payments-driven remains the only choice.
- Does wFirma expose a "GUS / official credit report" surface for
  contractors? Not in scope here; out-of-band research only.
- Is there an undocumented `reports/*` endpoint? Possible (wFirma's
  validated map is community-maintained, not exhaustive). A live
  probe of `reports/find`, `balances/find`, `settlements/find` would
  cost one round-trip each and could be added to
  `probe_payments_and_invoice_payment_state.py` as a Phase 10A.6
  follow-up. Not a blocker for Phase 10B.

---

**Verdict:** Build Architecture D. Do not invest engineering time
trying to embed or proxy a wFirma report that does not exist.
