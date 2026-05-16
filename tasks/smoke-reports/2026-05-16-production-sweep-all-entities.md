# Smoke report — Production sweep — all 11 live Master Data entities

**Date:** 2026-05-16
**Batches:** B0, B2, B4, B5, B7, B8, B9, B10
**Environment:** production
**Tester:** run_smoke.py driver

## Coverage

| Step | Method | Path | Expected | Actual | Verdict |
|---|---|---|---|---|---|
| health-local | GET | `/api/v1/health` | 200 | 200 | PASS |
| wfirma-customers-list | GET | `/api/v1/wfirma/customers` | 200 | 200 | PASS |
| wfirma-products-list | GET | `/api/v1/wfirma/products` | 200 | 200 | PASS |
| cm-list | GET | `/api/v1/customer-master/` | 200 | 200 | PASS |
| cm-put-smoke | PUT | `/api/v1/customer-master/OSO-SMOKE-CM` | 200 | 200 | PASS |
| cm-get-smoke | GET | `/api/v1/customer-master/OSO-SMOKE-CM` | 200 | 200 | PASS |
| shipping-list-smoke | GET | `/api/v1/customer-master/OSO-SMOKE-CM/shipping-addresses/` | 200 | 200 | PASS |
| shipping-post-smoke | POST | `/api/v1/customer-master/OSO-SMOKE-CM/shipping-addresses/` | 201 | 201 | PASS |
| carrier-acct-list | GET | `/api/v1/customer-master/OSO-SMOKE-CM/carrier-accounts/` | 200 | 200 | PASS |
| suppliers-list | GET | `/api/v1/suppliers/` | 200 | 200 | PASS |
| suppliers-create | POST | `/api/v1/suppliers/` | 201 | 201 | PASS |
| hs-list | GET | `/api/v1/hs-codes/` | 200 | 200 | PASS |
| hs-put | PUT | `/api/v1/hs-codes/71131900` | 200 | 200 | PASS |
| hs-delete | DELETE | `/api/v1/hs-codes/71131900` | 204 | 204 | PASS |
| units-list | GET | `/api/v1/units/` | 200 | 200 | PASS |
| units-put | PUT | `/api/v1/units/oso_pc` | 200 | 200 | PASS |
| units-delete | DELETE | `/api/v1/units/oso_pc` | 204 | 204 | PASS |
| pl-list | GET | `/api/v1/product-local/` | 200 | 200 | PASS |
| pl-put | PUT | `/api/v1/product-local/OSO-SMOKE-SKU` | 200 | 200 | PASS |
| pl-delete | DELETE | `/api/v1/product-local/OSO-SMOKE-SKU` | 204 | 204 | PASS |
| incoterms-list | GET | `/api/v1/incoterms/` | 200 | 200 | PASS |
| incoterms-put | PUT | `/api/v1/incoterms/EXW` | 200 | 200 | PASS |
| incoterms-delete | DELETE | `/api/v1/incoterms/EXW` | 204 | 204 | PASS |
| vat-list | GET | `/api/v1/vat-config/` | 200 | 200 | PASS |
| vat-post | POST | `/api/v1/vat-config/` | 201 | 201 | PASS |
| fx-list | GET | `/api/v1/fx-rates/` | 200 | 200 | PASS |
| fx-post | POST | `/api/v1/fx-rates/` | 201 | 201 | PASS |
| carriers-cfg-list | GET | `/api/v1/carriers-config/` | 200 | 200 | PASS |
| carriers-cfg-put | PUT | `/api/v1/carriers-config/oso_smoke` | 200 | 200 | PASS |
| carriers-cfg-delete | DELETE | `/api/v1/carriers-config/oso_smoke` | 204 | 204 | PASS |
| secret-shape-rejected | PUT | `/api/v1/carriers-config/oso_secret_test` | 422 | 422 | PASS |

**Started:**  2026-05-16T10:13:17+00:00
**Finished:** 2026-05-16T10:13:17+00:00

## Verdict

**PASS**
