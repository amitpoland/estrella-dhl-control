# Proforma — FULL WIREFRAME PORT · STEP 1 + 1A inventory

**Date:** 2026-07-05 · Source cited: pinned wireframe render `reports/wave3/cp3/pair-05-proforma.png` (LEFT panel). Every row cites an actually-rendered wireframe element. No memory, no inference. Reuse-only wiring (no new backend, no write-path change).

## STEP 1 — element inventory + classification

| # | Wireframe element (cited from pair-05 LEFT) | Class |
|---|---|---|
| 1 | "Pro Forma" title + subtitle "Draft pro forma invoices · Convert to invoice when ready" | IMPLEMENTED (PageHeader) |
| 2 | Header action "↓ Export CSV" (top-right) | IMPLEMENTED |
| 3 | "Pro Forma Drafts" heading + subtitle "Packing List is the source · extraction → review → push to wFirma" | PORT (heading exists; subtitle text differs) |
| 4 | Toolbar "Import Packing List" | REUSE (ImportPackingListModal → POST /proforma/draft/{id}/import-sales-prices; needs a batch/draft ctx) |
| 5 | Toolbar "+ Create Draft" | REUSE (NewProformaDraftModal → POST /proforma/create/{batch_id}/{client}; needs batch ctx) |
| 6 | Toolbar "↑ Push to wFirma" | REUSE (PzApi.postDraftToWfirma; act on selected) |
| 7 | Toolbar "Send" | REUSE (PzApi.sendProformaEmail → POST /proforma/draft/{id}/send-email; act on selected) |
| 8 | Toolbar "Print" | GATED (no print endpoint in pz-api.js; backend-gated) |
| 9 | 5 KPI tiles: Extracting · Operator Review · Ready · Pushed · Error | PORT (per-batch KPI exists; cross-batch = client-side aggregate of search results, no new endpoint) |
| 10 | Table columns: Draft No · Customer · Shipment · Items · Total · Match · Status | PORT (batch table has different cols; cross-batch table with wireframe cols) |
| 11 | Row checkbox + select-all | REUSE (selection state exists in ProformaListPage) |
| 12 | Cross-batch drafts (all batches on the landing, not `?batch_id`-scoped) | PORT (reuse GET /proforma/search via PzApi.searchProformaDrafts) |
| 13 | Status badges (Operator Review / Ready / Error+detail / Pushed to wFirma → PROF nn/yyyy) | PORT |
| 14 | Row → open detail | REUSE (onDrill) |

## STEP 1A — functional inventory

| Wireframe Element | UI | Interaction | Endpoint (existing) | Authority | Workflow | Status |
|---|---|---|---|---|---|---|
| Pro Forma Drafts landing (cross-batch) | build | list | GET /proforma/search | proforma read | draft list | PORT |
| 5 KPI tiles | build | none | (aggregate of search) | — | — | PORT |
| Drafts table (7 wf cols + checkbox) | build | select/drill | GET /proforma/search | proforma read | — | PORT |
| Import Packing List | reuse btn | modal | POST /proforma/draft/{id}/import-sales-prices | proforma | import prices | REUSE (needs batch/draft ctx) |
| + Create Draft | reuse btn | modal | POST /proforma/create/{batch_id}/{client} | proforma | draft create | REUSE (needs batch ctx) |
| ↑ Push to wFirma | reuse btn | on selected | POST /proforma/draft/{id}/post (postDraftToWfirma) | wFirma write-gated | post | REUSE |
| Send | reuse btn | on selected | POST /proforma/draft/{id}/send-email | email write-gated | send | REUSE |
| Print | gated btn | none | — (none) | — | — | GATED |

**Acceptance target:** UI Missing = 0, Functional Missing = 0, Wireframe Missing = 0; only backend-gated items (Print) remain GATED. No financial write-path change — Push/Send reuse existing write-gated endpoints unchanged; Create/Import remain batch-context actions (disabled-with-reason on the cross-batch landing, Lesson M honest gating).
