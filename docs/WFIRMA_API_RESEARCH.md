# wFirma API — Research Report

**Research date:** 2026-04-27  
**Status:** Pre-integration research — NO API calls made to production

---

## 1. Authentication

### Method: API Key (3 keys required)

| Key | Source | Notes |
|-----|--------|-------|
| `accessKey` | wFirma → Ustawienia → Aplikacje → Klucze API | Permanent once created |
| `secretKey` | wFirma → Ustawienia → Aplikacje → Klucze API | **Shown ONCE — copy immediately** |
| `appKey` | Provided individually by wFirma.pl per registered application | Must be requested from wFirma support |
| `companyId` | wFirma account URL or settings | Required if managing multiple companies |

### Setup Location (Polish UI)
```
Ustawienia → Bezpieczeństwo → Aplikacje → Klucze API
→ Kliknij "Dodaj" → Zapisz accessKey + secretKey natychmiast
```

### Auth Header Format (inferred from SDKs)
```http
POST https://api2.wfirma.pl/{module}/{action}
accessKey: your-access-key
secretKey: your-secret-key
appKey: your-app-key
Content-Type: application/json
```

### Confirmed by
- `dbojdo/wFirma` PHP SDK: `ApiKeysAuth('access-key', 'secret-key', 'app-key', $companyId)`
- Fynode docs: Access key + Secret key + Company ID pattern
- wFirma forum posts and partner documentation

### Deprecated: Basic Auth (login + password)
- **DO NOT USE** — officially deprecated per dbojdo/wFirma SDK
- Marked as "will not be supported anymore by wFirma"

### KSeF Authorization (separate concern)
- KSeF permissions are NOT inherited from the main administrator
- Each API user must have individual KSeF certificate/token configured
- KSeF module requires separate activation in wFirma account
- Invoices created via API are **immediately submitted to KSeF** — no draft stage via API

---

## 2. API Base URL and Request Pattern

### Base URLs
```
https://api2.wfirma.pl/     ← current (confirmed)
https://api.wfirma.pl/      ← legacy
```

### Endpoint Pattern
```
POST https://api2.wfirma.pl/{module}/{action}
```

### Standard Actions (per module)
| Action | Description |
|--------|-------------|
| `add`  | Create new record |
| `edit` | Modify existing record |
| `get`  | Get single record by ID |
| `find` | Query/list records with filters |
| `delete` | Remove record |
| `count` | Count matching records |

### URL Parameters
```
?inputFormat=json&outputFormat=json
```

### Request Body Structure (envelope pattern)
```json
{
  "api": {
    "{module}": {
      "{singular_entity}": {
        "field1": "value1",
        "field2": "value2"
      }
    }
  }
}
```

### Find/Query Request with Conditions
```json
{
  "api": {
    "invoices": {
      "parameters": {
        "conditions": {
          "condition": [
            {
              "field": "paymentmethod",
              "operator": "eq",
              "value": "transfer"
            }
          ]
        },
        "page": { "start": 0, "limit": 20 },
        "order": [
          { "field": "id", "order": "desc" }
        ]
      }
    }
  }
}
```

### Filter Operators Available
`eq`, `ne`, `gt`, `lt`, `ge`, `le`, `like`, `not like`, `in`

### Response Structure
```json
{
  "status": {
    "code": "OK"
  },
  "{module}": [
    {
      "{singular_entity}": {
        "id": "12345",
        "field1": "value"
      }
    }
  ]
}
```

---

## 3. Confirmed Modules (all SDKs cross-referenced)

### Tier 1 — Fully Confirmed (multiple SDK implementations)

| Module | Endpoints | Notes |
|--------|-----------|-------|
| `invoices` | add, edit, delete, find, get, count, fiscalise, unfiscalise, download, send | Full KSeF integration |
| `contractors` | add, edit, delete, find, get, count | Supplier/customer master data |
| `payments` | add, edit, delete, find, get | Payment records |
| `goods` | add, edit, delete, find, get | Products/warehouse goods catalog |
| `expenses` | find, get | Cost/purchase documents (limited write support) |
| `series` | add, edit, delete, find, get, count | Document numbering series |
| `notes` | add, edit, delete, find, get, count | Internal notes |
| `tags` | add, edit, delete, find, get, count | Record tagging |
| `webhooks` | find, add, delete | Event push notifications |
| `vat_codes` | find, get, count | VAT rate codes |
| `company_accounts` | find, get, count | Bank account records |
| `payment_cashboxes` | find, get | Cash register entries |
| `users` | find, get | User management |
| `warehouses` | find, get | Warehouse master data |

### Tier 2 — Partially Confirmed (evidence from Python client + search)

| Module | Endpoints | Confidence | Notes |
|--------|-----------|------------|-------|
| `warehousedocuments` | add, find, get, edit, delete | **MEDIUM — contradictory evidence** | See critical note below |
| `invoicecontents` | find, get | MEDIUM | Line items of invoices |
| `invoice_deliveries` | add, delete, find, get | MEDIUM | Delivery info on invoices |
| `declaration_countries` | find, get | LOW | Declaration reference data |

---

## 4. CRITICAL FINDING — PZ Warehouse Document API Support

### Evidence FOR (warehousedocuments API exists):
- `python-wfirma` (PyPI) explicitly lists: `warehouse documents including PW, PZ, R, RW, WZ, ZD, ZPD, ZPM` with standard CRUD
- Postman collection `speeding-moon-225969` contains `warehouse_document_z_p_d/get` and `warehouse_document_z_p_d/delete` endpoints — confirming at least GET/DELETE work
- `python-wfirma` maps document types: PW, PZ, R, RW, WZ, ZD, ZPD, ZPM

### Evidence AGAINST (warehouse write via API may not work):
- wFirma forum search result (2023): "Currently, there is no ability to create warehouse documents through the API; the only way to generate a receipt document (WZ) is by issuing an invoice, which will automatically generate the warehouse document."
- dbojdo/wFirma PHP SDK (the most maintained PHP SDK): **no warehouse module listed** — only invoices, contractors, payments
- webit/w-firma-api: **no warehouse module** in its full module list
- No public example of a successful `/warehousedocuments/add` call for a standalone PZ

### Verdict: **UNVERIFIED — CANNOT CONFIRM WITHOUT LIVE ENDPOINT TEST**

```
⚠️  PZ WAREHOUSE DOCUMENT CREATION VIA API
    Status: UNVERIFIED
    Risk: HIGH — incorrect assumption could cause silent data errors or broken stock
    Required: Live test on wFirma sandbox or test company before any production use
```

### Hypothesis on the contradiction
- GET/DELETE of warehouse documents likely works (they're read operations)
- ADD for PZ may require the `warehousedocuments` module AND specific paid plan
- Some wFirma plans may disable warehouse API write access
- wFirma may have added PZ write support AFTER the forum post (which appears old)

---

## 5. Rate Limits

- **Not documented publicly** in any source found
- Inferred from SDK implementations: no retry logic or rate-limit handling built in
- **Recommendation:** Implement exponential backoff: 2s → 4s → 8s between retries
- Do not exceed 60 requests/minute until confirmed safe

---

## 6. Sandbox / Test Mode

- **No public sandbox confirmed** in any documentation found
- wFirma does not appear to offer a developer test environment
- **Only safe option:** Create a separate test company (firma testowa) in wFirma with no real accounting data
- Some partners mention "firma demonstracyjna" as a test option

---

## 7. Error Handling

### Error Response Format
```json
{
  "status": {
    "code": "ERROR",
    "description": "Brak autoryzacji"
  }
}
```

### Known Error Codes
| Code | Meaning |
|------|---------|
| `AUTH_FAILED` | Invalid API keys |
| `PERMISSION_DENIED` | User lacks required module access |
| `KSEF_AUTH_ERROR` | KSeF certificate/token missing or expired |
| `VALIDATION_ERROR` | Required field missing or wrong format |
| `NOT_FOUND` | Record ID does not exist |

### Field Naming Inconsistency (known issue)
- The zmilonas PHP client README explicitly warns: "Field naming inconsistencies between requests and responses (camelCase vs underscores) — requires trial-and-error per official documentation"
- Always test each endpoint with GET first to see the actual field names before constructing write payloads

---

## 8. Request Format Notes

### Numeric Fields
- wFirma API uses **period as decimal separator** internally (1234.56)
- Do NOT send Polish-format numbers (1 234,56) to the API
- Polish format is for UI display only — convert before API calls

### Date Format
- ISO 8601: `YYYY-MM-DD`
- Example: `"date": "2026-04-27"`

### Boolean Fields
- Use `"1"` or `"0"` strings (not JSON true/false in older endpoints)

### Pagination
```json
"page": { "start": 0, "limit": 50 }
```

---

## 9. Known Integrations Using wFirma API

| Integration | Modules Used | Source |
|-------------|-------------|--------|
| WooCommerce plugin | invoices, contractors, goods | wordpress.org |
| Shopify (WP Desk) | invoices, contractors | wpdesk.pl |
| Fynode | invoices, payments | docs.fynode.com |
| SalesCRM | contacts, invoices | imker.pl |

**Note:** None of these integrations use the warehouse/PZ module — all focus on invoices and contractors. This further suggests PZ API write support is either new, rarely used, or plan-restricted.

---

## 10. Sources

- [wFirma API Help Page](https://pomoc.wfirma.pl/-api-interfejs-dla-programistow)
- [Official API Docs](https://doc.wfirma.pl)
- [Fynode Integration Docs](https://docs.fynode.com/en/accountings/wfirma)
- [dbojdo/wFirma PHP SDK](https://github.com/dbojdo/wFirma)
- [webit/w-firma-api Packagist](https://packagist.org/packages/webit/w-firma-api)
- [python-wfirma PyPI](https://pypi.org/project/python-wfirma/)
- [booklet/wfirma PHP client](https://github.com/booklet/wfirma)
- [zmilonas/wfirma-php-api](https://github.com/zmilonas/wfirma-php-api)
- [wFirma Postman collection](https://www.postman.com/speeding-moon-225969/my-workspace/documentation/u7c6l5i/wfirma-pl)
- [wFirma Forum — warehouse API thread](https://forum.wfirma.pl/temat/2511-dokumenty-magazynowe-api)
- [wFirma Forum — API sales and warehouse](https://forum.wfirma.pl/temat/4770-api-sprzedaz-i-magazyn)
