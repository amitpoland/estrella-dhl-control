# B-020 — Security review (mandatory before write)

**Date:** 2026-08-12  
**Tree:** `C:\PZ-main` @ branch `fix/b020-consumer-contractor-authority` (base `dbfd45f25b8725472f2b2b84a31e46b93c7b79b0`)  
**Domain:** DHL / customs identity + carrier doc-package customer resolution + reverification masters  

## Verdict

| Area | Disposition | Notes |
|---|---|---|
| Customs PDF consignor | **SAFE_TO_BIND** | Fail closed to existing unresolved sentinel on NONE/AMBIGUOUS; never invent a supplier name |
| AI / rule reverification | **SAFE_TO_BIND** | Advisory snapshots only; AMBIGUOUS → None masters (no silent wrong row) |
| Carrier `doc_package` customer | **SAFE_TO_BIND** with constraint | Unit-test only; no live MyDHL create. Prefer document-party ID over name when resolvable |
| Intelligence graph supplier | **SAFE_TO_BIND** | Align with client DISTINCT conflict handling |
| Fiscal / wFirma PZ supplier resolver | **HOLD — out of scope** | Different authority (audit name → suppliers master) |
| Intake seeding / packing_contractor_resolution | **HOLD — #1201** | Do not change intake in B-020 |
| Privilege / data leak | **CLEAR** | Read-only document→master lookups; no auth widening |
| Financial / fiscal authority | **CLEAR** (no change) | |

## Rules enforced

1. No new identity DB / mirror.  
2. No name match when a single document-party contractor ID is available.  
3. Multi-party → AMBIGUOUS / fail closed — never SQLite first-row.  
4. No live carrier / wFirma / email / inventory / accounting writes in verification.  

## HOLD conditions (campaign)

A consumer HOLD is only valid if customs identity cannot be determined safely **and** we cannot fail closed to the existing sentinel — that is not the case here. Proceed with SAFE_TO_BIND rows.

**This review is a checkpoint, not a campaign-ending HOLD.**
