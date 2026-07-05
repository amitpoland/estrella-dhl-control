# API Wrapper Comparison

**Base SHA:** aa414d90
**Census timestamp:** 2026-07-01T015910Z
**Inspector agent:** api-wrapper-inspector
**Mode:** READ-ONLY — no app code was modified
---

# API Wrapper Comparison

**Base SHA:** aa414d90
**Root pz-api.js methods:** 30
**V2 pz-api.js methods:** 81
**In both:** 29
**Root-only (v2 gap):** 1
**V2-only:** 52

## Method Coverage Table

| Method | Root | V2 | Category | Backend endpoint exists? |
|---|---|---|---|---|
| getProformaDrafts | ✓ | ✓ | BOTH | YES |
| previewProforma | ✓ | ✓ | BOTH | YES |
| getDraft | ✓ | ✓ | BOTH | YES |
| getServiceProducts | ✓ | ✓ | BOTH | YES |
| getProductOptions | ✓ | ✓ | BOTH | YES |
| patchDraft | ✓ | ✓ | BOTH | YES |
| patchDraftLine | ✓ | ✓ | BOTH | YES |
| addDraftLine | ✓ | ✓ | BOTH | YES |
| deleteDraftLine | ✓ | ✓ | BOTH | YES |
| addServiceCharge | ✓ | ✓ | BOTH | YES |
| deleteServiceCharge | ✓ | ✓ | BOTH | YES |
| approveDraft | ✓ | ✓ | BOTH | YES |
| reopenDraft | ✓ | ✓ | BOTH | YES |
| cancelDraft | ✓ | ✓ | BOTH | YES |
| resetDraftFromSalesPacking | ✓ | ✓ | BOTH | YES |
| listCustomerMaster | ✓ | ✓ | BOTH | YES |
| getCustomerMaster | ✓ | ✓ | BOTH | YES |
| saveCustomerMaster | ✓ | ✓ | BOTH | YES |
| previewWfirmaSyncCustomer | ✓ | ✓ | BOTH | YES |
| applyWfirmaSyncCustomer | ✓ | ✓ | BOTH | YES |
| getCustomerDictionaries | ✓ | ✓ | BOTH | YES |
| refreshCustomerDictionaries | ✓ | ✓ | BOTH | YES |
| getContractorScanStatus | ✓ | ✓ | BOTH | YES |
| runContractorScan | ✓ | ✓ | BOTH | YES |
| postDraftToWfirma | ✓ | ✓ | BOTH | YES |
| cloneDraft | ✓ | ✓ | BOTH | YES |
| draftToInvoice | ✓ | ✓ | BOTH | YES |
| getDraftEvents | ✓ | ✓ | BOTH | YES |
| discloseDraftConvert (root) / getDisclosureConvert (v2) | ✓ | ✓ | BOTH — renamed in v2 | YES (`routes_proforma.py:9023`) |
| getDraftVisibility | ✓ | ✗ | ROOT_ONLY | YES (`routes_proforma.py:8722`) |
| searchProformaDrafts | ✗ | ✓ | V2_ONLY | YES |
| deleteDraft | ✗ | ✓ | V2_ONLY | YES |
| sendProformaEmail | ✗ | ✓ | V2_ONLY | YES |
| getDraftReadiness | ✗ | ✓ | V2_ONLY | YES |
| resolveDraftAmbiguity | ✗ | ✓ | V2_ONLY | YES |
| getPackingDocuments | ✗ | ✓ | V2_ONLY | YES |
| linkAsSales | ✗ | ✓ | V2_ONLY | YES |
| getReservationPreview | ✗ | ✓ | V2_ONLY | YES |
| createReservation | ✗ | ✓ | V2_ONLY | YES |
| createCarrierShipment | ✗ | ✓ | V2_ONLY | YES |
| listCarrierServices | ✗ | ✓ | V2_ONLY | YES |
| listBoxTypes | ✗ | ✓ | V2_ONLY | YES |
| getReceiptStatus | ✗ | ✓ | V2_ONLY | YES |
| confirmReceipt | ✗ | ✓ | V2_ONLY | YES |
| approveProposal | ✗ | ✓ | V2_ONLY | YES |
| rejectProposal | ✗ | ✓ | V2_ONLY | YES |
| getWfirmaCapabilities | ✗ | ✓ | V2_ONLY | YES |
| getWfirmaCustomers | ✗ | ✓ | V2_ONLY | YES |
| getWfirmaProducts | ✗ | ✓ | V2_ONLY | YES |
| searchWfirmaContractors | ✗ | ✓ | V2_ONLY | YES |
| searchWfirmaGoods | ✗ | ✓ | V2_ONLY | YES |
| listSuppliers | ✗ | ✓ | V2_ONLY | YES |
| listProductLocal | ✗ | ✓ | V2_ONLY | YES |
| listDesigns | ✗ | ✓ | V2_ONLY | YES |
| listHsCodes | ✗ | ✓ | V2_ONLY | YES |
| listFxRates | ✗ | ✓ | V2_ONLY | YES |
| listVatConfig | ✗ | ✓ | V2_ONLY | YES |
| listIncoterms | ✗ | ✓ | V2_ONLY | YES |
| listUnits | ✗ | ✓ | V2_ONLY | YES |
| listCarriersConfig | ✗ | ✓ | V2_ONLY | YES |
| getCarrierStatus | ✗ | ✓ | V2_ONLY | YES |
| getHealthFull | ✗ | ✓ | V2_ONLY | YES |
| getDebugPending | ✗ | ✓ | V2_ONLY | YES |
| getStorageHealth | ✗ | ✓ | V2_ONLY | YES |
| getStorageLocks | ✗ | ✓ | V2_ONLY | YES |
| getSystemVersion | ✗ | ✓ | V2_ONLY | YES |
| getOpenApiSpec | ✗ | ✓ | V2_ONLY | YES |
| getPzHealth | ✗ | ✓ | V2_ONLY | YES |
| getBatchDetail | ✗ | ✓ | V2_ONLY | YES |
| getDhlReadiness | ✗ | ✓ | V2_ONLY | YES |
| getDhlAutoScanStatus | ✗ | ✓ | V2_ONLY | YES |
| getDhlDailySummary | ✗ | ✓ | V2_ONLY | YES |
| getDhlFollowupStatus | ✗ | ✓ | V2_ONLY | YES |
| getEmailQueue | ✗ | ✓ | V2_ONLY | YES |
| getIntelligenceStatus | ✗ | ✓ | V2_ONLY | YES |
| listBatches | ✗ | ✓ | V2_ONLY | YES |
| listUsers | ✗ | ✓ | V2_ONLY | YES |
| listMasterAudit | ✗ | ✓ | V2_ONLY | YES |
| getClientInvoiceLedger | ✗ | ✓ | V2_ONLY | YES |
| applyCustomerAddress | ✗ | ✓ | V2_ONLY | YES |
| suggestServiceCharges | ✗ | ✓ | V2_ONLY | YES |
| applyServiceCharges | ✗ | ✓ | V2_ONLY | YES |

## Root-only methods (v2 gaps)

These exist in the legacy root pz-api.js but have no v2 equivalent:

| Method | HTTP | Endpoint | Backend route exists? | Priority to port |
|---|---|---|---|---|
| getDraftVisibility | GET | `/api/v1/proforma/draft/{draft_id}/visibility` | YES (`routes_proforma.py:8722`) | HIGH — workflow gate readiness; v2 proforma detail pages use `getDraftReadiness` instead but visibility provides Phase 5.5A operator-facing workflow state distinct from readiness (INFERRED) |

## Dead legacy methods

Root-only methods where the backend endpoint also does not exist:

| Method | Notes |
|---|---|
| (none) | The single root-only method (`getDraftVisibility`) has a confirmed live backend route. There are no dead legacy methods. |

## Summary

- Coverage ratio: 29/30 = 96.7% of root methods have a v2 equivalent
- Functional gaps: 1 root-only method (`getDraftVisibility`) — backend route is live; v2 uses `getDraftReadiness` for gate-checking but the Phase 5.5A visibility endpoint is not exposed in v2 PzApi
- Dead code: 0 methods in root with no backend
- V2 expansion: v2 adds 52 net-new methods covering carrier (DHL AWB), warehouse receipt, action proposals, wFirma mapping, master data catalogue (suppliers, designs, HS codes, FX rates, VAT, incoterms, units, carriers config), system health, dashboard reads, ledger, and proforma service-charge authority — none of these have root counterparts
- Rename note: `discloseDraftConvert` (root) was renamed `getDisclosureConvert` in v2; both target identical endpoint `/api/v1/proforma/draft/{draft_id}/disclose-convert` and are counted as BOTH

## Sources

| File | Lines read | Role |
|---|---|---|
| `C:\PZ-verify\service\app\static\pz-api.js` | 1–273 (full file) | Root (legacy) API wrapper — method extraction |
| `C:\PZ-verify\service\app\static\v2\pz-api.js` | 1–661 (full file) | V2 (authority) API wrapper — method extraction |
| `C:\PZ-verify\service\app\api\routes_proforma.py` | Lines 8722–8723, 9023 (grep hits) | Backend route existence check for `getDraftVisibility` and `discloseDraftConvert` |
| `C:\PZ-verify\service\app\api\` (directory listing) | All routes_*.py filenames | Route file inventory for backend existence cross-reference |
