# Master Data Campaign — Live Task Queue

Mirror of `tasks/master-data-campaign.md`. Updated by execution agents as work progresses. Most-recent batch summary at the top.

---

## CURRENT STATE

- **Campaign:** MDC-2026-05 — Master Data Completion
- **Active batch:** B0 — **CLOSED 2026-05-16** · B1 — **COMPLETE**
- **Next batch (when greenlit):** B2 (KycModal cosmetic + CM-tab rationalisation)
- **Blocker for next batch:** none — B2 is `AUTO_SAFE` and ready

---

## QUEUE

| Batch | Status | Tasks | Classification | Notes |
|---|---|---|---|---|
| B0 — CM 422 save fix | ✅ DONE | MDC-001 | AUTO_SAFE | PR #98 **MERGED** SHA `b030382` 2026-05-16 00:20Z; deployed; 4 smoke tests green |
| B1 — Campaign controller | ✅ DONE | MDC-002 | AUTO_SAFE | this file + `master-data-campaign.md` + `lessons.md` |
| B2 — KycModal cosmetic | ⏸ QUEUED | MDC-010 → 014 | AUTO_SAFE | Depends on B0 deploy |
| B3 — Users + Roles wiring | ⏸ QUEUED | MDC-020, 021, 022 | NEEDS_SECURITY_REVIEW | Depends on B2 merge |
| B4 — Suppliers | ⏸ QUEUED | MDC-030 → 033 | NEEDS_SCHEMA_APPROVAL | New SQLite + routes + UI |
| B5 — HS + Units + Product-local | ⏸ QUEUED | MDC-040 → 043 | NEEDS_SCHEMA_APPROVAL | 3 new tables |
| B6 — Design Master | ⏸ QUEUED | MDC-050 → 052 | NEEDS_SCHEMA_APPROVAL + NEEDS_SECURITY_REVIEW | Read-only consumer guarantee required |
| B7 — Incoterms + VAT | ⏸ QUEUED | MDC-060, 061 | NEEDS_SCHEMA_APPROVAL + NEEDS_SECURITY_REVIEW | VAT write protection mandatory |
| B8 — FX rates | ⏸ PARTIAL | MDC-070 (read-only) ; MDC-071 **FORBIDDEN_NOW** | NEEDS_SECURITY_REVIEW | Override layer blocked by hard rules |
| B9 — Carrier config | ⏸ QUEUED | MDC-080 | NEEDS_SECURITY_REVIEW + NEEDS_SCHEMA_APPROVAL | UX agent must rule on naming vs Carriers nav |
| B10 — wFirma sync visibility | ⏸ READY | MDC-090, 091 | AUTO_SAFE | Independent of B3-B9; can run after B2 |
| B11 — Final audit | ⏸ QUEUED | MDC-100 → 103 | AUTO_SAFE | Last batch |

---

## TASK DETAIL — B2 (next when greenlit)

### MDC-010 — KycModal tabs: clear pending flag
- **File:** `service/app/static/dashboard.html` @ L2342
- **Change:** Remove `pending: true` from `kyc` and `invoices` tab definitions in `KYC_TABS`
- **Tests to update:** `test_dashboard_master_design.py` "pending tabs" assertions
- **Risk:** LOW
- **Stop:** source-grep tests green; browser smoke shows tabs are clickable

### MDC-011 — KycModal Invoices tab body
- **File:** `service/app/static/dashboard.html` (Invoices tab render branch in ClientKycModal)
- **Fields to bind:** `preferred_proforma_series_id`, `preferred_invoice_series_id`, `vat_mode`, `default_currency`, `default_language_id`, `payment_terms_days`
- **API:** existing `PUT /api/v1/customer-master/{cid}`
- **Tests:** add source-grep for each field + 2 PUT round-trip tests in `test_customer_master.py`
- **Risk:** LOW

### MDC-012 — KycModal KYC tab body
- **File:** `service/app/static/dashboard.html` (KYC tab render branch)
- **Fields:** `kyc_status`, `kyc_approved_on`, `kyc_expiry`, `beneficial_owner`, `owner_id_type`, `owner_id_number`, `aml_risk_rating`, `pep_check_result`, `compliance_notes`
- **API:** existing PUT CM
- **Tests:** source-grep + round-trip
- **Risk:** LOW

### MDC-013 — "Open full profile" button on CM-tab row
- **File:** `service/app/static/dashboard.html` (`MasterDataPage` CM-row actions)
- **Change:** add button that opens `ClientKycModal` directly for the contractor's wFirma client (find by `bill_to_contractor_id` → `customers.items.find(c.wfirma_customer_id === ...)`)
- **Risk:** LOW
- **Tests:** source-grep new testid

### MDC-014 — Verify disabled-with-reason invariants on Clients tab
- Confirm `+ New Client` retains tooltip "Create client in wFirma directly"
- No change expected; just guard

### B2 acceptance criteria
- All B2 source-grep tests green
- `test_customer_master.py` ≥ 84/84 (current 82 + 2 round-trips)
- `test_dashboard_master_design.py` green with updated "pending tabs" expectations
- PZ regression 160/160
- Browser smoke: open KycModal, switch through all 6 tabs, save Invoices and KYC tabs without 422

---

## LATEST BATCH SUMMARY

### B0 — CM 422 save fix CLOSED (2026-05-16)
- **PR:** #98 `fix/masterdata-save-validation`
- **Merged SHA:** `b030382` at 2026-05-16 00:20Z
- **Files deployed:** `routes_customer_master.py` (13 971 B), `customer_master_db.py` (32 649 B), `dashboard.html` (1 335 559 B) → `C:\PZ\app\`
- **Service state:** RUNNING (port 47213)
- **Health:** local 200 · public 200 (pz.estrellajewels.eu) · carrier gate `pending`
- **Tests:** 82/82 customer_master · 160/160 PZ regression
- **Smoke (4 API cases):**
  1. PUT all-blank optional fields → HTTP 200, stored as nulls ✅
  2. PUT `kuke_approved=true` + blank `kuke_limit` → HTTP 422 (correct validation still fires) ✅
  3. GET round-trip → HTTP 200 ✅
  4. PUT legacy payload that was 422 pre-fix → HTTP 200 ✅
- **Logs:** clean (only Uvicorn startup messages)
- **Artifact:** test record `BATCH0-SMOKE-TEST` left in `customer_master.sqlite` (no DELETE endpoint exists; bill_to_name="Batch 0 Smoke Test" — clearly labelled, low risk)

### B1 — Planning (2026-05-16)
**Files created:**
- `tasks/master-data-campaign.md` (controller; 11 sections)
- `tasks/todo.md` (this file)
- `tasks/lessons.md` (lessons log)

**Task count:** 30 MDC tasks across 12 batches
