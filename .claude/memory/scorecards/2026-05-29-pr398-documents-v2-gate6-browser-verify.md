# Browser-Verifier Evidence — PR #398 Documents V2 (GATE 6) — PASS

**Date**: 2026-05-29
**Surface**: `documents-v2.html` (Atlas-V2 Sprint 04, deployed via PR #398)
**Verifier**: Claude-in-Chrome (Browser 2 — Windows local, deviceId f3a3ecfc-0865-49e8-9d85-d89474f9ebed)
**Environment**: local production service `http://127.0.0.1:47213` (PZService, env=prod), authenticated operator session
**Verification batch**: `SHIPMENT_4218922912_2026-05_9040dd39` (AWB 4218922912, DHL, status=partial) — a real production batch with full document set
**Closes**: OQ10 (PR #398 Sprint 04 GATE 6 browser verification)

## GATE 6 checklist — all PASS

| # | Requirement | Result |
|---|-------------|--------|
| 1 | Source documents render | ✅ CUSTOMS: SAD (`ZC429_26PL44302D00BXH0R4_1_PL.pdf`, Available), AWB (`Tracking.pdf`, Available). COMMERCIAL: 4 invoices (EJL-26-27-177/178/179/180, all Available) |
| 2 | Generated documents render | ✅ PZ PDF (Available), CALC XLSX (Available), AUDIT MEMO (Available); AUDIT EN/PL + CORRECTIONS honestly labeled **Stale** (no fake readiness) |
| 3 | Audit trail renders | ✅ Full event timeline rendered (batch_created → invoice_uploaded → clearance decisions → sad_uploaded → wfirma_pz_adopted → status_change → wfirma_json_generated) |
| 4 | Links open backend file URLs | ✅ 11 links, all `/api/v1/files/{batch}/source/{sad,awb,invoices}/...` + generated `/api/v1/files/{batch}/PZ_AWB_...`. Verified resolve: SAD PDF → **200 application/pdf 14085 B**; PZ PDF → **200 application/pdf 44364 B** |
| 5 | Console clean | ✅ Only benign in-browser Babel transformer WARNING (expected for the no-bundler stack per frontend standard). **No errors.** |
| 6 | Network no 4xx/5xx on happy path | ✅ Data endpoint `/api/v1/dashboard/batches/{id}` (the #395 alias — page's sole data source) → **200**. Page + all shared JS modules (dashboard-shared/pz-api/pz-state/pz-components) → 200 |
| 7 | No write actions present (read-only viewer) | ✅ DOM scan: **0 `<button>`, 0 `<form>`, 0 write-links** (no delete/remove/post/submit). Confirms Lesson F single-domain read-only authority — no forbidden write paths |

## Screenshot evidence
Captured in-session (1280×595 jpeg, id `ss_341598ekw`): renders the Atlas-styled Documents page — header (AWB 4218922912, DHL, shipment date, `partial` badge), CUSTOMS DOCUMENTS (SAD + AWB with "View PDF ↗"), COMMERCIAL DOCUMENTS (invoices). Matches the page-text capture.

## Verdict
**GATE 6 PASS.** Documents V2 (PR #398) is verified end-to-end in a real authenticated production session: source + generated documents render, audit trail renders, document links resolve to backend file URLs (200/application/pdf), console clean, no 4xx/5xx, and the surface is strictly read-only (no write controls). Sprint 04 moves from *deploy-complete* to **fully closed**.

## Distinction (do not conflate)
This verifies `documents-v2.html` (the standalone Atlas V2 page, PR #398). It does NOT cover the broken **Documents card inside `shipment-v2.html`** (GitHub Issue #396 / OQ-NEW-396) — a separate surface using wrong `files_detail` keys. #396 remains OPEN.
