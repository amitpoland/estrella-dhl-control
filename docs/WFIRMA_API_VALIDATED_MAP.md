# wFirma API — Validated Endpoint Map

**Date:** 2026-04-27  
**Purpose:** Cross-referenced endpoint map from all available sources  
**Sources:** wFirma help, Fynode docs, dbojdo/wFirma SDK, webit/w-firma-api, python-wfirma, booklet/wfirma, zmilonas/wfirma-php-api, wFirma Postman collection

---

## Authentication (CONFIRMED across all sources)

```
Method:      API Keys (3 keys)
accessKey:   wFirma → Ustawienia → Aplikacje → Klucze API
secretKey:   same — copy immediately, shown ONCE
appKey:      requested from wFirma for each application
companyId:   required for multi-company accounts
```

Header format (confirmed from dbojdo SDK):
```
accessKey: <key>
secretKey: <key>
appKey: <key>
```

Request URL pattern (confirmed):
```
POST https://api2.wfirma.pl/{module}/{action}?inputFormat=json&outputFormat=json
```

---

## CONFIRMED ENDPOINTS (multi-source verification)

### contractors
| Endpoint | Status | Sources |
|----------|--------|---------|
| contractors/add | ✅ CONFIRMED | dbojdo, webit, booklet, python |
| contractors/find | ✅ CONFIRMED | All SDKs |
| contractors/get | ✅ CONFIRMED | All SDKs |
| contractors/edit | ✅ CONFIRMED | All SDKs |
| contractors/delete | ✅ CONFIRMED | All SDKs |
| contractors/count | ✅ CONFIRMED | dbojdo, webit |

### invoices
| Endpoint | Status | Sources |
|----------|--------|---------|
| invoices/add | ✅ CONFIRMED | All SDKs + Fynode |
| invoices/find | ✅ CONFIRMED | All SDKs + Postman |
| invoices/get | ✅ CONFIRMED | All SDKs |
| invoices/edit | ✅ CONFIRMED | All SDKs |
| invoices/delete | ✅ CONFIRMED | All SDKs |
| invoices/fiscalise | ✅ CONFIRMED | dbojdo, webit |
| invoices/unfiscalise | ✅ CONFIRMED | dbojdo, webit |
| invoices/download | ✅ CONFIRMED | dbojdo, webit |
| invoices/send | ✅ CONFIRMED | dbojdo, Fynode |

### goods (product catalog)
| Endpoint | Status | Sources |
|----------|--------|---------|
| goods/add | ✅ CONFIRMED | python-wfirma, zmilonas |
| goods/find | ✅ CONFIRMED | python-wfirma, zmilonas |
| goods/get | ✅ CONFIRMED | python-wfirma |
| goods/edit | ✅ CONFIRMED | python-wfirma |
| goods/delete | ✅ CONFIRMED | python-wfirma |

### payments
| Endpoint | Status | Sources |
|----------|--------|---------|
| payments/add | ✅ CONFIRMED | dbojdo, webit, python |
| payments/find | ✅ CONFIRMED | dbojdo, webit, python |
| payments/get | ✅ CONFIRMED | dbojdo, python |
| payments/edit | ✅ CONFIRMED | dbojdo, webit |
| payments/delete | ✅ CONFIRMED | dbojdo |

### expenses
| Endpoint | Status | Sources |
|----------|--------|---------|
| expenses/find | ✅ CONFIRMED | dbojdo, python |
| expenses/get | ✅ CONFIRMED | dbojdo, python |
| expenses/add | ⚠️ PARTIAL | python-wfirma only |
| expenses/edit | ⚠️ PARTIAL | python-wfirma only |
| expenses/delete | ⚠️ PARTIAL | python-wfirma only |

### series (document number series)
| Endpoint | Status | Sources |
|----------|--------|---------|
| series/find | ✅ CONFIRMED | dbojdo, webit |
| series/get | ✅ CONFIRMED | dbojdo |
| series/add | ✅ CONFIRMED | dbojdo |

### warehouses (master data)
| Endpoint | Status | Sources |
|----------|--------|---------|
| warehouses/find | ⚠️ PARTIAL | python-wfirma |
| warehouses/get | ⚠️ PARTIAL | python-wfirma |

### webhooks
| Endpoint | Status | Sources |
|----------|--------|---------|
| webhooks/find | ✅ CONFIRMED | dbojdo + Postman collection |
| webhooks/add | ✅ CONFIRMED | dbojdo |
| webhooks/delete | ✅ CONFIRMED | dbojdo |

---

## UNVERIFIED ENDPOINTS (cannot confirm without live test)

### warehousedocuments — 🔴 CRITICAL
| Endpoint | Status | Evidence |
|----------|--------|---------|
| warehousedocuments/find | ⚠️ PARTIAL | python-wfirma, Postman (ZPD get) |
| warehousedocuments/get | ⚠️ PARTIAL | Postman collection shows ZPD get |
| warehousedocuments/delete | ⚠️ PARTIAL | Postman collection shows ZPD delete |
| **warehousedocuments/add** | 🔴 **UNVERIFIED** | **No confirmed working example** |
| warehousedocuments/edit | 🔴 **UNVERIFIED** | No evidence |

**Critical note:** wFirma forum (2023) explicitly states warehouse document creation via API is not possible. Python-wfirma (alpha) lists the module but cannot confirm write support is live.

---

## MISSING ENDPOINTS (no evidence in any source)

| Functionality | Status | Notes |
|---------------|--------|-------|
| Analytics / reports | ❌ NOT FOUND | No reporting API endpoint found |
| Bank statement import | ❌ NOT FOUND | No evidence |
| KSeF direct query | ❌ NOT FOUND | KSeF is web UI only per wFirma help |
| Tax declarations | ❌ NOT FOUND | Not accessible via API |
| Multi-currency PZ | ❌ NOT FOUND | Unknown if supported |
| Batch PZ creation | ❌ NOT FOUND | No bulk create endpoint confirmed |

---

## RISKS

### Risk 1: warehousedocuments/add does not exist
- **Probability:** MEDIUM (contradictory evidence)
- **Impact:** Phase 3 of wFirma integration is not possible
- **Mitigation:** Phase 1 (clipboard) remains production path

### Risk 2: appKey requires wFirma registration process
- **Probability:** HIGH (confirmed — appKey is provided by wFirma per application)
- **Impact:** Cannot use API until wFirma assigns appKey to Estrella
- **Action:** Contact wFirma support to register app and receive appKey

### Risk 3: KSeF cascade on invoice operations
- **Probability:** HIGH for invoice operations
- **Impact:** API invoices submitted to KSeF immediately — no draft
- **Mitigation:** Use separate KSeF-authorized API user for invoice endpoints

### Risk 4: Field naming inconsistency
- **Probability:** HIGH (documented in zmilonas README)
- **Impact:** Wrong field names silently ignored, missing data
- **Mitigation:** Always test with `find` to read field names before `add`/`edit`

### Risk 5: Plan restriction on warehouse module
- **Probability:** MEDIUM
- **Impact:** Need to upgrade wFirma plan (cost unknown)
- **Action:** Verify current plan before proceeding

---

## Action Items (Ordered by Priority)

| Priority | Action | Owner | Blocks |
|----------|--------|-------|--------|
| 1 | Contact wFirma support to obtain appKey | Admin | ALL API |
| 2 | Verify plan supports warehouse API | Admin | Phase 3 |
| 3 | Create test company in wFirma | Admin | Phase 3 testing |
| 4 | Test `warehousedocuments/find` | Dev | Phase 3 verification |
| 5 | Build Phase A dashboard (local data only) | Dev | Reporting |
| 6 | Add wFirma read endpoints for Phase B | Dev | Full reporting |
| 7 | If PZ add confirmed: implement Phase 3 | Dev | Full automation |

---

## Contact for API Access

**wFirma support email:** pomoc@wfirma.pl  
**Developer API docs:** https://doc.wfirma.pl  
**Help page:** https://pomoc.wfirma.pl/-api-interfejs-dla-programistow  

**Suggested email subject:**
```
Pytanie techniczne: API warehousedocuments/add (tworzenie PZ) + rejestracja aplikacji (appKey)
```

**Message body:**
```
Dzień dobry,

Czy platforma wFirma.pl umożliwia tworzenie dokumentów magazynowych PZ 
przez API za pomocą endpointa warehousedocuments/add?

Jakich uprawnień i jakiego planu wymaga ta funkcja?

Czy jest możliwe zarejestrowanie aplikacji i uzyskanie appKey 
dla integracji z własnym systemem importowym?

Dziękuję.
```
