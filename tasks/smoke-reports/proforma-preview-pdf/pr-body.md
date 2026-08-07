## Summary
- Unify commercial issue date (`payment_terms.invoice_date` → `wfirma_issue_date`; never `created_at`) across Issued header, `NO_ISSUE_DATE` warning, Overview, and due-date base; expose API `issue_date`.
- Origin from Product Master `ln.origin` only (casefold enrich; no phantom `liveDraft.origin_country`; no invention for missing SKUs).
- Allowlisted payment terms (`Bank transfer · N days`); filter `preview.html` internals.
- Split modal **Print** (`window.print`) vs **Download PDF** (html2canvas+jsPDF of rendered Estrella sheet with **explicit row-packed** A4 pages — not tall-canvas slicing).
- A4 screen preview grows with content; Modern shows payment text in hero.

## Test plan
- [x] `pytest tests/test_proforma_preview_pdf_authority.py` (+ salvage/preview/document suites) — 136 passed
- [x] Real PDF harness: Draft #76 (33 lines) Classic/Modern/Bold + Draft #83 short — Print + Download A4, 33/33 SKUs, payment clean, multi-page packer
- [ ] Operator spot-check Preview modal on a live draft (Print + Download)
- [ ] No deploy in this PR

## Evidence
- Validation report: `tasks/smoke-reports/proforma-preview-pdf/report.json` (local; not committed)
- Architecture: no server Estrella commercial PDF generator; posted PDF remains wFirma `document.pdf`
