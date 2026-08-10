# TRACE — Statement of Account fiscal divergence + PDF gaps

**Date:** 2026-08-10  
**Tree:** `C:\PZ-wt\stmt-fiscal`  
**Branch:** `feat/statement-fiscal-universe-pdf`  
**HEAD / prod marker:** `5daf848bb53faeb5f98e6c21409819ceb7151192` (PR #1172 merged — `FISCAL_AR_INVOICE_TYPES`)  
**Phase:** 0 — read-only inspect + live Kenny comparison; **no behavior edits yet**.

**Prod probe:** `http://127.0.0.1:47213` read-only `X-API-Key` GETs.  
**Contractor:** `199226787` (MICHAEL KENNY LLP). Window `2026-01-01` → `2026-12-31`.

---

## 0. Operator report vs live facts (verdict)

| Operator report (pre-#1172 / stale UI) | Live prod @ `5daf848` |
|---|---|
| PROF 157/160/168 as debit rows | **Absent** — 0 proforma entries |
| `proforma_treated_as_debit` warning | **Absent** — `warnings_n = 0` (event renamed to `proforma_excluded_from_fiscal` + drop in #1172; not firing because fetch excludes PF) |
| Raw wFirma id `199226787` on customer-facing surface | Statement JSON still carries `contractor.wfirma_contractor_id`; PDF customer block still renders it when present |
| Incomplete address | Statement contractor = name / country / VAT only (no street/city/zip) |
| No Estrella logo | PDF uses text “EJ” mark, not `/v2/assets/estrella-logo.*` |
| Footer ≠ Proforma/Packing List | Statement invents own footer; does not call `get_company_profile` / packing seller helpers |
| Aging as Invoice age | Confirmed — `aging_per_currency.USD.method = "invoice_age"` |

**Fiscal arithmetic for Kenny is already correct after #1172.** Remaining work is architecture cleanup (shared authority), aging authority alignment, and customer-facing PDF professionalism — not re-excluding Proforma from totals.

---

## 1. Root cause — why Proformas entered Statement (historical, #1172)

Exact path (documented earlier in `trace-ledger-proforma-fiscal.md`, now fixed at fetch + aggregator):

```text
fetch_invoices_for_contractor(..., types=("normal","correction","proforma"))  # DEFAULT + explicit call sites
  → _parse_invoice_fact (type=proforma kept)
  → aggregate_statement_from_facts
       warned proforma_treated_as_debit but KEPT row
       totals treated proforma as positive debit
```

Parallel bulk path (`load_ar_fact_universe` default) fed Client Balance + MA the same commercial contamination.

**#1172 correction (live):**

| Layer | After #1172 |
|---|---|
| `ledger_fact_universe.FISCAL_AR_INVOICE_TYPES` | `("normal", "correction")` |
| `load_ar_fact_universe` default | fiscal only |
| `routes_ledgers._build_statement_dict` / invoice-ledger | passes `types=FISCAL_AR_INVOICE_TYPES` |
| `aggregate_statement_from_facts` | drops `type==proforma` (`proforma_excluded_from_fiscal`); fiscal entries = matched payments only |

**Not the cause today:** stale PDF cache, FE-only old data, or statement_pdf_renderer inventing PF rows. Renderer only paints the Statement DTO; live PDF has no PROF / no `199226787` in binary sniff for debit rows (id still in JSON).

---

## 2. Kenny read-only comparison (Client Ledger | MA | Statement)

### 2.1 Statement JSON — `/api/v1/ledgers/clients/199226787/statement.json`

| Field | Value |
|---|---|
| Currencies | USD |
| Totals | invoiced `10613.96` / received `6166.45` / outstanding `4447.51` / entry_count `5` |
| Warnings | `[]` |
| Aging | method **`invoice_age`**, total `4447.51` in bucket `1_30` |

| Date | Type | Doc | Debit | Credit | Running |
|---|---|---|---|---|---|
| 2026-07-14 | invoice | WDT 143/2026 | 2793.00 | 0 | 2793.00 |
| 2026-07-16 | invoice | WDT 145/2026 | 3373.45 | 0 | 6166.45 |
| 2026-07-16 | payment | 603295715 | 0 | 2793.00 | 3373.45 |
| 2026-07-23 | payment | 605911459 | 0 | 3373.45 | 0.00 |
| 2026-07-29 | invoice | WDT 152/2026 | 4447.51 | 0 | 4447.51 |

Matches operator’s expected fiscal shape (no PROF).

### 2.2 Invoice ledger — same contractor window

3 fiscal invoices only (ids `488962083`, `489960355`, `493934819`) — gross sum `10613.96`. **IDs ⊆ Statement invoice entries.**

### 2.3 Client Ledger roster — `GET /api/v1/ledgers/clients?contractor=199226787`

| Field | Value |
|---|---|
| open | `4447.51` |
| ytd_invoiced | `10613.96` |
| overdue_invoice_age | `4447.51` |
| overdue_due_date | **`null`** (roster still invoice-age oriented / due-date column empty) |

**Δ Statement outstanding vs Client Ledger open = 0.00**

### 2.4 Management Analysis — `/management-analysis.json` customer row

| Field | Value |
|---|---|
| invoice_count | 3 |
| outstanding | `4447.51` |
| overdue | `4447.51` |
| payment_terms / aging | **`due_date`** (`oldest_due_date=2026-07-28`, buckets `b_1_30`) |
| due_date_coverage (portfolio) | open_with_paymentdate **48**/48 = **100%** |

**Δ Statement outstanding vs MA outstanding = 0.00**  
**Aging authority Δ:** Statement = invoice_age; MA = due_date — **silent mix across surfaces.**

### 2.5 Customer Master address (authoritative postal — unused by Statement today)

`GET /api/v1/customer-master/199226787`:

- bill_to_name / ship_to_name: MICHAEL KENNY LLP  
- bill_to_street: The Square  
- bill_to_city: Castlerea, Roscommon  
- bill_to_postal_code: F45A256  
- bill_to_country: IE  
- vat_eu_number / nip: IE5455683P  

Statement `_build_statement_dict` contractor_meta today = wFirma contractor preflight only (`name`, `country`, `vat_id`, `wfirma_contractor_id`) — **no street/city/zip**.

---

## 3. Remaining root causes (this campaign — post-#1172)

### RC-1 — Duplicate Statement fact path (architecture)

```text
Client Balance / MA
  └─ load_ar_fact_universe(FISCAL_AR_INVOICE_TYPES)  → shared invoice_facts + payment_facts
       └─ aggregate_statement_from_facts / build_statement_index_by_contractor

Statement.json / Statement.pdf
  └─ SEPARATE fetch_invoices_for_contractor(types=FISCAL…)
  └─ SEPARATE fetch_payments_for_contractor
  └─ aggregate_statement(nodes) → parse → same aggregator
```

Arithmetic converges when both use fiscal types, but Statement **re-fetches** instead of consuming the shared corrected universe. Risk: future caller drift; defence-in-depth `proforma_excluded_from_fiscal` warning can still land in DTO → **PDF warnings band** if any path reintroduces PF nodes.

**Fix direction:** Statement builder consumes shared fiscal facts (filter by contractor from `load_ar_fact_universe` / `aggregate_statement_from_facts`), and PDF must **not** re-implement fiscal filtering.

### RC-2 — Aging authority hard-coded to invoice_age

`routes_ledgers.py` comment still forbids due-date pending “Phase 10A.5 probe”.  
**Obsolete:** MA already ages on `paymentdate` with 100% open coverage; `_parse_invoice_fact` already stores `paymentdate`.

Statement `aggregate_statement_from_facts` ~L982–1008:

```text
days_old = statement_date - inv["date"]   # issue date
method = "invoice_age"
```

**Authority decision for this campaign:** canonical AR aging = **due-date (`paymentdate`)** — same as MA. Statement must **default** to `due_date`. `invoice_age` only when explicitly requested by the caller. No silent per-surface mix.

### RC-3 — Customer-facing PDF / DTO presentation gaps

| Gap | Mechanism |
|---|---|
| Incomplete address | contractor_meta lacks Customer Master bill_to_* |
| wFirma id on PDF | `_customer_block_flowable` prints `wfirma_contractor_id` |
| Fake logo | `_masthead_flowable` draws “EJ” cell — does not reuse `/v2/assets/estrella-logo.svg` (or packing/proforma logo path) |
| Divergent footer | local footer drawer; not `get_company_profile` / commercial packing seller / estrella-doc footer helpers |
| Internal warnings on PDF | `_warnings_flowables` renders DQ events (“operator should review” class) on customer PDF |

JSON/screen/PDF totals already share `_build_statement_dict` → same numbers when fiscal facts match; presentation must stay total-parity while stripping internal metadata from **customer PDF only**.

---

## 4. Ruled out

| Hypothesis | Evidence |
|---|---|
| Aggregator still treats PF as debit on prod | Live Kenny: 0 PF rows; code drops PF |
| statement_pdf_renderer duplicates fiscal math | Pure render of DTO; no second fetch |
| Stale PDF cache of PROF rows | Fresh PDF 200; no PROF in content sniff |
| FE alone showing old Statement | Live API already fiscal-clean |
| Payments detached from fiscal invoices | Payments 603295715 / 605911459 matched; received = 6166.45 |

---

## 5. HOLD checks (pre-edit)

- Must not hide PF visually while leaving in totals (N/A — PF already out of totals).  
- Must not change Statement totals away from Client Ledger (Δ0.00 baseline for Kenny).  
- Must not guess address — use Customer Master bill_to_*.  
- Must not invent new logo/footer components — reuse CompanyProfile + existing asset / packing-proforma helpers.  
- Must not duplicate fiscal type filtering inside the PDF renderer.

---

## 6. Phase 1 implementation map (post-trace)

1. Statement builder: consume shared fiscal authority (`aggregate_statement_from_facts` from universe facts filtered by contractor); keep single DTO for JSON+PDF.  
2. Aging: default `due_date` via `paymentdate`; optional explicit `invoice_age`; document winner in route docstring + architecture note.  
3. Enrich contractor block from Customer Master postal fields (read-only).  
4. PDF: reuse logo asset + company legal footer; omit wFirma id / DQ warnings from customer PDF (keep warnings in JSON for internal UI).  
5. Regression: Inv 1000 + PF 500 + Pay 400 → Invoiced 1000 / Received 400 / Outstanding 600; zero PF rows; zero PF warning when fetch is fiscal.  
6. Browser/PDF check Kenny + ≥1 EUR/PLN customer; floors; security-review; PR; 7-agent gate; deploy; smoke.

---

## 8. Phase 1 implementation record (post-edit)

**Tree:** `C:\PZ-wt\stmt-fiscal` · branch `feat/statement-fiscal-universe-pdf`

| Change | Location |
|---|---|
| Statement consumes `load_ar_fact_universe` + `aggregate_statement_from_facts` (no per-contractor commercial re-fetch) | `routes_ledgers._build_statement_dict` |
| Aging default `due_date` (`paymentdate`); `invoice_age` only via explicit query | `ledger_aggregator` + route `aging_method` |
| Silent PF defensive drop (zero PF warning) | `aggregate_statement_from_facts` |
| Customer Master bill_to_* postal enrichment | `_contractor_meta_from_customer_master` |
| PDF: CompanyProfile seller footer via `_seller_from_company`; logo path reuse; hide wFirma id + warnings when customer_facing | `statement_pdf_renderer` + PDF route |
| Regression Inv 1000 + PF 500 + Pay 400 | `test_ledger_fiscal_proforma_exclusion` + phase10b |

**Aging authority winner:** `due_date` (invoice `paymentdate`) — Management Analysis parity. Invoice age is opt-in only.
