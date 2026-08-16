# Insurance Recovered — live authority census and root-cause classification

Read-only census of every issued wFirma sales document (type `normal` +
`correction`) against the CommercialChargeAuthority, measured 2026-08-16.

- Tree / HEAD: `C:\PZ-wt\insurance-fx-convergence` @ `5448bd13`
  (branch `feat/insurance-fx-and-recovered-convergence`, forked from `main` @ `ea292f71`).
- wFirma: read-only (`invoices/find`, `invoices/get`) with the four read
  credentials only; no `*_ALLOWED` write gate was loaded.
- Draft store: a WAL-safe point-in-time `sqlite3` backup copy of
  `C:\PZ\storage\proforma_links.db`. The live file was opened `mode=ro`.
- Documents censused: **764** (705 `normal`, 59 `correction`), 2020-05 → 2026-08.

## Two definitions being compared

| Term | Definition |
|---|---|
| SOURCE insurance | A line on the **issued fiscal document** whose `good/id` is the canonical insurance service. |
| AUTHORITY insurance | What `commercial_charge_authority.resolve_commercial_charges` resolves from the **linked proforma draft's** `service_charges_json`. |

## Canonical insurance identity — measured, not assumed

All **521** insurance evidence lines across 2020–2026 carry
`good_id = 13102217`. Zero lines matched on name only. There is no historical
alias and no second insurance product. The identity already has an authority
home — `customer_master_db.insurance_service_id` (default `13102217`) — so no
new mapping table is required.

## Root-cause classes

| Class | Count | Meaning |
|---|---:|---|
| **A — NO_AUTHORITY_RECORD** | 512 | Document bills insurance; **no proforma draft exists at all**, so the charge authority holds nothing and the statement renders blank. |
| **B1 — AUTHORITY_MISSING_BILLED_CHARGE** | 1 | Draft exists and is linked, but its snapshot carries no insurance charge while the issued document bills one. |
| **B2 — AUTHORITY_HOLDS_UNBILLED_CHARGE** | 1 | Draft snapshot carries an insurance charge that the issued document **never billed**. The statement reports a recovery that does not exist. |
| **C — AGREES** | 8 | Draft snapshot equals the issued document. Working correctly. |
| **D — AUTHORITY_ZERO_NO_SOURCE** | 1 | Authority resolves 0.00, document bills nothing. Correct; correctly excluded. |
| **E — NO_INSURANCE** | 241 | Neither side carries insurance. Correct. |

### Class A — the dominant class (512 / 764)

Insurance genuinely billed to the customer, invisible to the statement.

| Year | Documents |
|---|---:|
| 2020 | 21 |
| 2021 | 67 |
| 2022 | 49 |
| 2023 | 55 |
| 2024 | 83 |
| 2025 | 132 |
| 2026 | 105 |

Unrecognised billed insurance: **USD 7 310.62 · EUR 5 903.53 · PLN 93.48**.

Only **14** drafts in the entire store carry a `wfirma_invoice_id`, and only
**16** invoice links exist. The charge authority's snapshot is populated
exclusively by the draft → invoice conversion workflow, which is recent. Every
document issued directly in wFirma — six years of them — is structurally
outside it. This is a **population gap in the authority, not a resolver bug**.

### Class B1 — WDT 146/2026 (issued 2026-07-17, USD)

Issued document: `good=13102217`, net **19.27 USD**.
Draft 66 (`converted`, linked to invoice `490019491`): freight 100.00 only.
The insurance line was added on the fiscal document after the snapshot was
frozen.

### Class B2 — WDT 155/2026 (issued 2026-08-05, USD) — the named anomaly

Draft 73 (`converted`, linked to invoice `495933603`) holds
`insurance = 362.39 USD`, `resolution = calculated`,
`formula_basis = {rate_pct 0.4500, sales_total 80530.660}`.

The issued document (total 80 586.66 USD) carries **freight 56.00 and no
insurance line at all** — and its freight also disagrees with the draft's
28.00. The draft is pre-issue intent that the issued document did not follow.

Consequence: the currently published USD recovered total of **420.91** is
`362.39 + 13.30 + 35.22 + 10.00` — i.e. **362.39 of it was never billed to
anyone**.

### Class D — FV 15/2026

Draft 79 resolves insurance 0.00 (`calculated`, `sales_total 605.00`); the
document bills nothing. Consistent with the closed Slice-3 finding that FV 15
is correctly excluded.

## August 2026 — independently derived from the fiscal source

Insurance actually billed in August 2026: **EUR 90.43 · USD 68.52**.

| Document | Date | Ccy | Billed | Authority | Class |
|---|---|---|---:|---:|---|
| WDT 153/2026 | 2026-08-04 | EUR | 56.98 | — (no draft) | A |
| WDT 154/2026 | 2026-08-04 | EUR | 13.45 | 13.45 | C |
| WDT 155/2026 | 2026-08-05 | USD | — | 362.39 | **B2** |
| WDT 156/2026 | 2026-08-05 | USD | 10.00 | — (no draft) | A |
| FV 15/2026 | 2026-08-11 | USD | — | 0.00 | D |
| WDT 157/2026 | 2026-08-11 | USD | 13.30 | 13.30 | C |
| WDT 158/2026 | 2026-08-11 | EUR | 10.00 | 10.00 | C |
| WDT 159/2026 | 2026-08-12 | USD | 35.22 | 35.22 | C |
| WDT 160/2026 | 2026-08-12 | USD | 10.00 | 10.00 | C |
| WDT 161/2026 | 2026-08-12 | USD | — | — (draft, no charge) | E |
| WDT 162/2026 | 2026-08-14 | EUR | 10.00 | 10.00 | C |

The published statement shows EUR 33.45 / USD 420.91. The difference is
exactly classes A (+56.98 EUR, +10.00 USD) and B2 (−362.39 USD).

## The single defect behind every class

The statement asks the charge authority what insurance was **planned on a
proforma draft**, and publishes the answer as what was **recovered from the
customer**. Those are different facts, and 2 of the 14 linked documents prove
they diverge. The authority has no durable record of what an issued fiscal
document actually billed — and for 512 documents it has no record at all.

## Conflict handling required by the repair

A document where the draft snapshot and the issued document disagree on a
non-zero amount or currency (B1, B2) must be recorded as **NEEDS MANUAL
REVIEW** and never auto-overwritten in either direction. The fiscal document is
never mutated; the draft snapshot is never mutated.
