# Sprint 37 — wFirma Mapping (MOCK → authority-backed)

**Campaign:** Atlas-V2 (V2 shell wiring)
**Sprint:** 37 — wFirma Mapping
**Predecessor:** Sprint 36 Phase 2 (Proforma Toolbar) — PR #475 OPEN
**Branch (to create):** `feat/sprint37-wfirma-mapping-wiring`
**Base:** `origin/main` (after PR #475 merges)
**Target file:** `service/app/static/v2/ops-cell.jsx` → `WfirmaMappingPage` component
**New test file:** `service/tests/test_sprint37_wfirma_mapping_wiring.py`
**Authoring audit:** Mock Page Authority Audit (2026-06-06). wFirma Mapping selected as Sprint 37 over Master Data and Carriers. Evidence: 25+ verified backend endpoints, zero gaps, lowest effort, highest MOCK-elimination ROI.

---

## 1. Objective

Replace the hardcoded mock data in `WfirmaMappingPage` (`page === 'wfirma_setup'`) with **live, authority-backed rendering** from existing wFirma capability, customer, and product endpoints. Add `'wfirma_setup'` to `WIRED_PAGES`. Remove MOCK banner.

This is the **fastest MOCK page elimination** in the system — the backend already exists with zero gaps.

```
Existing wFirma authority  →  live renderer  →  browser verification  →  static deploy
(NOT: new backend → new authority → new workflow)
```

---

## 2. Authority Boundary

```
OWNS (this page):  read-only rendering of wFirma capabilities,
                   customer mapping list, product mapping list,
                   mapping counts, sync status.

ALLOWED WRITES:    PUT customer mapping, PUT product mapping
                   (with operator-initiated action only — no auto-save).

NEVER:             Create wFirma goods without operator action ·
                   Auto-register goods · Auto-resolve customers ·
                   Sync without preview · any wFirma mutation without
                   explicit operator click + confirmation.
```

**Authority owner (backend, unchanged):** `routes_wfirma_capabilities.py`
+ `wfirma_goods_service.py` + `wfirma_customer_service.py`. The frontend
is a read-and-map renderer; the backend remains the sole authority for
all wFirma integration logic.

---

## 3. The ONLY endpoints this page may consume

### Read endpoints (auto-load on mount)

| Endpoint | Source file | Purpose |
|---|---|---|
| `GET /api/v1/wfirma/capabilities` | routes_wfirma_capabilities.py | Capability strip (connected/invoice/goods/customer/warehouse) |
| `GET /api/v1/wfirma/customers` | routes_wfirma_capabilities.py | Customer mapping list with wFirma contractor IDs |
| `GET /api/v1/wfirma/products` | routes_wfirma_capabilities.py | Product mapping list with wFirma good IDs |

### Write endpoints (operator-initiated only)

| Endpoint | Source file | Purpose | Guard |
|---|---|---|---|
| `PUT /api/v1/wfirma/customers/{client_name}` | routes_wfirma_capabilities.py | Update customer mapping | Operator click + confirm |
| `PUT /api/v1/wfirma/products/{product_code}` | routes_wfirma_capabilities.py | Update product mapping | Operator click + confirm |

### Reference endpoints (for search/adopt modals — operator-initiated only)

| Endpoint | Source file | Purpose |
|---|---|---|
| `GET /api/v1/wfirma/contractors/search?q=` | routes_wfirma_capabilities.py | Search wFirma contractors |
| `GET /api/v1/wfirma/goods/search?q=` | routes_wfirma_capabilities.py | Search wFirma goods |
| `GET /api/v1/wfirma/goods/search-and-compare?q=` | routes_wfirma_capabilities.py | Search + compare with local product |

### Forbidden endpoints (exist but NOT for this sprint)

| Endpoint | Why forbidden |
|---|---|
| `POST /wfirma/goods/create-from-product-code/{code}` | Creates wFirma good — write authority, defer |
| `POST /wfirma/goods/adopt/{product_code}` | Adopts existing wFirma good — write authority, defer |
| `POST /wfirma/goods/auto-register/{batch_id}` | Bulk auto-register — high-risk batch write, defer |
| `POST /wfirma/customers/sync` | Execute customer sync — batch write, defer |
| `POST /wfirma/customers/auto-create-from-name` | Auto-create customer — write authority, defer |

---

## 4. What to change

### 4a. `pz-api.js` — add wFirma mapping functions

```javascript
// wFirma Mapping (Sprint 37)
getWfirmaCapabilities: ()       => _get(`${BASE}/wfirma/capabilities`),
getWfirmaCustomers: ()          => _get(`${BASE}/wfirma/customers`),
getWfirmaProducts: ()           => _get(`${BASE}/wfirma/products`),
putWfirmaCustomer: (name, body) => _put(`${BASE}/wfirma/customers/${enc(name)}`, body),
putWfirmaProduct: (code, body)  => _put(`${BASE}/wfirma/products/${enc(code)}`, body),
searchWfirmaContractors: (q)    => _get(`${BASE}/wfirma/contractors/search?q=${enc(q)}`),
searchWfirmaGoods: (q)          => _get(`${BASE}/wfirma/goods/search?q=${enc(q)}`),
```

### 4b. `ops-cell.jsx` → `WfirmaMappingPage`

1. **Remove** hardcoded `customers` and `products` arrays
2. **Add** `React.useEffect` on mount: fetch `PzApi.getWfirmaCapabilities()`, `PzApi.getWfirmaCustomers()`, `PzApi.getWfirmaProducts()`
3. **Replace** capability strip booleans with real `capabilities` response data
4. **Replace** customer list with real customer mapping data
5. **Replace** product list with real product mapping data
6. **Replace** mock counts with `customers.length` and `products.length` from live data
7. **Keep** role guards on write buttons
8. **Keep** mapping action buttons (but wire to real PUT endpoints)

### 4c. `mock-badge.jsx`

Add `'wfirma_setup'` to `WIRED_PAGES` array.

### 4d. Source-grep regression tests

Create `test_sprint37_wfirma_mapping_wiring.py` with:
- No hardcoded customer/product arrays in `ops-cell.jsx`
- `PzApi.getWfirmaCapabilities` referenced in `ops-cell.jsx`
- `PzApi.getWfirmaCustomers` referenced in `ops-cell.jsx`
- `PzApi.getWfirmaProducts` referenced in `ops-cell.jsx`
- `'wfirma_setup'` in WIRED_PAGES
- No mock banner on wfirma_setup page
- `pz-api.js` contains all 5+ wFirma mapping functions
- Write buttons require operator confirmation (no auto-save)

---

## 5. Success criteria

1. MOCK banner removed from wFirma Mapping page
2. `'wfirma_setup'` added to WIRED_PAGES (10th entry)
3. Capability strip shows real wFirma connection state
4. Customer list shows real customer mappings (or "0 customers" if empty)
5. Product list shows real product mappings (or "0 products" if empty)
6. No hardcoded arrays remain in `WfirmaMappingPage`
7. All source-grep regression tests pass
8. Browser smoke: no console errors, API calls return 200, real data rendered
9. No forbidden (write-heavy) endpoints consumed

---

## 6. `/run` prompt

Copy this into a fresh Claude Code session to start Sprint 37:

```
Sprint 37: wFirma Mapping — convert from MOCK to authority-backed.

Read `.claude/campaigns/atlas-v2/sprint-37-wfirma-mapping.md` first.

Target: `service/app/static/v2/ops-cell.jsx` → `WfirmaMappingPage`.

Steps:
1. Read `ops-cell.jsx` to find all hardcoded data (customers, products, capabilities)
2. Add wFirma mapping functions to `pz-api.js` (getWfirmaCapabilities, getWfirmaCustomers, getWfirmaProducts, putWfirmaCustomer, putWfirmaProduct, searchWfirmaContractors, searchWfirmaGoods)
3. Replace hardcoded arrays with useEffect → PzApi calls
4. Replace capability strip with real capabilities data
5. Add 'wfirma_setup' to WIRED_PAGES in mock-badge.jsx
6. Create test_sprint37_wfirma_mapping_wiring.py with source-grep regression tests
7. Run tests: pytest service/tests/test_sprint37_wfirma_mapping_wiring.py -v
8. Browser smoke: navigate to /v2/wfirma_setup, verify no MOCK banner, verify real data, check console
9. Commit and push

Safety constraints:
- Do not call any POST endpoint (no goods creation, no sync, no auto-register)
- Do not auto-save — every write requires operator click + confirmation
- Do not remove any UI elements — replace data source only
- Do not modify backend routes
```

---

## 7. Anti-drift checklist (read before PR)

- [ ] No hardcoded arrays remain in WfirmaMappingPage
- [ ] No `const customers = [` or `const products = [` in ops-cell.jsx
- [ ] WIRED_PAGES includes 'wfirma_setup'
- [ ] pz-api.js has getWfirmaCapabilities, getWfirmaCustomers, getWfirmaProducts
- [ ] No forbidden endpoints consumed (no auto-register, no sync, no create)
- [ ] Write buttons still guarded (no auto-save)
- [ ] Source-grep tests pass
- [ ] Browser smoke passes (no MOCK, no console errors, real data)
