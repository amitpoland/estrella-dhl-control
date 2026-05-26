# Sprint 14 — Accounting Hub V2

**Campaign:** Atlas-V2  
**Sprint:** 14 of 23  
**Branch:** `atlas-v2/sprint-14-accounting-hub-v2`  
**Dependency:** Sprint 02 merged (Inbox V2) — establishes wFirma read-only pattern  
**New file:** `service/app/static/accounting-hub-v2.html`  
**URL:** `/dashboard/accounting-hub-v2.html`  
**Design source:** `design-files/accounting-hub.jsx` (origin/atlas-v2/source-bundle)

---

## Authority Boundary

```
OWNS:  Consolidated read view of all wFirma document types
       (Proforma, Invoice, Credit Note, WZ, PZ, PW, RW, MM),
       Client Balance, Client Ledger, Supplier Ledger,
       wFirma sync status display, filter/search across doc types
NEVER: Document creation, document editing, posting payments,
       correcting invoices, deleting documents, wFirma writes,
       PZ creation (owned by pz-v2), Proforma issuance (owned by proforma-v2)
```

wFirma is the source of truth. This page is a **consolidated reader**, not an editor.

---

## Page Purpose

Today accounting visibility is fragmented: proforma in `proforma-v2`, invoices buried in
`shipment-detail.html`, PZ in batch.html, ledgers nowhere. The Accounting Hub gives Tejal
one workspace to find any wFirma document by type/date/party, see balances, and confirm
sync status — without touching writes.

Writes live on the owning V2 pages (proforma-v2 issues proformas; pz-v2 creates PZ).
This hub links to those pages via "Open in <X>" buttons. It never duplicates write logic.

---

## APIs This Page Consumes (read-only)

| Endpoint | Purpose | Status |
|----------|---------|--------|
| `GET /api/v1/accounting/proforma?from=&to=&party=` | Proforma list | NEW read-only endpoint |
| `GET /api/v1/accounting/invoice?from=&to=&party=` | Invoice list | NEW read-only endpoint |
| `GET /api/v1/accounting/pz?from=&to=&party=` | PZ list | exists in batch endpoints |
| `GET /api/v1/accounting/wz?from=&to=&party=` | WZ list | NEW read-only endpoint |
| `GET /api/v1/accounting/credit-note` | Credit notes | NEW read-only endpoint |
| `GET /api/v1/ledger/clients` | Client balances | NEW read-only endpoint |
| `GET /api/v1/ledger/suppliers` | Supplier balances | NEW read-only endpoint |
| `GET /api/v1/wfirma/sync/status` | Per-doc-type sync state | exists |

**Authority rule:** every accounting endpoint reads from wFirma via the existing
`wfirma_client.py` service. No local SQLite copy. If wFirma is down, page shows
SessionBanner with retry — never a stale local snapshot.

`backend-api` must add only read endpoints. `backend-safety-reviewer` verdicts.

---

## Shared Layer Extensions

- `pz-api.js`: `getAccountingDocs(docType, filters)`, `getLedger(party)`, `getWfirmaSyncStatus()`
- `pz-state.js`: `useAccountingDocs(docType, filters)`, `useLedger(party)`
- `pz-components.js`: `WfirmaSyncBadge` (consumes sync status → green/amber/red)
- `dashboard-shared.js`: no changes (no domain knowledge)

---

## Page Structure

- PageHeader (h1: "Accounting", subtitle: "wFirma source of truth")
- Left rail: doc-type / ledger picker (Proforma, Invoice, CN, WZ, PZ, PW, RW, MM, Client Balance, Client Ledger, Supplier Ledger, wFirma Sync)
- Main: filter bar (date range, party search) + CompactTable of selected doc type
- Each row: doc number, date, party, net, tax, gross, currency, state Badge, WfirmaSyncBadge, "Open in <owner page>" Btn
- EmptyState when filter returns nothing
- SessionBanner for auth/network/wFirma-down

---

## Mandatory Agents

| Order | Agent | Purpose |
|-------|-------|---------|
| 1 | chief-orchestrator | Routing |
| 2 | system-architect | Verify wFirma read paths exist, no writes leaked |
| 3 | gap-detection | Missing endpoints, missing ledger queries |
| 4 | reviewer-challenge | Attack any write path or local-copy temptation |
| 5 | backend-api | Add read-only accounting endpoints |
| 6 | backend-safety-reviewer | Verdict every backend change (no writes) |
| 7 | wfirma-integration | Verify wFirma read calls correct |
| 8 | frontend-ui | Build accounting-hub-v2.html |
| 9 | frontend-flow-reviewer | Review |
| 10 | testing-verification | Tests for read endpoints + DOM testids |
| 11 | test-coverage-reviewer | Review tests |
| 12 | gap-hunter | Cross-phase contradictions |
| 13 | browser-verifier | Open page, switch doc types, verify zero writes |
| 14 | integration-boundary | Verify API wiring |
| 15 | git-workflow + pr-author | Commit + PR |

---

## Acceptance Criteria

1. Page loads at `/dashboard/accounting-hub-v2.html` — no console errors, no 4xx
2. Doc-type picker switches list without page reload
3. Filter bar (date + party) filters list correctly
4. Each row's "Open in <owner>" link navigates to owning V2 page
5. WfirmaSyncBadge reflects real sync status (synced / pending / error)
6. Empty state shown when filter returns nothing
7. SessionBanner on auth or wFirma-down
8. All interactive elements have `data-testid`
9. **Zero writes** to any backend from this page (verified by network log review)
10. Rollback: remove `accounting-hub-v2.html` from `C:\PZ\app\static\`

---

## `/run` Prompt

```
/run

Campaign: Atlas-V2 | Sprint 14 — Accounting Hub V2
Branch: atlas-v2/sprint-14-accounting-hub-v2 (from origin/main; Sprint 02 must be merged)

STACK CONSTRAINTS:
1. Read .claude/skills/frontend-design.md BEFORE touching any HTML/JS
2. Stack: Vanilla HTML + Babel JSX. NO Vite. NO TypeScript. NO Tailwind. NO bundler.
3. Pattern file: service/app/static/proforma-v2.html — follow CDN load order + IIFE
4. Shared: window.EstrellaShared, window.PzApi, window.PzState, window.PzComponents
5. CSS custom properties only (no hardcoded hex)
6. Design reference: git show origin/atlas-v2/source-bundle:design-files/accounting-hub.jsx

TASK:
Create service/app/static/accounting-hub-v2.html — consolidated wFirma reader.
URL: /dashboard/accounting-hub-v2.html (served by existing /dashboard/{path} handler)

AUTHORITY:
OWNS: read-only consolidated view of all wFirma doc types + ledgers + sync status
NEVER: any write to wFirma, document creation/editing/deletion, payment posting,
       PZ creation (pz-v2 owns), Proforma issuance (proforma-v2 owns)

BACKEND WORK (read-only, no writes):
- backend-api adds GET endpoints for proforma/invoice/credit-note/wz/ledger reads
- wfirma-integration agent verifies wFirma read-call correctness
- backend-safety-reviewer verdicts every backend file (write detection = block)

GATE 2 CHECK: gh pr list --state open must be ≤ 2 before PR opens

MANDATORY AGENT SEQUENCE (Lesson K — explicit forbidden commands):
1. system-architect 2. gap-detection 3. reviewer-challenge
4. backend-api 5. backend-safety-reviewer 6. wfirma-integration
7. frontend-ui 8. frontend-flow-reviewer
9. testing-verification 10. test-coverage-reviewer 11. gap-hunter
12. browser-verifier (verify zero writes via Network panel)
13. integration-boundary 14. git-workflow + pr-author

TEST BASELINE before PR:
- make verify → 160/160
- pytest tests/test_proforma_v2_contract.py -q → 44/44
- pytest tests/test_carrier_*.py -q → 366/366

End with /deploy after PR merges.
```
