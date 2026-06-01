# Atlas Campaign 2–11 — Running Evidence Log

**Branch:** feat/atlas-campaign-2-11  
**Base:** c09fdfa (origin/main post-#417 merge)  
**Started:** 2026-06-01  
**Invariants:** all wFirma write flags OFF · live_enabled OFF · frozen files untouched · no merge/deploy/C:\PZ

---

## Phase 0 — Base ✓

| Check | Result |
|---|---|
| origin/main HEAD | c09fdfa |
| docs/ATLAS_BUILD_CAMPAIGN.md | Present |
| docs/ATLAS_WORKFLOW_MAP.md | Present |
| Open PRs | 1 (#416 customs-identity, flag-gated OFF) |
| Tree | Clean |
| Stashes | 11 intact |

---

## Phase 10 — Master-data backfill (OPERATOR TASK)

### Before counts (read-only, 2026-06-01)

| Table | DB | Rows | Action needed |
|---|---|---|---|
| `company_profile` | master_data.sqlite | **0** | ⚠ POPULATE FIRST — empty = consignee on PDF still hardcoded |
| `product_local` | master_data.sqlite | 0 | Populate HS overrides + origin per product_code |
| `designs` | master_data.sqlite | 0 | Populate design family/collection/metal/HS |
| `customer_master` | customer_master.sqlite | 61 | Verify series, currency, ship-to, EORI |
| `suppliers` | suppliers.sqlite | 5 | Verify name/address/EORI for all active suppliers |
| `wfirma_customers` | wfirma.db | 4 | Verify wfirma_customer_id mapped for all active clients |
| `wfirma_products` | wfirma.db | 44 | Verify wfirma_product_id for all active product codes |
| `product_master` | reservation_queue.db | 57 | Verify composite key; run backfill for missing rows |
| `product_descriptions` | documents.db | 492 | Verify name_pl/description_pl locked for all EJL codes |

### Backfill checklist (operator, in order)

1. **company_profile (FIRST — unblocks PR #416 consignee identity)**
   - `PATCH /api/v1/settings/company-profile` with `legal_name`, `street`, `postal_city`, `nip`, `vat_eu`
   - Verify: `GET /api/v1/settings/company-profile` → `legal_name` non-empty

2. **supplier master** — verify/add name + address + EORI for each of the 5 suppliers
   - Check `GET /api/v1/suppliers/` — confirm `eori` populated for EU customs docs

3. **customer_master** — for each of the 61 clients:
   - `preferred_invoice_series_id` set (prevents B1 recovery dead-ends)
   - `eori` set for customs documentation
   - `preferred_payment_method` / `payment_terms_days` set for proforma defaults

4. **product_local overlays** — for each product_code that ships:
   - `hs_code_override` populated (prevents GAP 5 — HS from free-text PDF parse)
   - `origin_country` confirmed (most are "IN" — verify exceptions)

5. **product_master backfill** (use admin endpoint):
   - `POST /api/v1/admin/product-master/backfill?dry_run=true` → review
   - `POST /api/v1/admin/product-master/backfill?dry_run=false` → apply

6. **product_descriptions** — for each EJL-prefix product_code with `source=auto`:
   - Lock bilingual description: `PUT /api/v1/wfirma/products/{code}/description` with `source=manual`

### After counts (fill in after operator data entry)
*(Operator records before/after here)*

---

## Phase 2 — Soften three hard-stops (MED)

### INSPECTOR

Touch-points confirmed:
- `service/app/core/guards.py` — `guard_pz_requires_sad`, `guard_dhl_requires_email`  
- `service/app/api/routes_proforma.py` — `_check_proforma_export_prerequisites`, `missing_products` ValueError
- `service/app/api/routes_dhl_clearance.py` — `guard_dhl_requires_email` call site
- `service/app/api/routes_pz.py` — `guard_pz_requires_sad` call site

Plan:
1. Add `advisory_gates_enabled: bool = Field(default=False)` to `config.py`
2. Modify `guard_pz_requires_sad` + `guard_dhl_requires_email` in `guards.py` — when advisory mode ON, return advisory dict instead of raising
3. Modify `_check_proforma_export_prerequisites` in `routes_proforma.py` — advisory flag → treat PZ-before-proforma as warning not blocker
4. Modify `_build_proforma_request_from_draft` missing_products path → advisory warning not 400
5. Tests: each gate warns instead of blocks; carrier baseline 381/381
