# Wave-3 Build Record: Accounting Hub
**Date:** 2026-07-04  
**Branch:** deploy/latest  
**Census item:** #3 (scope L — Accounting Hub)  
**Criterion 10 (control matrix gate):** PASS — Wireframe-Required Missing = 0

---

## Summary

Converted `service/app/static/v2/accounting-hub.jsx` from a full-MOCK page to
a live 6-tab hub. All mock arrays removed. `accounting` added to WIRED_PAGES.
Sprint-28 contract superseded to reflect V2 JSX architecture.

---

## Files changed (4)

| File | Change |
|---|---|
| `service/app/static/v2/accounting-hub.jsx` | Full rewrite: 468 lines → 874 lines (mock→live); all 6 tabs wired |
| `service/app/static/v2/mock-badge.jsx` | `'accounting'` added to WIRED_PAGES (19 → 20) |
| `service/app/static/v2/pz-api.js` | Wave-3 block: `getWfirmaContractorScanStatus` added |
| `service/tests/test_accounting_hub_v2_contract.py` | Superseded Sprint-28 contract → V2 JSX contract (11 tests, all PASS) |

---

## Control matrix — census §A AC rows

| Census | Control | Backend authority | Status | Tab wiring |
|---|---|---|---|---|
| AC-1 | Not in WIRED_PAGES | mock-badge.jsx | FIXED | `'accounting'` added |
| AC-2 | KPI tiles hardcoded | derived from live API responses | FIXED | live counters from batch/proforma/audit data |
| AC-3 | Tab A Purchase Ledger | `GET /api/v1/dashboard/batches` (routes_dashboard.py) | LIVE | `PzApi.listBatches()` |
| AC-4 | Tab B Sales/Proforma | `GET /api/v1/proforma/search` (routes_proforma.py) | LIVE | `PzApi.searchProformaDrafts()` |
| AC-5 | Tab C Client Ledger | `ledgers-page.jsx` (LedgersPage component) | LIVE | `<LedgersPage />` embedded |
| AC-6 | Tab D wFirma Sync | `GET /api/v1/wfirma/contractors/scan/status` + navigate | NAVIGATE | status card + navigate to `wfirma_setup` |
| AC-7 | Tab E Master Data | `/v2/master` (master-page.jsx) | NAVIGATE | navigate card to `master` |
| AC-8 | Tab F Audit Trail | `GET /api/v1/master/audit/` (routes_master.py) | LIVE | `PzApi.listMasterAudit()` |
| AC-9 | Supplier invoice nav slot | (no duplicate; existing route) | OUT | not a new control |
| WZ/PZ/PW/RW/MM | Wave-4 doc-register tabs | backend unverified | GATED | visible, R-Q3 honest gate, W4 badge |

Wireframe-Required Missing = **0** — criterion 10 PASS.

---

## Backend truth citations

| Tab | Endpoint | Route file | Method verified |
|---|---|---|---|
| Purchase Ledger | `GET /api/v1/dashboard/batches` | `routes_dashboard.py` | `PzApi.listBatches` (already in pz-api.js) |
| Sales/Proforma | `GET /api/v1/proforma/search` | `routes_proforma.py` | `PzApi.searchProformaDrafts` (already in pz-api.js) |
| Client Ledger | `GET /api/v1/ledgers/clients/{id}/invoice-ledger.json` | `routes_ledgers.py` | via `LedgersPage` component (ledgers-page.jsx) |
| wFirma Sync | `GET /api/v1/wfirma/contractors/scan/status` | `routes_wfirma_contractors.py:117` | `PzApi.getWfirmaContractorScanStatus` (added this session) |
| Audit Trail | `GET /api/v1/master/audit/` | `routes_master.py` | `PzApi.listMasterAudit` (already in pz-api.js) |
| Master Data | `/v2/master` slug | `master-page.jsx` | navigate (no duplicate API) |

---

## Contract supersession

**Old contract (Sprint-28):** targeted `accounting-hub-v2.html` (standalone HTML, V1 shell era).  
**New contract (Wave-3):** targets `accounting-hub.jsx` in Atlas Babel-JSX shell.

Contract test results: `pytest tests/test_accounting_hub_v2_contract.py` → **11/11 PASS**

Smoke suite: **63 passed, 1 skipped** (no regressions introduced).

---

## R-Q3 Honest UI — Wave-4 gated tabs

Per WIREFRAME_AUTHORITY.md §D: "Warehouse doc register | wire when doc APIs verified | Wave 4"

Wave-4 tabs (WZ / PZ / PW / RW / MM) are:
- Visible in the left rail with W4 badge
- Disabled (cursor: not-allowed; opacity: 0.45)
- Click → no action (not-allowed guard in handleSection)
- GatedDocTab renders: "BACKEND-REQUIRED · Wave 4" panel when somehow reached
- No capability hidden — Lesson M compliant

---

## No-duplicate verification

| Concern | Check | Result |
|---|---|---|
| wFirma Sync duplicate | Tab D navigates to `wfirma_setup` (Sprint 37, WIRED_PAGES) | PASS — no second wFirma mapping UI |
| Master Data duplicate | Tab E navigates to `master` (Sprint 38, WIRED_PAGES) | PASS — no second master table |
| Ledger duplicate | Tab C embeds `LedgersPage` (ledgers-page.jsx) as authority | PASS — no second ledger component |
| Doc-register duplicate | Wave-4 gated; warehouse doc APIs unverified | PASS — gated, not duplicated |

---

## Tree counts

- **Lines written:** 874 (accounting-hub.jsx)
- **Lines superseded:** 468 (old mock accounting-hub.jsx)
- **Net added:** ~406 lines
- **WIRED_PAGES count:** 19 → 20
- **pz-api.js Wave-3 block:** 1 method added (`getWfirmaContractorScanStatus`)
- **Contract tests:** 14 (Sprint-28) → 11 (Wave-3 V2 contract), all PASS
- **git status lines before session:** 42; **after session:** 44 (accounting-hub.jsx + mock-badge.jsx + pz-api.js + contract test + this record)
