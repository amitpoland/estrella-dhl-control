# Sprint 04 — Documents V2

**Campaign:** Atlas-V2  
**Sprint:** 04 of 13  
**Branch:** `atlas-v2/sprint-04-documents-v2`  
**Dependency:** Sprint 03 merged  
**New file:** `service/app/static/documents-v2.html`  
**URL:** `/dashboard/documents-v2.html?batch_id=<BATCH_ID>`

---

## Authority Boundary

```
OWNS:  customs document viewer per shipment: SAD list, ZC429 list, packing list,
       invoice list, audit trail; document status badges; PDF preview links;
       document upload status timeline; "Download" Btn (opens PDF in new tab)
NEVER: SAD approval/rejection, customs calculation, ZC429 processing,
       MRN entry, duty calculation, any document write operation,
       PZ, wFirma, DHL API mutations
```

---

## Page Purpose

Documents V2 is the read-only document archive for a single shipment.
Operator can see: which documents exist, their parse status, upload timestamps,
and open PDFs. No document processing happens here — that's the backend pipeline.

All document state is sourced from existing endpoints.

---

## APIs This Page Consumes (existing, read-only)

| Endpoint | Purpose |
|----------|---------|
| `GET /api/v1/dhl/documents/{batch_id}` | SAD, ZC429, other DHL docs |
| `GET /api/v1/batch/{batch_id}/documents` | Packing list, invoice docs per batch |
| `GET /api/v1/dashboard/batches/{batch_id}/readiness` | Document parse status, MRN present |

If endpoints return document metadata without download links, `pz-api.js` should derive
the download URL pattern — do not create a new download endpoint.

---

## Component Tree

```
DocumentsV2Root
├── SessionBanner
├── BatchHeader (AWB, shipment date)
├── SectionHeader "Customs Documents"
│   ├── DocumentRow (SAD): status Badge, filename, uploaded_at, Btn "View PDF"
│   ├── DocumentRow (ZC429): same structure
│   └── EmptyState if no customs docs
├── SectionHeader "Commercial Documents"
│   ├── DocumentRow (Invoice): status Badge, filename, parsed_at, Btn "View PDF"
│   ├── DocumentRow (Packing List): same
│   └── EmptyState if no commercial docs
└── SectionHeader "Audit Trail"
    └── CompactTable: action, timestamp, operator, note
```

---

## Mandatory Agents

| Order | `subagent_type` | Purpose |
|-------|-----------------|---------|
| 1 | `chief-orchestrator` | Routing |
| 2 | `system-architect` | Verify document API endpoints |
| 3 | `gap-detection` | Missing document endpoints, missing metadata fields |
| 4 | `reviewer-challenge` | Attack any plan adding write operations |
| 5 | `backend-api` | Add missing read-only document metadata fields if needed |
| 6 | `backend-safety-reviewer` | Review any backend change |
| 7 | `frontend-ui` | Build documents-v2.html |
| 8 | `frontend-flow-reviewer` | Review |
| 9 | `testing-verification` | Tests |
| 10 | `test-coverage-reviewer` | Review |
| 11 | `gap-hunter` | Cross-phase |
| 12 | `browser-verifier` | Open with real batch, verify PDF links open |
| 13 | `integration-boundary` | API wiring |
| 14 | `git-workflow` + `pr-author` | Commit + PR |

---

## Test Baseline

```bash
make verify                 # 160/160
cd service && python3 -m pytest tests/test_proforma_v2_contract.py -q  # 44/44
cd service && python3 -m pytest tests/test_carrier_*.py -q             # 366/366
```

---

## Acceptance Criteria

1. Page loads with valid `?batch_id=` — no console errors
2. SAD and ZC429 rows render with status Badge and "View PDF" Btn
3. Commercial document rows render (invoice, packing list)
4. "View PDF" opens document in new tab — does not inline-render PDF
5. EmptyState shown when no documents in a section
6. Audit trail table renders with timestamps
7. All interactive elements have `data-testid`
8. Zero write operations
9. Rollback: remove file; no restart needed

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 04 — Documents V2
Branch: atlas-v2/sprint-04-documents-v2 (create from origin/main, Sprint 03 must be merged first)

STACK CONSTRAINTS — mandatory, read before any UI work:
1. Read `.claude/skills/frontend-design.md` BEFORE touching any HTML/JS
2. `.claude/skills/ui-ux-pro-max` is supplemental only — read `EJ_OVERRIDES.md` first
3. Stack: Vanilla HTML + Babel JSX. NO Vite. NO TypeScript. NO Tailwind. NO bundler.
4. Pattern file: service/app/static/proforma-v2.html — follow CDN load order and IIFE structure exactly
5. Shared layer: window.EstrellaShared, window.PzApi, window.PzState, window.PzComponents
6. CSS: custom properties only. Zero hardcoded hex.

TASK:
Create service/app/static/documents-v2.html — customs and commercial document viewer.
URL: /dashboard/documents-v2.html?batch_id=<BATCH_ID>

AUTHORITY:
OWNS: document list, status badges, PDF view links, audit trail display
NEVER: SAD approval, customs calc, ZC429 processing, MRN entry, any write

COMPONENT TREE:
- BatchHeader
- SectionHeader "Customs Documents": DocumentRow per SAD/ZC429 (status Badge, filename, uploaded_at, Btn "View PDF" opens new tab)
- SectionHeader "Commercial Documents": DocumentRow per invoice/packing list  
- SectionHeader "Audit Trail": CompactTable with action/timestamp/operator columns
- EmptyState when no docs in a section

APIs (existing, read-only):
- GET /api/v1/dhl/documents/{batch_id}
- GET /api/v1/batch/{batch_id}/documents (or equivalent)
- GET /api/v1/dashboard/batches/{batch_id}/readiness (for parse status)

MANDATORY AGENT SEQUENCE:
1. system-architect — verify document API structure
2. gap-detection — missing endpoints, missing fields
3. reviewer-challenge — attack any write button proposal
4. backend-api — add read-only fields if needed (backend-safety-reviewer reviews)
5. frontend-ui — build documents-v2.html
6. frontend-flow-reviewer
7. testing-verification
8. test-coverage-reviewer
9. gap-hunter
10. browser-verifier — open with real batch, verify PDF links work
11. integration-boundary
12. git-workflow + pr-author

TEST BASELINE — must hold:
- make verify → 160/160
- cd service && python3 -m pytest tests/test_proforma_v2_contract.py -q → 44/44
- cd service && python3 -m pytest tests/test_carrier_*.py -q → 366/366

End with /deploy after PR merges.
```
