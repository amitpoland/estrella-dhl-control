# API Wrapper Comparison

**Base SHA:** aa414d90
**Census timestamp:** {{STAMP}}
**Inspector agent:** api-wrapper-inspector
**Mode:** READ-ONLY — no app code was modified
**Root pz-api.js methods:** {{N}}
**V2 pz-api.js methods:** {{M}}
**In both:** {{K}}
**Root-only (v2 gap):** {{J}}
**V2-only:** {{L}}
**Coverage ratio:** {{K}}/{{N}} = {{PCT}}%

---

## Method Coverage Table

| Method | Root | V2 | Category | Backend endpoint exists? |
|---|---|---|---|---|
| getProformaList | ✓ | ✓ | BOTH | YES |
| getCustomerMaster | ✗ | ✓ | V2_ONLY | YES |
| oldBatchSubmit | ✓ | ✗ | ROOT_ONLY | NO (dead) |
| … | … | … | … | … |

---

## Root-Only Methods (V2 Gaps)

| Method | HTTP | Endpoint | Backend route exists? | Port priority |
|---|---|---|---|---|

---

## Dead Legacy Methods

Root-only methods where the backend endpoint also does not exist:

| Method | Notes |
|---|---|
