# Mock Page Authority Audit

**Audit date:** 2026-06-06
**Source of truth:** `C:\PZ-verify` (verification clone)
**Scope:** Three mock pages — Master Data, Carriers, wFirma Mapping

---

## Domain Status Map

| Domain | Page | Status | Mock banner? | Backend authority |
|--------|------|--------|--------------|-------------------|
| Inbox | `inbox` | **LIVE** | No | GET /api/v1/inbox |
| Inventory | `inventory` | **LIVE** | No | Inventory state engine |
| DHL | `dhl` | **LIVE** | No | DHL projector + scan |
| Shipments | `shipments` | **LIVE** | No | GET /api/v1/dashboard/batches |
| Automation | `automation` | **LIVE** | No | AI bridge authority |
| Intelligence | `intelligence` | **LIVE** | No | Intelligence + invoice-learning |
| Documents | `documents` | **LIVE** | No | GET /api/v1/dashboard/batches |
| Proforma | `proforma` | **LIVE** | No | Proforma pipeline |
| Proforma Detail | `proforma_detail` | **LIVE** | No | Draft CRUD + wFirma lifecycle |
| Master Data | `master` | **MOCK** | Yes | **FULL CRUD EXISTS** |
| Carriers | `carriers` | **MOCK** | Yes | **PARTIAL — config CRUD exists, carrier API mgmt does not** |
| wFirma Mapping | `wfirma_setup` | **MOCK** | Yes | **FULL CRUD EXISTS** |

---

## 1. MASTER DATA — Authority Audit

### Current state
- File: `master-page.jsx`
- Data source: `const SEED = { ... }` — **100% hardcoded mock data**
- Every entity uses `React.useState(SEED)` — no API calls
- CRUD operations are local state mutations (handleSave, handleDelete) — never reach backend

### Backend routes that ALREADY EXIST

| Entity | List (GET) | Get one (GET) | Create/Upsert | Delete | Restore | Prefix |
|--------|-----------|---------------|---------------|--------|---------|--------|
| **Clients** | `GET /api/v1/customer-master/` | `GET /{contractor_id}` | `PUT /{contractor_id}` | `DELETE /{contractor_id}` | `POST /{id}/restore` | `/api/v1/customer-master` |
| **Suppliers** | `GET /api/v1/suppliers/` | `GET /{supplier_id}` | `POST /` + `PUT /{id}` | `DELETE /{supplier_id}` | `POST /{id}/restore` | `/api/v1/suppliers` |
| **Products** | `GET /api/v1/product-local/` | `GET /{product_code}` | `PUT /{product_code}` | `DELETE /{product_code}` | `POST /{code}/restore` | `/api/v1/product-local` |
| **Designs** | `GET /api/v1/designs/` | `GET /{design_code}` | `PUT /{design_code}` | `DELETE /{design_code}` | `POST /{code}/restore` | `/api/v1/designs` |
| **HS Codes** | `GET /api/v1/hs-codes/` | `GET /{hs_code}` | `PUT /{hs_code}` | `DELETE /{hs_code}` | `POST /{code}/restore` | `/api/v1/hs-codes` |
| **FX Rates** | `GET /api/v1/fx-rates/` | `GET /{fx_id}` | `POST /` + `PUT /{id}` | `DELETE /{fx_id}` | `POST /{id}/restore` | `/api/v1/fx-rates` |
| **VAT Rates** | `GET /api/v1/vat-config/` | `GET /{vat_id}` | `POST /` + `PUT /{id}` | `DELETE /{vat_id}` | `POST /{id}/restore` | `/api/v1/vat-config` |
| **Incoterms** | `GET /api/v1/incoterms/` | `GET /{code}` | `PUT /{code}` | `DELETE /{code}` | `POST /{code}/restore` | `/api/v1/incoterms` |
| **Units** | `GET /api/v1/units/` | `GET /{code}` | `PUT /{code}` | `DELETE /{code}` | `POST /{code}/restore` | `/api/v1/units` |
| **Carriers (config)** | `GET /api/v1/carriers-config/` | `GET /{carrier_code}` | `PUT /{carrier_code}` | `DELETE /{carrier_code}` | `POST /{code}/restore` | `/api/v1/carriers-config` |
| **Users** | `GET /api/v1/auth/users` | via list | — | — | — | `/api/v1/auth` |
| **Roles** | — (hardcoded ROLES list) | — | — | — | — | N/A |

Additional master data routes:
- `GET /api/v1/customer-master/sync-from-wfirma/preview` — preview wFirma sync
- `POST /api/v1/customer-master/sync-from-wfirma/apply` — apply wFirma customer sync
- `GET /api/v1/customer-master/dictionaries` — dictionary data
- `POST /api/v1/customer-master/dictionaries/refresh` — refresh dictionaries
- `GET /api/v1/suppliers/sync-from-wfirma/preview` — preview supplier sync
- `POST /api/v1/suppliers/sync-from-wfirma/apply` — apply supplier sync
- `GET /api/v1/master/audit/` — master data audit trail
- `GET /api/v1/settings/company-profile` — company profile (exporter identity)
- `PATCH /api/v1/settings/company-profile` — update company profile

### Wiring plan — what to change

1. **Replace `const SEED = {...}` with live API calls:**
   ```
   Clients:   PzApi → GET /api/v1/customer-master/
   Suppliers: PzApi → GET /api/v1/suppliers/
   Products:  PzApi → GET /api/v1/product-local/
   Designs:   PzApi → GET /api/v1/designs/
   HS Codes:  PzApi → GET /api/v1/hs-codes/
   FX Rates:  PzApi → GET /api/v1/fx-rates/
   VAT Rates: PzApi → GET /api/v1/vat-config/
   Incoterms: PzApi → GET /api/v1/incoterms/
   Units:     PzApi → GET /api/v1/units/
   Carriers:  PzApi → GET /api/v1/carriers-config/
   Users:     PzApi → GET /api/v1/auth/users
   Roles:     Static (ROLES constant from auth module, no CRUD)
   ```

2. **Replace `handleSave` with real PUT/POST calls:**
   - Upsert entities: PUT `/{code}` or `/{id}`
   - Create new: POST `/` (suppliers, fx-rates, vat-config) or PUT with new key (hs-codes, units, etc.)

3. **Replace `handleDelete` with real DELETE calls**

4. **Add `pz-api.js` functions for master data CRUD** (currently none exist)

5. **Replace mock counts** in nav sidebar with live counts from list endpoints

### Backend gaps for Master Data

| Entity | Gap | Notes |
|--------|-----|-------|
| **Users** | No create/update/delete via REST | Auth module has approve/reject/deactivate/set-role but no PUT for editing user details |
| **Roles** | No CRUD — hardcoded ROLES list in auth module | `ROLES = ["admin", "manager", "operator", "viewer"]` — not configurable via API |

### Verdict: **READY TO WIRE** (10 of 12 entities have full CRUD)

---

## 2. CARRIERS — Authority Audit

### Current state
- File: `carriers-page.jsx`
- Data source: `const CARRIERS = [...]` — **100% hardcoded mock data**
- 6 mock carriers: DHL, FedEx, UPS, GLS, InPost, DPD
- All write buttons disabled with API chip tooltips
- Fake credentials, fake ping times, fake quota counters

### Backend routes that ALREADY EXIST

| Route | Method | Purpose | Exists? |
|-------|--------|---------|---------|
| `/api/v1/carriers-config/` | GET | List carrier configurations | **YES** |
| `/api/v1/carriers-config/{carrier_code}` | GET | Get one carrier config | **YES** |
| `/api/v1/carriers-config/{carrier_code}` | PUT | Upsert carrier config | **YES** |
| `/api/v1/carriers-config/{carrier_code}` | DELETE | Soft-delete carrier config | **YES** |
| `/api/v1/carriers-config/{carrier_code}/restore` | POST | Restore deleted | **YES** |
| `/api/v1/carrier/{batch_id}/shipment` | POST | Create DHL shipment | **YES** |
| `/api/v1/carrier/{batch_id}/shipment` | GET | Get shipment state | **YES** |
| `/api/v1/carrier/{batch_id}/label-package` | POST | Generate customs package | **YES** |
| `/api/v1/carrier/status` | GET | Carrier API status | **YES** |
| `/api/v1/carrier/shadow/log` | GET | Shadow/audit log | **YES** |
| `/api/v1/carrier/webhook/...` | POST | Webhook receiver | **YES** |
| `/api/v1/customer-master/{id}/carrier-accounts` | GET/POST/PUT/DELETE | Per-client carrier accounts | **YES** |

### Backend routes that DO NOT EXIST

| Route | Purpose | Priority |
|-------|---------|----------|
| `GET /api/v1/carriers` | List connected carrier API accounts (sessions, OAuth state) | HIGH |
| `POST /api/v1/carriers/{id}/test` | Ping/test carrier API connection | MEDIUM |
| `POST /api/v1/carriers/{id}/credentials` | Rotate/update API credentials | HIGH |
| `POST /api/v1/carriers/{id}/disconnect` | Revoke carrier session | LOW |
| `POST /api/v1/carriers/{id}/oauth/start` | Begin OAuth2 flow (FedEx, UPS) | LOW |
| `GET /api/v1/carriers/{id}/webhooks` | Webhook health status | LOW |
| `GET /api/v1/carriers/{id}/services` | Supported services/rate plans | LOW |
| `GET /api/v1/carriers/audit` | Credential audit log | MEDIUM |

### What CAN be wired now

1. **Carrier config CRUD** — replace mock CARRIERS array with `GET /api/v1/carriers-config/`
2. **DHL status** — replace mock DHL ping data with `GET /api/v1/carrier/status`
3. **Per-client carrier accounts** — wire to `GET /api/v1/customer-master/{id}/carrier-accounts`

### What CANNOT be wired

- FedEx, UPS, GLS, InPost, DPD API connections — no backend integration exists
- OAuth flow for FedEx/UPS — no routes
- Credential rotation — no routes
- Multi-carrier webhook management — only DHL webhook exists

### Verdict: **PARTIALLY READY** — carrier config CRUD exists, but carrier API management (OAuth, credentials, ping, multi-carrier) does not. DHL-only data can be shown live.

---

## 3. wFIRMA MAPPING — Authority Audit

### Current state
- File: `ops-cell.jsx` → `WfirmaMappingPage` component
- Data source: hardcoded `customers` and `products` arrays
- References real endpoint names in UI (`GET /api/v1/wfirma/capabilities`, etc.)
- Capability strip uses hardcoded booleans

### Backend routes that ALREADY EXIST

| Route | Method | Purpose | Exists? |
|-------|--------|---------|---------|
| `/api/v1/wfirma/capabilities` | GET | wFirma capability probe | **YES** |
| `/api/v1/wfirma/customers` | GET | List customer mappings | **YES** |
| `/api/v1/wfirma/customers/{client_name}` | PUT | Update customer mapping | **YES** |
| `/api/v1/wfirma/products` | GET | List product mappings | **YES** |
| `/api/v1/wfirma/products/{product_code}` | PUT | Update product mapping | **YES** |
| `/api/v1/wfirma/contractors/search` | GET | Search wFirma contractors | **YES** |
| `/api/v1/wfirma/goods/search` | GET | Search wFirma goods | **YES** |
| `/api/v1/wfirma/goods/search-and-compare` | GET | Search + compare with local | **YES** |
| `/api/v1/wfirma/goods/search-bulk` | POST | Bulk goods search | **YES** |
| `/api/v1/wfirma/goods/create-from-product-code/{code}` | POST | Create wFirma good from local | **YES** |
| `/api/v1/wfirma/goods/adopt/{product_code}` | POST | Adopt existing wFirma good | **YES** |
| `/api/v1/wfirma/goods/update-and-adopt/{product_code}` | POST | Update + adopt | **YES** |
| `/api/v1/wfirma/goods/create-and-adopt/{product_code}` | POST | Create + adopt | **YES** |
| `/api/v1/wfirma/goods/auto-register-preview/{batch_id}` | POST | Preview auto-register | **YES** |
| `/api/v1/wfirma/goods/auto-register/{batch_id}` | POST | Execute auto-register | **YES** |
| `/api/v1/wfirma/customers/auto-create-from-name` | POST | Auto-create customer | **YES** |
| `/api/v1/wfirma/customers/auto-resolve-preview/{batch_id}` | POST | Preview auto-resolve | **YES** |
| `/api/v1/wfirma/goods/refresh-name-from-block/{product_code}` | POST | Refresh name | **YES** |
| `/api/v1/wfirma/customers/sync-preview` | GET | Preview customer sync | **YES** |
| `/api/v1/wfirma/customers/sync` | POST | Execute customer sync | **YES** |
| `/api/v1/wfirma/customers/sync-from-wfirma/preview` | GET | Preview reverse sync | **YES** |
| `/api/v1/wfirma/customers/sync-from-wfirma/apply` | POST | Apply reverse sync | **YES** |
| `/api/v1/wfirma/shipment/{batch_id}/setup-detail` | GET | Shipment setup detail | **YES** |
| `/api/v1/wfirma/customers/create-internal-test` | POST | Test customer creation | **YES** |

### Backend gaps for wFirma Mapping

**None.** Every function the UI page references has a real backend route.

### Wiring plan

1. **Replace hardcoded `customers` array** with `GET /api/v1/wfirma/customers`
2. **Replace hardcoded `products` array** with `GET /api/v1/wfirma/products`
3. **Replace hardcoded capability strip** with `GET /api/v1/wfirma/capabilities`
4. **Wire Map/Edit buttons** to `PUT /api/v1/wfirma/customers/{name}` and `PUT /api/v1/wfirma/products/{code}`
5. **Wire diagnostic button** to `GET /api/v1/wfirma/goods/search-and-compare` or bulk search
6. **Add `pz-api.js` functions** for wFirma capability, customer list, product list

### Verdict: **FULLY READY TO WIRE** — zero backend gaps

---

## 4. Wiring Priority (recommended order)

| Priority | Page | Effort | Reason |
|----------|------|--------|--------|
| **1** | wFirma Mapping | **LOW** | Zero backend gaps. Replace 3 hardcoded arrays with 3 GET calls. Capability strip is a single GET. |
| **2** | Master Data | **MEDIUM** | Full CRUD exists for 10/12 entities. Need `pz-api.js` functions for 10 entity types. Users/Roles have partial gaps. |
| **3** | Carriers | **HIGH** | Config CRUD exists. But the page's primary purpose (carrier API management, OAuth, credentials, multi-carrier) has no backend. DHL-only can be partially wired. |

### pz-api.js functions needed

```javascript
// wFirma Mapping (priority 1)
getWfirmaCapabilities: ()       => _get(`${BASE}/wfirma/capabilities`),
getWfirmaCustomers: ()          => _get(`${BASE}/wfirma/customers`),
getWfirmaProducts: ()           => _get(`${BASE}/wfirma/products`),
putWfirmaCustomer: (name, body) => _put(`${BASE}/wfirma/customers/${enc(name)}`, body),
putWfirmaProduct: (code, body)  => _put(`${BASE}/wfirma/products/${enc(code)}`, body),

// Master Data (priority 2)
getCustomers: ()                => _get(`${BASE}/customer-master/`),
getSuppliers: ()                => _get(`${BASE}/suppliers/`),
getProducts: ()                 => _get(`${BASE}/product-local/`),
getDesigns: ()                  => _get(`${BASE}/designs/`),
getHsCodes: ()                  => _get(`${BASE}/hs-codes/`),
getFxRates: ()                  => _get(`${BASE}/fx-rates/`),
getVatConfig: ()                => _get(`${BASE}/vat-config/`),
getIncoterms: ()                => _get(`${BASE}/incoterms/`),
getUnits: ()                    => _get(`${BASE}/units/`),
getCarriersConfig: ()           => _get(`${BASE}/carriers-config/`),
getUsers: ()                    => _get(`${BASE}/auth/users`),

// Carriers (priority 3)
getCarrierStatus: ()            => _get(`${BASE}/carrier/status`),
```

---

## 5. Mock Banner Control

The WIRED_PAGES array in `mock-badge.jsx` controls which pages show the MOCK banner:

```javascript
const WIRED_PAGES = ['proforma', 'inbox', 'inventory', 'dhl', 'shipments',
                     'automation', 'intelligence', 'documents', 'proforma_detail'];
```

When a page is wired, add its page key to this array:
- `'wfirma_setup'` — after wFirma Mapping is wired
- `'master'` — after Master Data is wired
- `'carriers'` — after Carriers is wired (or partially wired with disclosure)

**Rule:** A page is wired when its primary data comes from a live GET endpoint, not a hardcoded array. Write buttons may still be disabled if backend write authority is missing — that is honest state, not mock.
