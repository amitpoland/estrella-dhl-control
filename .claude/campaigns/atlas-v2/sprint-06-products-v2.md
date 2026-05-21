# Sprint 06 — Products V2

**Campaign:** Atlas-V2  
**Sprint:** 06 of 13  
**Branch:** `atlas-v2/sprint-06-products-v2`  
**Dependency:** Sprint 05 merged  
**New file:** `service/app/static/products-v2.html`  
**URL:** `/dashboard/products-v2.html`

---

## Authority Boundary

```
OWNS:  product authority: SKU → wFirma product_id mapping,
       Polish product name, VAT rate, unit, sync_status display,
       "Save Product Mapping" write (explicit click only),
       product list with search/filter, unmapped product highlighting
NEVER: customer mapping, proforma drafts, PZ lifecycle,
       DHL, warehouse, VAT calculation (display only), invoice creation
```

---

## Page Purpose

The product authority management page. Operators map internal SKU codes to
wFirma product IDs, set Polish names and VAT rates. This is the source of
truth for the product bridge — what `pz-components.js`'s `ProductAuthorityRow`
reads. Build this before PZ V2 (Sprint 07) since PZ gates depend on product mapping.

---

## APIs This Page Consumes

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `GET /api/v1/wfirma/products` | Read | List product mappings |
| `GET /api/v1/wfirma/products/{code}` | Read | Single product detail |
| `PUT /api/v1/wfirma/products/{code}` | Write | Save product mapping |
| `GET /api/v1/wfirma/product-options` | Read | wFirma product lookup for mapping dropdown |

Check if these endpoints exist. If not, `backend-api` must add them as thin
read-through wrappers over `wfirma_db.get_product` / `wfirma_db.get_products_batch`.

---

## Write Safety Rules

- "Save Product Mapping" is the only write button
- No auto-save on blur or dropdown change
- VAT rate changes show "This affects proforma VAT calculations" warning before save
- No new wFirma write flags

---

## Mandatory Agents

| Order | `subagent_type` | Purpose |
|-------|-----------------|---------|
| 1 | `chief-orchestrator` | Routing |
| 2 | `system-architect` | Verify product bridge API exists |
| 3 | `gap-detection` | Missing product endpoints |
| 4 | `reviewer-challenge` | Attack any VAT calc changes, any write flag |
| 5 | `backend-api` | Add product mapping endpoints if missing |
| 6 | `backend-safety-reviewer` | Review backend changes |
| 7 | `frontend-ui` | Build products-v2.html |
| 8 | `frontend-flow-reviewer` | Review |
| 9 | `testing-verification` | Tests |
| 10 | `test-coverage-reviewer` | Review |
| 11 | `gap-hunter` | Cross-phase |
| 12 | `browser-verifier` | Open page, test list + mapping save |
| 13 | `integration-boundary` | API wiring |
| 14 | `git-workflow` + `pr-author` | Commit + PR |

---

## Test Baseline

```bash
make verify                 # 160/160
cd service && python3 -m pytest tests/test_proforma_v2_contract.py -q  # 44/44
cd service && python3 -m pytest tests/test_carrier_*.py -q             # 366/366
```

---

## Acceptance Criteria

1. Product list loads with search — all known product codes shown
2. Unmapped products highlighted (StatusDot warn)
3. Click product → detail with wFirma product dropdown
4. Select wFirma product → "Save Product Mapping" Btn; fires PUT; success Toast
5. VAT rate change shows warning before save
6. Filter by: All / Mapped / Unmapped
7. All interactive elements have `data-testid`
8. No new wFirma write flags
9. Rollback: remove file; no restart needed

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 06 — Products V2
Branch: atlas-v2/sprint-06-products-v2 (create from origin/main, Sprint 05 must be merged)

STACK CONSTRAINTS — mandatory, read before any UI work:
1. Read `.claude/skills/frontend-design.md` BEFORE touching any HTML/JS
2. `.claude/skills/ui-ux-pro-max` is supplemental only — read `EJ_OVERRIDES.md` first
3. Stack: Vanilla HTML + Babel JSX. NO Vite. NO TypeScript. NO Tailwind. NO bundler.
4. Pattern file: service/app/static/proforma-v2.html
5. Shared layer: window.EstrellaShared, window.PzApi, window.PzState, window.PzComponents
6. CSS: custom properties only. Zero hardcoded hex.

TASK:
Create service/app/static/products-v2.html — product authority management page.
URL: /dashboard/products-v2.html

AUTHORITY:
OWNS: SKU → wFirma product_id mapping, Polish name, VAT rate, unit, sync_status
NEVER: customer mapping, proforma, PZ, DHL, VAT calculation (display only)

WRITE SAFETY:
- "Save Product Mapping" is the only write button — no auto-save
- VAT rate change must show "This affects proforma VAT calculations" warning before saving

APIs (check if exist, have backend-api add if missing):
- GET /api/v1/wfirma/products — list mappings
- GET /api/v1/wfirma/products/{code} — detail
- PUT /api/v1/wfirma/products/{code} — save mapping
- GET /api/v1/wfirma/product-options — dropdown options

MANDATORY AGENT SEQUENCE:
1. system-architect — verify product bridge API
2. gap-detection
3. reviewer-challenge — attack any VAT calc change
4. backend-api — add endpoints if missing (backend-safety-reviewer reviews)
5. frontend-ui — build products-v2.html
6. frontend-flow-reviewer
7. testing-verification
8. test-coverage-reviewer
9. gap-hunter
10. browser-verifier
11. integration-boundary
12. git-workflow + pr-author

TEST BASELINE:
- make verify → 160/160
- tests/test_proforma_v2_contract.py → 44/44
- tests/test_carrier_*.py → 366/366

End with /deploy after PR merges.
```
