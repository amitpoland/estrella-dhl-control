# Campaign: Proforma Contract Lock
**Status:** IN PROGRESS (updated 2026-06-10) — PR A COMPLETED (#546, merge a6b84f0, deployed, GATE 6 PASS) · PR B COMPLETED (#548, merge 74bee9d, deployed, GATE 6 PASS) · PR C (DHL/AWB generation flow, issue #11) NOT YET OPEN
**Authority:** Operator directive 2026-06-10
**Campaign slug:** proforma-contract-lock

---

## Root Cause

Previous fixes keep disappearing because there is no unified authority contract protecting
proforma display rules. Each PR fixes one thing without locking it down — the next PR
silently reverts it. This campaign fixes all 11 known display/data gaps AND adds a
contract test that makes regression impossible.

---

## 11 Known Issues (Audit 2026-06-10)

| # | Issue | Root cause | Status |
|---|-------|-----------|--------|
| 1 | No inline address edit on Buyer / Ship-to | No edit modal on party cards; Customer Master only path | MISSING |
| 2 | Freight + Insurance not auto-projected into draft | `suggest-freight` + `suggest-insurance` endpoints exist but UI never calls them | MISSING |
| 3 | Payment Due Date not calculated | `wfirma_payment_due` only set post-wFirma. Pre-post drafts show `—` | MISSING |
| 4 | NBP exchange rate — previous-day | Backend fields exist (`exchange_rate_date`, `nbp_table`); needs verification | NEEDS VERIFY |
| 5 | Bank details not passed to print template | `previewDocData.banks = []` hardcoded | BROKEN |
| 6 | Footer says "7 days" when draft says 90 days | `EJDocCompliance` hardcodes "7 days" — disconnected from draft | BROKEN |
| 7 | Return & Warranty text too faint | `color: "#64748B"` + font-size 9 on white paper | BROKEN |
| 8 | Country of Origin fallback missing | `ln.origin \|\| '—'` — no fallback to shipment source country | MISSING |
| 9 | Description EN + PL — only design code shown | `desc: ln.design_no \|\| ln.product_code` — PL/EN fields never used | MISSING |
| 10 | Country codes not expanded | "PL", "LT" shown raw — no COUNTRY_NAMES lookup | BROKEN |
| 11 | AWB + Generate are split; both gated | `⚙ Generate ▾` disabled, AWB shown separately from batch_id | PLANNED/GATED |

---

## 3-PR Plan (authority-grouped)

### PR A — Proforma Display Contract Lock
**Authority: Proforma document rendering**
**Risk: Low — frontend only, no new backend routes**

Fixes (all in one PR):
- **#6** Footer payment terms — `EJDocCompliance` accepts `paymentDays` + `paymentDueStr` props
- **#7** Footer contrast — `#64748B` → `#334155`, font-size 9 → 10
- **#5** Bank details — populate `previewDocData.banks` from `companyProfile.bank_accounts`
- **#10** Country names — add `COUNTRY_NAMES` lookup; expand in customer + exporter before render
- **#3** Payment due calculation — `invoice_date + payment_terms_days` fallback when `wfirma_payment_due` absent
- **#9** PL/EN descriptions — map `editable_lines` `description_pl` + `description_en`; dual-line render in doc template
- **#8** Origin fallback — `ln.origin || draft.origin_country || companyProfile.country`

Contract test added: `test_proforma_display_contract.py`
- Draft #24 preview shape assertions
- buyer fields, payment_due, bank, origin, PL/EN descriptions, country names, freight/insurance
- All assertions are source-grep tests (no server needed)

### PR B — Customer and Service-Charge Authority
**Authority: Customer Master + service charges**
**Risk: Medium — writes to Customer Master, service charge lines**

Fixes:
- **#1** Inline Bill-to / Ship-to edit modal (address, phone, contact)
  - "✎ Edit" button on BUYER + RECIPIENT party cards
  - Modal → `PATCH /api/v1/customer-master/{id}/address`
  - Shows: which fields override Customer Master vs are draft-specific
  - Audit trace: edited_by + edited_at in customer master record
- **#2** Auto-suggest freight + insurance
  - On Lines tab mount: call `GET /suggest-freight` + `GET /suggest-insurance`
  - If values returned: show "Suggested charges" banner
  - One-click "Add Freight €X + Insurance €Y" button (confirmed by operator)
  - Guard: no duplicate service-charge lines
  - Exact disabled + error states documented

### PR C — DHL / AWB Generation Flow
**Authority: DHL carrier integration**
**Risk: Medium — external integration boundary**

Fixes:
- **#11** Unified "Generate Air Waybill" button
  - One button replacing split `⚙ Generate ▾` + disconnected AWB display
  - Readiness contract: dimensions + gross weight + declared value required before enable
  - If DHL pipeline active → calls generate endpoint → shows AWB number in party area
  - If not active → disabled with exact reason: "DHL shipment not yet created — go to Shipment tab"
  - No accidental DHL write — confirmation modal before any write
  - `data-testid="tb-generate-awb"` replaces both `tb-generate` and disconnected batch_id display

---

## Sequencing

```
GATE 2 slot opens
  └─ PR A  (display contract + contract test)  ← FIRST: locks all rendering
       └─ PR B  (customer + service charges)
            └─ PR C  (DHL/AWB)
```

PRs B and C may overlap if 2 GATE 2 slots are available simultaneously.

---

## Anti-regression contract (PR A must add this)

`service/tests/test_proforma_display_contract.py`

Required assertions (source-grep, no server):
1. `COUNTRY_NAMES` dict is defined and contains at least `PL`, `LT`, `DE`, `IN`, `ES`
2. `previewDocData.banks` is populated from `companyProfile`, not hardcoded `[]`
3. `EJDocCompliance` receives payment terms as prop (not hardcoded "7 days")
4. Payment due fallback logic: `wfirma_payment_due || addDays(invoice_date, payment_terms_days)`
5. `description_pl` and `description_en` are mapped from `editable_lines`
6. `origin` fallback chain: `ln.origin || draft.origin_country || companyProfile.country`
7. Country expansion applied to both `customer.country` and `exporter.country`

---

## Files in scope

| PR | Files touched |
|----|--------------|
| A | `service/app/static/v2/proforma-detail.jsx` |
| A | `service/app/static/v2/estrella-doc-proforma.jsx` |
| A | `service/tests/test_proforma_display_contract.py` (new) |
| B | `service/app/static/v2/proforma-detail.jsx` |
| B | `service/app/api/routes_customer_master.py` (new PATCH endpoint if missing) |
| B | `service/tests/test_proforma_service_charges.py` (new) |
| C | `service/app/static/v2/proforma-detail.jsx` |
| C | `service/app/api/routes_dhl_*.py` (generate AWB endpoint) |
| C | `service/tests/test_proforma_awb_generation.py` (new) |

---

## GATE state at planning time

| Gate | State |
|------|-------|
| GATE 2 | 3/3 (#498, #522, #545) — waiting for slot |
| GATE 3 | All 3 branches ACTIVE |
| Test baseline | 160 PZ + 412 carrier |
| Origin/main HEAD | 914414e |

---

## Start condition

Merge #545 (URL hydration fix, frontend-only, 25 tests, low risk) → slot opens → begin PR A.
