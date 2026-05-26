# Sprint 23 — Documents Suite V2 (Proforma · CMR · Statement · Email · XLSX)

**Campaign:** Atlas-V2  
**Sprint:** 23 of 23 (final)  
**Branch:** `atlas-v2/sprint-23-docs-suite-v2`  
**Dependency:** Sprints 01, 04, 14, 15 merged — Proforma, Documents Hub, Accounting, Ledgers must exist  
**Affected files:**
- `service/app/static/docs/proforma-preview.html` (NEW — operator-facing PDF preview shell)
- `service/app/static/docs/cmr-preview.html` (NEW)
- `service/app/static/docs/statement-preview.html` (NEW)
- `service/app/static/docs/email-preview.html` (NEW)
- `service/app/static/docs/xlsx-preview.html` (NEW)
- Generators in `service/app/services/document_render.py` (extend, do not rewrite)

**Design source:** `design-files/estrella-docs/doc-{cmr,proforma,statement,email-mobile,xlsx}.jsx` + `tokens.css`

---

## Authority Boundary

```
OWNS:  Operator-facing PDF/email previews and downloadable artifacts for
       Proforma, CMR, Statement, Email, XLSX. Visual design tokens
       (estrella-docs/tokens.css). Consistent branding across all generated docs.
NEVER: Generate document with different data than authority source (proforma data
       comes from proforma-v2 backend; statement from ledgers-v2; etc.).
       Document content is rendered, not invented by this sprint.
```

This sprint unifies the **visual rendering** of operator-facing artifacts. The data
authority for each remains its owning V2 page. The output files reside under
`service/app/static/docs/` and are served via download endpoints.

---

## Lesson G Binding (MANDATORY for all 5 artifact types)

Every download endpoint added or modified MUST:

1. Set `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` + `Pragma: no-cache` + `Expires: 0`
2. Generate via validate-then-rollback (validate output before audit pointer update)
3. Audit pointer update MUST be the LAST step
4. Regression test required per artifact type:
   - `test_proforma_cache_and_overwrite.py`
   - `test_cmr_cache_and_overwrite.py`
   - `test_statement_cache_and_overwrite.py`
   - `test_email_render_cache.py`
   - `test_xlsx_cache_and_overwrite.py`

`backend-safety-reviewer` MUST verdict each download endpoint against Lesson G.

---

## APIs

| Endpoint | Purpose | Auth |
|----------|---------|------|
| `GET /api/v1/documents/proforma/{id}.pdf` | Proforma PDF | operator |
| `GET /api/v1/documents/cmr/{shipment_id}.pdf` | CMR PDF | operator |
| `GET /api/v1/documents/statement/{party}/{period}.pdf` | Statement PDF | operator |
| `GET /api/v1/documents/email/{message_id}/preview.html` | Email render preview | operator |
| `GET /api/v1/documents/xlsx/{batch_id}.xlsx` | Batch XLSX | operator |

All read; no writes.

---

## Page Structure

5 small shell HTML files, each rendering a preview of the underlying artifact via:
- `<iframe>` for PDFs (preview before download)
- Inline rendered HTML for email
- Excel-Online or sheetjs preview for XLSX

Each preview page has a download Btn and an "Open in <owner page>" link.

---

## Mandatory Agents

Same 15. Adds:
- `backend-safety-reviewer` Lesson G verdict per download endpoint
- `testing-verification` adds 5 regression tests (one per artifact)
- `compliance` verdict on data retention + GDPR for stored generated artifacts
- `document-intelligence` verdict on render correctness (data matches authority)

---

## Acceptance Criteria

1. All 5 preview pages load, render correctly
2. Each download Btn emits `Cache-Control: no-store` headers (verified via Network tab)
3. Validate-then-rollback in place for each generator (verified by test suite)
4. 5 new regression tests pass
5. Each preview links back to owning V2 page
6. `data-testid` on all interactive surfaces
7. Rollback: remove preview files + revert generator additions

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 23 — Documents Suite V2 (FINAL SPRINT)
Branch: atlas-v2/sprint-23-docs-suite-v2 (Sprints 01 + 04 + 14 + 15 merged)

STACK CONSTRAINTS: same as Sprint 14.
Design ref: git show origin/atlas-v2/source-bundle:design-files/estrella-docs/

TASK: Unify operator-facing document rendering — Proforma, CMR, Statement, Email, XLSX.
Add 5 preview shells + download endpoints for each artifact.

AUTHORITY:
OWNS: visual rendering + download endpoints + branding tokens
NEVER: invent data (each artifact's data comes from its owning V2 page authority)

LESSON G BINDING (mandatory per artifact):
- Cache-Control: no-store on every download endpoint
- Validate-then-rollback for every generator
- 5 regression tests required:
  test_proforma_cache_and_overwrite.py
  test_cmr_cache_and_overwrite.py
  test_statement_cache_and_overwrite.py
  test_email_render_cache.py
  test_xlsx_cache_and_overwrite.py
- backend-safety-reviewer verdict per download endpoint

KEY AGENTS:
- document-intelligence (render correctness)
- compliance (artifact retention, GDPR)
- backend-safety-reviewer (Lesson G enforcement)

GATE 2 + 15-agent sequence + test baseline: same as Sprint 14.
ADDITIONAL: 5 regression tests must pass before PR opens.

End with /deploy after merge.
ATLAS-V2 CAMPAIGN COMPLETE after this sprint merges + deploys.
```
