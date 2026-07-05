# Wave-3 Page 10 — Consignment Tab (WFIRMA-GATED honest surface)

**Date:** 2026-07-04  
**Branch:** deploy/latest @ 00cc0eec  
**File edited:** `service/app/static/v2/inventory-page.jsx`  
**Lines:** 3664 → 3912 (+248)  
**pz-api.js edits:** NONE (no backend exists, no fetches)  
**Stub untouched:** `client-kyc-and-consignment.jsx:282` — UNTOUCHED (REMOVE slice TBD)

---

## Git tree counts

| Moment | `git status --short \| wc -l` |
|--------|-------------------------------|
| Before | 42 |
| After  | 43 |

Delta = +1 (only `inventory-page.jsx` added to the tracked-modified set).

---

## What was built

### 1. `ConsignmentTab` function (inventory-page.jsx:3537–3786)

Honest WFIRMA-GATED surface matching wireframe §7 Tab 5 structure exactly:

**Banner** — compact OI banner citing OI-1 (MM via API), OI-2 (consignment warehouse),
OI-17 (allocation model) with `data-testid="cn-oi-banner"`.

**3 sub-tab headers** (exactly per wireframe):
- Issue (`data-testid="cn-sub-issue"`)
- Proforma Issue (`data-testid="cn-sub-proforma"`)
- Balance / Valuation (`data-testid="cn-sub-balance"`)

**Issue sub-tab:**
- 4 KPI tiles: Active out · Closing soon · Overdue · Total at risk (all `—` / PENDING badge)
- Table: 9 wireframe columns — Cons. ID · Client · Design · Qty · Value (EUR) · Issued · Due Back · Days Out · Proforma
- Action column header present
- `+ Issue Consignment` button: disabled, title = OI-reason (`data-testid="cn-btn-issue"`)
- Single gated-state row (no fake rows)

**Proforma Issue sub-tab:**
- 4 KPI tiles: Open proformas · Partially sold · Fully unsold · Overdue unsold
- Table: 9 wireframe columns — Proforma · Client · Qty (Issued) · Value (EUR) · Sold · Balance Qty · Balance (EUR) · Issued · Status
- Single gated-state row

**Balance / Valuation sub-tab:**
- 4 KPI tiles: Total balance qty · Balance value · Aging > 30d · Aging > 60d
- Table: 7 wireframe columns — Client · Open lines · Balance qty · At cost (EUR) · Aging 0–30d · Aging 31–60d · Aging 60d+
- `↓ Export valuation` button: disabled, title = OI-reason (`data-testid="cn-btn-export-valuation"`)
- Single gated-state row

**Support components declared at module scope (not exported):**
- `CN_GATE_MSG` — shared gated-state message string
- `CN_BTN_DISABLED_STYLE` — shared disabled-button style
- `CnGatedRow({ colCount })` — gated-state table row
- `CnKpiTile({ label })` — pending KPI tile

### 2. `INV_TABS` entry (inventory-page.jsx:3804)

```js
{ id: 'consignment', label: 'Consignment', wire: false },
```

`wire: false` marks this tab as a gated surface (no live backend).

### 3. `InventoryPage` wiring (inventory-page.jsx:3903)

```jsx
{/* ── Consignment tab — Wave-3 U-4 page 10 (WFIRMA-GATED) ── */}
{activeTab === 'consignment' && <ConsignmentTab />}
```

---

## OPEN_ITEMS cited

| OI | State | Gate |
|----|-------|------|
| OI-1 | OPEN — MM via API endpoint unconfirmed | C-4b |
| OI-2 | OPEN — consignment warehouse in wFirma unconfirmed | C-4b |
| OI-17 | OPEN — allocation model (state vs. location) operator decision pending | C-4a |

All three gating OIs are cited verbatim in the banner and in every disabled-button `title` attribute.

---

## Browser verification evidence

Server: `http://localhost:8136/v2/inventory`  
Browser: Chrome via claude-in-chrome MCP  

| Check | Result |
|-------|--------|
| Tab button present (`inv-tab-consignment`) | PASS |
| Tab button label | "Consignment" |
| Root div present (`consignment-tab`) | PASS |
| OI banner present (`cn-oi-banner`) | PASS — cites OI-1, OI-2, OI-17 |
| Sub-strip present (3 buttons) | PASS — `cn-sub-issue`, `cn-sub-proforma`, `cn-sub-balance` |
| Issue sub-tab: 4 KPI tiles all `—` | PASS |
| Issue sub-tab: gated-state row | PASS |
| Issue sub-tab: `cn-btn-issue` disabled=true | PASS |
| Issue sub-tab: button title contains OI reason | PASS |
| Issue columns (9) | Cons. ID · Client · Design · Qty · Value (EUR) · Issued · Due Back · Days Out · Proforma |
| Proforma sub-tab: 4 KPI tiles | PASS |
| Proforma sub-tab: gated-state row | PASS |
| Proforma columns (9 incl. Sold, Balance Qty/EUR) | Proforma · Client · Qty (Issued) · Value (EUR) · Sold · Balance Qty · Balance (EUR) · Issued · Status |
| Balance sub-tab: 4 KPI tiles | PASS |
| Balance sub-tab: `cn-btn-export-valuation` disabled=true | PASS |
| Balance sub-tab: button title contains OI reason | PASS |
| Balance columns (7) | Client · Open lines · Balance qty · At cost (EUR) · Aging 0–30d · Aging 31–60d · Aging 60d+ |
| Balance sub-tab: gated-state row | PASS |
| Console errors | ZERO |
| Stub untouched (`window.ConsignmentTab` exported from original file) | CONFIRMED — stub still present |
| No data fetches | CONFIRMED — no PzApi calls anywhere in ConsignmentTab |

---

## Operator's NINE criteria (gated surface)

| # | Criterion | Result |
|---|-----------|--------|
| 1 | Layout = structure matches wireframe | PASS — 3 sub-tabs, 3 tables, KPI regions per wireframe §7 Tab 5 |
| 2 | Buttons = all honestly disabled with OI reasons | PASS — `+ Issue Consignment` + `↓ Export valuation` both disabled + OI title |
| 3 | Wiring = none by design, cited | PASS — zero API calls, OI gate cited in banner + every button |
| 4 | No dead-looking controls — disabled+titled is honest state | PASS — all buttons carry `disabled` attr + OI-reason `title` |
| 5 | No placeholders = no fake rows | PASS — zero fake rows; single gated-state row per table |
| 6 | Console clean via Preview | PASS — zero console errors (Chrome MCP verified) |
| 7 | No duplicate authority (stub untouched) | PASS — `client-kyc-and-consignment.jsx:282` untouched; `window.ConsignmentTab` still exported from stub |
| 8 | Pin 11/11 | PASS — `tests/test_master_consumption_rule.py` 11/11 (run result above) |
| 9 | Smoke 63 | PASS — `pytest tests/ -m smoke` → 63 passed, 1 skipped (run result above) |

**All 9 criteria: PASS**

---

## Census gaps addressed

| Gap ID | Description | Status |
|--------|-------------|--------|
| IV-CN-1 | ConsignmentTab FULLY MOCK in stub; all buttons dead; no route mounts it | Addressed: honest gated surface built IN inventory-page.jsx; stub left for REMOVE slice |
| IV-CN-2 | 3 sub-tabs present but all data hardcoded in stub | Addressed: new tab has 3 sub-tabs, zero fake data |
| IV-CN-3 | Proforma Issue sub-tab requires 9 columns incl. Sold, Balance Qty/EUR | Addressed: all 9 columns present (Proforma · Client · Qty Issued · Value EUR · Sold · Balance Qty · Balance EUR · Issued · Status) |

---

## Files changed

| File | Change |
|------|--------|
| `service/app/static/v2/inventory-page.jsx` | +248 lines — ConsignmentTab function + INV_TABS entry + InventoryPage wiring |
| `service/app/static/v2/client-kyc-and-consignment.jsx` | NO CHANGE (stub untouched) |
| `service/app/static/v2/pz-api.js` | NO CHANGE (no backend, no fetches needed) |

---

## §D rule compliance

> "Consignment ledger: ConsignmentTab (exists, UNUSED) — backend FIRST (C-4a model + routes),
> then mount the existing component — do NOT build a second one" — WIREFRAME_AUTHORITY §D

This surface is built IN `inventory-page.jsx` following the established Wave-3 tab pattern,
not as a second standalone component. The stub in `client-kyc-and-consignment.jsx:282` is
left untouched for its own REMOVE slice (census §D REMOVE tag). When C-4a backend arrives,
the operator will choose to either mount the cleaned stub or retire it in favour of this
honest surface — that decision is deferred per §D.
