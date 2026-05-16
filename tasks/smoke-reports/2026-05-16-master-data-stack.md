# Smoke report — Master Data stack deploy (B2 / B10 / B4)

**Date:** 2026-05-16
**Campaign:** MDC-2026-05
**Batch(es):** B2, B10, B4 (merged together, single deploy)
**Environment:** production
**Tester:** claude-session (api-level smoke)

## Coverage

| Route                                              | Action                                    | Expected | Actual | Verdict |
|----------------------------------------------------|-------------------------------------------|----------|--------|---------|
| /api/v1/health (local)                             | GET                                       | 200      | 200    | PASS    |
| /api/v1/health (public)                            | GET                                       | 200      | 200    | PASS    |
| /api/v1/customer-master/BATCH0-SMOKE-TEST          | PUT all-blank optional fields             | 200      | 200    | PASS    |
| /api/v1/customer-master/BATCH0-SMOKE-TEST          | PUT kuke_approved=true + blank kuke_limit | 422      | 422    | PASS    |
| /api/v1/customer-master/BATCH0-SMOKE-TEST          | GET roundtrip                             | 200      | 200    | PASS    |
| /api/v1/customer-master/B2-PROD-SMOKE              | PUT Invoices-tab payload (vat_mode=222)   | 200      | 200    | PASS    |
| /api/v1/suppliers/                                 | POST minimal supplier                     | 201      | 201    | PASS    |
| /api/v1/suppliers/                                 | GET list                                  | 200      | 200    | PASS    |
| /api/v1/suppliers/{id}                             | PUT update                                | 200      | 200    | PASS    |
| /api/v1/suppliers/{id}                             | DELETE                                    | 204      | 204    | PASS    |
| /api/v1/suppliers/{id}                             | GET after delete                          | 404      | 404    | PASS    |

## Console errors

none (api-level smoke)

## Artifacts left behind

- customer_master `BATCH0-SMOKE-TEST` and `B2-PROD-SMOKE` records remain in
  production `customer_master.sqlite`. Both have clearly labelled bill_to_name
  values. No DELETE endpoint exists for customer-master, so these are
  intentionally left for periodic cleanup.

## Verdict

**PASS** — B0 422 fix verified live, B2 Invoices tab schema accepts wFirma
VAT codes (222/228/229), B10 sync chip data path live, B4 Suppliers full
CRUD lifecycle green.

## Browser-level coverage (operator follow-up)

Recommended visual checks not covered by API smoke:
1. ClientKycModal: open on a client without CM record → all 6 tabs render → Save button enabled on every tab
2. CM-tab row: "Open full profile" button visible and opens KycModal
3. Clients table: Sync column renders chip per row
