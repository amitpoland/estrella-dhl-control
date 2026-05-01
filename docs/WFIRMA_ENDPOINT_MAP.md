# wFirma API — Endpoint Map

**Last updated:** 2026-04-27  
**Base URL:** `https://api2.wfirma.pl/`  
**Format:** `POST /{module}/{action}?inputFormat=json&outputFormat=json`

Legend:
- ✅ CONFIRMED — multiple independent sources
- ⚠️ PARTIAL — limited evidence, needs live test
- ❌ NOT CONFIRMED — no evidence of support
- 🔴 HIGH RISK — use only after verified sandbox test

---

## Authentication Header (all requests)

```http
accessKey: <your-access-key>
secretKey: <your-secret-key>
appKey: <your-app-key>
Content-Type: application/json
```

---

## Module: contractors ✅

### `POST /contractors/add`
```json
{
  "api": {
    "contractors": {
      "contractor": {
        "name": "Estrella Jewels LLP.",
        "nip": "5252812119",
        "type": "foreign_supplier",
        "country": "IN",
        "street": "123 Jewel St",
        "city": "Mumbai",
        "zip": "400001"
      }
    }
  }
}
```

### `POST /contractors/find`
```json
{
  "api": {
    "contractors": {
      "parameters": {
        "conditions": {
          "condition": [{ "field": "nip", "operator": "eq", "value": "5252812119" }]
        }
      }
    }
  }
}
```

### `POST /contractors/get`
```json
{
  "api": {
    "contractors": {
      "contractor": { "id": "12345" }
    }
  }
}
```

Other actions: `edit`, `delete`, `count` ✅

---

## Module: goods (products catalog) ✅

### `POST /goods/add`
```json
{
  "api": {
    "goods": {
      "good": {
        "name": "Pierścionek złoty próby 585 z diamentami",
        "unit": "szt.",
        "price": 1234.56,
        "vat": "23",
        "description": "14KT gold ring with diamonds",
        "type": "product"
      }
    }
  }
}
```

### `POST /goods/find`
```json
{
  "api": {
    "goods": {
      "parameters": {
        "conditions": {
          "condition": [{ "field": "name", "operator": "like", "value": "%złot%" }]
        },
        "page": { "start": 0, "limit": 50 }
      }
    }
  }
}
```

Other actions: `get`, `edit`, `delete`, `count` ✅

---

## Module: invoices ✅

### `POST /invoices/add` — Create sales invoice
```json
{
  "api": {
    "invoices": {
      "invoice": {
        "contractor": { "id": "12345" },
        "paymentmethod": "transfer",
        "paymentdate": "2026-05-27",
        "date": "2026-04-27",
        "type": "normal",
        "series": { "id": "1" },
        "invoicecontents": {
          "invoicecontent": [
            {
              "good": { "id": "678" },
              "count": "5",
              "price": 1234.56,
              "discount": "0"
            }
          ]
        }
      }
    }
  }
}
```

### `POST /invoices/find` — Query invoices
```json
{
  "api": {
    "invoices": {
      "parameters": {
        "conditions": {
          "condition": [
            { "field": "date", "operator": "ge", "value": "2026-04-01" },
            { "field": "date", "operator": "le", "value": "2026-04-30" }
          ]
        },
        "order": [{ "field": "date", "order": "desc" }],
        "page": { "start": 0, "limit": 20 }
      }
    }
  }
}
```

Other actions: `get`, `edit`, `delete`, `fiscalise`, `unfiscalise`, `download`, `send`, `count` ✅

---

## Module: expenses ⚠️ (limited write)

### `POST /expenses/find`
```json
{
  "api": {
    "expenses": {
      "parameters": {
        "conditions": {
          "condition": [{ "field": "date", "operator": "ge", "value": "2026-04-01" }]
        }
      }
    }
  }
}
```

- `get` ✅
- `find` ✅  
- `add` ⚠️ — exists but limited documentation
- `edit`, `delete` ⚠️ — unconfirmed

---

## Module: payments ✅

### `POST /payments/add`
```json
{
  "api": {
    "payments": {
      "payment": {
        "invoice": { "id": "12345" },
        "date": "2026-04-27",
        "value": 1234.56,
        "method": "transfer"
      }
    }
  }
}
```

Other actions: `find`, `get`, `edit`, `delete` ✅

---

## Module: warehouses ✅ (read only confirmed)

### `POST /warehouses/find`
```json
{
  "api": {
    "warehouses": {
      "parameters": {
        "page": { "start": 0, "limit": 10 }
      }
    }
  }
}
```

Response will include warehouse IDs needed for warehousedocuments.

---

## Module: warehousedocuments 🔴 CRITICAL — UNVERIFIED FOR WRITE

### Supported document types (from python-wfirma)
`PW`, `PZ`, `R`, `RW`, `WZ`, `ZD`, `ZPD`, `ZPM`

### `GET` and `DELETE` — PARTIALLY CONFIRMED ⚠️
The Postman collection `speeding-moon-225969` shows `warehouse_document_z_p_d/get` and `warehouse_document_z_p_d/delete` exist.

### `POST /warehousedocuments/get` — Retrieve single document ⚠️
```json
{
  "api": {
    "warehousedocuments": {
      "warehousedocument": { "id": "67890" }
    }
  }
}
```

### `POST /warehousedocuments/find` — Query documents ⚠️
```json
{
  "api": {
    "warehousedocuments": {
      "parameters": {
        "conditions": {
          "condition": [
            { "field": "type", "operator": "eq", "value": "PZ" },
            { "field": "date", "operator": "ge", "value": "2026-04-01" }
          ]
        },
        "page": { "start": 0, "limit": 50 }
      }
    }
  }
}
```

### `POST /warehousedocuments/add` — 🔴 NOT CONFIRMED

**Status: UNVERIFIED**

This is the endpoint needed for PZ import creation. The endpoint **may** look like this based on pattern inference:

```json
{
  "api": {
    "warehousedocuments": {
      "warehousedocument": {
        "type": "PZ",
        "date": "2026-04-27",
        "contractor": { "id": "12345" },
        "warehouse": { "id": "1" },
        "description": "Import AWB 3283625844 / MRN 26PL123456789A",
        "warehousedocumentcontents": {
          "warehousedocumentcontent": [
            {
              "good": { "id": "678" },
              "count": "5",
              "price": 1234.56,
              "description": "Invoice EJL/25-26/1248; AWB ...; MRN ...; A00 allocated in cost; NBP 3,7058"
            }
          ]
        }
      }
    }
  }
}
```

**Before using this endpoint:**
1. Test `warehousedocuments/find` — if it returns 404, the module is not available
2. Check wFirma plan includes warehouse module
3. Test `warehousedocuments/add` on a separate test company
4. Compare created document against manual PZ entry line-by-line
5. Get explicit confirmation from wFirma support that PZ add is supported on your plan

---

## Module: payment_cashboxes ✅ (read)

### `POST /payment_cashboxes/find`
```json
{
  "api": {
    "payment_cashboxes": {
      "parameters": {
        "page": { "start": 0, "limit": 20 }
      }
    }
  }
}
```

---

## Module: series ✅

### `POST /series/find`
```json
{
  "api": {
    "series": {
      "parameters": {}
    }
  }
}
```

---

## Module: webhooks ✅

### `POST /webhooks/add`
```json
{
  "api": {
    "webhooks": {
      "webhook": {
        "url": "https://your-server.com/wfirma-hook",
        "events": "invoice.add,invoice.edit"
      }
    }
  }
}
```

---

## Module: vat_codes ✅ (read only)

### `POST /vat_codes/find`
```json
{
  "api": {
    "vat_codes": {
      "parameters": {}
    }
  }
}
```

---

## Module: company_accounts ✅ (read only)

### `POST /company_accounts/find`
Used to get bank account records for reconciliation / reporting.

---

## Full Module Status Summary

| Module | add | find | get | edit | delete | Verified |
|--------|-----|------|-----|------|--------|----------|
| contractors | ✅ | ✅ | ✅ | ✅ | ✅ | Multi-source |
| goods | ✅ | ✅ | ✅ | ✅ | ✅ | Multi-source |
| invoices | ✅ | ✅ | ✅ | ✅ | ✅ | Multi-source |
| payments | ✅ | ✅ | ✅ | ✅ | ✅ | Multi-source |
| expenses | ⚠️ | ✅ | ✅ | ⚠️ | ⚠️ | Partial |
| series | ✅ | ✅ | ✅ | ✅ | ✅ | Confirmed |
| warehouses | ❌ | ✅ | ✅ | ❌ | ❌ | Read only |
| **warehousedocuments** | 🔴 | ⚠️ | ⚠️ | 🔴 | ⚠️ | **UNVERIFIED** |
| goods (catalog) | ✅ | ✅ | ✅ | ✅ | ✅ | Confirmed |
| payment_cashboxes | ❌ | ✅ | ✅ | ❌ | ❌ | Read only |
| company_accounts | ❌ | ✅ | ✅ | ❌ | ❌ | Read only |
| webhooks | ✅ | ✅ | ✅ | ✅ | ✅ | Confirmed |
| vat_codes | ❌ | ✅ | ✅ | ❌ | ❌ | Read only |
| notes | ✅ | ✅ | ✅ | ✅ | ✅ | Confirmed |
| tags | ✅ | ✅ | ✅ | ✅ | ✅ | Confirmed |
| users | ❌ | ✅ | ✅ | ❌ | ❌ | Read only |

---

## Validated Endpoint Map (SAFE TO USE NOW)

```
✅ contractors/add      ← needed for supplier master data sync
✅ contractors/find     ← lookup before creating PZ
✅ goods/add            ← create product catalog entries
✅ goods/find           ← lookup goods before creating warehousedocument
✅ invoices/find        ← for reporting dashboard
✅ payments/find        ← for outstanding balance reporting
✅ expenses/find        ← for cost reporting
✅ warehouses/find      ← get warehouse IDs

🔴 warehousedocuments/add   ← BLOCKED until PZ endpoint verified
```

---

## Unverified Endpoints (BLOCKED until confirmed)

```
❌ warehousedocuments/add   — PZ direct creation
❌ warehousedocuments/edit  — PZ modification
```

---

## Missing Endpoints (no evidence found)

```
❌ Reports / analytics endpoint   — no evidence in any SDK
❌ KSeF direct query              — separate wFirma module (web UI only?)
❌ Bank statement import          — no evidence
❌ Multi-currency PZ              — unknown support
```
