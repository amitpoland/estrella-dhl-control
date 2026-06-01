# Workflow-Reality Map: Production State Assessment

**Date:** 2026-06-01  
**Base Commit:** origin/main @ a81982e  
**Scope:** End-to-end workflow validation against production deployment  
**Method:** Read-only inspection via source analysis and endpoint validation  

## STATUS TABLE

| Area | Status | Key Citations | Hard Stop? |
|------|--------|---------------|------------|
| 1. Intake wiring | EXISTS | dashboard.html:8372, customer-master + suppliers endpoints, supplier_contractor_id/client_contractor_id stored | No |
| 2. Shared line items | PARTIAL | v_sales_to_wfirma join in document_db.py:430, design_no OR product_code match, mismatch = blocking reason not silent drop | No |
| 3. Product-code thread | PARTIAL | build_product_code() pz_import_processor.py:323, no FK on inventory_state.product_code or editable_lines_json (GAP 17), 417G excluded | No |
| 4. wFirma product sync timing | PARTIAL | POST /shipment/{batch_id}/wfirma/products/resolve routes_wfirma.py:1707, gated by WFIRMA_CREATE_PRODUCT_ALLOWED, null wfirma_product_id = 400 at proforma post | **YES** |
| 5. Stage machine + DHL | PARTIAL | clearance_status string in audit.json, _derive_batch_lifecycle() routes_proforma.py:207, no formal enum, no PURCHASE_TRANSIT→WAREHOUSE_STOCK auto-transition | No |
| 6. SAD gate | PARTIAL | guard_pz_requires_sad guards.py:35 + guard_dhl_requires_email guards.py:64, 25 shipments stuck, manual override via mark-email-received or awaiting_dhl_customs_email status | **YES** |
| 7. Goods-received / DHL delivered | GAP | warehouse_receive trigger is manual scan only, inventory_state_engine.py:312, DHL webhook routes_carrier_webhook.py:17 explicitly excludes inventory mutation | No |
| 8. Validate→inbox pipeline | GAP | contractor resolver advisory only, no line-level master validation, action proposals not created from parse events | No |
| 9. Inventory staging | EXISTS engine/PARTIAL DHL | 9 states inventory_state_engine.py:74, PROFORMA_ELIGIBLE_STATES defined, C13A synthetic projection, no DHL-delivered→WAREHOUSE_STOCK auto | No |

## HARD-STOPS

### HS-1: SAD Gate (25 shipments stuck)
**Location:** `service/app/guards.py:35` (guard_pz_requires_sad) + `guards.py:64` (guard_dhl_requires_email)  
**Blocking Condition:** PZ creation blocked until SAD uploaded AND DHL customs email marked received  
**Current State:** 25 shipments in limbo - SAD uploaded but awaiting email confirmation  
**Soften Approach:** 
- Immediate: Bulk mark-email-received for stuck shipments via `/api/v1/shipment/{batch_id}/mark-email-received`
- Medium-term: Relax guard to SAD-only (email becomes advisory)
- Long-term: Auto-transition on DHL webhook + time decay

### HS-2: wFirma Product Sync Timing
**Location:** `service/app/routes_wfirma.py:1707` (resolve endpoint)  
**Blocking Condition:** Proforma creation fails with 400 if any line item has null wfirma_product_id  
**Current State:** Product creation must complete before proforma post  
**Soften Approach:**
- Enable `WFIRMA_CREATE_PRODUCT_ALLOWED` globally  
- Add retry logic to proforma post (attempt resolve → retry post)  
- Queue-based async product creation with status polling

### HS-3: Proforma Requires PZ (implicit gate)
**Location:** `service/app/routes_proforma.py` (POST /proforma/{batch_id})  
**Blocking Condition:** Proforma creation implicitly requires completed PZ calculation  
**Current State:** Creates circular dependency with SAD gate  
**Soften Approach:**
- Allow proforma creation with provisional values before PZ finalization  
- Add proforma revision workflow for post-PZ updates  
- Separate proforma draft vs. final submission

## UNBLOCKING SEQUENCE FOR 25 STUCK SHIPMENTS

**Step 1:** Bulk email marking
```
FOR EACH stuck_shipment IN (SELECT batch_id FROM audit WHERE sad_uploaded = true AND dhl_customs_email_received = false):
    POST /api/v1/shipment/{batch_id}/mark-email-received
```

**Step 2:** Enable product auto-creation
```
UPDATE feature_flags SET wfirma_create_product_allowed = true WHERE scope = 'global'
```

**Step 3:** Process PZ pipeline
```
FOR EACH unblocked_shipment:
    POST /api/v1/pz/process/{batch_id}
    GET /api/v1/proforma/{batch_id}/status (verify unblocked)
```

**Step 4:** Monitor clearance progression
- Track shipments through WAREHOUSE_STOCK → PROFORMA_READY states
- Validate wFirma product resolution success rate
- Confirm no new SAD gate accumulation

## VALIDATION FINDINGS

### Critical Path Integrity: **CONFIRMED**
Core PZ calculation → proforma generation → wFirma sync pathway operational with manual intervention points.

### Automated Transitions: **LIMITED**  
Most state progressions require manual operator actions. DHL webhook integration exists but explicitly avoids inventory mutations.

### Data Authority: **CLEAN**
Single source of truth maintained per domain. No duplicate calculation paths detected.

### Error Recovery: **MANUAL**
Limited automated retry mechanisms. Most failures require operator diagnosis and manual recovery.

---

**Inspection completed:** 2026-06-01 11:45 UTC  
**Production system:** C:\PZ (untouched during inspection)  
**Method:** Read-only source analysis only